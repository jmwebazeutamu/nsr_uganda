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
        from datetime import timedelta

        from django.db.models import Max
        from django.utils import timezone

        from apps.security.abac import _scoped_codes

        # --- query params ---
        window = request.query_params.get("window", "7d")
        severity = request.query_params.get("severity", "all").lower()
        sub_region_code = (request.query_params.get("sub_region_code") or "").strip()

        # --- time window ---
        base = DqaResult.objects.filter(passed=False)
        if window != "all":
            try:
                days = int(window.rstrip("d"))
            except ValueError:
                days = 7
            since = timezone.now() - timedelta(days=days)
            base = base.filter(executed_at__gte=since)

        # --- severity filter ---
        if severity in ("blocking", "warning", "info"):
            base = base.filter(severity=severity)

        # --- ABAC + optional drill-down ---
        codes = _scoped_codes(request.user)
        if codes is not None:
            if not codes:
                base = base.none()
            else:
                if sub_region_code:
                    if sub_region_code not in codes:
                        return _render(request, [], "dqa-violations")
                    code_list = [sub_region_code]
                else:
                    code_list = codes
                household_ids = list(
                    Household.objects.filter(sub_region_code__in=code_list)
                    .values_list("id", flat=True),
                )
                if not household_ids:
                    return _render(request, [], "dqa-violations")
                # record_id is either the household ULID exactly
                # (record_type=household) OR "<hh>:<line>"
                # (record_type=member). startswith covers both.
                # Use a precomputed prefix list to keep this a
                # single SQL IN-vs-LIKE pass — SQLite doesn't have
                # array-prefix matching so we expand member-prefix
                # IDs as <hh_id>: + LIKE, but for the test set
                # (≤2 sub-regions) the IN clause on a derived
                # member-id-prefix list is fine.
                from django.db.models import Q
                q = Q(record_id__in=household_ids)
                for hh in household_ids:
                    q |= Q(record_id__startswith=f"{hh}:")
                base = base.filter(q)
        elif sub_region_code:
            # Superuser drilling down: narrow without short-circuit.
            hh_ids = list(
                Household.objects.filter(sub_region_code=sub_region_code)
                .values_list("id", flat=True),
            )
            if not hh_ids:
                return _render(request, [], "dqa-violations")
            from django.db.models import Q
            q = Q(record_id__in=hh_ids)
            for hh in hh_ids:
                q |= Q(record_id__startswith=f"{hh}:")
            base = base.filter(q)

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
