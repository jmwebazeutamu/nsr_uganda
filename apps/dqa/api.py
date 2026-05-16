from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from .models import DqaResult, DqaRule


class DqaRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DqaRule
        fields = (
            "id", "rule_id", "version", "description", "severity",
            "applicability_filter", "expression", "error_message_template",
            "effective_from", "effective_to", "status",
            "author", "approved_by", "approved_at",
            # DQA-1 lifecycle audit fields.
            "approval_note", "rejection_reason", "submitted_at",
        )


class DqaResultSerializer(serializers.ModelSerializer):
    rule_id = serializers.CharField(source="rule.rule_id", read_only=True)
    rule_version = serializers.IntegerField(source="rule.version", read_only=True)

    class Meta:
        model = DqaResult
        fields = (
            "id", "rule", "rule_id", "rule_version",
            "record_type", "record_id",
            "passed", "severity", "reason", "executed_at",
        )


@extend_schema_view(
    list=extend_schema(tags=["dqa"], summary="List DQA rules"),
    retrieve=extend_schema(tags=["dqa"], summary="Retrieve a DQA rule"),
)
class DqaRuleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DqaRule.objects.all().order_by("rule_id", "-version")
    serializer_class = DqaRuleSerializer
    filterset_fields = ["status", "severity", "rule_id"]


@extend_schema_view(
    list=extend_schema(tags=["dqa"], summary="List DQA evaluation results"),
    retrieve=extend_schema(tags=["dqa"], summary="Retrieve a DQA result"),
)
class DqaResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DqaResult.objects.all().order_by("-executed_at")
    serializer_class = DqaResultSerializer
    filterset_fields = ["passed", "severity", "record_type"]
