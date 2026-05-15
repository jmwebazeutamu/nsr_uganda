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

from django.db.models import Count
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_management.models import Household
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


@extend_schema(
    tags=["rpt"],
    summary="Household count grouped by sub-region",
    responses={200: DashboardRowSerializer(many=True)},
)
class HouseholdsBySubRegion(APIView):
    """Counts of Household rows grouped by sub_region_code. Rows the
    operator cannot see are excluded BEFORE aggregation — a sub-region
    operator sees exactly one bucket (their own); national sees all."""

    def get(self, request):
        scoped = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        rows = list(
            scoped.values("sub_region_code")
            .annotate(count=Count("id"))
            .order_by("sub_region_code"),
        )
        out = [{"key": r["sub_region_code"] or "(unset)", "count": r["count"]}
               for r in rows]
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
