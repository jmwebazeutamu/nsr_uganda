"""API-DRS DRF viewsets."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.audit_views import AuditReadMixin

from .models import DataRequest, DataSharingAgreement, Partner, RequestStatus
from .services import (
    DrsError,
    approve_data_request,
    deliver_data_request,
    expire_data_request,
    reject_data_request,
    submit_data_request,
)


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = ("id", "code", "name", "contact_email", "status",
                  "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class DsaSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSharingAgreement
        fields = ("id", "partner", "reference", "purpose",
                  "allowed_scopes", "valid_from", "valid_to",
                  "status", "signed_by", "signed_at",
                  "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class DataRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataRequest
        fields = ("id", "dsa", "requester", "requester_note",
                  "request_payload", "status",
                  "submitted_at", "approver", "decided_at",
                  "decision_reason", "delivered_at", "expires_at",
                  "manifest_sha256", "row_count_delivered",
                  "created_at", "updated_at")
        read_only_fields = (
            "id", "requester", "status",
            "submitted_at", "approver", "decided_at",
            "decision_reason", "delivered_at", "expires_at",
            "manifest_sha256", "row_count_delivered",
            "created_at", "updated_at",
        )


class _Approver(serializers.Serializer):
    approver = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class _Deliver(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    manifest_sha256 = serializers.CharField(min_length=64, max_length=64)
    row_count = serializers.IntegerField(min_value=0)


@extend_schema_view(
    list=extend_schema(tags=["api-drs"], summary="List partners"),
    retrieve=extend_schema(tags=["api-drs"], summary="Retrieve a partner"),
)
class PartnerViewSet(AuditReadMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "partner"
    queryset = Partner.objects.all().order_by("code")
    serializer_class = PartnerSerializer
    filterset_fields = ["status"]


@extend_schema_view(
    list=extend_schema(tags=["api-drs"], summary="List data-sharing agreements"),
    retrieve=extend_schema(tags=["api-drs"], summary="Retrieve a DSA"),
)
class DsaViewSet(AuditReadMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "dsa"
    queryset = DataSharingAgreement.objects.all().order_by("-valid_from")
    serializer_class = DsaSerializer
    filterset_fields = ["status", "partner"]


@extend_schema_view(
    list=extend_schema(tags=["api-drs"], summary="List data requests"),
    retrieve=extend_schema(tags=["api-drs"], summary="Retrieve a data request"),
    create=extend_schema(tags=["api-drs"], summary="Open a new DRAFT data request"),
)
class DataRequestViewSet(AuditReadMixin, viewsets.ModelViewSet):
    audit_entity_type = "data_request"
    queryset = DataRequest.objects.all().order_by("-created_at")
    serializer_class = DataRequestSerializer
    filterset_fields = ["status", "dsa", "requester"]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(
            requester=self.request.user.username or "anonymous",
            status=RequestStatus.DRAFT,
        )

    @extend_schema(
        tags=["api-drs"], summary="Submit a DRAFT request",
        request=None,
        responses={200: DataRequestSerializer,
                   400: OpenApiResponse(description="DSA scope violation or bad state")},
    )
    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        req = self.get_object()
        try:
            submit_data_request(req)
        except DrsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["api-drs"], summary="Approve a SUBMITTED request",
        request=_Approver,
        responses={200: DataRequestSerializer,
                   400: OpenApiResponse(description="bad state or self-approval")},
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        ser = _Approver(data=request.data)
        ser.is_valid(raise_exception=True)
        req = self.get_object()
        try:
            approve_data_request(req, approver=ser.validated_data["approver"])
        except DrsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["api-drs"], summary="Reject a SUBMITTED request",
        request=_Approver,
        responses={200: DataRequestSerializer,
                   400: OpenApiResponse(description="bad state or self-approval")},
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        ser = _Approver(data=request.data)
        ser.is_valid(raise_exception=True)
        if not ser.validated_data.get("reason"):
            return Response({"detail": "reject requires a non-empty reason"},
                            status=status.HTTP_400_BAD_REQUEST)
        req = self.get_object()
        try:
            reject_data_request(
                req, approver=ser.validated_data["approver"],
                reason=ser.validated_data["reason"],
            )
        except DrsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["api-drs"], summary="Mark an APPROVED request as DELIVERED",
        request=_Deliver,
        responses={200: DataRequestSerializer,
                   400: OpenApiResponse(description="bad state or bad manifest")},
    )
    @action(detail=True, methods=["post"], url_path="deliver")
    def deliver(self, request, pk=None):
        ser = _Deliver(data=request.data)
        ser.is_valid(raise_exception=True)
        req = self.get_object()
        try:
            deliver_data_request(
                req, manifest_sha256=ser.validated_data["manifest_sha256"],
                row_count=ser.validated_data["row_count"],
                actor=ser.validated_data["actor"],
            )
        except DrsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)

    @extend_schema(
        tags=["api-drs"], summary="Expire a DELIVERED request",
        request=None, responses={200: DataRequestSerializer},
    )
    @action(detail=True, methods=["post"], url_path="expire")
    def expire(self, request, pk=None):
        req = self.get_object()
        try:
            expire_data_request(req, actor=request.user.username or "system")
        except DrsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)
