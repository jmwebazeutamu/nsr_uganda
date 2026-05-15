from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.abac import MatchPairScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .models import DdupModelVersion, MatchPair, MergeDecision
from .services import MergeError, reverse_merge_decision


class DdupModelVersionSerializer(serializers.ModelSerializer):
    # Feedback counters computed live from MergeDecision joins
    # (US-S10-002). Read-only — there's no setter on the model side.
    auto_merge_count = serializers.IntegerField(read_only=True)
    manual_merge_count = serializers.IntegerField(read_only=True)
    auto_reverse_count = serializers.IntegerField(read_only=True)
    manual_reverse_count = serializers.IntegerField(read_only=True)
    auto_reverse_rate = serializers.FloatField(read_only=True, allow_null=True)

    class Meta:
        model = DdupModelVersion
        fields = ("id", "version", "description", "config", "status",
                  "author", "approved_by", "approved_at", "effective_from",
                  "auto_merge_count", "manual_merge_count",
                  "auto_reverse_count", "manual_reverse_count",
                  "auto_reverse_rate")


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
                  "reverse_window_until", "reversed_at", "reversed_by",
                  "reversed_reason")


class _ReverseRequest(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField()


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
class MatchPairViewSet(
    AuditReadMixin, MatchPairScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet,
):
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
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(
        tags=["ddup"],
        summary="Reverse a MERGE decision within its 30-day window",
        description=("Calls apps.ddup.services.reverse_merge_decision. The "
                     "loser member is restored, surviving overrides rolled "
                     "back from pre_merge_snapshot, household head pointers "
                     "restored, pair flipped back to PENDING. Guards: action "
                     "must be MERGE, not already reversed, within window, "
                     "reason non-empty (DPPA accountability)."),
        request=_ReverseRequest,
        responses={
            200: MergeDecisionSerializer,
            400: OpenApiResponse(
                description="Guard violation (window closed, already "
                            "reversed, non-MERGE action, missing reason).",
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse(self, request, pk=None):
        ser = _ReverseRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        decision = self.get_object()
        try:
            reverse_merge_decision(
                decision,
                actor=ser.validated_data["actor"],
                reason=ser.validated_data["reason"],
            )
        except MergeError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        decision.refresh_from_db()
        return Response(self.get_serializer(decision).data)
