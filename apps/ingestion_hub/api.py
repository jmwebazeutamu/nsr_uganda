from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.security.abac import HouseholdIdScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .models import (
    Connector,
    ConnectorRun,
    SourceSystem,
    StageRecord,
)
from .services import (
    DihError,
    StageEditError,
    edit_stage_record,
    process_stage_record,
    promote_stage_record,
    quarantine_stage_record,
    reject_stage_record,
    submit_walk_in_capture,
)

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
            "last_edited_by", "last_edited_at",
            "sla_deadline", "created_at", "updated_at",
        )


class PromoteRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class RejectRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField()


class ProcessRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64, default="system")
    allow_fast_track = serializers.BooleanField(default=True)


class EditRequestSerializer(serializers.Serializer):
    """In-place correction of a StageRecord's canonical_payload."""
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField()
    field_changes = serializers.DictField(
        child=serializers.JSONField(),
        allow_empty=False,
        help_text=(
            "Dotted-path → new-value. Only the whitelisted paths in "
            "apps.ingestion_hub.services.EDITABLE_PATH_PATTERNS may "
            "be edited (gps_* and members.<i>.<safe-field>)."
        ),
    )


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


class StageRecordViewSet(
    AuditReadMixin, HouseholdIdScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet,
):
    """Stage records carry the provisional Registry ID and the canonical
    payload. The /promote and /reject actions are the public surface for
    NSR Unit operator decisions (AC-DIH-PROMOTE-ATOMIC, AC-DIH-REJECT-VOID).

    Pre-promotion StageRecords have a provisional_registry_id that
    doesn't yet match a Household, so the IN-subquery returns nothing
    for scoped operators — pre-promotion rows are NSR-Unit-visibility
    only, matching SAD §4.6 (NSR Unit reviews the DIH queue).
    """

    scope_field_path = "provisional_registry_id"

    audit_entity_type = "stage_record"
    queryset = StageRecord.objects.all().order_by("-created_at")
    serializer_class = StageRecordSerializer
    filterset_fields = ["state"]

    def get_queryset(self):
        # US-S15-003 — optional ?sub_region_code= drill-down. Used by
        # the home dashboard queue panel when an operator narrows to
        # a region. Pre-promotion stages reference a Household by
        # provisional_registry_id, so we IN-subquery into the matching
        # Household IDs.
        #
        # The ?state= filter has to be applied manually because
        # django-filter isn't installed, so filterset_fields silently
        # no-ops. Without this the DIH review tab would show every
        # stage record including the ones already promoted — see
        # feedback memory.
        qs = super().get_queryset()
        params = self.request.query_params
        state = params.get("state")
        if state:
            # Comma-separated supported so the DIH tab can express
            # "show everything except promoted/rejected" with one URL.
            states = [s.strip() for s in state.split(",") if s.strip()]
            if states:
                qs = qs.filter(state__in=states)
        sr = params.get("sub_region_code")
        if sr:
            from apps.data_management.models import Household
            hh_ids = list(
                Household.objects.filter(sub_region_code=sr)
                                  .values_list("id", flat=True),
            )
            qs = qs.filter(provisional_registry_id__in=hh_ids)
        return qs

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
        summary="Run the staging gates and route the stage record",
        description=(
            "Pipeline per SAD §4.6.2: DQA -> IDV -> DDUP. Routes the stage "
            "to QUALITY_FAILED / IDV_PENDING / DDUP_REVIEW / PENDING_PROMOTION, "
            "or auto-promotes when AC-DIH-FT-AUTO conditions are met. "
            "Idempotent on terminal states (PROMOTED / REJECTED / QUARANTINED)."
        ),
        request=ProcessRequestSerializer,
        responses={200: StageRecordSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        ser = ProcessRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        try:
            process_stage_record(
                stage,
                actor=ser.validated_data["actor"],
                allow_fast_track=ser.validated_data["allow_fast_track"],
            )
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

    @extend_schema(
        tags=["dih"],
        summary="Archive a quality-failed stage record",
        description=(
            "Moves a quality_failed StageRecord to the archive "
            "(state=quarantined). One-way — quarantined records cannot "
            "be promoted into the registry. Reason is mandatory and "
            "persisted on the audit trail."
        ),
        request=RejectRequestSerializer,
        responses={
            200: StageRecordSerializer,
            400: OpenApiResponse(description="not quality_failed, or reason missing"),
        },
    )
    @action(detail=True, methods=["post"], url_path="quarantine")
    def quarantine(self, request, pk=None):
        ser = RejectRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        try:
            quarantine_stage_record(
                stage,
                actor=ser.validated_data["actor"],
                reason=ser.validated_data["reason"],
            )
        except DihError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        stage.refresh_from_db()
        return Response(self.get_serializer(stage).data)

    @extend_schema(
        tags=["dih"],
        summary="Edit a stage record's canonical payload",
        description=(
            "Sparse correction of the staged payload before promotion. "
            "Only whitelisted paths may be edited (gps_lat/lng/accuracy_m "
            "and members.<i>.<surname|first_name|other_name|date_of_birth|"
            "age_years|telephone_1|telephone_2>). NIN, consent, and the "
            "geographic chain are NOT editable — those require re-capture. "
            "AC-DIH-EDIT-NO-SELF-APPROVE: the editor cannot also promote."
        ),
        request=EditRequestSerializer,
        responses={
            200: StageRecordSerializer,
            400: OpenApiResponse(description="state guard / whitelist / shape violation"),
        },
    )
    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request, pk=None):
        ser = EditRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        try:
            edit_stage_record(
                stage,
                field_changes=ser.validated_data["field_changes"],
                actor=ser.validated_data["actor"],
                reason=ser.validated_data["reason"],
            )
        except StageEditError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        stage.refresh_from_db()
        return Response(self.get_serializer(stage).data)


# ---------------------------------------------------------------------------
# Walk-in submission endpoint (Slice A — US-S23-WALKIN)
#
# Top-level POST that creates a brand-new StageRecord from the
# household-capture wizard. Not a detail action on the viewset
# because the caller has no StageRecord ID yet.

@extend_schema(
    tags=["dih"],
    summary="Submit a household captured at a parish office",
    description=(
        "Atomic: opens a ConnectorRun under the seeded PARISH-WALKIN "
        "source, lands the canonical payload, stages it with a "
        "provisional Registry ID. Response carries the "
        "provisional_registry_id so the receipt slip can show it."
    ),
    request=None,  # canonical payload schema lives in the questionnaire spec
    responses={
        201: StageRecordSerializer,
        400: OpenApiResponse(description="payload invalid or parish source not seeded"),
    },
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def walk_in_submit(request):
    payload = request.data
    if not isinstance(payload, dict) or not payload:
        return Response(
            {"detail": "payload must be a non-empty object"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    actor = (request.user.username or "").strip() or "anonymous"
    try:
        stage = submit_walk_in_capture(payload, actor=actor)
    except DihError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        StageRecordSerializer(stage).data,
        status=status.HTTP_201_CREATED,
    )
