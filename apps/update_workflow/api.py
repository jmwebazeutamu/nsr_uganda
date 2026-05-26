from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.abac import ChangeRequestScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin
from apps.security.models import AuditEvent

from .field_catalog import field_keys_by_category
from .field_catalog import is_pmt_relevant as _catalog_is_pmt_relevant
from .models import ChangeRequest, ChangeType, EntityType, SourceChannel
from .routing import route_label
from .services import (
    UpdError,
    commit_change_request,
    escalate_change_request,
    hold_change_request,
    reject_change_request,
    release_change_request,
    submit_change_request,
)


class ChangeRequestSerializer(serializers.ModelSerializer):
    # household_id is the household the CR ultimately affects — equal to
    # entity_id when entity_type='household', resolved via Member FK when
    # entity_type='member'. Exposed so the "Open household" affordance in
    # the React UPD screen can navigate without a second API round-trip.
    household_id = serializers.SerializerMethodField()

    class Meta:
        model = ChangeRequest
        fields = (
            "id", "entity_type", "entity_id", "household_id",
            "change_type", "pmt_relevant",
            "changes", "evidence",
            "source_channel", "requester", "requester_note",
            "status", "required_role", "sla_deadline",
            "approver", "decided_at", "decision_reason",
            "pmt_preview",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "household_id", "status", "required_role", "sla_deadline",
            "approver", "decided_at", "decision_reason",
            "pmt_preview", "created_at", "updated_at",
        )

    def get_household_id(self, obj):
        if obj.entity_type == "household":
            return obj.entity_id
        if obj.entity_type == "member":
            # Local import to keep the module dependency lazy — Member
            # lives in data_management and the import-order should not
            # be load-bearing.
            from apps.data_management.models import Member
            return (
                Member.objects.filter(id=obj.entity_id)
                .values_list("household_id", flat=True)
                .first()
            )
        return None


class _ActorReason(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class _BulkRequest(serializers.Serializer):
    """Payload for the bulk_approve / bulk_reject / bulk_escalate
    actions. `ids` is the list of ChangeRequest ULIDs to act on; rows
    not in the operator's ABAC scope are silently filtered (the
    ChangeRequestScopedQuerysetMixin already restricts get_queryset()),
    rows that violate per-row guards (no-self-approve, wrong state)
    surface as `skipped` in the response."""

    ids = serializers.ListField(
        child=serializers.CharField(max_length=26, min_length=26),
        min_length=1, max_length=200,
    )
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


# --- US-S22-003 — bundle serializer for the Open-CR modal. Validates
# rows against the field catalog, requires note >= 6 chars, rejects
# duplicate (category, field) pairs.

class _BundleRow(serializers.Serializer):
    category = serializers.CharField(max_length=24)
    field = serializers.CharField(max_length=48)
    new_value = serializers.CharField(allow_blank=False, max_length=1024)


class _BundleRequest(serializers.Serializer):
    household_id = serializers.CharField(max_length=26, min_length=26)
    entity = serializers.ChoiceField(choices=[t.value for t in EntityType])
    change_type = serializers.ChoiceField(choices=[t.value for t in ChangeType])
    pmt_relevant = serializers.BooleanField(required=False, default=False)
    rows = _BundleRow(many=True)
    note = serializers.CharField(min_length=6, max_length=2048)

    def validate_rows(self, value):
        if not value:
            raise serializers.ValidationError("at least one row is required")
        seen: set[tuple[str, str]] = set()
        catalog = field_keys_by_category()
        for row in value:
            cat, fld = row["category"], row["field"]
            if cat not in catalog:
                raise serializers.ValidationError(f"unknown category {cat!r}")
            if fld not in catalog[cat]:
                raise serializers.ValidationError(
                    f"unknown field {fld!r} for category {cat!r}",
                )
            key = (cat, fld)
            if key in seen:
                raise serializers.ValidationError(
                    f"duplicate row for ({cat!r}, {fld!r})",
                )
            seen.add(key)
            if not row["new_value"].strip():
                raise serializers.ValidationError(
                    f"new_value is required for ({cat!r}, {fld!r})",
                )
        return value


@extend_schema_view(
    list=extend_schema(tags=["upd"], summary="List change requests"),
    retrieve=extend_schema(tags=["upd"], summary="Retrieve a change request"),
    create=extend_schema(tags=["upd"], summary="Create a draft change request"),
)
class ChangeRequestViewSet(
    AuditReadMixin, ChangeRequestScopedQuerysetMixin, viewsets.ModelViewSet,
):
    audit_entity_type = "change_request"
    queryset = ChangeRequest.objects.all().order_by("-created_at")
    serializer_class = ChangeRequestSerializer
    filterset_fields = [
        "status", "change_type", "pmt_relevant", "entity_type",
        # entity_id added in US-S12-003 so the React household-detail
        # Updates tab can fetch a single household's change-request
        # history in one round-trip.
        "entity_id",
    ]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        # US-S15-003 — optional ?sub_region_code= drill-down.
        # ChangeRequest stores the subject in (entity_type, entity_id);
        # only HOUSEHOLD-typed rows have a meaningful sub-region join.
        # Member-level CRs are excluded here (their entity_id is a
        # Member id, not a Household id) — same trade-off taken in
        # _count_change_requests (US-S14-004).
        qs = super().get_queryset()
        sr = self.request.query_params.get("sub_region_code")
        if sr:
            from apps.data_management.models import Household

            from .models import EntityType
            hh_ids = list(
                Household.objects.filter(sub_region_code=sr)
                                  .values_list("id", flat=True),
            )
            qs = qs.filter(
                entity_type=EntityType.HOUSEHOLD,
                entity_id__in=hh_ids,
            )
        return qs

    @extend_schema(
        tags=["upd"],
        summary="Submit a DRAFT change request for approval",
        request=None,
        responses={200: ChangeRequestSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        req = self.get_object()
        try:
            submit_change_request(req)
        except UpdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["upd"],
        summary="Approve a PENDING_APPROVAL change request",
        request=_ActorReason,
        responses={200: ChangeRequestSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        ser = _ActorReason(data=request.data)
        ser.is_valid(raise_exception=True)
        req = self.get_object()
        try:
            commit_change_request(req, approver=ser.validated_data["actor"])
        except UpdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["upd"],
        summary="Reject a PENDING_APPROVAL change request",
        request=_ActorReason,
        responses={200: ChangeRequestSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        ser = _ActorReason(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data.get("reason", "")
        req = self.get_object()
        try:
            reject_change_request(req, approver=ser.validated_data["actor"], reason=reason)
        except UpdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    # --- US-S22-001 — hold / release / me ---------------------------------

    @extend_schema(
        tags=["upd"],
        summary="Hold a PENDING_APPROVAL change request pending more info",
        request=_ActorReason,
        responses={200: ChangeRequestSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="hold")
    def hold(self, request, pk=None):
        ser = _ActorReason(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data.get("reason", "")
        req = self.get_object()
        try:
            hold_change_request(req, approver=ser.validated_data["actor"], reason=reason)
        except UpdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["upd"],
        summary="Release an ON_HOLD change request back into the queue",
        request=_ActorReason,
        responses={200: ChangeRequestSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        ser = _ActorReason(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data.get("reason", "")
        req = self.get_object()
        try:
            release_change_request(req, approver=ser.validated_data["actor"], reason=reason)
        except UpdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["upd"],
        summary="Current user identity for the UPD workbench",
        responses={200: OpenApiResponse(
            description="{username: str, is_staff: bool, is_superuser: bool}",
        )},
    )
    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        u = request.user
        return Response({
            "username": u.username,
            "is_staff": bool(u.is_staff),
            "is_superuser": bool(u.is_superuser),
        })

    # --- US-S22-003 — bundle endpoint -------------------------------------
    #
    # Accepts the rich Open-CR modal's payload (multi-row, multi-
    # category) and creates a single ChangeRequest in PENDING_APPROVAL.
    # Rows are validated against the field catalog; the changes JSON
    # is `{field: {old: "", new: row.new_value}}` since the modal
    # captures only the new value (old comes from the household
    # snapshot at the modal layer for display, not authoritative).
    # The concurrent-edit guard on commit_change_request still
    # protects the actual apply step.

    @extend_schema(
        tags=["upd"],
        summary="Create a multi-row change request from the Open-CR modal",
        request=None,
        responses={201: OpenApiResponse(
            description="{cr_id: ULID, audit_id: ULID, routed_to: str, "
                        "pmt_relevant: bool, changes: int}",
        )},
    )
    @action(detail=False, methods=["post"], url_path="bundle")
    def bundle(self, request):
        ser = _BundleRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Derive pmt_relevant from rows when not forced. The modal
        # mirrors this; sending pmt_relevant=true overrides upward
        # (operator can flag a cosmetic-looking row as PMT), but
        # sending false when any row is PMT-relevant is auto-bumped
        # to keep the audit honest.
        derived_pmt = any(
            _catalog_is_pmt_relevant(r["category"], r["field"]) for r in data["rows"]
        )
        pmt_relevant = bool(data.get("pmt_relevant", False)) or derived_pmt

        # Build the changes JSON. Old is "" (the commit-time
        # concurrent-edit guard will re-read live values and refuse
        # to apply if the diff doesn't line up — protects against
        # stale-snapshot submissions).
        changes: dict[str, dict[str, str]] = {}
        for r in data["rows"]:
            changes[r["field"]] = {"old": "", "new": r["new_value"]}

        # Map "all_members" to household for storage; commit-time
        # fan-out is the follow-up slice. Surface the operator's
        # intent in requester_note so reviewers can see it.
        if data["entity"] == EntityType.ALL_MEMBERS:
            entity_type = EntityType.HOUSEHOLD
            entity_id = data["household_id"]
            note = f"[entity=all_members] {data['note']}"
        elif data["entity"] == EntityType.MEMBER:
            # Member roster picker is OOS for this slice — the modal
            # exposes the option but submission against entity=member
            # requires a follow-up that adds member_id resolution.
            return Response(
                {"detail": "entity=member requires a member picker (follow-up slice)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        else:
            entity_type = EntityType.HOUSEHOLD
            entity_id = data["household_id"]
            note = data["note"]

        actor = getattr(request.user, "username", "") or "console-operator"

        cr = ChangeRequest.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=data["change_type"],
            pmt_relevant=pmt_relevant,
            changes=changes,
            evidence=[{"kind": "note", "label": note}],
            source_channel=SourceChannel.WEB,
            requester=actor,
            requester_note=note,
        )
        try:
            submit_change_request(cr)
        except UpdError as e:
            cr.delete()
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve the AuditEvent id stamped by submit_change_request
        # so the response carries the audit ULID per the spec.
        audit = (
            AuditEvent.objects
            .filter(entity_type="change_request", entity_id=cr.id, action="submit")
            .order_by("-id")
            .first()
        )
        return Response(
            {
                "cr_id": cr.id,
                "audit_id": audit.id if audit else "",
                "routed_to": route_label(cr.change_type, pmt_relevant=cr.pmt_relevant),
                "pmt_relevant": cr.pmt_relevant,
                "changes": len(changes),
                "status": cr.status,
            },
            status=status.HTTP_201_CREATED,
        )


    # --- US-S10-004 — bulk actions ----------------------------------------
    #
    # Each bulk endpoint takes a list of ids and runs them one-by-one
    # through the same service the per-row endpoint uses, so audit
    # emission + no-self-approve guards + state transitions are
    # identical. Rows that fail their guard are counted as skipped
    # rather than aborting the whole batch — matches the GRM S4-005 +
    # UPD S5-001 admin bulk-action pattern.

    def _bulk_act(self, request, action_fn, *, requires_reason=False):
        """Shared dispatcher for the three bulk endpoints."""
        ser = _BulkRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = ser.validated_data["actor"]
        reason = ser.validated_data.get("reason", "")
        if requires_reason and not reason:
            return Response(
                {"detail": "reason is required for bulk_reject"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ids = ser.validated_data["ids"]
        # Only consider rows already visible in this user's scope —
        # ChangeRequestScopedQuerysetMixin filters get_queryset();
        # missing ids quietly drop out.
        qs = self.filter_queryset(self.get_queryset()).filter(id__in=ids)
        results = {"acted": [], "skipped": []}
        for req in qs:
            try:
                action_fn(req, actor=actor, reason=reason)
                results["acted"].append(req.id)
            except UpdError as e:
                results["skipped"].append({"id": req.id, "reason": str(e)})
        # Rows requested but not in the queryset (out of scope / not
        # found) report as not_found so the caller can distinguish
        # them from guard-skipped rows.
        found_ids = set(qs.values_list("id", flat=True))
        results["not_found"] = sorted(set(ids) - found_ids)
        return Response(results)

    @extend_schema(
        tags=["upd"],
        summary="Bulk-approve PENDING_APPROVAL requests",
        request=_BulkRequest,
        responses={200: OpenApiResponse(
            description="{acted: [ids], skipped: [{id, reason}], not_found: [ids]}"
        )},
    )
    @action(detail=False, methods=["post"], url_path="bulk-approve")
    def bulk_approve(self, request):
        def _commit(req, *, actor, reason):
            commit_change_request(req, approver=actor)
        return self._bulk_act(request, _commit)

    @extend_schema(
        tags=["upd"],
        summary="Bulk-reject PENDING_APPROVAL requests",
        request=_BulkRequest,
        responses={200: OpenApiResponse(
            description="{acted: [ids], skipped: [{id, reason}], not_found: [ids]}"
        ), 400: OpenApiResponse(description="reason required")},
    )
    @action(detail=False, methods=["post"], url_path="bulk-reject")
    def bulk_reject(self, request):
        def _reject(req, *, actor, reason):
            reject_change_request(req, approver=actor, reason=reason)
        return self._bulk_act(request, _reject, requires_reason=True)

    @extend_schema(
        tags=["upd"],
        summary="Bulk-escalate PENDING_APPROVAL requests to district M&E",
        request=_BulkRequest,
        responses={200: OpenApiResponse(
            description="{acted: [ids], skipped: [{id, reason}], not_found: [ids]}"
        )},
    )
    @action(detail=False, methods=["post"], url_path="bulk-escalate")
    def bulk_escalate(self, request):
        def _escalate(req, *, actor, reason):
            # escalate_change_request doesn't take actor/reason — the
            # service hard-codes "sla-auto-escalator" as the actor in
            # the audit emit. Bulk-action callers acknowledge that the
            # row was acted on but the audit attribution remains the
            # auto-escalator identity (operations runbook convention).
            escalate_change_request(req)
        return self._bulk_act(request, _escalate)
