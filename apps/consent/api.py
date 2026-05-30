"""Consent Management DRF surface (US-CONSENT-01,02,05,06,07).

Convention mirrors apps/dqa/api.py and apps/data_requests: ViewSets +
serializers declared inline (no serializers.py), lifecycle transitions are
@action endpoints that delegate to apps.consent.services so the dual-approval
and audit guarantees cannot be bypassed.

Every endpoint is gated by CONSENT_MODULE_ENABLED — when the flag is off the
whole surface returns 503, matching the Data Explorer gate (ADR-0023).
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_management.models import Member

from . import services
from .models import (
    ConsentPurpose,
    ConsentRecord,
    ConsentState,
    ConsentStatementVersion,
    ConsentWithdrawalTicket,
    WithdrawalDecisionType,
)

# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


class ConsentModuleOff(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "consent_module_disabled"
    default_code = "consent_module_disabled"


class ConsentModuleEnabled(permissions.BasePermission):
    """Flag gate. Raises 503 (not 403) when the module is off, so callers can
    distinguish 'feature dark' from 'forbidden' — mirrors the Data Explorer
    FeatureFlagOff pattern (ADR-0023). The flag check runs before any role
    check so a flag-off response cannot enumerate membership."""

    def has_permission(self, request, view):
        if not services.module_enabled():
            raise ConsentModuleOff()
        return True


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class ConsentPurposeSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    lawful_basis_label = serializers.CharField(
        source="get_lawful_basis_display", read_only=True)

    class Meta:
        model = ConsentPurpose
        fields = (
            "id", "code", "name", "lawful_basis", "lawful_basis_label",
            "withdrawable", "default_on", "is_primary", "is_optional",
            "blurb", "basis_note", "display_order",
            "status", "status_label",
            "author", "approved_by", "approved_at", "approval_note",
            "rejection_reason", "submitted_at",
        )
        read_only_fields = (
            "status", "approved_by", "approved_at", "approval_note",
            "rejection_reason", "submitted_at",
        )


class ConsentStatementVersionSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    purpose_code = serializers.CharField(source="purpose.code", read_only=True)

    class Meta:
        model = ConsentStatementVersion
        fields = (
            "id", "purpose", "purpose_code", "version", "text_i18n",
            "placeholder_languages", "is_material",
            "status", "status_label", "effective_from", "effective_to",
            "author", "approved_by", "approved_at", "approval_note",
            "rejection_reason", "submitted_at",
        )
        read_only_fields = (
            "status", "approved_by", "approved_at", "approval_note",
            "rejection_reason", "submitted_at", "effective_from", "effective_to",
        )


class ConsentRecordSerializer(serializers.ModelSerializer):
    purpose_code = serializers.CharField(source="purpose.code", read_only=True)
    state_label = serializers.CharField(source="get_state_display", read_only=True)
    withdrawable = serializers.BooleanField(source="purpose.withdrawable", read_only=True)

    class Meta:
        model = ConsentRecord
        fields = (
            "id", "member", "purpose", "purpose_code", "state", "state_label",
            "withdrawable", "statement_version", "captured_via",
            "capture_method", "captured_by", "captured_at",
        )


class WithdrawalTicketSerializer(serializers.ModelSerializer):
    purpose_code = serializers.CharField(source="purpose.code", read_only=True)
    state_label = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = ConsentWithdrawalTicket
        fields = (
            "id", "member", "purpose", "purpose_code", "state", "state_label",
            "reason_code", "reason_note", "requested_by", "requested_at",
            "sla_deadline", "closed_at",
        )


# ---------------------------------------------------------------------------
# Catalogue viewsets (US-CONSENT-01, -02)
# ---------------------------------------------------------------------------


class ConsentPurposeViewSet(viewsets.ModelViewSet):
    queryset = ConsentPurpose.objects.all().order_by("display_order", "code")
    serializer_class = ConsentPurposeSerializer
    permission_classes = [permissions.IsAuthenticated, ConsentModuleEnabled]
    lookup_field = "code"

    def perform_create(self, serializer):
        serializer.save(author=self.request.user.get_username())

    def _actor(self):
        return self.request.user.get_username()

    @action(detail=True, methods=["post"])
    def submit(self, request, code=None):
        purpose = self.get_object()
        try:
            services.submit_purpose_for_approval(purpose, actor=self._actor())
        except services.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(purpose).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, code=None):
        purpose = self.get_object()
        try:
            services.activate_purpose(
                purpose, approver=self._actor(),
                note=request.data.get("note", ""))
        except services.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(purpose).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, code=None):
        purpose = self.get_object()
        try:
            services.reject_purpose(
                purpose, approver=self._actor(),
                reason=request.data.get("reason", ""))
        except services.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(purpose).data)

    @action(detail=True, methods=["post"])
    def retire(self, request, code=None):
        purpose = self.get_object()
        try:
            services.retire_purpose(purpose, actor=self._actor())
        except services.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(purpose).data)


class ConsentStatementVersionViewSet(viewsets.ModelViewSet):
    queryset = ConsentStatementVersion.objects.all().select_related("purpose")
    serializer_class = ConsentStatementVersionSerializer
    permission_classes = [permissions.IsAuthenticated, ConsentModuleEnabled]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user.get_username())

    def _actor(self):
        return self.request.user.get_username()

    @action(detail=True, methods=["get"])
    def reconsent_count(self, request, pk=None):
        """Pre-commit count of GRANTED records a material activation would
        flag Pending re-consent (CR2)."""
        stmt = self.get_object()
        return Response({"count": services.pending_reconsent_count(stmt.purpose)})

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        stmt = self.get_object()
        try:
            services.submit_statement_for_approval(stmt, actor=self._actor())
        except services.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(stmt).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        stmt = self.get_object()
        try:
            services.activate_statement(
                stmt, approver=self._actor(),
                note=request.data.get("note", ""))
        except services.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(stmt).data)


# ---------------------------------------------------------------------------
# Citizen / operator member matrix + capture + withdraw (US-CONSENT-05, -06)
# ---------------------------------------------------------------------------


class MemberConsentView(APIView):
    """GET the full per-purpose consent matrix for a member (US-CONSENT-05,
    -08). Returns every ACTIVE purpose with the member's current state."""

    permission_classes = [permissions.IsAuthenticated, ConsentModuleEnabled]

    def get(self, request, member_id):
        member = get_object_or_404(Member, pk=member_id)
        records = {
            r.purpose_id: r for r in
            ConsentRecord.objects.filter(member=member).select_related("purpose")
        }
        from .models import LifecycleStatus
        purposes = ConsentPurpose.objects.filter(
            status=LifecycleStatus.ACTIVE).order_by("display_order", "code")
        matrix = []
        for p in purposes:
            rec = records.get(p.id)
            matrix.append({
                "purpose_code": p.code,
                "name": p.name,
                "lawful_basis": p.lawful_basis,
                "withdrawable": p.withdrawable,
                "state": rec.state if rec else None,
                "state_label": rec.get_state_display() if rec else None,
                "captured_at": rec.captured_at if rec else None,
            })
        return Response({"member_id": member.id, "purposes": matrix})


class _CaptureRequest(serializers.Serializer):
    purpose_code = serializers.CharField()
    state = serializers.ChoiceField(choices=ConsentState.choices)
    capture_method = serializers.CharField(required=False, allow_blank=True, default="")
    proxy_member_id = serializers.CharField(required=False, allow_blank=True, default="")
    proxy_relationship = serializers.CharField(required=False, allow_blank=True, default="")
    witness_name = serializers.CharField(required=False, allow_blank=True, default="")
    witness_role = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class MemberCaptureView(APIView):
    """POST a consent capture for a member (US-CONSENT-03). Runs the
    AC-CONSENT-* DQA hooks before commit."""

    permission_classes = [permissions.IsAuthenticated, ConsentModuleEnabled]

    def post(self, request, member_id):
        member = get_object_or_404(Member, pk=member_id)
        req = _CaptureRequest(data=request.data)
        req.is_valid(raise_exception=True)
        data = req.validated_data
        purpose = get_object_or_404(ConsentPurpose, code=data["purpose_code"])

        # DQA hooks — verbal requires a witness (AC-CONSENT-METHOD-VALID).
        from .dqa_hooks import check_capture
        errors = check_capture(
            state=data["state"], capture_method=data["capture_method"],
            witness_name=data["witness_name"], witness_role=data["witness_role"],
            member=member, proxy_relationship=data["proxy_relationship"],
            purpose_code=purpose.code)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        rec = services.capture_consent(
            member=member, purpose=purpose, state=data["state"],
            captured_via="WEB_INTAKE", capture_method=data["capture_method"],
            captured_by=request.user.get_username(),
            proxy_member_id=data["proxy_member_id"],
            proxy_relationship=data["proxy_relationship"],
            reason=data["reason"])
        if data["witness_name"]:
            services.attach_evidence(
                record=rec, evidence_type="WITNESS_STATEMENT",
                witness_name=data["witness_name"], witness_role=data["witness_role"])
        return Response(ConsentRecordSerializer(rec).data, status=status.HTTP_201_CREATED)


class _WithdrawRequest(serializers.Serializer):
    purpose_code = serializers.CharField()
    reason_code = serializers.CharField(required=False, allow_blank=True, default="")
    reason_note = serializers.CharField(required=False, allow_blank=True, default="")


class MemberWithdrawView(APIView):
    """POST a withdrawal request for a member (US-CONSENT-06). Idempotent per
    day; returns the ticket id, deadline, and next-step copy."""

    permission_classes = [permissions.IsAuthenticated, ConsentModuleEnabled]

    def post(self, request, member_id):
        member = get_object_or_404(Member, pk=member_id)
        req = _WithdrawRequest(data=request.data)
        req.is_valid(raise_exception=True)
        data = req.validated_data
        purpose = get_object_or_404(ConsentPurpose, code=data["purpose_code"])
        try:
            ticket = services.open_withdrawal_ticket(
                member=member, purpose=purpose,
                requested_by=request.user.get_username(),
                reason_code=data["reason_code"], reason_note=data["reason_note"])
        except services.ConsentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "ticket_id": ticket.id,
            "sla_deadline": ticket.sla_deadline,
            "next_step": (
                "Your request has been logged. The Data Protection Office will "
                "review it within 30 days. You will be notified of the outcome."),
        }, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# DPO withdrawal queue (US-CONSENT-07)
# ---------------------------------------------------------------------------


class _DecisionRequest(serializers.Serializer):
    decision = serializers.ChoiceField(choices=WithdrawalDecisionType.choices)
    rationale = serializers.CharField()
    second_approver = serializers.CharField(required=False, allow_blank=True, default="")


class WithdrawalTicketViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WithdrawalTicketSerializer
    permission_classes = [permissions.IsAuthenticated, ConsentModuleEnabled]

    def get_queryset(self):
        qs = ConsentWithdrawalTicket.objects.all().select_related("purpose")
        # Manual filtering — django-filter is not installed (see project memory).
        state = self.request.query_params.get("state")
        if state:
            qs = qs.filter(state=state)
        purpose_code = self.request.query_params.get("purpose_code")
        if purpose_code:
            qs = qs.filter(purpose__code=purpose_code)
        return qs.order_by("-requested_at")

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        ticket = self.get_object()
        req = _DecisionRequest(data=request.data)
        req.is_valid(raise_exception=True)
        data = req.validated_data
        try:
            services.decide_withdrawal(
                ticket, decision=data["decision"], rationale=data["rationale"],
                decided_by=request.user.get_username(),
                second_approver=data["second_approver"])
        except services.ConsentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(ticket).data)
