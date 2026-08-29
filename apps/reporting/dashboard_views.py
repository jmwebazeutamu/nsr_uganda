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

from drf_spectacular.utils import extend_schema
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
    from apps.grievance.models import Grievance, GrievanceStatus
    base = Grievance.objects.exclude(
        status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
    )
    if tier:
        base = base.filter(tier=tier)
    hh_ids = _scoped_household_ids(user, region=region)
    if hh_ids is None:
        return base.count()
    if not hh_ids:
        return 0
    return base.filter(household_id__in=hh_ids).count()


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
