"""DRF API for the partners module — US-S23-008.

Endpoints in this commit:

  GET    /api/v1/partners/                    list, with q/type/status/sector filters
  POST   /api/v1/partners/                    create (gated by PARTNERS_MODULE_ENABLED)
  GET    /api/v1/partners/{id}/               retrieve
  PATCH  /api/v1/partners/{id}/               update (gated)

Dashboard + DSA + signature endpoints land in US-S23-009 / 010.

Per ADR-0010, every coded field on the response carries both the
raw `<field>` and the resolved `<field>_label` companion (auto-
attached via apps.data_management.serializer_labels).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count, Sum
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.data_management.serializer_labels import attach_label_methodfields
from apps.security.audit_views import AuditReadMixin

from .choice_field_map import MODEL_FIELDS
from .models import DataSharingAgreement, Partner, PartnerUsageDaily


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = (
            "id", "code", "name", "registration_no", "country", "website",
            "primary_email",
            # Coded fields and their resolved labels (attached below).
            "type", "type_label",
            "sector", "sector_label",
            "status", "status_label",
            "tone", "tone_label",
            "lead_user", "logo_short", "note",
            "last_activity_at", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "created_at", "updated_at", "last_activity_at",
        )


attach_label_methodfields(PartnerSerializer, MODEL_FIELDS["Partner"])


class _PartnersWriteFlagPermission(permissions.BasePermission):
    """Read endpoints are open to any authenticated caller; write
    endpoints respect the PARTNERS_MODULE_ENABLED feature flag.
    Refuses with 403 when the flag is off."""

    message = "Partners module is gated off (PARTNERS_MODULE_ENABLED)."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not getattr(settings, "PARTNERS_MODULE_ENABLED", False):
            raise PermissionDenied(self.message)
        return True


@extend_schema_view(
    list=extend_schema(
        tags=["partners"], summary="List partners",
        description="Filters: q (search name/code), type, status, sector.",
    ),
    retrieve=extend_schema(tags=["partners"], summary="Retrieve a partner"),
    create=extend_schema(tags=["partners"], summary="Create a partner"),
    partial_update=extend_schema(tags=["partners"], summary="Update a partner"),
)
class PartnerViewSet(AuditReadMixin, viewsets.ModelViewSet):
    """CRUD for partner organisations. Writes are flag-gated."""

    audit_entity_type = "partner"
    queryset = Partner.objects.all().order_by("-last_activity_at", "code")
    serializer_class = PartnerSerializer
    permission_classes = [permissions.IsAuthenticated, _PartnersWriteFlagPermission]
    # Disable PUT — the spec only authorises PATCH (partial update).
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q)
        for key in ("type", "status", "sector"):
            v = params.get(key)
            if v:
                qs = qs.filter(**{key: v})
        return qs


# --- Dashboard aggregation endpoints (US-S23-009) ---------------------------
#
# These read against Partner + DataSharingAgreement + PartnerUsageDaily and
# return shapes the JSX dashboard widgets consume directly. Each endpoint
# is intentionally a single SQL aggregation; the dashboard refreshes them
# on a polling interval so we keep query cost cheap.


def _rolling_window(days: int = 30) -> tuple[date, date]:
    """Return (start_date, today) — inclusive of today."""
    today = date.today()
    return today - timedelta(days=days - 1), today


@extend_schema(
    tags=["partners"],
    summary="Partner-registry KPIs (US-S23-009)",
    description=(
        "Counts that drive the four KPI cards on the partners "
        "dashboard: active partners, active DSAs, rows delivered "
        "in the trailing 30 days, and DSA budget breaches."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_summary(request):
    start, end = _rolling_window(30)

    # Active partners: anything that is currently delivering (active,
    # renewing, alert) or under contract (onboarding/provider counts
    # are surfaced separately in the dashboard but not here).
    active_partners = Partner.objects.filter(
        status__in=("active", "renewing", "alert"),
    ).count()

    onboarding_partners = Partner.objects.filter(status="onboarding").count()

    active_dsas = DataSharingAgreement.objects.filter(
        status="active",
    ).count()

    expiring_30 = DataSharingAgreement.objects.filter(
        status__in=("active", "expiring"),
        effective_to__isnull=False,
        effective_to__lte=date.today() + timedelta(days=30),
        effective_to__gte=date.today(),
    ).count()

    usage = (
        PartnerUsageDaily.objects
        .filter(day__gte=start, day__lte=end)
        .aggregate(total=Sum("rows_delivered"))
    )
    rows_30d = usage["total"] or 0

    # Distinct partners that delivered any rows in the window.
    active_requesters = (
        PartnerUsageDaily.objects
        .filter(day__gte=start, day__lte=end, rows_delivered__gt=0)
        .values("partner").distinct().count()
    )

    # Budget breaches — partners whose 30d sum exceeds their DSA budget.
    # Only DSAs with a non-null monthly_row_budget count (providers skip).
    over_budget = 0
    for partner in Partner.objects.exclude(status="provider"):
        budget_total = (
            DataSharingAgreement.objects
            .filter(partner=partner, status="active",
                    monthly_row_budget__isnull=False)
            .aggregate(b=Sum("monthly_row_budget"))["b"] or 0
        )
        if budget_total <= 0:
            continue
        used = (
            PartnerUsageDaily.objects
            .filter(partner=partner, day__gte=start, day__lte=end)
            .aggregate(u=Sum("rows_delivered"))["u"] or 0
        )
        if used > budget_total:
            over_budget += 1

    return Response({
        "active_partners": active_partners,
        "onboarding_partners": onboarding_partners,
        "active_dsas": active_dsas,
        "dsas_expiring_30d": expiring_30,
        "rows_delivered_30d": rows_30d,
        "active_requesters_30d": active_requesters,
        "dsas_over_budget_30d": over_budget,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    })


@extend_schema(
    tags=["partners"],
    summary="DSAs by days-until-expiry (US-S23-009 / RenewalTimeline)",
    parameters=[
        OpenApiParameter(
            name="days", type=OpenApiTypes.INT, required=False,
            description="Window in days (default 120).",
        ),
    ],
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_renewals(request):
    try:
        days = int(request.query_params.get("days") or 120)
    except ValueError:
        days = 120
    cutoff = date.today() + timedelta(days=days)
    qs = (
        DataSharingAgreement.objects
        .filter(
            effective_to__isnull=False,
            effective_to__gte=date.today(),
            effective_to__lte=cutoff,
        )
        .select_related("partner")
        .order_by("effective_to")
    )
    items = [
        {
            "dsa_id": d.id,
            "reference": d.reference,
            "partner_code": d.partner.code,
            "partner_name": d.partner.name,
            "partner_tone": d.partner.tone,
            "effective_to": d.effective_to.isoformat() if d.effective_to else None,
            "days_until_expiry": (d.effective_to - date.today()).days,
        }
        for d in qs
    ]
    return Response({"window_days": days, "items": items})


@extend_schema(
    tags=["partners"],
    summary="Partners-by-sector mix (US-S23-009 / SectorMix)",
    description=(
        "Returns one row per `partner_sector` code: partner count and "
        "trailing-30d rows delivered. Sectors with zero partners are "
        "omitted."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_sector_mix(request):
    start, end = _rolling_window(30)
    sectors = (
        Partner.objects.values("sector", "tone")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    out = []
    for row in sectors:
        sector_code = row["sector"] or ""
        if not sector_code:
            continue
        rows_delivered = (
            PartnerUsageDaily.objects
            .filter(partner__sector=sector_code,
                    day__gte=start, day__lte=end)
            .aggregate(s=Sum("rows_delivered"))["s"] or 0
        )
        out.append({
            "sector_code": sector_code,
            "tone": row["tone"] or "neutral",
            "partner_count": row["count"],
            "rows_delivered_30d": rows_delivered,
        })
    return Response({"items": out})


@extend_schema(
    tags=["partners"],
    summary="Top N requesters by 30d row volume (US-S23-009)",
    parameters=[
        OpenApiParameter(
            name="n", type=OpenApiTypes.INT, required=False,
            description="Number of top requesters (default 5).",
        ),
    ],
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_top_consumers(request):
    try:
        n = max(1, int(request.query_params.get("n") or 5))
    except ValueError:
        n = 5
    start, end = _rolling_window(30)
    rows = (
        PartnerUsageDaily.objects
        .filter(day__gte=start, day__lte=end, rows_delivered__gt=0)
        .values("partner", "partner__code", "partner__name", "partner__tone")
        .annotate(total=Sum("rows_delivered"))
        .order_by("-total")[:n]
    )
    items = [
        {
            "partner_id": r["partner"],
            "partner_code": r["partner__code"],
            "partner_name": r["partner__name"],
            "partner_tone": r["partner__tone"] or "neutral",
            "rows_delivered_30d": r["total"],
        }
        for r in rows
    ]
    return Response({"window_days": 30, "items": items})
