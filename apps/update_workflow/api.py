import hashlib
import json

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.security.abac import ChangeRequestScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin
from apps.security.models import AuditEvent

from .field_catalog import CATEGORIES, field_keys_by_category
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


class _BundleDocument(serializers.Serializer):
    """Supporting document — uploaded as base64-in-JSON to keep the
    bundle payload uniform. Per-file + total caps enforced in the
    parent serializer's validate()."""

    filename = serializers.CharField(min_length=1, max_length=255)
    content_type = serializers.CharField(min_length=1, max_length=128)
    data_base64 = serializers.CharField(min_length=1, max_length=8 * 1024 * 1024)


class _BundleRequest(serializers.Serializer):
    household_id = serializers.CharField(max_length=26, min_length=26)
    entity = serializers.ChoiceField(choices=[t.value for t in EntityType])
    # Required when entity='member'; ignored otherwise. Validated against
    # the household roster in validate() so a CR can't target a member
    # that doesn't belong to the named household.
    member_id = serializers.CharField(
        max_length=26, min_length=26, required=False, allow_blank=True,
    )
    change_type = serializers.ChoiceField(choices=[t.value for t in ChangeType])
    pmt_relevant = serializers.BooleanField(required=False, default=False)
    rows = _BundleRow(many=True)
    # Optional supporting documents (PDF / JPG / PNG / HEIC / WebP).
    # Caps + MIME whitelist enforced in validate_documents().
    documents = _BundleDocument(many=True, required=False, default=list)
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

    def validate_documents(self, value):
        # Decode + size-check every uploaded document up-front so a
        # bad file doesn't leak past the serializer. Caps live in
        # evidence_storage; importing here keeps the module-level
        # dependency lazy (serializer is imported on app load).
        import base64

        from .evidence_storage import (
            ALLOWED_MIME_TYPES,
            MAX_FILE_BYTES,
            MAX_FILES,
            MAX_TOTAL_BYTES,
        )

        if not value:
            return []
        if len(value) > MAX_FILES:
            raise serializers.ValidationError(
                f"at most {MAX_FILES} documents per change request",
            )

        decoded: list[dict] = []
        total = 0
        for doc in value:
            if doc["content_type"] not in ALLOWED_MIME_TYPES:
                raise serializers.ValidationError(
                    f"unsupported content_type {doc['content_type']!r}; "
                    f"allowed: {sorted(ALLOWED_MIME_TYPES)}",
                )
            try:
                body = base64.b64decode(doc["data_base64"], validate=True)
            except Exception as e:  # noqa: BLE001 — third-party + invalid input
                raise serializers.ValidationError(
                    f"data_base64 for {doc['filename']!r} is not valid base64: {e}",
                ) from e
            if len(body) > MAX_FILE_BYTES:
                raise serializers.ValidationError(
                    f"document {doc['filename']!r} is "
                    f"{len(body)} bytes; max per file is {MAX_FILE_BYTES}",
                )
            total += len(body)
            if total > MAX_TOTAL_BYTES:
                raise serializers.ValidationError(
                    f"total document size exceeds {MAX_TOTAL_BYTES} bytes",
                )
            decoded.append({
                "filename": doc["filename"],
                "content_type": doc["content_type"],
                "body": body,
            })
        # Return the decoded list — the handler reads `body` directly
        # instead of re-decoding.
        return decoded

    def validate(self, attrs):
        # Cross-field rules — entity scope vs. row fields, member_id
        # presence + ownership.
        from .field_catalog import field_entity

        entity = attrs["entity"]
        rows = attrs.get("rows", [])

        if entity == EntityType.MEMBER:
            if not attrs.get("member_id"):
                raise serializers.ValidationError(
                    {"member_id": "required when entity='member'"},
                )
            # Every row must be a member-scope field.
            offenders = [
                f"{r['category']}.{r['field']}" for r in rows
                if field_entity(r["category"], r["field"]) != "member"
            ]
            if offenders:
                raise serializers.ValidationError(
                    {"rows": f"household-scope fields cannot be submitted with "
                             f"entity='member': {', '.join(offenders)}"},
                )
            # Validate the member belongs to the household.
            from apps.data_management.models import Member
            hh_id = attrs["household_id"]
            mem_id = attrs["member_id"]
            if not Member.objects.filter(id=mem_id, household_id=hh_id).exists():
                raise serializers.ValidationError(
                    {"member_id": f"member {mem_id} does not belong to household {hh_id}"},
                )
        else:
            # entity=household or all_members → no member-scope fields
            # allowed (those need the picker to be honest about which
            # member they target).
            offenders = [
                f"{r['category']}.{r['field']}" for r in rows
                if field_entity(r["category"], r["field"]) == "member"
            ]
            if offenders:
                raise serializers.ValidationError(
                    {"rows": f"member-scope fields require entity='member': "
                             f"{', '.join(offenders)}"},
                )
        return attrs


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
        params = self.request.query_params

        # `filterset_fields` above is documentation-only — django-filter
        # isn't installed, so DRF doesn't wire it. Apply the same
        # filters manually so the UPD workbench's status tabs and the
        # household-detail Updates tab actually narrow the result set.
        # `status` accepts a comma-separated list so the Decided tab can
        # request both committed and rejected in one round-trip.
        status_param = params.get("status")
        if status_param:
            statuses = [s for s in (v.strip() for v in status_param.split(",")) if s]
            if statuses:
                qs = qs.filter(status__in=statuses)
        for field in ("change_type", "entity_type", "entity_id"):
            val = params.get(field)
            if val:
                qs = qs.filter(**{field: val})
        pmt = params.get("pmt_relevant")
        if pmt is not None and pmt != "":
            qs = qs.filter(pmt_relevant=str(pmt).lower() in ("1", "true", "yes"))

        sr = params.get("sub_region_code")
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
            # Member roster picker is now wired (CR-modal slice 2).
            # The serializer already validated member_id belongs to
            # household and that every row is a member-scope field.
            entity_type = EntityType.MEMBER
            entity_id = data["member_id"]
            note = data["note"]
        else:
            entity_type = EntityType.HOUSEHOLD
            entity_id = data["household_id"]
            note = data["note"]

        actor = getattr(request.user, "username", "") or "console-operator"

        # Store any uploaded documents via the configured backend and
        # build evidence rows. The serializer already validated MIME,
        # per-file size, and total size; here we just compute the
        # content-address hash, persist, and record the row.
        import hashlib

        from .evidence_storage import get_evidence_storage

        store = get_evidence_storage()
        evidence_rows: list[dict] = [{"kind": "note", "label": note}]
        for doc in data.get("documents") or []:
            sha = hashlib.sha256(doc["body"]).hexdigest()
            store.put(sha, doc["body"])
            evidence_rows.append({
                "kind": "document",
                "filename": doc["filename"],
                "content_type": doc["content_type"],
                "size": len(doc["body"]),
                "sha256": sha,
            })

        cr = ChangeRequest.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=data["change_type"],
            pmt_relevant=pmt_relevant,
            changes=changes,
            evidence=evidence_rows,
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


# --- US-S28-CATALOG — field catalog endpoint --------------------------------


def _resolve_field_options(field: dict, *, language: str) -> list[dict]:
    """Return `[{code, label}]` for a select field.

    Precedence:
      1. If the field declares `choice_list`, resolve against the
         active ChoiceList version at today's date (the active version
         IS the source of truth — no `as_of` knob here; bulk-DRS
         queries handle historical resolution separately).
      2. Otherwise fall back to the hardcoded `options` array, treating
         each entry as both code and label (legacy fields whose labels
         haven't been promoted into a ChoiceList yet).
    """
    cl_name = field.get("choice_list")
    if cl_name:
        # Local import — keeps the field_catalog module
        # import-cycle-free (reference_data depends on nothing inside
        # update_workflow, but importing services at module top would
        # mean the catalog module pulls Django models on import).
        from apps.reference_data.services import resolve_options
        resolved = resolve_options(cl_name, language=language)
        if resolved:
            return resolved
        # ChoiceList missing or inactive — fall through to the
        # hardcoded options rather than ship an empty dropdown.
    return [{"code": o, "label": o} for o in (field.get("options") or [])]


def _serialise_field(field: dict, *, language: str) -> dict:
    """Project one catalog field into its public shape. Adds the
    resolved options (for select) and strips internal-only keys."""
    out = {
        "key": field["key"],
        "label": field["label"],
        "type": field["type"],
        "pmt": bool(field.get("pmt", False)),
        "entity": field.get("entity", "household"),
    }
    if field["type"] == "select":
        out["choice_list"] = field.get("choice_list")
        out["options"] = _resolve_field_options(field, language=language)
    return out


def _build_field_catalog_bundle(*, language: str) -> dict:
    return {
        "language": language,
        "categories": [
            {
                "key": c["key"],
                "label": c["label"],
                "tone": c.get("tone", "neutral"),
                "fields": [
                    _serialise_field(f, language=language) for f in c["fields"]
                ],
            }
            for c in CATEGORIES
        ],
    }


def _field_catalog_etag(bundle: dict) -> str:
    """Stable digest of the serialised bundle. The ChoiceList resolver
    cache invalidates on ChoiceList/Option saves, so the etag flips
    automatically when a list version becomes active."""
    payload = json.dumps(bundle, sort_keys=True, default=str).encode("utf-8")
    return f'W/"{hashlib.sha256(payload).hexdigest()[:16]}"'


@extend_schema(
    tags=["upd"],
    summary="Open-CR wizard field catalog with resolved select options",
    description=(
        "Returns the full Open-CR field catalog used by the modal. "
        "Select fields tagged with `choice_list` get their options "
        "resolved against the active ChoiceList version at request "
        "time, so the modal never ships stale codes. Legacy select "
        "fields (no `choice_list`) ship their hardcoded options as "
        "{code, label} pairs unchanged. `lang` param selects label "
        "language (default 'en'). ETag-cached — 304 on repeat reads."
    ),
    responses={200: OpenApiResponse(description="Catalog bundle")},
)
class FieldCatalogView(APIView):
    """ADR-0010 — coded fields via ChoiceList. Single round-trip catalog
    for the Open-CR modal, replacing the duplicated JSX hardcoded
    field list at design/v0.1/components/change-request-modal.jsx."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = (request.query_params.get("lang") or "en").strip() or "en"
        bundle = _build_field_catalog_bundle(language=language)
        etag = _field_catalog_etag(bundle)

        if_none_match = request.META.get("HTTP_IF_NONE_MATCH")
        if if_none_match and if_none_match.strip() == etag:
            resp = Response(status=status.HTTP_304_NOT_MODIFIED)
            resp["ETag"] = etag
            return resp

        resp = Response(bundle)
        resp["ETag"] = etag
        resp["Cache-Control"] = "private, max-age=60, must-revalidate"
        return resp
