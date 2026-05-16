from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.data_management.models import Household
from apps.security.abac import ScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .models import Programme, ProgrammeEnrolment, Referral
from .services import (
    ReferralError,
    accept_referral,
    enrol_household,
    exit_enrolment,
    reject_referral,
    send_referral,
    send_referral_webhook,
)


class ProgrammeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Programme
        fields = ("id", "code", "name", "description", "webhook_url",
                  "dsa_reference", "is_active")


class ReferralSerializer(serializers.ModelSerializer):
    # Programme code + name are surfaced alongside the FK so a
    # downstream consumer (e.g. household-detail Programmes tab) can
    # render a human-readable row without a second round-trip.
    programme_code = serializers.CharField(source="programme.code", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)

    class Meta:
        model = Referral
        fields = (
            "id", "programme", "programme_code", "programme_name",
            "household", "eligibility_rule_version",
            "status", "sent_at", "accepted_at", "enrolled_at",
            "rejected_at", "exited_at",
            "programme_side_id", "reason",
            "last_delivery_id", "last_delivery_at",
        )
        read_only_fields = (
            "id", "status", "sent_at", "accepted_at", "enrolled_at",
            "rejected_at", "exited_at",
            "last_delivery_id", "last_delivery_at",
        )


class EnrolmentSerializer(serializers.ModelSerializer):
    programme_code = serializers.CharField(source="programme.code", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)

    class Meta:
        model = ProgrammeEnrolment
        fields = ("id", "programme", "programme_code", "programme_name",
                  "household", "referral", "status",
                  "effective_date", "exit_reason", "payment_metadata",
                  "created_at", "updated_at")


class _SendReq(serializers.Serializer):
    programme_id = serializers.CharField()
    household_id = serializers.CharField()
    actor = serializers.CharField(max_length=64)
    eligibility_rule_version = serializers.IntegerField(default=1)


class _AcceptReq(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    programme_side_id = serializers.CharField(required=False, allow_blank=True)


class _RejectReq(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField()


class _EnrolReq(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    effective_date = serializers.DateField(required=False)
    payment_metadata = serializers.JSONField(required=False)


@extend_schema_view(
    list=extend_schema(tags=["ref"], summary="List programmes"),
)
class ProgrammeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Programme.objects.all().order_by("code")
    serializer_class = ProgrammeSerializer
    filterset_fields = ["is_active"]


@extend_schema_view(
    list=extend_schema(tags=["ref"], summary="List referrals"),
    retrieve=extend_schema(tags=["ref"], summary="Retrieve a referral"),
)
class ReferralViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "referral"
    scope_field_path = "household__sub_region_code"
    queryset = Referral.objects.all().order_by("-sent_at")
    serializer_class = ReferralSerializer
    filterset_fields = ["status", "programme", "household"]

    @extend_schema(tags=["ref"], summary="Send a new referral", request=_SendReq,
                   responses={200: ReferralSerializer})
    @action(detail=False, methods=["post"], url_path="send")
    def send(self, request):
        ser = _SendReq(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            programme = Programme.objects.get(pk=ser.validated_data["programme_id"])
            household = Household.objects.get(pk=ser.validated_data["household_id"])
            referral = send_referral(
                programme=programme, household=household,
                actor=ser.validated_data["actor"],
                eligibility_rule_version=ser.validated_data["eligibility_rule_version"],
            )
            send_referral_webhook(referral)
        except (Programme.DoesNotExist, Household.DoesNotExist) as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ReferralError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(referral).data)

    @extend_schema(tags=["ref"], summary="Mark a referral ACCEPTED by the programme",
                   request=_AcceptReq, responses={200: ReferralSerializer})
    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        ser = _AcceptReq(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            r = accept_referral(self.get_object(), actor=ser.validated_data["actor"],
                                programme_side_id=ser.validated_data.get("programme_side_id", ""))
        except ReferralError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(r).data)

    @extend_schema(tags=["ref"], summary="Reject a referral", request=_RejectReq,
                   responses={200: ReferralSerializer})
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        ser = _RejectReq(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            r = reject_referral(self.get_object(), actor=ser.validated_data["actor"],
                                reason=ser.validated_data["reason"])
        except ReferralError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(r).data)

    @extend_schema(tags=["ref"], summary="Enrol the household after acceptance",
                   request=_EnrolReq,
                   responses={200: EnrolmentSerializer,
                              400: OpenApiResponse(description="precondition unmet")})
    @action(detail=True, methods=["post"], url_path="enrol")
    def enrol(self, request, pk=None):
        ser = _EnrolReq(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            enrolment = enrol_household(
                self.get_object(),
                actor=ser.validated_data["actor"],
                effective_date=ser.validated_data.get("effective_date"),
                payment_metadata=ser.validated_data.get("payment_metadata"),
            )
        except ReferralError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(EnrolmentSerializer(enrolment).data)


@extend_schema_view(
    list=extend_schema(tags=["ref"], summary="List programme enrolments"),
)
class ProgrammeEnrolmentViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "programme_enrolment"
    scope_field_path = "household__sub_region_code"
    queryset = ProgrammeEnrolment.objects.all().order_by("-effective_date")
    serializer_class = EnrolmentSerializer
    filterset_fields = ["status", "programme", "household"]

    @extend_schema(tags=["ref"], summary="Exit an enrolment",
                   request=_RejectReq, responses={200: EnrolmentSerializer})
    @action(detail=True, methods=["post"], url_path="exit")
    def do_exit(self, request, pk=None):
        ser = _RejectReq(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            e = exit_enrolment(self.get_object(), actor=ser.validated_data["actor"],
                               reason=ser.validated_data["reason"])
        except ReferralError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(e).data)
