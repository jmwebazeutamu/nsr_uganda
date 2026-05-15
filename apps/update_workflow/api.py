from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.audit_views import AuditReadMixin

from .models import ChangeRequest
from .services import (
    UpdError,
    commit_change_request,
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


@extend_schema_view(
    list=extend_schema(tags=["upd"], summary="List change requests"),
    retrieve=extend_schema(tags=["upd"], summary="Retrieve a change request"),
    create=extend_schema(tags=["upd"], summary="Create a draft change request"),
)
class ChangeRequestViewSet(AuditReadMixin, viewsets.ModelViewSet):
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
