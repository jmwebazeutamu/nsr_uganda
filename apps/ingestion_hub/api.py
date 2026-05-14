from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    Connector,
    ConnectorRun,
    SourceSystem,
    StageRecord,
)
from .services import DihError, promote_stage_record, reject_stage_record


# --- Serializers -----------------------------------------------------------

class SourceSystemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceSystem
        fields = ("id", "code", "name", "kind", "description", "is_active")


class ConnectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connector
        fields = ("id", "source_system", "name", "config", "is_active")


class ConnectorRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorRun
        fields = ("id", "connector", "started_at", "finished_at", "status",
                  "records_received", "records_landed", "records_staged",
                  "records_promoted", "records_quarantined", "records_rejected", "note")


class StageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = StageRecord
        fields = (
            "id", "provisional_registry_id",
            "raw_landing", "connector_run", "mapping_rule_version",
            "canonical_payload", "state",
            "dqa_summary", "ddup_candidates", "idv_outcome",
            "promoted_household_id", "promoted_at",
            "rejected_reason", "rejected_at", "rejected_by",
            "sla_deadline", "created_at", "updated_at",
        )


class PromoteRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class RejectRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField()


# --- ViewSets --------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["dih"], summary="List source systems"),
    retrieve=extend_schema(tags=["dih"], summary="Retrieve a source system"),
)
class SourceSystemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SourceSystem.objects.all().order_by("code")
    serializer_class = SourceSystemSerializer


@extend_schema_view(
    list=extend_schema(tags=["dih"], summary="List connectors"),
    retrieve=extend_schema(tags=["dih"], summary="Retrieve a connector"),
)
class ConnectorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Connector.objects.all().order_by("source_system", "name")
    serializer_class = ConnectorSerializer


@extend_schema_view(
    list=extend_schema(tags=["dih"], summary="List connector runs"),
    retrieve=extend_schema(tags=["dih"], summary="Retrieve a connector run"),
)
class ConnectorRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConnectorRun.objects.all().order_by("-started_at")
    serializer_class = ConnectorRunSerializer
    filterset_fields = ["status", "connector"]


class StageRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """Stage records carry the provisional Registry ID and the canonical
    payload. The /promote and /reject actions are the public surface for
    NSR Unit operator decisions (AC-DIH-PROMOTE-ATOMIC, AC-DIH-REJECT-VOID)."""

    queryset = StageRecord.objects.all().order_by("-created_at")
    serializer_class = StageRecordSerializer
    filterset_fields = ["state"]

    @extend_schema(
        tags=["dih"],
        summary="Promote a stage record into the registry",
        description=(
            "Atomic: the provisional Registry ID becomes the confirmed "
            "Registry ID; Household + Members are written; an AuditEvent is "
            "emitted; the call is idempotent on replay."
        ),
        request=PromoteRequestSerializer,
        responses={200: StageRecordSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="promote")
    def promote(self, request, pk=None):
        ser = PromoteRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        try:
            promote_stage_record(stage, actor=ser.validated_data["actor"],
                                 reason=ser.validated_data.get("reason", ""))
        except DihError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        stage.refresh_from_db()
        return Response(self.get_serializer(stage).data)

    @extend_schema(
        tags=["dih"],
        summary="Reject a stage record",
        description="Voids the provisional Registry ID and records the reason (AC-DIH-REJECT-VOID).",
        request=RejectRequestSerializer,
        responses={200: StageRecordSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        ser = RejectRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        try:
            reject_stage_record(stage, actor=ser.validated_data["actor"],
                                reason=ser.validated_data["reason"])
        except DihError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        stage.refresh_from_db()
        return Response(self.get_serializer(stage).data)
