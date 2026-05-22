from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import AuditEvent, OperatorScope, ScopeLevel


class AuditEventSerializer(serializers.ModelSerializer):
    prev_hash = serializers.SerializerMethodField()
    self_hash = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = (
            "id", "occurred_at", "actor_id", "actor_kind", "action",
            "entity_type", "entity_id", "field_changes", "reason",
            "ip_address", "user_agent", "prev_hash", "self_hash",
        )

    def get_prev_hash(self, obj) -> str | None:
        return obj.prev_hash.hex() if obj.prev_hash else None

    def get_self_hash(self, obj) -> str | None:
        return obj.self_hash.hex() if obj.self_hash else None


@extend_schema_view(
    list=extend_schema(tags=["security"], summary="List audit events"),
    retrieve=extend_schema(tags=["security"], summary="Retrieve an audit event"),
)
class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Append-only audit chain. SAD §8.4."""

    queryset = AuditEvent.objects.all().order_by("-occurred_at")
    serializer_class = AuditEventSerializer
    # entity_id added in US-S12-002 so the React household-detail
    # Audit tab can fetch a single entity's chain in one round-trip.
    filterset_fields = ["action", "entity_type", "actor_kind", "entity_id"]


@extend_schema(
    tags=["security"],
    summary="Identity of the currently-authenticated user",
    description=(
        "Returns the request user's username, display name, role hint, "
        "and (if any) the partner organisation derived from their "
        "PARTNER-level OperatorScope. The topbar uses this so it can "
        "show 'opm-analyst · OPM' instead of falling back to the "
        "hardcoded persona fixture in screens-home.jsx."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    """GET /api/v1/security/users/me/ — identity of the current session."""
    u = request.user
    # Derive the role hint from scope + flags. Operator/NSR-unit covers
    # superusers and anyone with no PARTNER scope; partner-analyst is
    # anyone bound to a PARTNER-level OperatorScope.
    partner_codes = list(
        OperatorScope.objects.filter(
            user=u, active=True, scope_level=ScopeLevel.PARTNER,
        ).exclude(scope_code="").values_list("scope_code", flat=True),
    )
    role = "partner-analyst" if partner_codes else (
        "nsr-unit" if u.is_superuser else "operator"
    )
    partner_payload = None
    if partner_codes:
        # ADR-0013: canonical Partner lives in apps.partners. Resolve
        # the first active partner the user is bound to (multi-partner
        # accounts are out of MVP scope).
        from apps.partners.models import Partner
        p = Partner.objects.filter(code__in=partner_codes).first()
        if p is not None:
            partner_payload = {
                "id": str(p.id),
                "code": p.code,
                "name": p.name,
                "tone": p.tone or "neutral",
            }
    return Response({
        "username": u.username,
        "display_name": (u.get_full_name() or u.username) if u.is_authenticated else "",
        "is_authenticated": True,
        "is_superuser": bool(u.is_superuser),
        "is_staff": bool(u.is_staff),
        "role": role,
        "partner": partner_payload,
    })
