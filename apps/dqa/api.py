import random

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .engine import evaluate
from .models import DqaResult, DqaRule, DqaRulePreviewRun
from .services import ApprovalError, approve, reject, retire, submit_for_approval


# US-076 — author role gate. Create/update on the Rule endpoint is
# restricted to members of the "dqa_author" Django group (or
# superusers, for ops). Read + lifecycle actions remain available to
# any authenticated operator; the service-layer guards (cannot self-
# approve, cannot rule-jump states) carry the remaining authorisation.
class IsDqaAuthor(permissions.BasePermission):
    message = "Only DQA Authors can create or edit rules."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        # Action endpoints (submit/approve/reject/retire) are not
        # "write the rule" — they're transitions, gated by services.py.
        if getattr(view, "action", None) in (
            "submit_for_approval", "approve", "reject", "retire", "preview",
        ):
            return True
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name="dqa_author").exists()


class DqaRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DqaRule
        fields = (
            "id", "rule_id", "version", "description", "severity",
            "applicability_filter", "expression", "error_message_template",
            "effective_from", "effective_to", "status",
            "author", "approved_by", "approved_at",
            # DQA-1 lifecycle audit fields.
            "approval_note", "rejection_reason", "submitted_at",
        )


class DqaResultSerializer(serializers.ModelSerializer):
    rule_id = serializers.CharField(source="rule.rule_id", read_only=True)
    rule_version = serializers.IntegerField(source="rule.version", read_only=True)

    class Meta:
        model = DqaResult
        fields = (
            "id", "rule", "rule_id", "rule_version",
            "record_type", "record_id",
            "passed", "severity", "reason", "executed_at",
        )


class _PreviewRequest(serializers.Serializer):
    sample_size = serializers.IntegerField(min_value=1, max_value=10000, default=50)
    record_type = serializers.ChoiceField(choices=["member", "household"])


class _PreviewResponse(serializers.Serializer):
    pass_count = serializers.IntegerField()
    fail_count = serializers.IntegerField()
    sample_failed_record_ids = serializers.ListField(child=serializers.CharField())


# Mapping from preview's record_type to (Model, default_qs) so the
# preview endpoint never has to think in Django model paths. Add a
# row here when a new record_type becomes previewable.
def _preview_queryset(record_type: str):
    if record_type == "member":
        from apps.data_management.models import Member
        return Member, Member.objects.all().order_by("id")
    if record_type == "household":
        from apps.data_management.models import Household
        return Household, Household.objects.all().order_by("id")
    return None, None


class _NoteRequest(serializers.Serializer):
    note = serializers.CharField()


class _ReasonRequest(serializers.Serializer):
    reason = serializers.CharField()


@extend_schema_view(
    list=extend_schema(tags=["dqa"], summary="List DQA rules"),
    retrieve=extend_schema(tags=["dqa"], summary="Retrieve a DQA rule"),
    create=extend_schema(tags=["dqa"], summary="Create a DRAFT rule (DQA Author only)"),
    update=extend_schema(tags=["dqa"], summary="Update a DRAFT rule (DQA Author only)"),
    partial_update=extend_schema(tags=["dqa"], summary="Patch a DRAFT rule (DQA Author only)"),
)
class DqaRuleViewSet(viewsets.ModelViewSet):
    queryset = DqaRule.objects.all().order_by("rule_id", "-version")
    serializer_class = DqaRuleSerializer
    filterset_fields = ["status", "severity", "rule_id"]
    permission_classes = [IsDqaAuthor]
    # DELETE intentionally absent — rules are retired, not deleted, per
    # SAD §4.2 (rule history is part of the audit trail).
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    @extend_schema(
        tags=["dqa"],
        summary="Preview rule impact on a sample (US-077)",
        description=(
            "Evaluates the rule against a random sample of records of "
            "the requested type and returns pass/fail counts plus up "
            "to 10 IDs of failing records. Record VALUES are never "
            "returned. Persists a DqaRulePreviewRun audit row."
        ),
        request=_PreviewRequest,
        responses={
            200: _PreviewResponse,
            400: OpenApiResponse(description="bad sample_size or record_type"),
        },
    )
    @action(detail=True, methods=["post"], url_path="preview")
    def preview(self, request, pk=None):
        rule = self.get_object()
        ser = _PreviewRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        sample_size = ser.validated_data["sample_size"]
        record_type = ser.validated_data["record_type"]
        _model, qs = _preview_queryset(record_type)
        if qs is None:
            return Response(
                {"detail": f"unknown record_type {record_type!r}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Deterministic seed so the same rule + sample_size returns
        # the same preview within a test run (US-077 acceptance:
        # tests get a fixed sample). Random.Random instance keeps the
        # seed local — doesn't disturb global randomness.
        rng = random.Random(f"{rule.id}|{sample_size}|{record_type}")
        all_ids = list(qs.values_list("id", flat=True))
        if len(all_ids) <= sample_size:
            chosen_ids = all_ids
        else:
            chosen_ids = rng.sample(all_ids, sample_size)
        rows = list(qs.filter(id__in=chosen_ids))
        pass_count = 0
        failed_ids: list[str] = []
        for row in rows:
            ev = evaluate(rule, row, record_type=record_type, record_id=str(row.id))
            if ev.passed:
                pass_count += 1
            else:
                failed_ids.append(str(row.id))
        fail_count = len(failed_ids)
        run = DqaRulePreviewRun.objects.create(
            rule=rule, sample_size=sample_size, record_type=record_type,
            pass_count=pass_count, fail_count=fail_count,
            sample_failed_record_ids=failed_ids[:10],
            executed_by=getattr(request.user, "username", "") or "anonymous",
        )
        return Response({
            "pass_count": pass_count,
            "fail_count": fail_count,
            "sample_failed_record_ids": run.sample_failed_record_ids,
        })

    # --- DQA-5: lifecycle action endpoints ------------------------------
    #
    # Each maps 1:1 onto a service function. Each action audits via the
    # service layer (see apps/dqa/services.py). Service-raised
    # ApprovalError → 400 with the message so the React Rule Editor can
    # surface it verbatim.

    @extend_schema(
        tags=["dqa"],
        summary="Submit a DRAFT rule for approval",
        request=None,
        responses={200: DqaRuleSerializer,
                   400: OpenApiResponse(description="bad state")},
    )
    @action(detail=True, methods=["post"], url_path="submit-for-approval")
    def submit_for_approval(self, request, pk=None):
        rule = self.get_object()
        actor = getattr(request.user, "username", "") or "system"
        try:
            submit_for_approval(rule, actor=actor)
        except ApprovalError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        rule.refresh_from_db()
        return Response(self.get_serializer(rule).data)

    @extend_schema(
        tags=["dqa"],
        summary="Approve a PENDING rule (note required)",
        request=_NoteRequest,
        responses={200: DqaRuleSerializer,
                   400: OpenApiResponse(
                       description="bad state, missing note, or self-approve",
                   )},
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        rule = self.get_object()
        ser = _NoteRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        approver = getattr(request.user, "username", "") or "system"
        try:
            approve(
                rule, approver=approver,
                note=ser.validated_data["note"], actor=approver,
            )
        except ApprovalError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        rule.refresh_from_db()
        return Response(self.get_serializer(rule).data)

    @extend_schema(
        tags=["dqa"],
        summary="Reject a PENDING rule (reason required)",
        request=_ReasonRequest,
        responses={200: DqaRuleSerializer,
                   400: OpenApiResponse(
                       description="bad state, missing reason, or self-reject",
                   )},
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        rule = self.get_object()
        ser = _ReasonRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        approver = getattr(request.user, "username", "") or "system"
        try:
            reject(
                rule, approver=approver,
                reason=ser.validated_data["reason"], actor=approver,
            )
        except ApprovalError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        rule.refresh_from_db()
        return Response(self.get_serializer(rule).data)

    @extend_schema(
        tags=["dqa"],
        summary="Retire an ACTIVE rule",
        request=None,
        responses={200: DqaRuleSerializer,
                   400: OpenApiResponse(description="bad state")},
    )
    @action(detail=True, methods=["post"], url_path="retire")
    def retire(self, request, pk=None):
        rule = self.get_object()
        actor = getattr(request.user, "username", "") or "system"
        try:
            retire(rule, actor=actor)
        except ApprovalError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        rule.refresh_from_db()
        return Response(self.get_serializer(rule).data)


@extend_schema_view(
    list=extend_schema(tags=["dqa"], summary="List DQA evaluation results"),
    retrieve=extend_schema(tags=["dqa"], summary="Retrieve a DQA result"),
)
class DqaResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DqaResult.objects.all().order_by("-executed_at")
    serializer_class = DqaResultSerializer
    filterset_fields = ["passed", "severity", "record_type"]
