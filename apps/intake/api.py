from dataclasses import asdict

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.security.abac import HouseholdIdScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .cspro import CsproParseError, parse_dictionary
from .cspro_diff import diff_dictionaries
from .field_dictionary import build_field_dictionary
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
class SubmissionViewSet(
    AuditReadMixin, HouseholdIdScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet,
):
    audit_entity_type = "submission"
    # Submission.provisional_registry_id == Household.id post-promotion.
    # Pre-promotion the FK target doesn't exist, so a scoped operator
    # can't see pre-promotion submissions — those belong to NSR Unit.
    scope_field_path = "provisional_registry_id"
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


# ---------------------------------------------------------------------------
# CSPro wave review (ADR-0034)
#
# UBOS owns the field instrument and delivers it in waves. MGLSD cannot
# refuse a wave, so the only defence against a changed question or a
# reused answer code arriving unnoticed is to read the dictionary and
# compare it against the last one accepted.
#
# Read-only and stateless: two dictionaries in, a classified changeset
# out. Nothing is stored and no decision is recorded here — this is the
# surface a reviewer READS. Recording what they decided needs the
# persisted FormVersion and the dual-approval workflow, which is a
# separate build.


def _read_dictionary(field_name, uploaded, text):
    """Parse an uploaded .dcf or a pasted body into a CsproDictionary."""
    if uploaded is not None:
        raw = uploaded.read()
        for encoding in ("utf-8-sig", "latin-1"):
            # CSPro writes UTF-8 with a BOM; older tools write Latin-1.
            # Neither should stop a wave being reviewed.
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:  # pragma: no cover - latin-1 decodes any byte sequence
            raise serializers.ValidationError(
                {field_name: "could not decode the file as text"},
            )
    if not (text or "").strip():
        raise serializers.ValidationError(
            {field_name: "supply a .dcf file or its text"},
        )
    try:
        return parse_dictionary(text)
    except CsproParseError as exc:
        raise serializers.ValidationError({field_name: str(exc)}) from exc


@extend_schema(
    tags=["intake"],
    summary="Diff two CSPro data dictionaries",
    description=(
        "Classify what changed between a previously accepted instrument "
        "and an incoming wave's. Accepts `old_file`/`new_file` uploads or "
        "`old_text`/`new_text` bodies. Read-only: nothing is stored."
    ),
    request=None,
    responses={
        200: OpenApiResponse(description="Classified changeset"),
        400: OpenApiResponse(description="A dictionary could not be parsed"),
    },
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def cspro_diff(request):
    old = _read_dictionary(
        "old", request.FILES.get("old_file"), request.data.get("old_text"),
    )
    new = _read_dictionary(
        "new", request.FILES.get("new_file"), request.data.get("new_text"),
    )
    diff = diff_dictionaries(old, new)
    return Response({
        "old": {"name": old.name, "version": old.version,
                "label": old.label, "items": len(old.items())},
        "new": {"name": new.name, "version": new.version,
                "label": new.label, "items": len(new.items())},
        "counts": diff.counts(),
        "is_clean": diff.is_clean,
        "changes": [
            {**asdict(c), "severity": str(c.severity)}
            for c in diff.sorted_changes()
        ],
    })


cspro_diff.parser_classes = [MultiPartParser, FormParser, JSONParser]


@extend_schema(
    tags=["intake"],
    summary="Field dictionary for the active instrument",
    description=(
        "Label and choice list for every canonical payload field, read "
        "from the active FormVersion, plus the age thresholds the "
        "household composition summary needs. Screens render coded "
        "values through this rather than carrying their own field maps, "
        "so the instrument and the console cannot disagree about what a "
        "field is called. Fields the registry does not define are absent "
        "rather than guessed at, and thresholds it cannot supply are "
        "returned as null with the reason in `missing_thresholds`."
    ),
    responses={200: OpenApiResponse(description="Field dictionary")},
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def field_dictionary(request):
    version = request.query_params.get("form_version")
    form_version = None
    if version:
        form_version = FormVersion.objects.filter(version=version).first()
        if form_version is None:
            return Response(
                {"detail": f"No form version {version}."},
                status=status.HTTP_404_NOT_FOUND,
            )
    return Response(build_field_dictionary(form_version).as_dict())
