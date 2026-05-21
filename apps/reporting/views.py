"""RPT dashboards — aggregate read endpoints.

Sprint 3 first cut. Each dashboard is a plain APIView that:
1. Applies the requesting user's ABAC scope to the underlying queryset
   (via apps.security.abac.scope_q_for_field) BEFORE aggregating, so a
   sub-region operator never sees national totals.
2. Emits one AuditEvent with action='dashboard_read' per call, so the
   anomaly-detection feed (SAD §8.4 / threat model T1) sees who is
   pulling which roll-up at what cadence.

Dashboards are intentionally not ModelViewSets — they return aggregates,
not rows, so there's no detail/retrieve route to model.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from django.db.models import Count, Max
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_management.models import (
    Disability,
    FoodConsumption,
    Household,
)
from apps.dqa.models import DqaResult
from apps.grievance.models import Grievance, GrievanceStatus
from apps.security.abac import scope_q_for_field
from apps.security.audit import emit as emit_audit
from apps.security.audit_views import _client_ip


class DashboardRowSerializer(serializers.Serializer):
    key = serializers.CharField()
    count = serializers.IntegerField()


def _audit_dashboard_read(request, code: str, bucket_count: int) -> None:
    emit_audit(
        "dashboard_read", "rpt_dashboard", code,
        actor=getattr(request.user, "username", "") or "anonymous",
        reason=f"buckets={bucket_count}",
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _render(request, rows: list[dict], filename: str):
    """Render a list of {key, count} dicts as either JSON (default)
    or CSV (when ?export=csv). Audit emission and scope filtering
    are caller responsibilities — this helper is purely about
    representation.

    Returns a DRF Response (JSON path) or a plain HttpResponse
    (CSV path). Both are valid APIView return values.

    NB: We use ?export=csv rather than the more obvious ?format=csv
    because DRF reserves the latter as the content-negotiation hook
    and 404s on unknown values without a custom renderer registered.
    """
    if request.query_params.get("export", "").lower() != "csv":
        return Response(rows)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(("key", "count"))
    for row in rows:
        writer.writerow((row["key"], row["count"]))
    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{filename}.csv"'
    )
    return response


def _render_records_csv(rows: list[dict], fields: tuple[str, ...], filename: str) -> HttpResponse:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    return response


@extend_schema(
    tags=["rpt"],
    summary="Household count grouped by selected geography level",
    responses={200: DashboardRowSerializer(many=True)},
)
class HouseholdsBySubRegion(APIView):
    """Household coverage grouped by geography.

    Query params:
        group_by=sub_region|region|district  (default sub_region)
        region=<GeographicUnit.code>
        sub_region=<GeographicUnit.code>

    Rows the operator cannot see are excluded BEFORE aggregation.
    The URL name is retained for compatibility with earlier clients.
    """

    def get(self, request):
        group_by = request.query_params.get("group_by", "sub_region")
        groupings = {
            "region": ("region__code", "region__name"),
            "sub_region": ("sub_region_code", "sub_region__name"),
            "district": ("district__code", "district__name"),
        }
        code_field, name_field = groupings.get(group_by, groupings["sub_region"])

        scoped = Household.objects.select_related("region", "sub_region", "district").filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        region = (request.query_params.get("region") or "").strip()
        sub_region = (request.query_params.get("sub_region") or "").strip()
        district = (request.query_params.get("district") or "").strip()
        if region:
            scoped = scoped.filter(region__code=region)
        if sub_region:
            scoped = scoped.filter(sub_region_code=sub_region)
        if district:
            scoped = scoped.filter(district__code=district)

        rows = list(
            scoped.values(code_field, name_field)
            .annotate(count=Count("id"))
            .order_by(code_field),
        )
        out = [
            {
                "key": r[code_field] or "(unset)",
                "label": r[name_field] or r[code_field] or "(unset)",
                "count": r["count"],
            }
            for r in rows
        ]
        _audit_dashboard_read(request, "households_by_sub_region", len(out))
        return _render(request, out, "households-by-sub-region")


@extend_schema(
    tags=["rpt"],
    summary="Household count grouped by current PMT band",
    responses={200: DashboardRowSerializer(many=True)},
)
class HouseholdsByPmtBand(APIView):
    """Counts of Household rows grouped by current_vulnerability_band.
    Households without a PMT score yet land in the '(unscored)' bucket."""

    def get(self, request):
        scoped = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        rows = list(
            scoped.values("current_vulnerability_band")
            .annotate(count=Count("id"))
            .order_by("current_vulnerability_band"),
        )
        out = [
            {"key": r["current_vulnerability_band"] or "(unscored)",
             "count": r["count"]}
            for r in rows
        ]
        _audit_dashboard_read(request, "households_by_pmt_band", len(out))
        return _render(request, out, "households-by-pmt-band")


@extend_schema(
    tags=["rpt"],
    summary="Household count grouped by urban/rural classification",
    responses={200: DashboardRowSerializer(many=True)},
)
class HouseholdsByUrbanRural(APIView):
    """Registry coverage split by the household's urban/rural marker.
    Scoped on Household.sub_region_code before aggregation."""

    def get(self, request):
        scoped = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        rows = list(
            scoped.values("urban_rural")
            .annotate(count=Count("id"))
            .order_by("urban_rural"),
        )
        out = [{"key": r["urban_rural"] or "(unset)", "count": r["count"]}
               for r in rows]
        _audit_dashboard_read(request, "households_by_urban_rural", len(out))
        return _render(request, out, "households-by-urban-rural")


@extend_schema(
    tags=["rpt"],
    summary="Household count grouped by current intake source",
    responses={200: DashboardRowSerializer(many=True)},
)
class HouseholdsByIntakeSource(APIView):
    """Registry coverage by source channel. This uses the denormalised
    Household.current_intake_source set during promotion."""

    def get(self, request):
        scoped = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        rows = list(
            scoped.values("current_intake_source")
            .annotate(count=Count("id"))
            .order_by("current_intake_source"),
        )
        out = [
            {"key": r["current_intake_source"] or "(unset)", "count": r["count"]}
            for r in rows
        ]
        _audit_dashboard_read(request, "households_by_intake_source", len(out))
        return _render(request, out, "households-by-intake-source")


@extend_schema(
    tags=["rpt"],
    summary="Overdue grievance count grouped by tier",
    responses={200: DashboardRowSerializer(many=True)},
)
class OverdueGrievancesByTier(APIView):
    """Counts of open grievances past their sla_deadline, grouped by
    tier. ABAC-scoped through the household. Used by L3/L4 supervisors
    to surface tier-wise SLA breach pressure."""

    def get(self, request):
        from django.utils import timezone

        from apps.security.abac import _scoped_codes  # local import: cycle safety

        codes = _scoped_codes(request.user)
        base = Grievance.objects.filter(
            sla_deadline__lt=timezone.now(),
            status__in=[GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS,
                        GrievanceStatus.ESCALATED],
        )
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(household_id__in=household_ids)
        rows = list(
            scoped.values("tier").annotate(count=Count("id")).order_by("tier"),
        )
        out = [{"key": r["tier"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "overdue_grievances_by_tier", len(out))
        return _render(request, out, "overdue-grievances-by-tier")


@extend_schema(
    tags=["rpt"],
    summary="Intake submissions per day (last 30 days)",
    responses={200: DashboardRowSerializer(many=True)},
)
class SubmissionsPerDay(APIView):
    """Submission counts grouped by date for the last 30 days. Uses
    Submission.provisional_registry_id (linked to a household) to apply
    geographic scope — pre-promotion submissions without a household
    are invisible to sub-region operators and visible only to national
    scope / superuser (same HouseholdIdScopedQuerysetMixin semantics as
    apps.intake.api)."""

    def get(self, request):
        from datetime import timedelta

        from django.db.models.functions import TruncDate
        from django.utils import timezone

        from apps.intake.models import Submission
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        since = timezone.now() - timedelta(days=30)
        base = Submission.objects.filter(created_at__gte=since)
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            # Submissions reference the household by provisional_registry_id,
            # which becomes the Household.id after promotion.
            scoped = base.filter(provisional_registry_id__in=household_ids)
        rows = list(
            scoped.annotate(day=TruncDate("created_at"))
            .values("day").annotate(count=Count("id")).order_by("day"),
        )
        out = [{"key": r["day"].isoformat(), "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "submissions_per_day", len(out))
        return _render(request, out, "submissions-per-day")


@extend_schema(
    tags=["rpt"],
    summary="Pending dedup pairs grouped by tier",
    responses={200: DashboardRowSerializer(many=True)},
)
class PendingDedupPairsByTier(APIView):
    """MatchPair rows in PENDING state grouped by tier (1 NIN, 2 phone,
    3 probabilistic). Pair-level visibility follows the both-ends-in-
    scope rule from MatchPairScopedQuerysetMixin: both members must
    fall within the operator's geographic scope, else the pair is
    invisible to sub-region operators."""

    def get(self, request):
        from apps.data_management.models import Member
        from apps.ddup.models import MatchPair, PairStatus
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = MatchPair.objects.filter(status=PairStatus.PENDING)
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            member_ids = list(
                Member.objects.filter(household__sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(
                record_a_id__in=member_ids, record_b_id__in=member_ids,
            )
        rows = list(
            scoped.values("tier").annotate(count=Count("id")).order_by("tier"),
        )
        out = [{"key": f"tier_{r['tier']}", "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "pending_dedup_pairs_by_tier", len(out))
        return _render(request, out, "pending-dedup-pairs-by-tier")


@extend_schema(
    tags=["rpt"],
    summary="Dedup match pairs grouped by status",
    responses={200: DashboardRowSerializer(many=True)},
)
class DedupPairsByStatus(APIView):
    """DDUP workload split by pair status. Scoped with the same both-ends-
    in-scope rule as PendingDedupPairsByTier."""

    def get(self, request):
        from apps.data_management.models import Member
        from apps.ddup.models import MatchPair
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = MatchPair.objects.all()
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            member_ids = list(
                Member.objects.filter(household__sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(record_a_id__in=member_ids, record_b_id__in=member_ids)
        rows = list(
            scoped.values("status").annotate(count=Count("id")).order_by("status"),
        )
        out = [{"key": r["status"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "dedup_pairs_by_status", len(out))
        return _render(request, out, "dedup-pairs-by-status")


@extend_schema(
    tags=["rpt"],
    summary="PMT score distribution in 10-point buckets",
    responses={200: DashboardRowSerializer(many=True)},
)
class PmtScoreHistogram(APIView):
    """Histogram of latest PMT scores in 10-point buckets ([0,10),
    [10,20), ..., [90,100]). Uses Household.current_pmt_score so each
    household contributes once. ABAC-scoped on Household."""

    def get(self, request):
        scoped = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
            current_pmt_score__isnull=False,
        )
        # 10 fixed buckets; SQL-side bucketing keeps a single query.
        buckets: dict[int, int] = {b: 0 for b in range(0, 100, 10)}
        for score in scoped.values_list("current_pmt_score", flat=True):
            bucket = int(min(score, 99)) // 10 * 10  # cap at 99 → bucket 90
            buckets[bucket] += 1
        out = [{"key": f"{b:02d}-{b + 9:02d}", "count": c}
               for b, c in buckets.items()]
        _audit_dashboard_read(request, "pmt_score_histogram", 10)
        return _render(request, out, "pmt-score-histogram")


@extend_schema(
    tags=["rpt"],
    summary="Open grievance count grouped by category",
    responses={200: DashboardRowSerializer(many=True)},
)
class GrievancesByCategory(APIView):
    """Counts of non-closed grievances grouped by Category. Lets ops
    see which case types dominate — DATA_CORRECTION volume hints at
    enumeration quality issues; OPERATOR_CONDUCT clusters trigger
    targeted retraining.

    Scope-before-aggregate via the household reference, same as
    OpenGrievancesByTier (S3-004). Orphan grievances (no
    household_id) are visible only to NATIONAL / superuser since
    sub-region operators have no in-IN-subquery match for them.
    """

    def get(self, request):
        from apps.grievance.models import Grievance, GrievanceStatus
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = Grievance.objects.exclude(
            status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
        )
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(household_id__in=household_ids)
        rows = list(
            scoped.values("category").annotate(count=Count("id")).order_by("category"),
        )
        out = [{"key": r["category"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "grievances_by_category", len(out))
        return _render(request, out, "grievances-by-category")


@extend_schema(
    tags=["rpt"],
    summary="Weekly household registrations (last 12 weeks)",
    responses={200: DashboardRowSerializer(many=True)},
)
class WeeklyHouseholdRegistrations(APIView):
    """Counts of Household.created_at grouped by ISO week for the
    last 12 weeks. The first trend-over-time dashboard — gives ops
    a registration-throughput picture they can spot drops in.

    Scope filter on Household.sub_region_code (S2-003 pattern); CSV
    export inherited from the _render helper. Week keys are
    'YYYY-Www' (ISO format) so they sort lexicographically and
    chart libraries don't have to special-case them.
    """

    def get(self, request):
        from datetime import timedelta

        from django.db.models.functions import TruncWeek
        from django.utils import timezone

        cutoff = timezone.now() - timedelta(weeks=12)
        scoped = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
            created_at__gte=cutoff,
        )
        rows = list(
            scoped.annotate(week=TruncWeek("created_at"))
            .values("week").annotate(count=Count("id")).order_by("week"),
        )
        out = [
            {
                "key": f"{r['week'].isocalendar()[0]}-W{r['week'].isocalendar()[1]:02d}",
                "count": r["count"],
            }
            for r in rows
        ]
        _audit_dashboard_read(request, "weekly_household_registrations", len(out))
        return _render(request, out, "weekly-household-registrations")


@extend_schema(
    tags=["rpt"],
    summary="DIH promotion latency distribution per connector",
    responses={200: DashboardRowSerializer(many=True)},
)
class PromotionLatencyByConnector(APIView):
    """Distribution of (StageRecord.promoted_at − StageRecord.created_at)
    grouped by Connector, bucketed by elapsed time. Lets ops spot
    connectors with rising staging dwell — typically a sign that DQA
    or DDUP is back-pressuring promotion.

    Bucket cutoffs (inclusive lower bound):
        under_1h  : 0   → < 1h
        1_6h      : 1h  → < 6h
        6_24h     : 6h  → < 24h
        1_7d      : 1d  → < 7d
        over_7d   : 7d  → +∞

    ABAC: StageRecords promote to Households; we scope through the
    promoted_household_id lookup (HouseholdIdScopedQuerysetMixin
    semantics — sub-region operators only see promotions whose
    resulting Household sits in their geography). Pre-promotion
    stages are invisible to sub-region operators by definition.

    Output key shape: 'CONN-CODE / bucket' — one row per
    (connector, bucket) combination, so the chart can be a stacked
    bar instead of a per-connector subplot.
    """

    def get(self, request):
        from datetime import timedelta

        from apps.ingestion_hub.models import StageRecord, StageRecordState
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = (
            StageRecord.objects
            .filter(state=StageRecordState.PROMOTED, promoted_at__isnull=False)
            .select_related("connector_run__connector__source_system")
        )
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(promoted_household_id__in=household_ids)

        buckets = [
            ("under_1h", timedelta(hours=1)),
            ("1_6h", timedelta(hours=6)),
            ("6_24h", timedelta(hours=24)),
            ("1_7d", timedelta(days=7)),
            ("over_7d", None),  # sentinel: tail
        ]
        counts: dict[str, int] = {}
        for sr in scoped:
            delta = sr.promoted_at - sr.created_at
            label = next(
                (label for label, cutoff in buckets
                 if cutoff is not None and delta < cutoff),
                "over_7d",
            )
            code = sr.connector_run.connector.source_system.code
            key = f"{code} / {label}"
            counts[key] = counts.get(key, 0) + 1

        out = [{"key": k, "count": v} for k, v in sorted(counts.items())]
        _audit_dashboard_read(request, "promotion_latency_by_connector", len(out))
        return _render(request, out, "promotion-latency-by-connector")


@extend_schema(
    tags=["rpt"],
    summary="DIH stage records grouped by state",
    responses={200: DashboardRowSerializer(many=True)},
)
class DihStagesByState(APIView):
    """DIH pipeline funnel by StageRecord.state. For sub-region users,
    visible stages are limited to records whose provisional/promoted
    household ID is in scope."""

    def get(self, request):
        from apps.ingestion_hub.models import StageRecord
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = StageRecord.objects.all()
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(provisional_registry_id__in=household_ids)
        rows = list(scoped.values("state").annotate(count=Count("id")).order_by("state"))
        out = [{"key": r["state"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "dih_stages_by_state", len(out))
        return _render(request, out, "dih-stages-by-state")


@extend_schema(
    tags=["rpt"],
    summary="DIH connector runs grouped by status",
    responses={200: DashboardRowSerializer(many=True)},
)
class ConnectorRunsByStatus(APIView):
    """Operational connector health. ConnectorRun rows are DIH-level
    operational metadata, so national/superuser scope sees all; users
    without national scope fail closed."""

    def get(self, request):
        from apps.ingestion_hub.models import ConnectorRun
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = ConnectorRun.objects.all()
        scoped = base if codes is None else base.none()
        rows = list(scoped.values("status").annotate(count=Count("id")).order_by("status"))
        out = [{"key": r["status"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "connector_runs_by_status", len(out))
        return _render(request, out, "connector-runs-by-status")


@extend_schema(
    tags=["rpt"],
    summary="NIRA verification attempts grouped by status",
    responses={200: DashboardRowSerializer(many=True)},
)
class IdvAttemptsByStatus(APIView):
    """IDV retry queue health. The table stores hashed NINs only and has
    no geography pointer, so this is restricted to national/superuser
    dashboard visibility."""

    def get(self, request):
        from apps.identity_verification.models import NiraVerificationAttempt
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = NiraVerificationAttempt.objects.all()
        scoped = base if codes is None else base.none()
        rows = list(scoped.values("status").annotate(count=Count("id")).order_by("status"))
        out = [{"key": r["status"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "idv_attempts_by_status", len(out))
        return _render(request, out, "idv-attempts-by-status")


@extend_schema(
    tags=["rpt"],
    summary="Change requests grouped by status",
    responses={200: DashboardRowSerializer(many=True)},
)
class ChangeRequestsByStatus(APIView):
    """UPD queue split by lifecycle status. Scopes household and member
    requests through ChangeRequestScopedQuerysetMixin's same logic."""

    def get(self, request):
        from django.db.models import Q

        from apps.data_management.models import Member
        from apps.security.abac import _scoped_codes
        from apps.update_workflow.models import ChangeRequest

        codes = _scoped_codes(request.user)
        base = ChangeRequest.objects.all()
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            member_ids = list(
                Member.objects.filter(household_id__in=household_ids)
                .values_list("id", flat=True),
            )
            scoped = base.filter(
                Q(entity_type="household", entity_id__in=household_ids)
                | Q(entity_type="member", entity_id__in=member_ids),
            )
        rows = list(scoped.values("status").annotate(count=Count("id")).order_by("status"))
        out = [{"key": r["status"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "change_requests_by_status", len(out))
        return _render(request, out, "change-requests-by-status")


@extend_schema(
    tags=["rpt"],
    summary="Data requests grouped by status",
    responses={200: DashboardRowSerializer(many=True)},
)
class DataRequestsByStatus(APIView):
    """DRS lifecycle split by status. Partner-scoped operators see only
    requests for their partner; national/superuser sees all."""

    def get(self, request):
        from apps.data_requests.models import DataRequest
        from apps.partners.models import Partner
        from apps.security.abac import _scoped_partner_codes

        partner_codes = _scoped_partner_codes(request.user)
        base = DataRequest.objects.all()
        if partner_codes is None:
            scoped = base
        elif not partner_codes:
            scoped = base.none()
        else:
            partner_ids = list(
                Partner.objects.filter(code__in=partner_codes).values_list("id", flat=True),
            )
            scoped = base.filter(dsa__partner_id__in=partner_ids)
        rows = list(scoped.values("status").annotate(count=Count("id")).order_by("status"))
        out = [{"key": r["status"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "data_requests_by_status", len(out))
        return _render(request, out, "data-requests-by-status")


@extend_schema(
    tags=["rpt"],
    summary="Referrals grouped by programme and status",
    responses={200: DashboardRowSerializer(many=True)},
)
class ReferralsByProgrammeStatus(APIView):
    """Referral conversion surface. Keys are '<programme_code> / <status>';
    geographic scope flows through Referral.household."""

    def get(self, request):
        from apps.referral.models import Referral

        scoped = Referral.objects.filter(
            scope_q_for_field(request.user, "household__sub_region_code"),
        ).select_related("programme")
        rows = list(
            scoped.values("programme__code", "status")
            .annotate(count=Count("id"))
            .order_by("programme__code", "status"),
        )
        out = [
            {"key": f"{r['programme__code']} / {r['status']}", "count": r["count"]}
            for r in rows
        ]
        _audit_dashboard_read(request, "referrals_by_programme_status", len(out))
        return _render(request, out, "referrals-by-programme-status")


@extend_schema(
    tags=["rpt"],
    summary="Audit events grouped by action",
    responses={200: DashboardRowSerializer(many=True)},
)
class AuditEventsByAction(APIView):
    """Compliance activity roll-up by audit action. Audit rows do not
    reliably carry geography, so this dashboard is national/superuser
    only and fails closed for scoped local operators."""

    def get(self, request):
        from apps.security.abac import _scoped_codes
        from apps.security.models import AuditEvent

        codes = _scoped_codes(request.user)
        base = AuditEvent.objects.all()
        scoped = base if codes is None else base.none()
        rows = list(scoped.values("action").annotate(count=Count("id")).order_by("action"))
        out = [{"key": r["action"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "audit_events_by_action", len(out))
        return _render(request, out, "audit-events-by-action")


class CompareWindowSerializer(serializers.Serializer):
    from_ = serializers.DateTimeField(source="from")  # `from` is keyword
    to = serializers.DateTimeField()
    count = serializers.IntegerField()


class CompareResultSerializer(serializers.Serializer):
    metric = serializers.CharField()
    period = serializers.ChoiceField(choices=["wow", "mom"])
    current = CompareWindowSerializer()
    previous = CompareWindowSerializer()
    delta_abs = serializers.IntegerField()
    delta_pct = serializers.FloatField(allow_null=True)


# Registry of supported comparative metrics (US-S11-007). Each entry
# is a callable taking (request, since, until) and returning the count
# of matching rows in [since, until). New metrics land by appending an
# entry here and the GET handler picks them up automatically — keeps
# the comparative surface independent of the per-dashboard plumbing.
def _count_households_created(request, since, until):
    return Household.objects.filter(
        scope_q_for_field(request.user, "sub_region_code"),
        created_at__gte=since, created_at__lt=until,
    ).count()


def _count_submissions(request, since, until):
    from apps.intake.models import Submission
    from apps.security.abac import _scoped_codes
    codes = _scoped_codes(request.user)
    base = Submission.objects.filter(created_at__gte=since, created_at__lt=until)
    if codes is None:
        return base.count()
    if not codes:
        return 0
    household_ids = list(
        Household.objects.filter(sub_region_code__in=codes)
                          .values_list("id", flat=True),
    )
    return base.filter(provisional_registry_id__in=household_ids).count()


def _count_grievances_opened(request, since, until):
    from apps.security.abac import _scoped_codes
    codes = _scoped_codes(request.user)
    base = Grievance.objects.filter(created_at__gte=since, created_at__lt=until)
    if codes is None:
        return base.count()
    if not codes:
        return 0
    household_ids = list(
        Household.objects.filter(sub_region_code__in=codes)
                          .values_list("id", flat=True),
    )
    return base.filter(household_id__in=household_ids).count()


def _count_change_requests_committed(request, since, until):
    from apps.security.abac import _scoped_codes
    from apps.update_workflow.models import ChangeRequest, ChangeRequestStatus
    codes = _scoped_codes(request.user)
    base = ChangeRequest.objects.filter(
        status=ChangeRequestStatus.COMMITTED,
        decided_at__gte=since, decided_at__lt=until,
    )
    if codes is None:
        return base.count()
    if not codes:
        return 0
    household_ids = list(
        Household.objects.filter(sub_region_code__in=codes)
                          .values_list("id", flat=True),
    )
    return base.filter(household_id__in=household_ids).count()


_COMPARE_METRICS = {
    "households_created": _count_households_created,
    "submissions": _count_submissions,
    "grievances_opened": _count_grievances_opened,
    "change_requests_committed": _count_change_requests_committed,
}

_COMPARE_PERIODS = {"wow": 7, "mom": 30}


@extend_schema(
    tags=["rpt"],
    summary="Same metric across two time windows (week-over-week / month-over-month)",
    responses={200: CompareResultSerializer()},
)
class ComparativeMetric(APIView):
    """Returns a single number for the current window plus the same
    number for the immediately-preceding window of equal length, with
    absolute + percent deltas.

    Query params:
        metric  — one of households_created, submissions,
                  grievances_opened, change_requests_committed
        compare — wow (default) for 7-day or mom for 30-day windows

    The point of this dashboard isn't to replace the trend charts (S8-004,
    S6-005) — it's to surface a single 'is this week worse than last week'
    signal an operator can read at a glance. ABAC scope flows through
    each counter exactly like the row-level dashboards.
    """

    def get(self, request):
        from datetime import timedelta

        from django.utils import timezone

        metric_key = request.query_params.get("metric", "households_created")
        period = request.query_params.get("compare", "wow")
        if metric_key not in _COMPARE_METRICS:
            return Response(
                {"detail": f"unknown metric '{metric_key}'; allowed: "
                           f"{sorted(_COMPARE_METRICS)}"},
                status=400,
            )
        if period not in _COMPARE_PERIODS:
            return Response(
                {"detail": f"unknown compare '{period}'; allowed: wow, mom"},
                status=400,
            )
        days = _COMPARE_PERIODS[period]
        now = timezone.now()
        cur_to = now
        cur_from = now - timedelta(days=days)
        prev_to = cur_from
        prev_from = cur_from - timedelta(days=days)

        counter = _COMPARE_METRICS[metric_key]
        cur = counter(request, cur_from, cur_to)
        prev = counter(request, prev_from, prev_to)
        delta_abs = cur - prev
        # Avoid 0/0 nonsense — when there's no prior baseline, percent
        # delta is meaningless and we surface it as None for the caller
        # to render as '—' rather than '+Infinity%'.
        delta_pct = (delta_abs / prev) if prev else None

        out = {
            "metric": metric_key,
            "period": period,
            "current": {"from": cur_from, "to": cur_to, "count": cur},
            "previous": {"from": prev_from, "to": prev_to, "count": prev},
            "delta_abs": delta_abs,
            "delta_pct": delta_pct,
        }
        _audit_dashboard_read(
            request, f"comparative_{metric_key}_{period}", 1,
        )
        if request.query_params.get("export", "").lower() != "csv":
            return Response(out)

        # CSV variant — two-row tabular layout the partner spreadsheets
        # can paste into. Columns mirror the field names so the file is
        # self-describing.
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow((
            "metric", "period", "window", "from", "to", "count",
            "delta_abs", "delta_pct",
        ))
        writer.writerow((
            metric_key, period, "previous",
            prev_from.isoformat(), prev_to.isoformat(), prev,
            "", "",
        ))
        writer.writerow((
            metric_key, period, "current",
            cur_from.isoformat(), cur_to.isoformat(), cur,
            delta_abs, f"{delta_pct:.4f}" if delta_pct is not None else "",
        ))
        response = HttpResponse(buf.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="comparative-{metric_key}-{period}.csv"'
        )
        return response


@extend_schema(
    tags=["rpt"],
    summary="Open grievance count grouped by tier",
    responses={200: DashboardRowSerializer(many=True)},
)
class OpenGrievancesByTier(APIView):
    """Counts of non-closed grievances grouped by tier, scoped via the
    associated household — orphan grievances (no household_id) are not
    visible to sub-region operators (HouseholdIdScopedQuerysetMixin
    semantics: orphans live outside any sub-region's IN-subquery)."""

    def get(self, request):
        from apps.security.abac import _scoped_codes  # local import: cycle safety

        codes = _scoped_codes(request.user)
        base = Grievance.objects.exclude(
            status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
        )
        if codes is None:
            scoped = base
        elif not codes:
            scoped = base.none()
        else:
            household_ids = list(
                Household.objects.filter(sub_region_code__in=codes)
                .values_list("id", flat=True),
            )
            scoped = base.filter(household_id__in=household_ids)
        rows = list(
            scoped.values("tier").annotate(count=Count("id")).order_by("tier"),
        )
        out = [{"key": r["tier"], "count": r["count"]} for r in rows]
        _audit_dashboard_read(request, "open_grievances_by_tier", len(out))
        return _render(request, out, "open-grievances-by-tier")


def _visible_household_ids(user) -> list[str] | None:
    """Return visible Household IDs, None for national/superuser wildcard."""
    from apps.security.abac import _scoped_codes

    codes = _scoped_codes(user)
    if codes is None:
        return None
    if not codes:
        return []
    return list(
        Household.objects.filter(sub_region_code__in=codes).values_list("id", flat=True),
    )


def _visible_member_ids(user) -> list[str] | None:
    from apps.data_management.models import Member

    household_ids = _visible_household_ids(user)
    if household_ids is None:
        return None
    if not household_ids:
        return []
    return list(
        Member.objects.filter(household_id__in=household_ids).values_list("id", flat=True),
    )


@extend_schema(tags=["rpt"], summary="Grievance record export")
class GrievanceRecords(APIView):
    """Visible grievance rows behind GRM reports. Query params:
    status=open|in_progress|escalated|resolved|closed|active,
    overdue=true, category=<category>, tier=<tier>."""

    def get(self, request):
        from django.utils import timezone

        from apps.grievance.models import Grievance

        base = Grievance.objects.all().order_by("-created_at")
        status = (request.query_params.get("status") or "").strip()
        if status == "active":
            base = base.exclude(status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED])
        elif status:
            base = base.filter(status=status)
        if request.query_params.get("overdue", "").lower() == "true":
            base = base.filter(
                sla_deadline__lt=timezone.now(),
                status__in=[
                    GrievanceStatus.OPEN,
                    GrievanceStatus.IN_PROGRESS,
                    GrievanceStatus.ESCALATED,
                ],
            )
        category = (request.query_params.get("category") or "").strip()
        tier = (request.query_params.get("tier") or "").strip()
        if category:
            base = base.filter(category=category)
        if tier:
            base = base.filter(tier=tier)

        household_ids = _visible_household_ids(request.user)
        if household_ids is None:
            scoped = base
        elif not household_ids:
            scoped = base.none()
        else:
            scoped = base.filter(household_id__in=household_ids)

        rows = [
            {
                "id": g.id,
                "category": g.category,
                "tier": g.tier,
                "status": g.status,
                "household_id": g.household_id,
                "member_id": g.member_id,
                "assigned_to": g.assigned_to,
                "opened_at": g.opened_at.isoformat() if g.opened_at else "",
                "sla_deadline": g.sla_deadline.isoformat() if g.sla_deadline else "",
                "resolved_at": g.resolved_at.isoformat() if g.resolved_at else "",
            }
            for g in scoped[:5000]
        ]
        _audit_dashboard_read(request, "grievance_records", len(rows))
        if request.query_params.get("export", "").lower() == "csv":
            return _render_records_csv(
                rows,
                (
                    "id", "category", "tier", "status", "household_id", "member_id",
                    "assigned_to", "opened_at", "sla_deadline", "resolved_at",
                ),
                "grievance-records",
            )
        return Response(rows)


@extend_schema(tags=["rpt"], summary="Change request record export")
class ChangeRequestRecords(APIView):
    """Visible UPD change-request rows. Query params:
    status=<status>, overdue=true, change_type=<type>."""

    def get(self, request):
        from django.db.models import Q
        from django.utils import timezone

        from apps.data_management.models import Member
        from apps.update_workflow.models import ChangeRequest

        base = ChangeRequest.objects.all().order_by("-created_at")
        status = (request.query_params.get("status") or "").strip()
        change_type = (request.query_params.get("change_type") or "").strip()
        if status:
            base = base.filter(status=status)
        if change_type:
            base = base.filter(change_type=change_type)
        if request.query_params.get("overdue", "").lower() == "true":
            base = base.filter(sla_deadline__lt=timezone.now())

        household_ids = _visible_household_ids(request.user)
        if household_ids is None:
            scoped = base
        elif not household_ids:
            scoped = base.none()
        else:
            member_ids = list(
                Member.objects.filter(household_id__in=household_ids).values_list("id", flat=True),
            )
            scoped = base.filter(
                Q(entity_type="household", entity_id__in=household_ids)
                | Q(entity_type="member", entity_id__in=member_ids),
            )

        rows = [
            {
                "id": cr.id,
                "entity_type": cr.entity_type,
                "entity_id": cr.entity_id,
                "change_type": cr.change_type,
                "status": cr.status,
                "required_role": cr.required_role,
                "requester": cr.requester,
                "created_at": cr.created_at.isoformat() if cr.created_at else "",
                "sla_deadline": cr.sla_deadline.isoformat() if cr.sla_deadline else "",
                "decided_at": cr.decided_at.isoformat() if cr.decided_at else "",
            }
            for cr in scoped[:5000]
        ]
        _audit_dashboard_read(request, "change_request_records", len(rows))
        if request.query_params.get("export", "").lower() == "csv":
            return _render_records_csv(
                rows,
                (
                    "id", "entity_type", "entity_id", "change_type", "status",
                    "required_role", "requester", "created_at", "sla_deadline", "decided_at",
                ),
                "change-request-records",
            )
        return Response(rows)


@extend_schema(tags=["rpt"], summary="Dedup match-pair record export")
class DedupPairRecords(APIView):
    """Visible DDUP match pairs. Query params: status=<status>, tier=<tier>."""

    def get(self, request):
        from apps.ddup.models import MatchPair

        base = MatchPair.objects.all().order_by("-created_at")
        status = (request.query_params.get("status") or "").strip()
        tier = (request.query_params.get("tier") or "").strip()
        if status:
            base = base.filter(status=status)
        if tier:
            base = base.filter(tier=tier)

        member_ids = _visible_member_ids(request.user)
        if member_ids is None:
            scoped = base
        elif not member_ids:
            scoped = base.none()
        else:
            scoped = base.filter(record_a_id__in=member_ids, record_b_id__in=member_ids)

        rows = [
            {
                "id": pair.id,
                "record_type": pair.record_type,
                "record_a_id": pair.record_a_id,
                "record_b_id": pair.record_b_id,
                "tier": pair.tier,
                "match_reason": pair.match_reason,
                "composite_score": str(pair.composite_score or ""),
                "status": pair.status,
                "created_at": pair.created_at.isoformat() if pair.created_at else "",
            }
            for pair in scoped[:5000]
        ]
        _audit_dashboard_read(request, "dedup_pair_records", len(rows))
        if request.query_params.get("export", "").lower() == "csv":
            return _render_records_csv(
                rows,
                (
                    "id", "record_type", "record_a_id", "record_b_id", "tier",
                    "match_reason", "composite_score", "status", "created_at",
                ),
                "dedup-pair-records",
            )
        return Response(rows)


@extend_schema(tags=["rpt"], summary="Data request record export")
class DataRequestRecords(APIView):
    """DRS request register. Partner-scoped users see only their partner."""

    def get(self, request):
        from apps.data_requests.models import DataRequest
        from apps.partners.models import Partner
        from apps.security.abac import _scoped_partner_codes

        base = DataRequest.objects.select_related("dsa__partner").all().order_by("-created_at")
        status = (request.query_params.get("status") or "").strip()
        if status:
            base = base.filter(status=status)

        partner_codes = _scoped_partner_codes(request.user)
        if partner_codes is None:
            scoped = base
        elif not partner_codes:
            scoped = base.none()
        else:
            partner_ids = list(
                Partner.objects.filter(code__in=partner_codes).values_list("id", flat=True),
            )
            scoped = base.filter(dsa__partner_id__in=partner_ids)

        rows = [
            {
                "id": req.id,
                "partner_code": req.dsa.partner.code,
                "dsa_reference": req.dsa.reference,
                "requester": req.requester,
                "status": req.status,
                "submitted_at": req.submitted_at.isoformat() if req.submitted_at else "",
                "decided_at": req.decided_at.isoformat() if req.decided_at else "",
                "delivered_at": req.delivered_at.isoformat() if req.delivered_at else "",
                "expires_at": req.expires_at.isoformat() if req.expires_at else "",
                "row_count_delivered": req.row_count_delivered or "",
            }
            for req in scoped[:5000]
        ]
        _audit_dashboard_read(request, "data_request_records", len(rows))
        if request.query_params.get("export", "").lower() == "csv":
            return _render_records_csv(
                rows,
                (
                    "id", "partner_code", "dsa_reference", "requester", "status",
                    "submitted_at", "decided_at", "delivered_at", "expires_at",
                    "row_count_delivered",
                ),
                "data-request-records",
            )
        return Response(rows)


@extend_schema(tags=["rpt"], summary="NIRA verification attempt record export")
class IdvAttemptRecords(APIView):
    """NIRA retry diagnostics. National/superuser only; no raw NINs."""

    def get(self, request):
        from apps.identity_verification.models import NiraVerificationAttempt
        from apps.security.abac import _scoped_codes

        codes = _scoped_codes(request.user)
        base = NiraVerificationAttempt.objects.all().order_by("-created_at")
        status = (request.query_params.get("status") or "").strip()
        if status:
            base = base.filter(status=status)
        scoped = base if codes is None else base.none()

        rows = [
            {
                "id": attempt.id,
                "status": attempt.status,
                "attempts": attempt.attempts,
                "requester": attempt.requester,
                "last_error": attempt.last_error,
                "next_retry_at": attempt.next_retry_at.isoformat() if attempt.next_retry_at else "",
                "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else "",
                "created_at": attempt.created_at.isoformat() if attempt.created_at else "",
            }
            for attempt in scoped[:5000]
        ]
        _audit_dashboard_read(request, "idv_attempt_records", len(rows))
        if request.query_params.get("export", "").lower() == "csv":
            return _render_records_csv(
                rows,
                (
                    "id", "status", "attempts", "requester", "last_error",
                    "next_retry_at", "completed_at", "created_at",
                ),
                "idv-attempt-records",
            )
        return Response(rows)


class DqaViolationsByRule(APIView):
    """US-082b — DQA rule-violations dashboard.

    Aggregates `DqaResult` failure rows (the table populated by
    US-082a's DIH-inline writer) grouped by rule, sorted by
    fail_count descending. Surfaces "which rules fail most often"
    so the System Admin can target enumerator training at the
    questions that cause the most pain.

    Query params:
        window=7d|30d|all          (default 7d)
        severity=blocking|warning|info|all  (default all)
        sub_region_code=<code>     (optional drill-down via the
                                    Household join — same pattern
                                    as US-S15-003 queue panels)

    ABAC: failure rows are scoped via the originating Household's
    sub_region_code. DqaResult.record_id stores either:
      - household ULID (record_type=household), or
      - "<household_ulid>:<line>" (record_type=member).
    Both forms start with the household's ULID, so a prefix match
    against `Household` IDs in scope filters correctly. Orphan
    failures (from `_evaluate_dqa` calls without a stage_id —
    legacy "staged" / "line-N" ids) are invisible to scoped
    operators by construction.

    Response: [{rule_id, rule_label, severity, fail_count,
                last_seen_at}, ...] sorted by fail_count desc.
    """

    def get(self, request):
        base = _dqa_failure_queryset(request)
        if base is None:
            _audit_dashboard_read(request, "dqa_violations", 0)
            return _render(request, [], "dqa-violations")

        # --- aggregate ---
        rows = list(
            base.values("rule_id", "rule__rule_id",
                        "rule__description", "rule__severity")
                .annotate(fail_count=Count("id"), last_seen_at=Max("executed_at"))
                .order_by("-fail_count", "rule__rule_id"),
        )
        out = [{
            "rule_id": r["rule__rule_id"],
            "rule_label": r["rule__description"],
            "severity": r["rule__severity"],
            "fail_count": r["fail_count"],
            "last_seen_at": r["last_seen_at"],
        } for r in rows]
        _audit_dashboard_read(request, "dqa_violations", len(out))
        return _render(request, out, "dqa-violations")


def _dqa_failure_queryset(request):
    """Shared filter/scope logic for the DQA aggregate and its record
    drill-down. Returns None when the caller's scope/drill-down yields
    no visible household universe."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.security.abac import _scoped_codes

    # --- query params ---
    window = request.query_params.get("window", "7d")
    severity = request.query_params.get("severity", "all").lower()
    sub_region_code = (request.query_params.get("sub_region_code") or "").strip()
    rule_id = (request.query_params.get("rule_id") or "").strip()

    # --- time window ---
    base = DqaResult.objects.filter(passed=False).select_related("rule")
    if window != "all":
        try:
            days = int(window.rstrip("d"))
        except ValueError:
            days = 7
        since = timezone.now() - timedelta(days=days)
        base = base.filter(executed_at__gte=since)

    # --- field filters ---
    if severity in ("blocking", "warning", "info"):
        base = base.filter(severity=severity)
    if rule_id:
        base = base.filter(rule__rule_id=rule_id)

    # --- ABAC + optional drill-down ---
    codes = _scoped_codes(request.user)
    if codes is not None:
        if not codes:
            return None
        if sub_region_code:
            if sub_region_code not in codes:
                return None
            code_list = [sub_region_code]
        else:
            code_list = codes
        household_ids = list(
            Household.objects.filter(sub_region_code__in=code_list)
            .values_list("id", flat=True),
        )
        if not household_ids:
            return None
        base = base.filter(_dqa_record_id_scope_q(household_ids))
    elif sub_region_code:
        # Superuser / national drill-down.
        household_ids = list(
            Household.objects.filter(sub_region_code=sub_region_code)
            .values_list("id", flat=True),
        )
        if not household_ids:
            return None
        base = base.filter(_dqa_record_id_scope_q(household_ids))

    return base


def _dqa_record_id_scope_q(household_ids: list[str]):
    """DqaResult.record_id is either '<household_id>' for household rules
    or '<household_id>:<line>' for member rules."""
    from django.db.models import Q

    q = Q(record_id__in=household_ids)
    for household_id in household_ids:
        q |= Q(record_id__startswith=f"{household_id}:")
    return q


class DqaViolationRecordSerializer(serializers.Serializer):
    result_id = serializers.IntegerField()
    rule_id = serializers.CharField()
    rule_label = serializers.CharField()
    severity = serializers.CharField()
    record_type = serializers.CharField()
    record_id = serializers.CharField()
    household_id = serializers.CharField(allow_blank=True)
    household_label = serializers.CharField(allow_blank=True)
    member_line_number = serializers.CharField(allow_blank=True)
    member_name = serializers.CharField(allow_blank=True)
    sub_region_code = serializers.CharField(allow_blank=True)
    source_system_code = serializers.CharField(allow_blank=True)
    connector_name = serializers.CharField(allow_blank=True)
    reason = serializers.CharField()
    executed_at = serializers.DateTimeField()


@extend_schema(
    tags=["rpt"],
    summary="DQA violation record drill-down",
    responses={200: DqaViolationRecordSerializer(many=True)},
)
class DqaViolationRecords(APIView):
    """Specific failed DQA result rows behind the violations dashboard.

    Query params mirror DqaViolationsByRule:
        window=7d|30d|all
        severity=blocking|warning|info|all
        sub_region_code=<code>
        rule_id=<logical rule id, e.g. AC-MEM-SURNAME>

    Supports ?export=csv. The response is intentionally one row per
    DqaResult failure so an operator can inspect or download exactly
    which records are failing a rule.
    """

    def get(self, request):
        base = _dqa_failure_queryset(request)
        if base is None:
            rows = []
        else:
            results = list(base.order_by("-executed_at", "rule__rule_id", "record_id")[:5000])
            household_ids = sorted({
                _dqa_household_id_from_record_id(result.record_id)
                for result in results
                if _dqa_household_id_from_record_id(result.record_id)
            })
            context = _dqa_record_context(household_ids)
            rows = [_dqa_violation_record_row(result, context) for result in results]

        _audit_dashboard_read(request, "dqa_violation_records", len(rows))
        if request.query_params.get("export", "").lower() != "csv":
            return Response(rows)
        return _render_dqa_violation_records_csv(rows)


def _dqa_household_id_from_record_id(record_id: str) -> str:
    return (record_id or "").split(":", 1)[0]


def _dqa_member_line_from_record_id(record_id: str) -> str:
    if ":" not in (record_id or ""):
        return ""
    return record_id.split(":", 1)[1]


def _dqa_record_context(household_ids: list[str]) -> dict:
    from apps.data_management.models import Member
    from apps.ingestion_hub.models import StageRecord

    households = {
        hh.id: hh
        for hh in Household.objects.filter(id__in=household_ids).select_related("village")
    }
    members = {
        (member.household_id, str(member.line_number)): member
        for member in Member.objects.filter(household_id__in=household_ids)
    }
    stages = {
        stage.provisional_registry_id: stage
        for stage in (
            StageRecord.objects
            .filter(provisional_registry_id__in=household_ids)
            .select_related("connector_run__connector__source_system")
        )
    }
    return {"households": households, "members": members, "stages": stages}


def _household_label(household) -> str:
    if household is None:
        return ""
    village = getattr(household, "village", None)
    bits = [str(household.id)]
    if village is not None:
        bits.append(village.name)
    return " / ".join(bits)


def _member_name(member) -> str:
    if member is None:
        return ""
    return " ".join(
        part for part in [member.surname, member.first_name, member.other_name] if part
    )


def _dqa_violation_record_row(result: DqaResult, context: dict) -> dict:
    household_id = _dqa_household_id_from_record_id(result.record_id)
    member_line = _dqa_member_line_from_record_id(result.record_id)
    household = context["households"].get(household_id)
    member = context["members"].get((household_id, member_line))
    stage = context["stages"].get(household_id)
    source_system = ""
    connector_name = ""
    if stage is not None and stage.connector_run_id:
        connector = stage.connector_run.connector
        connector_name = connector.name
        source_system = connector.source_system.code
    return {
        "result_id": result.id,
        "rule_id": result.rule.rule_id,
        "rule_label": result.rule.description,
        "severity": result.severity,
        "record_type": result.record_type,
        "record_id": result.record_id,
        "household_id": household_id,
        "household_label": _household_label(household),
        "member_line_number": member_line,
        "member_name": _member_name(member),
        "sub_region_code": household.sub_region_code if household else "",
        "source_system_code": source_system,
        "connector_name": connector_name,
        "reason": result.reason,
        "executed_at": result.executed_at,
    }


def _render_dqa_violation_records_csv(rows: list[dict]) -> HttpResponse:
    buf = io.StringIO()
    fields = (
        "result_id", "rule_id", "rule_label", "severity", "record_type",
        "record_id", "household_id", "household_label", "member_line_number",
        "member_name", "sub_region_code", "source_system_code", "connector_name",
        "reason", "executed_at",
    )
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            **row,
            "executed_at": row["executed_at"].isoformat() if row.get("executed_at") else "",
        })
    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="dqa-violation-records.csv"'
    )
    return response


# ===========================================================================
# US-S22-DE-10 — detail-entity dashboard tiles
# ===========================================================================


@extend_schema(
    tags=["rpt"],
    summary="Disability prevalence by sub-region (US-S22-DE-10)",
    responses={200: DashboardRowSerializer(many=True)},
)
class DisabilityPrevalenceBySubRegion(APIView):
    """Members with the WG disability flag, grouped by sub-region.

    The Disability row is per-Member; its wg_disability_flag is set
    when ANY Washington Group column reports "03" / "04" (a lot of
    difficulty / cannot do at all). This tile reports the count of
    flagged members per sub-region — the % is computed on the
    client against the per-sub-region member denominator from the
    households-by-sub-region tile.

    ABAC: the underlying Member queryset is scoped via the
    household's sub_region_code. Soft-deleted members are excluded.
    """

    def get(self, request):
        scoped_hh = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        rows = list(
            Disability.objects
            .filter(
                wg_disability_flag=True,
                is_deleted=False,
                member__is_deleted=False,
                member__household__in=scoped_hh,
            )
            .values(
                "member__household__sub_region_code",
                "member__household__sub_region__name",
            )
            .annotate(count=Count("id"))
            .order_by("member__household__sub_region_code"),
        )
        out = [
            {
                "key": r["member__household__sub_region_code"] or "(unset)",
                "label": (
                    r["member__household__sub_region__name"]
                    or r["member__household__sub_region_code"]
                    or "(unset)"
                ),
                "count": r["count"],
            }
            for r in rows
        ]
        _audit_dashboard_read(request, "disability_prevalence_by_sub_region", len(out))
        return _render(request, out, "disability-prevalence-by-sub-region")


# WFP FCS thresholds — Food Consumption Score (0–112) maps to:
#   poor:        0–21
#   borderline:  21.5–35
#   acceptable:  > 35
# See WFP Food Consumption Score (FCS) Indicators §2.1.
_FCS_BANDS = (
    ("poor",       "Poor (0–21)",           Decimal("0"),    Decimal("21")),
    ("borderline", "Borderline (21.5–35)", Decimal("21.01"), Decimal("35")),
    ("acceptable", "Acceptable (>35)",     Decimal("35.01"), Decimal("999")),
)


@extend_schema(
    tags=["rpt"],
    summary="Food Consumption Score distribution by band (US-S22-DE-10)",
    responses={200: DashboardRowSerializer(many=True)},
)
class FoodConsumptionScoreDistribution(APIView):
    """Households grouped by WFP Food Consumption Score band.

    Every Household has at most one FoodConsumption row; the WFP-
    weighted fcs_score is computed on save per ADR-0022. Households
    without a FoodConsumption row don't appear — they pre-date the
    rollout and need their canonical_payload re-promoted.

    ABAC: filtered by the operator's sub_region_code scope.
    """

    def get(self, request):
        scoped_hh = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        rows = (
            FoodConsumption.objects
            .filter(is_deleted=False, household__in=scoped_hh)
            .values_list("fcs_score", flat=True)
        )
        bucket = {band[0]: 0 for band in _FCS_BANDS}
        for score in rows:
            for slug, _label, low, high in _FCS_BANDS:
                if low <= score <= high:
                    bucket[slug] += 1
                    break
        out = [
            {"key": slug, "label": label, "count": bucket[slug]}
            for slug, label, _low, _high in _FCS_BANDS
        ]
        _audit_dashboard_read(request, "fcs_distribution", len(out))
        return _render(request, out, "fcs-distribution")
