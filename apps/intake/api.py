from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.audit_views import AuditReadMixin

from .models import Channel, FormVersion, Submission, SubmissionResult
from .services import IntakeError, submit_intake


class FormVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormVersion
        fields = ("id", "version", "name", "description", "schema",
                  "is_active", "effective_from", "effective_to")


class SubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = (
            "id", "channel", "form_version", "enumerator", "supervisor",
            "gps_lat", "gps_lng", "gps_accuracy_m",
            "started_at", "finished_at",
            "result", "state",
            "stage_record_id", "provisional_registry_id",
            "note", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "state", "stage_record_id", "provisional_registry_id",
            "created_at", "updated_at",
        )


class SubmitIntakeRequestSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=Channel.choices)
    enumerator = serializers.CharField(max_length=64)
    supervisor = serializers.CharField(max_length=64, required=False, allow_blank=True)
    result = serializers.ChoiceField(choices=SubmissionResult.choices,
                                     default=SubmissionResult.COMPLETED)
    canonical_payload = serializers.JSONField()
    auto_process = serializers.BooleanField(default=True)


@extend_schema_view(
    list=extend_schema(tags=["intake"], summary="List form versions"),
    retrieve=extend_schema(tags=["intake"], summary="Retrieve a form version"),
)
class FormVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FormVersion.objects.all().order_by("-version")
    serializer_class = FormVersionSerializer
    filterset_fields = ["is_active"]


@extend_schema_view(
    list=extend_schema(tags=["intake"], summary="List submissions"),
    retrieve=extend_schema(tags=["intake"], summary="Retrieve a submission"),
)
class SubmissionViewSet(AuditReadMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "submission"
    queryset = Submission.objects.all().order_by("-created_at")
    serializer_class = SubmissionSerializer
    filterset_fields = ["channel", "state", "result"]

    @extend_schema(
        tags=["intake"],
        summary="Submit a new intake (Web/CAPI/USSD/Bulk)",
        description=(
            "Routes the canonical payload through DIH: lands, stages, and "
            "optionally runs the orchestrator (DQA -> IDV -> DDUP). Clean "
            "walk-ins fast-track to PROMOTED per AC-DIH-FT-AUTO."
        ),
        request=SubmitIntakeRequestSerializer,
        responses={200: SubmissionSerializer, 400: OpenApiResponse(description="precondition unmet")},
    )
    @action(detail=False, methods=["post"], url_path="submit")
    def submit(self, request):
        ser = SubmitIntakeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            submission = submit_intake(
                channel=ser.validated_data["channel"],
                canonical_payload=ser.validated_data["canonical_payload"],
                enumerator=ser.validated_data["enumerator"],
                supervisor=ser.validated_data.get("supervisor", ""),
                result=ser.validated_data["result"],
                auto_process=ser.validated_data["auto_process"],
                actor=request.user.username or "anonymous",
            )
        except IntakeError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(submission).data)
