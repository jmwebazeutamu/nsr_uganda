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


def _scoped_household_ids(user):
    """Return the list of Household IDs visible to `user`, or None for
    unscoped (national / superuser). Used by the count helpers that
    can't reach Household directly via a scope FK."""
    codes = _scoped_codes(user)
    if codes is None:
        return None
    if not codes:
        return []
    return list(
        Household.objects.filter(sub_region_code__in=codes)
                          .values_list("id", flat=True),
    )


def _count_pending_stages(user, state: str) -> int:
    from apps.ingestion_hub.models import StageRecord
    base = StageRecord.objects.filter(state=state)
    hh_ids = _scoped_household_ids(user)
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


def _count_change_requests(user) -> int:
    from apps.update_workflow.models import ChangeRequest, ChangeRequestStatus
    base = ChangeRequest.objects.filter(status=ChangeRequestStatus.PENDING_APPROVAL)
    hh_ids = _scoped_household_ids(user)
    if hh_ids is None:
        return base.count()
    if not hh_ids:
        return 0
    return base.filter(household_id__in=hh_ids).count()


def _count_open_grievances(user, *, tier: str | None = None) -> int:
    from apps.grievance.models import Grievance, GrievanceStatus
    base = Grievance.objects.exclude(
        status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
    )
    if tier:
        base = base.filter(tier=tier)
    hh_ids = _scoped_household_ids(user)
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


@extend_schema(
    tags=["rpt"],
    summary="Operator dashboard KPIs in one round-trip",
    responses={200: OperatorKpisSerializer()},
)
class OperatorKpisView(APIView):
    """One-shot aggregator for the home-screen KPI cards. Per-user
    ABAC-scoped; emits one AuditEvent."""

    def get(self, request):
        from apps.ingestion_hub.models import StageRecordState

        scoped_hh = Household.objects.filter(
            scope_q_for_field(request.user, "sub_region_code"),
        )
        households_total = scoped_hh.count()
        households_with_pmt = scoped_hh.filter(
            current_pmt_score__isnull=False,
        ).count()

        payload = {
            "households_total": households_total,
            "households_with_pmt": households_with_pmt,
            "stages_pending_promotion": _count_pending_stages(
                request.user, StageRecordState.PENDING_PROMOTION,
            ),
            "stages_ddup_review": _count_pending_stages(
                request.user, StageRecordState.DDUP_REVIEW,
            ),
            "stages_quality_failed": _count_pending_stages(
                request.user, StageRecordState.QUALITY_FAILED,
            ),
            "stages_idv_pending": _count_pending_stages(
                request.user, StageRecordState.IDV_PENDING,
            ),
            "change_requests_pending": _count_change_requests(request.user),
            "grievances_open": _count_open_grievances(request.user),
            "grievances_l2_open": _count_open_grievances(request.user, tier="L2"),
            "data_requests_pending_approval": _count_data_requests(
                request.user, "submitted",
            ),
            "data_requests_delivered_7d": _count_delivered_recent(request.user, 7),
        }
        emit_audit(
            "dashboard_read", "rpt_dashboard", "operator_kpis",
            actor=getattr(request.user, "username", "") or "anonymous",
            reason=f"households_total={households_total}",
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(payload)
