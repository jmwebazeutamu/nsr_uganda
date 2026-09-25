from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.data_management.models import Household
from apps.data_management.serializer_labels import attach_label_methodfields
from apps.partners.models import Programme
from apps.security.abac import ScopedQuerysetMixin
from apps.security.abac import scope_q_for_field
from apps.security.actor import actor_from_request
from apps.security.audit_views import AuditReadMixin

from .choice_field_map import MODEL_FIELDS
from .models import ProgrammeEnrolment, Referral
from .services import (
    ReferralError,
    accept_referral,
    enrol_household,
    exit_enrolment,
    reject_referral,
    send_referral,
    send_referral_webhook,
)
from .direct_enrolment import (
    EnrolmentEligibilityError,
    eligible_household_rows,
    enrol_households_directly,
)


class ReferralSerializer(serializers.ModelSerializer):
    # Programme code + name are surfaced alongside the FK so a
    # downstream consumer (e.g. household-detail Programmes tab) can
    # render a human-readable row without a second round-trip.
    programme_code = serializers.CharField(source="programme.code", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)

    class Meta:
        model = Referral
        fields = (
            "id", "reference", "programme", "programme_code", "programme_name",
            "household", "eligibility_rule_version",
            "status", "status_label",
            "sent_at", "accepted_at", "enrolled_at",
            "rejected_at", "exited_at",
            "programme_side_id", "reason",
            "last_delivery_id", "last_delivery_at",
        )
        read_only_fields = (
            "id", "reference", "status", "sent_at", "accepted_at", "enrolled_at",
            "rejected_at", "exited_at",
            "last_delivery_id", "last_delivery_at",
        )


attach_label_methodfields(ReferralSerializer, MODEL_FIELDS["Referral"])


class EnrolmentSerializer(serializers.ModelSerializer):
    programme_code = serializers.CharField(source="programme.code", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    household_head_name = serializers.SerializerMethodField()
    household_sub_region_name = serializers.CharField(source="household.sub_region.name", read_only=True)
    household_district_name = serializers.CharField(source="household.district.name", read_only=True)

    def get_household_head_name(self, enrolment):
        head = enrolment.household.head_member
        return f"{head.surname} {head.first_name}".strip() if head else ""

    class Meta:
        model = ProgrammeEnrolment
        # No `reference` here: an enrolment is a programme-side record,
        # not something a person quotes back to the registry. The three
        # that got numbers are the ones people ring up about.
        fields = ("id", "programme", "programme_code", "programme_name",
                  "household", "household_head_name", "household_sub_region_name", "household_district_name", "referral",
                  "status", "status_label",
                  "effective_date", "exit_reason", "payment_metadata",
                  "created_at", "updated_at")


attach_label_methodfields(EnrolmentSerializer, MODEL_FIELDS["ProgrammeEnrolment"])


class _SendReq(serializers.Serializer):
    programme_id = serializers.CharField()
    household_id = serializers.CharField()
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    eligibility_rule_version = serializers.IntegerField(default=1)


class _AcceptReq(serializers.Serializer):
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    programme_side_id = serializers.CharField(required=False, allow_blank=True)


class _RejectReq(serializers.Serializer):
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    reason = serializers.CharField()


class _EnrolReq(serializers.Serializer):
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    effective_date = serializers.DateField(required=False)
    payment_metadata = serializers.JSONField(required=False)


class _DirectEnrolmentRequest(serializers.Serializer):
    programme_id = serializers.CharField()
    household_ids = serializers.ListField(
        child=serializers.CharField(), allow_empty=False,
    )
    effective_date = serializers.DateField(required=False)


class _EligibleHouseholdSerializer(serializers.ModelSerializer):
    head_name = serializers.SerializerMethodField()
    region_code = serializers.CharField(read_only=True)
    sub_region_code = serializers.CharField(read_only=True)
    district_code = serializers.CharField(read_only=True)

    class Meta:
        model = Household
        fields = (
            "id", "head_name", "current_pmt_score", "current_vulnerability_band",
            "region_code", "sub_region_code", "district_code",
        )

    def get_head_name(self, household):
        head = household.head_member
        return f"{head.surname} {head.first_name}".strip() if head else ""


def _eligibility_error_response(exc: EnrolmentEligibilityError):
    return Response(
        {
            "detail": str(exc), "code": exc.code,
            "schema_dependencies": exc.dependencies,
            "rejections": exc.rejections,
        },
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


# NOTE: The legacy `ProgrammeViewSet` (at /api/v1/ref/programmes/)
# was removed in US-S26-005. Programme reads now go through the
# canonical /api/v1/programmes/ endpoint on the partners app.


@extend_schema_view(
    list=extend_schema(tags=["ref"], summary="List referrals"),
    retrieve=extend_schema(tags=["ref"], summary="Retrieve a referral"),
)
class ReferralViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    # Referring a household to a programme is the REFERRAL purpose.
    # Vocabulary is the ConsentPurpose catalogue (DEP-22), not a
    # second list of purposes beside the consent one.
    access_purpose = "REFERRAL"
    audit_entity_type = "referral"
    scope_field_path = "household__sub_region_code"
    queryset = Referral.objects.all().order_by("-sent_at")
    serializer_class = ReferralSerializer

    def get_queryset(self):
        """Apply canonical referral filters after inherited ABAC scope.

        ``django-filter`` is not installed, so ``filterset_fields`` would
        accept ``?household=`` while silently returning every visible row.
        The household detail is a single-household projection and must be
        filtered by the server before its results are serialised.
        """
        qs = super().get_queryset()

        # `?q=` — a case number somebody read out or pasted in.
        #
        # Normalised server-side with the same module the number was
        # issued from: dashes and spaces optional, prefix optional, and
        # O read as 0, I or l as 1. Falls through to a contains-match
        # on the reference and the ULID so a partial still narrows.
        #
        # Detail routes are excluded. Narrowing a LIST is the whole job
        # of these filters; on a detail route the only thing they can
        # do is remove the record being asked for, which surfaces as a
        # 404 that reads like a permission problem.
        if not self.kwargs.get("pk"):
            q = (self.request.query_params.get("q") or "").strip()
            if q:
                from django.db.models import Q

                from apps.reference_data.references import (
                    REFERRAL as _PREFIX, normalise,
                )

                exact = normalise(q, prefix=_PREFIX)
                if exact:
                    qs = qs.filter(reference=exact)
                else:
                    bare = q.upper().replace(" ", "")
                    qs = qs.filter(
                        Q(reference__icontains=bare) | Q(id__icontains=bare),
                    )
        for field in ("status", "programme", "household"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs

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
                actor=actor_from_request(request),
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
            r = accept_referral(self.get_object(), actor=actor_from_request(request),
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
            r = reject_referral(self.get_object(), actor=actor_from_request(request),
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
                actor=actor_from_request(request),
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
    # Enrolment is the downstream half of a referral.
    # Vocabulary is the ConsentPurpose catalogue (DEP-22), not a
    # second list of purposes beside the consent one.
    access_purpose = "REFERRAL"
    audit_entity_type = "programme_enrolment"
    scope_field_path = "household__sub_region_code"
    queryset = ProgrammeEnrolment.objects.select_related(
        "programme", "household", "household__head_member",
        "household__sub_region", "household__district",
    ).order_by("-effective_date")
    serializer_class = EnrolmentSerializer

    def get_queryset(self):
        """Apply canonical enrolment filters after inherited ABAC scope.

        This prevents an absent optional DRF filter dependency from turning
        the household relationship endpoint into an unfiltered roster.
        """
        qs = super().get_queryset()
        for field in ("status", "programme", "household"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs

    @extend_schema(
        tags=["ref"], summary="List canonically eligible households for a programme",
        responses={200: _EligibleHouseholdSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="eligible-households")
    def eligible_households(self, request):
        programme_id = request.query_params.get("programme")
        if not programme_id:
            return Response({"detail": "programme query parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            programme = Programme.objects.select_related("dsa").get(pk=programme_id)
        except Programme.DoesNotExist:
            return Response({"detail": "Programme not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            households = eligible_household_rows(programme)
            # Eligibility does not widen an operator's normal geographic view.
            households = households.filter(scope_q_for_field(request.user, "sub_region_code"))
        except EnrolmentEligibilityError as exc:
            return _eligibility_error_response(exc)
        page = self.paginate_queryset(households)
        serializer = _EligibleHouseholdSerializer(page if page is not None else households, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @extend_schema(
        tags=["ref"], summary="Directly enrol selected eligible households",
        request=_DirectEnrolmentRequest,
        responses={201: OpenApiResponse(description="Batch summary and created canonical enrolments")},
    )
    @action(detail=False, methods=["post"], url_path="enrol-direct")
    def enrol_direct(self, request):
        data = _DirectEnrolmentRequest(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            programme = Programme.objects.select_related("dsa").get(pk=data.validated_data["programme_id"])
        except Programme.DoesNotExist:
            return Response({"detail": "Programme not found."}, status=status.HTTP_404_NOT_FOUND)
        household_ids = data.validated_data["household_ids"]
        # Check the requested rows against ABAC before the transactional
        # policy check, so IDs outside the actor's scope cannot be enrolled.
        visible_ids = set(
            Household.objects.filter(id__in=household_ids)
            .filter(scope_q_for_field(request.user, "sub_region_code"))
            .values_list("id", flat=True),
        )
        if {str(value) for value in household_ids} != {str(value) for value in visible_ids}:
            return Response(
                {"detail": "One or more selected households are outside your geographic scope.", "code": "abac_scope"},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            created = enrol_households_directly(
                programme=programme, household_ids=household_ids,
                actor=actor_from_request(request),
                effective_date=data.validated_data.get("effective_date"),
            )
        except EnrolmentEligibilityError as exc:
            return _eligibility_error_response(exc)
        return Response(
            {
                "summary": {
                    "requested_count": len(set(str(value) for value in household_ids)),
                    "created_count": len(created),
                    "programme_id": str(programme.id),
                },
                "enrolments": EnrolmentSerializer(created, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["ref"], summary="Exit an enrolment",
                   request=_RejectReq, responses={200: EnrolmentSerializer})
    @action(detail=True, methods=["post"], url_path="exit")
    def do_exit(self, request, pk=None):
        ser = _RejectReq(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            e = exit_enrolment(self.get_object(), actor=actor_from_request(request),
                               reason=ser.validated_data["reason"])
        except ReferralError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(e).data)
