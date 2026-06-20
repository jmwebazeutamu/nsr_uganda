from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.security.abac import HouseholdIdScopedQuerysetMixin
from apps.security.audit import emit as emit_audit
from apps.security.audit_views import AuditReadMixin

from .models import (
    Connector,
    ConnectorRun,
    SourceSystem,
    StageRecord,
    StageRecordState,
)
from .permissions import IsDihTrigger
from .services import (
    DeleteError,
    DihError,
    StageEditError,
    TriggerError,
    delete_connector_run,
    edit_stage_record,
    process_stage_record,
    promote_stage_record,
    quarantine_stage_record,
    record_promote_dqa_block,
    reject_stage_record,
    resolve_ddup_as_duplicate,
    resolve_ddup_as_not_duplicate,
    resolve_idv_pending,
    resolve_pinned_form_uid,
    submit_walk_in_capture,
    trigger_connector_pull,
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
    # Enriched for the System Admin > Connector runs dashboard
    # (US-S11-022). The dashboard labels each row with the source code
    # ("KOBO-PILOT") + connector name ("kobo-aRpVGbQ…"); without these
    # fields the table only sees an opaque FK and can't render the
    # operator-visible string. select_related on the viewset queryset
    # keeps this O(1).
    source_code = serializers.CharField(
        source="connector.source_system.code", read_only=True,
    )
    connector_name = serializers.CharField(
        source="connector.name", read_only=True,
    )

    class Meta:
        model = ConnectorRun
        fields = ("id", "connector", "connector_name", "source_code",
                  "run_type", "started_at", "finished_at", "status",
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
    # US-S11-044 — documented justification for clearing
    # REJECT_WITH_OVERRIDE intra-household DQA violations during
    # promotion. Recorded via dqa.household.override AuditEvent.
    override_reason = serializers.CharField(required=False, allow_blank=True)


class RejectRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField()


class ProcessRequestSerializer(serializers.Serializer):
    actor = serializers.CharField(max_length=64, default="system")
    allow_fast_track = serializers.BooleanField(default=True)


class ResolveIdvRequestSerializer(serializers.Serializer):
    """Operator decision on an IDV_PENDING record (US-S11-031). Mirrors
    the reject/promote shape — actor + reason are mandatory because
    the audit trail is the only paper record of the override."""
    actor = serializers.CharField(max_length=64)
    decision = serializers.ChoiceField(choices=["accept", "reject"])
    reason = serializers.CharField()


class ResolveDdupRequestSerializer(serializers.Serializer):
    """Operator decision on a DDUP_REVIEW stage record. `decision`:
    - 'duplicate'      → stage IS the same person as `surviving_member_id`;
                         provisional ID is voided per AC-DIH-REJECT-VOID,
                         survivor recorded in audit. No new Member created.
    - 'not_duplicate'  → operator dismisses the candidate(s); stage
                         advances to PENDING_PROMOTION. Dismissed
                         candidates land in the audit chain.

    `surviving_member_id` is required only for 'duplicate' decisions
    and must match one of the discovered candidates on the stage."""
    actor = serializers.CharField(max_length=64)
    decision = serializers.ChoiceField(choices=["duplicate", "not_duplicate"])
    reason = serializers.CharField()
    surviving_member_id = serializers.CharField(
        max_length=26, required=False, allow_blank=True,
    )


class BulkStageActionRequestSerializer(serializers.Serializer):
    """Common request shape for the two bulk DIH-queue actions
    (US-S11-041): bulk-promote + bulk-resolve-idv. stage_ids are
    the StageRecord ULIDs the operator ticked in the queue; the
    backend filters to the rows whose state matches the action."""

    stage_ids = serializers.ListField(
        child=serializers.CharField(max_length=26),
        allow_empty=False,
        max_length=500,
        help_text="Up to 500 StageRecord ULIDs per call.",
    )
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class BulkStageActionResultSerializer(serializers.Serializer):
    """One per-row outcome returned by a bulk action."""
    stage_id = serializers.CharField()
    ok = serializers.BooleanField()
    state = serializers.CharField(allow_blank=True)
    detail = serializers.CharField(allow_blank=True)


class BulkStageActionResponseSerializer(serializers.Serializer):
    succeeded = serializers.IntegerField()
    skipped = serializers.IntegerField()
    results = BulkStageActionResultSerializer(many=True)


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


class TriggerRunRequestSerializer(serializers.Serializer):
    """Operator-initiated Kobo pull from the System Admin console."""
    dry_run = serializers.BooleanField(
        default=False,
        help_text=(
            "If true, the connector run is opened as run_type=TEST, "
            "credentials + list_forms are exercised, and submission "
            "rows are counted but not landed. Useful for verifying "
            "credentials + mapping before a real pull."
        ),
    )
    form_uid = serializers.CharField(
        required=False, allow_blank=True, max_length=64,
        help_text=(
            "Optional Kobo form UID. When omitted, the connector picks "
            "the first deployed form (or the previously-pulled form "
            "stored on Connector.config). US-S11-022 added this so "
            "operators can disambiguate when a workspace carries "
            "multiple deployed forms (e.g. the v1 legacy alongside "
            "the current questionnaire)."
        ),
    )
    batch_cap = serializers.IntegerField(
        required=False, min_value=1, max_value=500,
        help_text=(
            "Per-pull row cap (US-S11-033). Defaults to "
            "services.TRIGGER_PULL_BATCH_CAP (50) when omitted. "
            "Bounded at 500 to keep the synchronous request short — "
            "larger backlogs should run via the scheduled Celery beat."
        ),
    )


class FormListItemSerializer(serializers.Serializer):
    """One row in the form-picker dropdown. Mirrors the dict shape
    KoboConnector.list_forms returns, plus the US-S11-026 `pinned`
    flag — exactly one form (or zero) in the list will have it set
    to true, marking which form the trigger would pull if the
    operator submitted without a form_uid. The modal defaults the
    dropdown selection to it."""
    uid = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    asset_type = serializers.CharField(allow_blank=True, required=False)
    deployed = serializers.BooleanField()
    pinned = serializers.BooleanField(default=False)


class DeleteRunRequestSerializer(serializers.Serializer):
    """Operator-supplied reason for deleting a ConnectorRun. Optional
    field-wise but the audit trail benefits when present — operators
    are nudged toward filling it via the confirm modal's required
    field on the client side."""
    reason = serializers.CharField(
        required=False, allow_blank=True, max_length=512,
    )


class DeleteRunResponseSerializer(serializers.Serializer):
    """Cascade counts returned by POST /connector-runs/{id}/delete/."""
    deleted_run_id = serializers.CharField()
    source_code = serializers.CharField(allow_blank=True)
    fast_track_samples_deleted = serializers.IntegerField()
    promotion_decisions_deleted = serializers.IntegerField()
    quarantine_rows_deleted = serializers.IntegerField()
    stage_records_deleted = serializers.IntegerField()
    raw_landings_deleted = serializers.IntegerField()


class TriggerRunResponseSerializer(serializers.Serializer):
    """Summary returned by POST /source-systems/{id}/trigger-run/."""
    run_id = serializers.CharField()
    source_code = serializers.CharField()
    form_uid = serializers.CharField()
    form_name = serializers.CharField()
    dry_run = serializers.BooleanField()
    landed = serializers.IntegerField()
    staged = serializers.IntegerField()
    quarantined = serializers.IntegerField()
    errored = serializers.IntegerField()
    skipped_duplicate = serializers.IntegerField()
    stage_states = serializers.DictField(child=serializers.IntegerField())
    geo_backfill_created = serializers.IntegerField()
    batch_cap_hit = serializers.BooleanField()
    note = serializers.CharField()


# --- ViewSets --------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["dih"], summary="List source systems"),
    retrieve=extend_schema(tags=["dih"], summary="Retrieve a source system"),
)
class SourceSystemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SourceSystem.objects.all().order_by("code")
    serializer_class = SourceSystemSerializer

    @extend_schema(
        tags=["dih"],
        summary="Trigger an operator-initiated connector pull (US-S11-021)",
        description=(
            "Pulls submissions for this source system through the same "
            "code path as the `pull_kobo_submissions_action` admin "
            "action, so console and admin behave identically. Kobo-only "
            "for v1. Guarded by IsDihTrigger (Sys Admin or NSR Unit "
            "Coordinator) and refuses when another run is "
            "pending/running, when no active DPA exists "
            "(AC-DIH-DPA-REQUIRED), or when the source has no "
            "credential or no deployed form. A `dih.connector.triggered` "
            "AuditEvent is emitted regardless of outcome."
        ),
        request=TriggerRunRequestSerializer,
        responses={
            200: TriggerRunResponseSerializer,
            400: OpenApiResponse(description="precondition unmet"),
            403: OpenApiResponse(description="caller lacks trigger permission"),
        },
    )
    @action(
        detail=True, methods=["post"], url_path="trigger-run",
        permission_classes=[IsDihTrigger],
    )
    def trigger_run(self, request, pk=None):
        ser = TriggerRunRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        source = self.get_object()
        actor = (getattr(request.user, "username", "") or "").strip() or "admin"
        dry_run = ser.validated_data["dry_run"]
        form_uid = ser.validated_data.get("form_uid", "") or None
        batch_cap_arg = ser.validated_data.get("batch_cap")

        # Emit the trigger audit first so a downstream failure still
        # leaves a paper trail of the attempt. The outcome is added in
        # a follow-up `trigger_failed`/`trigger_succeeded` event below.
        emit_audit(
            "dih.connector.triggered", "source_system", source.id,
            actor=actor,
            reason=(
                f"console-initiated pull (dry_run={dry_run}, "
                f"form_uid={form_uid or '*default*'}, "
                f"batch_cap={batch_cap_arg if batch_cap_arg is not None else '*default*'})"
            ),
        )
        # Only pass batch_cap when the caller specified it — falls
        # back to the service's TRIGGER_PULL_BATCH_CAP default otherwise.
        pull_kwargs = {"actor": actor, "dry_run": dry_run, "form_uid": form_uid}
        if batch_cap_arg is not None:
            pull_kwargs["batch_cap"] = batch_cap_arg
        try:
            result = trigger_connector_pull(source, **pull_kwargs)
        except TriggerError as exc:
            emit_audit(
                "dih.connector.trigger_rejected", "source_system", source.id,
                actor=actor, reason=str(exc),
            )
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        emit_audit(
            "dih.connector.trigger_succeeded", "connector_run", result["run_id"],
            actor=actor, reason=result["note"],
        )
        return Response(TriggerRunResponseSerializer(result).data)

    @extend_schema(
        tags=["dih"],
        summary="List deployed forms for a Kobo SourceSystem (US-S11-022)",
        description=(
            "Returns the upstream form catalogue that an operator can "
            "select from in the Run-connector modal. Kobo-only for v1 "
            "— non-Kobo kinds 400. Guarded by IsDihTrigger so the data "
            "isn't exposed beyond the operator surface that uses it."
        ),
        responses={
            200: FormListItemSerializer(many=True),
            400: OpenApiResponse(description="non-Kobo / missing credentials"),
            403: OpenApiResponse(description="caller lacks trigger permission"),
        },
    )
    @action(
        detail=True, methods=["get"], url_path="forms",
        permission_classes=[IsDihTrigger],
    )
    def forms(self, request, pk=None):
        from .connection_test import CredentialMissingError, credentials_for
        from .connectors.base import get_connector
        from .models import SourceSystemKind

        source = self.get_object()
        if source.kind != SourceSystemKind.KOBO:
            return Response(
                {"detail": f"{source.code}: only Kobo sources expose a form list"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        connector_impl = get_connector(source.code)
        if connector_impl is None or connector_impl.list_forms is None:
            return Response(
                {"detail": f"{source.code}: no live connector registered"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            creds = credentials_for(source)
        except CredentialMissingError as exc:
            return Response(
                {"detail": f"{source.code}: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            forms = connector_impl.list_forms(creds)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"{source.code}: list_forms failed: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Mark the form the trigger would pull if no form_uid is
        # supplied. Modal uses this to default the dropdown selection
        # so what the operator sees matches what the server would do.
        pinned_uid = resolve_pinned_form_uid(source)
        for f in forms:
            f["pinned"] = (pinned_uid is not None and f.get("uid") == pinned_uid)
        return Response(FormListItemSerializer(forms, many=True).data)


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
    queryset = (
        ConnectorRun.objects
        .select_related("connector__source_system")
        .order_by("-started_at")
    )
    serializer_class = ConnectorRunSerializer
    filterset_fields = ["status", "connector"]

    @extend_schema(
        tags=["dih"],
        summary="Delete a ConnectorRun + all dependents (US-S11-023)",
        description=(
            "Hard-delete a ConnectorRun and every dependent row "
            "(FastTrackAuditSample → PromotionDecision → Quarantine "
            "→ StageRecord → RawLanding → ConnectorRun). All FKs are "
            "PROTECT so the order matters; the service walks them in "
            "a single atomic transaction.\n\n"
            "Refuses when: the run is PENDING/RUNNING (race the "
            "worker), records_promoted > 0, or any StageRecord on "
            "the run is in state=PROMOTED (preserves the Household "
            "audit-lineage chain documented in AC-DIH-LINEAGE).\n\n"
            "Permission: IsDihTrigger (Sys Admin + NSR Unit "
            "Coordinator), matching the trigger surface — if you can "
            "launch a pull, you can undo a bad one. Emits a "
            "`dih.connector.run_deleted` AuditEvent with the cascade "
            "counts."
        ),
        request=DeleteRunRequestSerializer,
        responses={
            200: DeleteRunResponseSerializer,
            400: OpenApiResponse(description="run still running / has promoted records"),
            403: OpenApiResponse(description="caller lacks IsDihTrigger permission"),
        },
    )
    @action(
        detail=True, methods=["post"], url_path="delete",
        permission_classes=[IsDihTrigger],
    )
    def delete_run(self, request, pk=None):
        ser = DeleteRunRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        run = self.get_object()
        actor = (getattr(request.user, "username", "") or "").strip() or "admin"
        reason = ser.validated_data.get("reason", "") or ""
        try:
            counts = delete_connector_run(run, actor=actor, reason=reason)
        except DeleteError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(DeleteRunResponseSerializer(counts).data)


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
        # US-S11-044 — pass override_reason through so the operator
        # can clear REJECT_WITH_OVERRIDE violations with documented
        # justification (audited via dqa.household.override).
        from apps.dqa.pipeline import (
            DqaBlockError,
            DqaRejectWithOverrideError,
        )
        try:
            promote_stage_record(
                stage,
                actor=ser.validated_data["actor"],
                reason=ser.validated_data.get("reason", ""),
                override_reason=ser.validated_data.get("override_reason", ""),
            )
        except DqaBlockError as e:
            # Surface the block on the stage so the Decision panel + status
            # report it (the promote txn rolled back, leaving the record at
            # its prior state with a stale summary otherwise).
            blocked = record_promote_dqa_block(
                stage, actor=ser.validated_data["actor"], codes=e.codes,
            )
            return Response(
                {
                    "detail": str(e), "kind": "dqa_block",
                    "codes": e.codes, "evaluation_id": e.evaluation_id,
                    "state": blocked.state,
                    "dqa_summary": blocked.dqa_summary,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except DqaRejectWithOverrideError as e:
            return Response(
                {
                    "detail": str(e), "kind": "dqa_reject_with_override",
                    "codes": e.codes, "evaluation_id": e.evaluation_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
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
        summary="Resolve an IDV_PENDING stage record (US-S11-031)",
        description=(
            "Operator decision on a record stuck at IDV_PENDING after "
            "NIRA returned service_unavailable / no_match / mismatch / "
            "bad_format. `decision=accept` overrides IDV with "
            "`manual_accept`, runs DDUP discovery (which was skipped "
            "in the original gate run), and routes to PENDING_PROMOTION "
            "or DDUP_REVIEW depending on the candidates. "
            "`decision=reject` delegates to the reject path so the "
            "provisional ID is voided per AC-DIH-REJECT-VOID. Refuses "
            "when state != IDV_PENDING (no double-resolve)."
        ),
        request=ResolveIdvRequestSerializer,
        responses={
            200: StageRecordSerializer,
            400: OpenApiResponse(description="not idv_pending / reason missing / bad decision"),
        },
    )
    @action(detail=True, methods=["post"], url_path="resolve-idv")
    def resolve_idv(self, request, pk=None):
        ser = ResolveIdvRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        try:
            resolve_idv_pending(
                stage,
                actor=ser.validated_data["actor"],
                reason=ser.validated_data["reason"],
                decision=ser.validated_data["decision"],
            )
        except DihError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        stage.refresh_from_db()
        return Response(self.get_serializer(stage).data)

    @extend_schema(
        tags=["dih"],
        summary="Resolve a DDUP_REVIEW stage record",
        description=(
            "Operator decision on a DDUP_REVIEW stage. `decision=duplicate` "
            "voids the provisional ID per AC-DIH-REJECT-VOID and records "
            "`surviving_member_id` in the audit chain. `decision=not_duplicate` "
            "advances the stage to PENDING_PROMOTION and records the "
            "dismissed candidates. Refuses when state != DDUP_REVIEW (no "
            "double-resolve). Bridges the gap between DIH staging-side "
            "dedup discovery and the registry's MatchPair workflow — no "
            "MatchPair row is written since there's no Member id for the "
            "stage yet."
        ),
        request=ResolveDdupRequestSerializer,
        responses={
            200: StageRecordSerializer,
            400: OpenApiResponse(
                description=(
                    "not ddup_review / reason too short / unknown "
                    "surviving_member_id / surviving_member_id not in candidates"
                ),
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="resolve-ddup")
    def resolve_ddup(self, request, pk=None):
        ser = ResolveDdupRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = self.get_object()
        decision = ser.validated_data["decision"]
        try:
            if decision == "duplicate":
                resolve_ddup_as_duplicate(
                    stage,
                    actor=ser.validated_data["actor"],
                    reason=ser.validated_data["reason"],
                    surviving_member_id=(
                        ser.validated_data.get("surviving_member_id") or ""
                    ),
                )
            else:
                resolve_ddup_as_not_duplicate(
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

    # ───────────────────────────────────────────────────────────────
    # US-S11-041 — Bulk operations for the NSR Unit DIH review queue.
    # Each iterates per row, continues past per-row errors, returns
    # a uniform results array so the UI can toast a coherent summary.
    # ───────────────────────────────────────────────────────────────

    def _bulk_iterate(self, ids, action_fn):
        """Resolve each id through self.get_queryset() (honours ABAC)
        and invoke action_fn(stage). action_fn returns (ok, detail).
        Returns the results list + succeeded/skipped counts."""
        results = []
        succeeded = 0
        skipped = 0
        qs = self.get_queryset().filter(id__in=ids)
        # Preserve operator-submitted order so the response lines up
        # with what they ticked.
        by_id = {s.id: s for s in qs}
        for sid in ids:
            stage = by_id.get(sid)
            if stage is None:
                results.append({
                    "stage_id": sid, "ok": False, "state": "",
                    "detail": "not found in your scope or already removed",
                })
                skipped += 1
                continue
            ok, detail = action_fn(stage)
            stage.refresh_from_db()
            results.append({
                "stage_id": sid, "ok": ok,
                "state": stage.state, "detail": detail,
            })
            if ok:
                succeeded += 1
            else:
                skipped += 1
        return results, succeeded, skipped

    @extend_schema(
        tags=["dih"],
        summary="Bulk-promote selected stage records (US-S11-041)",
        description=(
            "Iterates over `stage_ids`, calling promote_stage_record "
            "per row. Rows whose state isn't PENDING_PROMOTION are "
            "skipped + reported; the call doesn't 4xx so the operator "
            "gets back a coherent results array. Each successful "
            "promotion writes its own AuditEvent + PromotionDecision."
        ),
        request=BulkStageActionRequestSerializer,
        responses={
            200: BulkStageActionResponseSerializer,
            400: OpenApiResponse(description="bad request body"),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk-promote")
    def bulk_promote(self, request):
        ser = BulkStageActionRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = ser.validated_data["actor"]
        reason = ser.validated_data.get("reason", "") or ""

        def _run(stage):
            if stage.state != StageRecordState.PENDING_PROMOTION:
                return False, f"state is '{stage.state}', not pending_promotion"
            try:
                promote_stage_record(stage, actor=actor, reason=reason)
            except DihError as exc:
                return False, str(exc)
            return True, "promoted"

        results, succeeded, skipped = self._bulk_iterate(
            ser.validated_data["stage_ids"], _run,
        )
        return Response(BulkStageActionResponseSerializer({
            "succeeded": succeeded, "skipped": skipped, "results": results,
        }).data)

    @extend_schema(
        tags=["dih"],
        summary="Bulk Clear IDV (accept) on selected stage records (US-S11-041)",
        description=(
            "Iterates over `stage_ids`, calling resolve_idv_pending "
            "with decision='accept' per row. Rows whose state isn't "
            "IDV_PENDING are skipped + reported. After accept each "
            "row routes to PENDING_PROMOTION (DDUP-clean) or "
            "DDUP_REVIEW (strong candidate). Use bulk-promote on a "
            "follow-up call for the rows that landed in "
            "PENDING_PROMOTION."
        ),
        request=BulkStageActionRequestSerializer,
        responses={
            200: BulkStageActionResponseSerializer,
            400: OpenApiResponse(description="bad request body"),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk-resolve-idv")
    def bulk_resolve_idv(self, request):
        from .services import resolve_idv_pending
        ser = BulkStageActionRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = ser.validated_data["actor"]
        reason = (ser.validated_data.get("reason") or "").strip()
        if not reason:
            return Response(
                {"detail": "reason is required for bulk IDV clearance"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _run(stage):
            if stage.state != StageRecordState.IDV_PENDING:
                return False, f"state is '{stage.state}', not idv_pending"
            try:
                resolve_idv_pending(
                    stage, actor=actor, reason=reason, decision="accept",
                )
            except DihError as exc:
                return False, str(exc)
            return True, "idv accepted"

        results, succeeded, skipped = self._bulk_iterate(
            ser.validated_data["stage_ids"], _run,
        )
        return Response(BulkStageActionResponseSerializer({
            "succeeded": succeeded, "skipped": skipped, "results": results,
        }).data)


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
    # Auto-run the staging gates so a clean walk-in fast-tracks to
    # promoted, and a dirty one routes to quality_failed / ddup_review /
    # idv_pending without an extra operator click. Failures here don't
    # invalidate the submission — the record stays at provisional and
    # the operator can re-run via /process/ from the DIH detail rail.
    try:
        stage = process_stage_record(stage, actor=actor)
    except DihError:  # noqa: PERF203 — surface as 201 with payload state
        pass
    return Response(
        StageRecordSerializer(stage).data,
        status=status.HTTP_201_CREATED,
    )
