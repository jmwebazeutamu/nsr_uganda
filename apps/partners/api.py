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

from django.conf import settings
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from apps.data_management.serializer_labels import attach_label_methodfields
from apps.security.audit_views import AuditReadMixin

from .choice_field_map import MODEL_FIELDS
from .models import Partner


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
