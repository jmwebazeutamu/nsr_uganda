"""API-DRS DRF viewsets."""

from __future__ import annotations

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.security.abac import PartnerScopedQuerysetMixin
from apps.security.audit import emit as emit_audit
from apps.security.audit_views import AuditReadMixin, _client_ip

from .builder_schema import build_schema
from .bundles import get_bundle, prepare_and_deliver
from .models import DataRequest, RequestStatus
from .services import (
    DrsError,
    approve_data_request,
    deliver_data_request,
    expire_data_request,
    reject_data_request,
    submit_data_request,
)


class DownloadRateThrottle(UserRateThrottle):
    """Scoped throttle for the bundle-download action. Rate is set in
    settings.REST_FRAMEWORK.DEFAULT_THROTTLE_RATES['drs-download'];
    defaults to 10/min, env-tunable via DRS_DOWNLOAD_THROTTLE_RATE."""

    scope = "drs-download"


class DataRequestSerializer(serializers.ModelSerializer):
    # Operator-side detail panel renders the DSA reference next to
    # the row, not the ULID. Exposed read-only so a POST still
    # accepts dsa as the PK.
    dsa_reference = serializers.CharField(source="dsa.reference", read_only=True)
    partner_code = serializers.CharField(source="dsa.partner.code", read_only=True)
    partner_name = serializers.CharField(source="dsa.partner.name", read_only=True)

    class Meta:
        model = DataRequest
        fields = ("id", "dsa", "dsa_reference", "partner_code", "partner_name",
                  "requester", "requester_note",
                  "request_payload", "status",
                  "submitted_at", "approver", "decided_at",
                  "decision_reason", "delivered_at", "expires_at",
                  "manifest_sha256", "row_count_delivered",
                  "created_at", "updated_at")
        read_only_fields = (
            "id", "dsa_reference", "partner_code", "partner_name",
            "requester", "status",
            "submitted_at", "approver", "decided_at",
            "decision_reason", "delivered_at", "expires_at",
            "manifest_sha256", "row_count_delivered",
            "created_at", "updated_at",
        )


class MyDataRequestSerializer(serializers.ModelSerializer):
    """Partner-facing projection of DataRequest.

    Returns enough payload for the partner's own portal to render the
    request the partner themselves built: fields requested, criteria
    tree, geographic / programme leaves, row cap, and decision
    metadata (reason + when). Earlier versions were too slim — the
    "My data requests" rail had an empty FIELDS REQUESTED block
    because request_payload wasn't on the wire. Adds a download_url
    placeholder that points at the future signed-URL endpoint."""

    dsa_reference = serializers.CharField(source="dsa.reference", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = DataRequest
        fields = ("id", "dsa_reference", "status",
                  # Audit + decision metadata — partner has a right
                  # to know why a request was rejected and when each
                  # transition happened.
                  "created_at", "submitted_at", "decided_at",
                  "delivered_at", "expires_at",
                  "decision_reason",
                  # The actual content of the request — fields,
                  # criteria tree, max_rows. Needed by the detail
                  # rail's FIELDS REQUESTED + CRITERIA sections.
                  "request_payload",
                  "manifest_sha256",
                  "row_count_delivered", "download_url")
        read_only_fields = fields

    def get_download_url(self, obj):
        # Signed-URL endpoint lands when DRS-O-02 closes (MinIO wiring,
        # US-S6-003). Today we return a placeholder path; the partner
        # UI shows a disabled "download" button when this is null.
        if obj.status != RequestStatus.DELIVERED or not obj.manifest_sha256:
            return None
        return f"/api/v1/drs/requests/{obj.id}/download/"


class _Approver(serializers.Serializer):
    approver = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class _Deliver(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    manifest_sha256 = serializers.CharField(min_length=64, max_length=64)
    row_count = serializers.IntegerField(min_value=0)


# Partner + DSA endpoints moved to apps/partners/api.py per ADR-0013.
# Consumers should call /api/v1/partners/ and /api/v1/dsas/ instead
# of /api/v1/drs/partners/ + /api/v1/drs/dsas/.


@extend_schema_view(
    list=extend_schema(tags=["api-drs"], summary="List data requests"),
    retrieve=extend_schema(tags=["api-drs"], summary="Retrieve a data request"),
    create=extend_schema(tags=["api-drs"], summary="Open a new DRAFT data request"),
)
class DataRequestViewSet(
    AuditReadMixin, PartnerScopedQuerysetMixin, viewsets.ModelViewSet,
):
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

    @extend_schema(
        tags=["api-drs"],
        summary="Builder schema (fields, filter operators, delivery methods)",
        description=("Returns the catalogue the DRS query builder UI needs "
                     "to render. Same top-level shape for every role — "
                     "partner roles get DSA-restricted fields flagged with "
                     "`disabled: true` + a human-readable reason rather than "
                     "being silently omitted. Contract: the key set on the "
                     "top-level response is invariant across all roles "
                     "(BUG-S11-002a). Audit emits action=schema_read."),
        responses={200: OpenApiResponse(
            description="{role, dsa_reference, fields, filter_operators, "
                        "delivery_methods}",
        )},
    )
    @action(detail=False, methods=["get"], url_path="builder-schema")
    def builder_schema(self, request):
        schema = build_schema(request.user)
        emit_audit(
            "schema_read", "drs_builder_schema",
            schema.get("dsa_reference") or "operator",
            actor=getattr(request.user, "username", "") or "anonymous",
            reason=f"role={schema['role']}",
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            field_changes={"fields": len(schema["fields"]),
                           "delivery_methods": len(schema["delivery_methods"])},
        )
        return Response(schema)

    @extend_schema(
        tags=["partner-drs"],
        summary="My data requests (partner self-service)",
        description=("Returns the requesting user's own DataRequests "
                     "with a slim partner-facing projection. ABAC "
                     "filter already applies via PartnerScopedQuerysetMixin "
                     "— this endpoint just renders the same scoped "
                     "queryset with a narrower serializer (no admin "
                     "fields, no other partners' requesters)."),
        responses={200: MyDataRequestSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        ser_cls = MyDataRequestSerializer
        if page is not None:
            return self.get_paginated_response(
                ser_cls(page, many=True, context={"request": request}).data,
            )
        return Response(
            ser_cls(qs, many=True, context={"request": request}).data,
        )

    @extend_schema(
        tags=["partner-drs"],
        summary="Download a DELIVERED request's bundle",
        description=("Returns the rendered NDJSON bundle bytes for a "
                     "DELIVERED DataRequest. ABAC-scoped via the same "
                     "PartnerScopedQuerysetMixin as /mine/. Today the "
                     "endpoint streams bytes from the bundle store; "
                     "when DRS-O-02 closes (MinIO + signed URLs), this "
                     "endpoint returns a 302 redirect to the signed URL "
                     "instead. Audit emits action=download per call."),
        responses={
            200: OpenApiResponse(
                description="NDJSON bundle bytes (application/x-ndjson)",
            ),
            404: OpenApiResponse(description="not DELIVERED, or bundle missing"),
        },
    )
    @action(detail=True, methods=["get"], url_path="download",
            throttle_classes=[DownloadRateThrottle])
    def download(self, request, pk=None):
        req = self.get_object()
        if req.status != RequestStatus.DELIVERED:
            return Response(
                {"detail": f"download requires DELIVERED (got {req.status})"},
                status=status.HTTP_404_NOT_FOUND,
            )
        body = get_bundle(req.manifest_sha256) if req.manifest_sha256 else None
        if body is None:
            return Response(
                {"detail": "bundle bytes not found in storage"},
                status=status.HTTP_404_NOT_FOUND,
            )
        emit_audit(
            "download", "data_request", req.id,
            actor=getattr(request.user, "username", "") or "anonymous",
            reason=f"manifest={req.manifest_sha256[:8]}",
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            field_changes={"row_count_delivered": req.row_count_delivered},
        )
        response = HttpResponse(body, content_type="application/x-ndjson")
        response["Content-Disposition"] = (
            f'attachment; filename="data-request-{req.id}.ndjson"'
        )
        return response

    @extend_schema(
        tags=["api-drs"], summary="Render and deliver an APPROVED request",
        description=("Generates the export bundle (NDJSON, scoped by the DSA), "
                     "hashes it, persists to the bundle store, and flips the "
                     "request to DELIVERED. Combines render + deliver into a "
                     "single call so partners and ops scripts don't have to "
                     "compute the SHA-256 client-side."),
        request=None,
        responses={200: DataRequestSerializer,
                   400: OpenApiResponse(description="bad state")},
    )
    @action(detail=True, methods=["post"], url_path="render-and-deliver")
    def render_and_deliver(self, request, pk=None):
        req = self.get_object()
        try:
            prepare_and_deliver(
                req, actor=request.user.username or "render-bot",
            )
        except DrsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        req.refresh_from_db()
        return Response(self.get_serializer(req).data)
