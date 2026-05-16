from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from .models import AuditEvent


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
