from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.abac import ChangeRequestScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .models import ChangeRequest
from .services import (
    UpdError,
    commit_change_request,
    escalate_change_request,
    reject_change_request,
    submit_change_request,
)


class ChangeRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChangeRequest
        fields = (
            "id", "entity_type", "entity_id",
            "change_type", "pmt_relevant",
            "changes", "evidence",
            "source_channel", "requester", "requester_note",
            "status", "required_role", "sla_deadline",
            "approver", "decided_at", "decision_reason",
            "pmt_preview",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "status", "required_role", "sla_deadline",
            "approver", "decided_at", "decision_reason",
            "pmt_preview", "created_at", "updated_at",
        )


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
    filterset_fields = ["status", "change_type", "pmt_relevant", "entity_type"]
    http_method_names = ["get", "post", "head", "options"]

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
