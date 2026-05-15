from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from apps.security.audit_views import AuditReadMixin

from .models import DdupModelVersion, MatchPair, MergeDecision


class DdupModelVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DdupModelVersion
        fields = ("id", "version", "description", "config", "status",
                  "author", "approved_by", "approved_at", "effective_from")


class MatchPairSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatchPair
        fields = ("id", "record_type", "record_a_id", "record_b_id",
                  "tier", "match_reason", "composite_score", "per_field_scores",
                  "model_version", "status", "created_at", "updated_at")


class MergeDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MergeDecision
        fields = ("id", "match_pair", "action",
                  "surviving_record_id", "losing_record_id",
                  "chosen_field_values", "reason",
                  "decided_by", "decided_at",
                  "reverse_window_until", "reversed_at", "reversed_by")


@extend_schema_view(
    list=extend_schema(tags=["ddup"], summary="List DDUP model versions"),
    retrieve=extend_schema(tags=["ddup"], summary="Retrieve a DDUP model version"),
)
class DdupModelVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DdupModelVersion.objects.all().order_by("-version")
    serializer_class = DdupModelVersionSerializer


@extend_schema_view(
    list=extend_schema(tags=["ddup"], summary="List dedup match pairs"),
    retrieve=extend_schema(tags=["ddup"], summary="Retrieve a match pair"),
)
class MatchPairViewSet(AuditReadMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "match_pair"
    queryset = MatchPair.objects.all().order_by("-created_at")
    serializer_class = MatchPairSerializer
    filterset_fields = ["status", "tier", "record_type"]


@extend_schema_view(
    list=extend_schema(tags=["ddup"], summary="List merge decisions"),
    retrieve=extend_schema(tags=["ddup"], summary="Retrieve a merge decision"),
)
class MergeDecisionViewSet(AuditReadMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "merge_decision"
    queryset = MergeDecision.objects.all().order_by("-decided_at")
    serializer_class = MergeDecisionSerializer
