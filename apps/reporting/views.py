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

from django.db.models import Count
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
        return Response(out)


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
        return Response(out)


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
        return Response(out)
