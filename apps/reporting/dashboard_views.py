"""Operator dashboard counts (US-S12-001).

Single round-trip endpoint that returns the live counts the home
screen's KPI cards display. ABAC-scoped — each count respects the
same `scope_q_for_field` / `_scoped_codes` plumbing the row-level
dashboards use. Counts are integers; the React side maps them onto
the role-aware KPI dictionary in screens-home.jsx.

Why one endpoint instead of seven: the home screen mounts cold
every navigation; chaining seven fetches across DIH / UPD / GRM /
DRS APIs would dominate latency. One aggregator hides the join cost
behind one network round-trip + lets the audit chain emit one
`dashboard_read` event instead of seven (less noise for the
anomaly-detection feed).
"""

from __future__ import annotations

from datetime import timedelta

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_management.models import Household
from apps.security.abac import _scoped_codes, scope_q_for_field
from apps.security.audit import emit as emit_audit
from apps.security.audit_views import _client_ip


class OperatorKpisSerializer(serializers.Serializer):
    # Echoes ?region= back to the client so the home screen can
    # show "Filtered: <region>" without having to track its own
    # request state (US-S14-004).
    region = serializers.CharField(allow_blank=True, required=False)
    households_total = serializers.IntegerField()
    households_with_pmt = serializers.IntegerField()
    stages_pending_promotion = serializers.IntegerField()
    stages_ddup_review = serializers.IntegerField()
    stages_quality_failed = serializers.IntegerField()
    stages_idv_pending = serializers.IntegerField()
    change_requests_pending = serializers.IntegerField()
    grievances_open = serializers.IntegerField()
    grievances_l2_open = serializers.IntegerField()
    data_requests_pending_approval = serializers.IntegerField()
    data_requests_delivered_7d = serializers.IntegerField()
    # Partner-side, like the DRS counts: national regardless of the
    # geographic drill-down, because a partner is not in a sub-region.
    partners_total = serializers.IntegerField()
    programmes_active = serializers.IntegerField()


def _scoped_household_ids(user, *, region: str | None = None):
    """Return the list of Household IDs visible to `user`, or None for
    unscoped (national / superuser). Used by the count helpers that
    can't reach Household directly via a scope FK.

    When `region` is provided it narrows the result to just that
    sub-region — used by US-S14-004's home-screen drill-down. If
    the region isn't in the user's scope the result is an empty
    list (caller treats this as "no data visible"). National
    operators (`codes is None`) can drill into any region.
    """
    codes = _scoped_codes(user)
    if region:
        if codes is not None and region not in codes:
            return []
        codes = [region]
    if codes is None:
        return None
    if not codes:
        return []
    return list(
        Household.objects.filter(sub_region_code__in=codes)
                          .values_list("id", flat=True),
    )


def _count_pending_stages(user, state: str, *, region: str | None = None) -> int:
    from apps.ingestion_hub.models import StageRecord
    base = StageRecord.objects.filter(state=state)
    hh_ids = _scoped_household_ids(user, region=region)
    if hh_ids is None:
        return base.count()
    if not hh_ids:
        return 0
    # Pre-promotion stages reference Households via provisional_
    # registry_id; the same-ULID promotion contract (ADR-0002) means
    # the IN-subquery is a direct equality once promoted, and pre-
    # promotion rows are invisible to sub-region scope per StageRecord
    # ABAC semantics (S2-003 / S2-008).
    return base.filter(provisional_registry_id__in=hh_ids).count()


def _count_change_requests(user, *, region: str | None = None) -> int:
    from apps.update_workflow.models import ChangeRequest, ChangeStatus, EntityType
    base = ChangeRequest.objects.filter(status=ChangeStatus.PENDING_APPROVAL)
    hh_ids = _scoped_household_ids(user, region=region)
    if hh_ids is None:
        return base.count()
    if not hh_ids:
        return 0
    # ChangeRequest stores the subject in (entity_type, entity_id) —
    # not a dedicated household_id field. We count household-level
    # CRs only here; member-level CRs would need a Member→Household
    # join which would dominate dashboard latency. The home-screen
    # KPI is a triage hint, not a precise count.
    return base.filter(
        entity_type=EntityType.HOUSEHOLD,
        entity_id__in=hh_ids,
    ).count()


def _count_open_grievances(
    user, *, tier: str | None = None, region: str | None = None,
) -> int:
    from apps.grievance.models import ACTIVE_GRIEVANCE_STATUSES, Grievance
    from apps.grievance.visibility import visible_grievances

    # The same rule the workbench list uses. These two disagreed: the
    # tile counted through _scoped_household_ids (national scope -> all)
    # while the list asked whether you were a superuser or in the "GRM
    # Officer" group. One screen, two numbers.
    #
    # And the same definition of "open" the badge and the workbench use
    # — it was spelled out here as an exclude, there as a filter, and a
    # third time in the browser.
    base = visible_grievances(user, Grievance.objects.all()).filter(
        status__in=ACTIVE_GRIEVANCE_STATUSES,
    )
    if tier:
        base = base.filter(tier=tier)
    if region:
        # Home-screen drill-down. Narrowing inside what the user may
        # already see, never widening it.
        hh_ids = _scoped_household_ids(user, region=region)
        if hh_ids is None:
            return base.filter(sub_region_code=region).count()
        if not hh_ids:
            return 0
        return base.filter(household_id__in=hh_ids).count()
    return base.count()


def _count_data_requests(user, status_value: str) -> int:
    from apps.data_requests.models import DataRequest
    base = DataRequest.objects.filter(status=status_value)
    # DRS scope is partner-side ABAC (S4-001), not geographic — but
    # for an operator-facing aggregate the national count is what
    # the DPO / NSR Unit Coordinator wants; sub-region operators
    # don't interact with DRS.
    return base.count()


def _count_delivered_recent(user, days: int) -> int:
    from django.utils import timezone

    from apps.data_requests.models import DataRequest, RequestStatus
    since = timezone.now() - timedelta(days=days)
    return DataRequest.objects.filter(
        status=RequestStatus.DELIVERED, delivered_at__gte=since,
    ).count()


def _count_partners() -> int:
    """Registered partners. Not geographic and not ABAC-scoped by
    sub-region — a partner organisation is national, and the DRS counts
    above already set that precedent."""
    from apps.partners.models import Partner
    return Partner.objects.count()


def _count_active_programmes() -> int:
    from apps.partners.models import Programme
    return Programme.objects.filter(status="active").count()


def compute_operator_kpis(user, *, region: str | None = None) -> dict:
    """The home-screen KPI payload for `user`, ABAC-scoped.

    Lifted out of OperatorKpisView so the server-rendered landing page
    and the JSON endpoint share one implementation. Callers are
    responsible for emitting their own `dashboard_read` AuditEvent —
    this function does no auditing, so it stays usable from a context
    that has no HttpRequest.
    """
    from apps.ingestion_hub.models import StageRecordState

    # US-S14-004 — optional region drill-down. An out-of-scope region
    # yields zeros rather than a 403: the caller still gets the shape
    # of the dashboard, ABAC just returns nothing for that region.
    codes = _scoped_codes(user)
    region_out_of_scope = bool(region and codes is not None and region not in codes)

    scoped_hh = Household.objects.filter(scope_q_for_field(user, "sub_region_code"))
    if region and not region_out_of_scope:
        scoped_hh = scoped_hh.filter(sub_region_code=region)
    if region_out_of_scope:
        households_total = 0
        households_with_pmt = 0
    else:
        households_total = scoped_hh.count()
        households_with_pmt = scoped_hh.filter(
            current_pmt_score__isnull=False,
        ).count()

    # DRS counts are partner-side (not geographic) — the region filter
    # doesn't apply. They stay national even when drilling down.
    return {
        "region": region or "",
        "households_total": households_total,
        "households_with_pmt": households_with_pmt,
        "stages_pending_promotion": _count_pending_stages(
            user, StageRecordState.PENDING_PROMOTION, region=region,
        ),
        "stages_ddup_review": _count_pending_stages(
            user, StageRecordState.DDUP_REVIEW, region=region,
        ),
        "stages_quality_failed": _count_pending_stages(
            user, StageRecordState.QUALITY_FAILED, region=region,
        ),
        "stages_idv_pending": _count_pending_stages(
            user, StageRecordState.IDV_PENDING, region=region,
        ),
        "change_requests_pending": _count_change_requests(user, region=region),
        "grievances_open": _count_open_grievances(user, region=region),
        "grievances_l2_open": _count_open_grievances(user, tier="L2", region=region),
        "data_requests_pending_approval": _count_data_requests(user, "submitted"),
        "data_requests_delivered_7d": _count_delivered_recent(user, 7),
        "partners_total": _count_partners(),
        "programmes_active": _count_active_programmes(),
    }


# ---------------------------------------------------------------------------
# Home-screen charts (US-S24-HOME-CHARTS)
#
# One aggregator, for the same reason compute_operator_kpis is one: the
# home screen mounts cold on every navigation, and five separate
# dashboard endpoints would be five round-trips plus five
# `dashboard_read` audit events for a single page view.
#
# Separate from compute_operator_kpis, though, because these are heavier
# aggregates over Member and DqaResult. The KPI strip must paint
# immediately; the charts can arrive a beat later rather than holding
# the numbers hostage to a join.
#
# Every series follows the sub-region drill-down, like the KPIs do, and
# each carries its own `region` echo so the rendered chart can state the
# scope it is showing. A printed chart that silently covers one
# sub-region while reading as national is the same class of error as the
# duplicated region filter — it is wrong and it looks authoritative.


def _band_series(counts: dict[str, int]) -> list[dict]:
    """Every band, in policy order, zero-filled.

    Omitting a band with no households would quietly redraw the chart's
    axis between one wave and the next, so "no households are in extreme
    poverty" and "we stopped measuring extreme poverty" would look
    identical. Bands present in the data but absent from the vocabulary
    are appended rather than dropped — an unrecognised value is a fact,
    not something to hide.
    """
    from apps.pmt.models import Band

    series = [
        {"key": band.value,
         "label": band.value.replace("_", " ").capitalize(),
         "count": counts.get(band.value, 0)}
        for band in Band
    ]
    known = {band.value for band in Band}
    for key, n in sorted(counts.items()):
        if key and key not in known:
            series.append({"key": key, "label": key, "count": n})
    unscored = counts.get("", 0) + counts.get(None, 0)
    if unscored:
        series.append({"key": "", "label": "Not scored", "count": unscored})
    return series


def _scoped_households(user, *, region: str | None):
    """Households visible to `user`, narrowed to `region` when given.
    Returns None when the drill-down is outside the caller's scope —
    callers render empty rather than raising."""
    codes = _scoped_codes(user)
    if region and codes is not None and region not in codes:
        return None
    qs = Household.objects.filter(scope_q_for_field(user, "sub_region_code"))
    if region:
        qs = qs.filter(sub_region_code=region)
    return qs


def households_by_pmt_band(user, *, region: str | None = None) -> list[dict]:
    """Scored households grouped by their current vulnerability band."""
    from django.db.models import Count

    scoped = _scoped_households(user, region=region)
    if scoped is None:
        return _band_series({})
    rows = (
        scoped.values("current_vulnerability_band")
        .annotate(n=Count("id")).order_by()
    )
    return _band_series({r["current_vulnerability_band"]: r["n"] for r in rows})


def members_by_pmt_band(user, *, region: str | None = None) -> list[dict]:
    """Members grouped by THEIR HOUSEHOLD'S band.

    A member has no band of their own — the PMT scores a household. This
    answers "how many people are in households at each band", which is
    the figure that matters for programme sizing and is not derivable
    from the household chart, because household size varies sharply by
    band.
    """
    from django.db.models import Count

    from apps.data_management.models import Member

    codes = _scoped_codes(user)
    if region and codes is not None and region not in codes:
        return _band_series({})
    qs = Member.objects.filter(
        scope_q_for_field(user, "sub_region_code"), is_deleted=False,
    )
    if region:
        qs = qs.filter(sub_region_code=region)
    rows = (
        qs.values("household__current_vulnerability_band")
        .annotate(n=Count("id")).order_by()
    )
    return _band_series(
        {r["household__current_vulnerability_band"]: r["n"] for r in rows},
    )


def dih_backlog_by_reason(user, *, region: str | None = None) -> list[dict]:
    """Staged records held before promotion, by what is holding them.

    The size of the quality backlog and its composition in one series:
    a queue of 40 held on DQA failures is a different day's work from 40
    held awaiting NIRA.
    """
    from apps.ingestion_hub.models import StageRecordState

    reasons = [
        (StageRecordState.QUALITY_FAILED, "DQA failure"),
        (StageRecordState.DDUP_REVIEW, "Duplicate review"),
        (StageRecordState.IDV_PENDING, "Identity (NIRA)"),
        (StageRecordState.PENDING_PROMOTION, "Awaiting promotion"),
    ]
    return [
        {"key": str(state), "label": label,
         "count": _count_pending_stages(user, state, region=region)}
        for state, label in reasons
    ]


def dqa_failures_by_rule(
    user, *, region: str | None = None, limit: int = 8, days: int = 30,
) -> list[dict]:
    """Which rules are failing most — where the quality problem is.

    Only failures are persisted (passes would grow the table at intake
    rate x every active rule), so this is a count of failures, not a
    failure RATE. Labelled as such on the chart; a bar here does not
    mean "this rule fails often", it means "this rule produced this many
    findings".
    """
    from django.db.models import Count
    from django.db.models.functions import Substr
    from django.utils import timezone

    from apps.dqa.models import DqaResult

    since = timezone.now() - timedelta(days=days)
    base = (
        DqaResult.objects
        .filter(passed=False, executed_at__gte=since)
        .select_related("rule")
    )

    hh_ids = _scoped_household_ids(user, region=region)
    if hh_ids is not None:
        if not hh_ids:
            return []
        # DqaResult.record_id is '<household_id>' for a household rule
        # and '<household_id>:<line>' for a member rule, and carries no
        # FK to scope through. Every externally visible id is a
        # 26-character ULID (ADR-0002), so the household is the first 26
        # characters in both shapes.
        #
        # Deliberately NOT reusing reporting.views._dqa_record_id_scope_q,
        # which ORs one `record_id__startswith` per household id — fine
        # over a few hundred households, a query with millions of OR
        # clauses at national load.
        base = base.annotate(_hh=Substr("record_id", 1, 26)).filter(_hh__in=hh_ids)

    rows = (
        base.values("rule__rule_id", "rule__severity")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {"key": r["rule__rule_id"] or "(unknown rule)",
         "label": r["rule__rule_id"] or "(unknown rule)",
         "severity": r["rule__severity"] or "",
         "count": r["n"]}
        for r in rows
    ]


def enrolments_by_programme(user, *, region: str | None = None) -> list[dict]:
    """Active enrolments per programme.

    ProgrammeEnrolment is keyed on household, so this counts HOUSEHOLDS
    enrolled, not people. The chart says so: conflating the two would
    overstate every programme's reach by a factor of household size.
    """
    from django.db.models import Count

    from apps.referral.models import ProgrammeEnrolment

    codes = _scoped_codes(user)
    if region and codes is not None and region not in codes:
        return []
    qs = ProgrammeEnrolment.objects.filter(
        scope_q_for_field(user, "household__sub_region_code"),
        status="active",
    )
    if region:
        qs = qs.filter(household__sub_region_code=region)
    rows = (
        qs.values("programme__code", "programme__name")
        .annotate(n=Count("id")).order_by("-n")
    )
    return [
        {"key": r["programme__code"] or "",
         "label": r["programme__name"] or r["programme__code"] or "(unnamed)",
         "count": r["n"]}
        for r in rows
    ]


def compute_home_charts(user, *, region: str | None = None) -> dict:
    """Every home-screen chart series in one payload."""
    return {
        "region": region or "",
        "households_by_pmt_band": households_by_pmt_band(user, region=region),
        "members_by_pmt_band": members_by_pmt_band(user, region=region),
        "dih_backlog_by_reason": dih_backlog_by_reason(user, region=region),
        "dqa_failures_by_rule": dqa_failures_by_rule(user, region=region),
        "enrolments_by_programme": enrolments_by_programme(user, region=region),
    }


def households_by_sub_region(user, *, limit: int = 9) -> list[dict]:
    """Household counts per sub-region, ABAC-scoped, largest first.

    Same scoping rule as HouseholdsBySubRegion in views.py: rows the
    operator cannot see are excluded BEFORE aggregation, so a
    sub-region-scoped operator sees only their own bar.
    """
    from django.db.models import Count

    rows = (
        Household.objects
        .filter(scope_q_for_field(user, "sub_region_code"))
        .exclude(sub_region_code="")
        .exclude(sub_region_code__isnull=True)
        .values("sub_region_code", "sub_region__name")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {
            "code": r["sub_region_code"],
            "name": r["sub_region__name"] or r["sub_region_code"],
            "count": r["n"],
        }
        for r in rows
    ]


@extend_schema(
    tags=["rpt"],
    summary="Operator dashboard KPIs in one round-trip",
    responses={200: OperatorKpisSerializer()},
)
class OperatorKpisView(APIView):
    """One-shot aggregator for the home-screen KPI cards. Per-user
    ABAC-scoped; emits one AuditEvent."""

    def get(self, request):
        region = (request.query_params.get("region") or "").strip() or None
        payload = compute_operator_kpis(request.user, region=region)
        emit_audit(
            "dashboard_read", "rpt_dashboard", "operator_kpis",
            actor=getattr(request.user, "username", "") or "anonymous",
            reason=(
                f"households_total={payload['households_total']} "
                f"region={region or 'all'}"
            ),
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(payload)


@extend_schema(
    tags=["rpt"],
    summary="Home-screen chart series in one round-trip",
    responses={200: OpenApiResponse(description="Chart series keyed by chart name")},
)
class HomeChartsView(APIView):
    """Five aggregate series for the home screen's chart band.

    Split from OperatorKpisView on purpose: these are heavier joins over
    Member and DqaResult, and the KPI strip should not wait on them.
    One AuditEvent for the set, matching the KPI endpoint's rationale.
    """

    def get(self, request):
        region = (request.query_params.get("region") or "").strip() or None
        payload = compute_home_charts(request.user, region=region)
        emit_audit(
            "dashboard_read", "rpt_dashboard", "home_charts",
            actor=getattr(request.user, "username", "") or "anonymous",
            reason=f"region={region or 'all'}",
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(payload)
