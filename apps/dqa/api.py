import random

from django.conf import settings
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import evaluate
from .household_evaluator import (
    EVALUATOR_SERVICE_VERSION,
    evaluate_household,
    load_active_household_rules,
    persist_household_evaluation,
)
from .models import (
    DqaEvaluation,
    DqaResult,
    DqaRule,
    DqaRulePreviewRun,
    EvaluationOutcome,
    ExpressionType,
    RuleCategory,
    RuleScope,
    RuleStage,
    Severity,
)
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
            # US-S11-044 intra-household additions. Rule Editor reads
            # and writes these; the seed bootstrap-creates them as DRAFT.
            "category", "scope", "expression_type", "stages",
            "parameters", "applies_to", "test_fixtures",
            "message_template_i18n_key",
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
        # seed local — doesn't disturb global randomness. Sampling
        # here is for non-security preview record selection, not
        # cryptographic.
        rng = random.Random(  # nosec B311 — non-security preview sampler
            f"{rule.id}|{sample_size}|{record_type}",
        )
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


# ---------------------------------------------------------------------------
# US-S11-044 — intra-household evaluation surface.
#
# Three endpoints, all feature-flag-gated on DQA_INTRA_HOUSEHOLD_ENABLED:
#
#   POST /dqa/evaluate/household        — synchronous evaluator. Wizard
#                                          calls this on each field-edit
#                                          batch. Optionally persists.
#   GET  /dqa/evaluations/{household_id} — DqaEvaluation history. Powers
#                                          household detail panel.
#   GET  /dqa/severity-vocabulary        — design tokens for the UI.
#
# Rule CRUD + lifecycle uses the existing DqaRuleViewSet (the new
# category/scope/stages/parameters/applies_to/test_fixtures fields are
# now surfaced by DqaRuleSerializer).


def _flag_enabled() -> bool:
    return bool(getattr(settings, "DQA_INTRA_HOUSEHOLD_ENABLED", False))


def _disabled_response():
    return Response(
        {"detail": "intra-household DQA is disabled in this environment"},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class _EvaluateHouseholdRequest(serializers.Serializer):
    """Request body for /dqa/evaluate/household.

    `payload` is the household dict the wizard / DIH builds; shape
    follows /docs/06_questionnaire.docx (household + members[]).
    `stage` tells the evaluator which stage filter to apply when
    loading rules from the catalog.
    `persist`+`household_id` together opt into writing a
    DqaEvaluation row and emitting an AuditEvent.
    """

    payload = serializers.JSONField()
    stage = serializers.ChoiceField(choices=RuleStage.choices)
    persist = serializers.BooleanField(required=False, default=False)
    household_id = serializers.CharField(required=False, allow_blank=True, default="")
    household_version = serializers.IntegerField(required=False, allow_null=True)
    evaluated_at = serializers.DateTimeField(required=False)


class _EvaluateHouseholdResponse(serializers.Serializer):
    stage = serializers.CharField()
    outcome = serializers.ChoiceField(choices=EvaluationOutcome.choices)
    evaluator_service_version = serializers.CharField()
    results = serializers.ListField(child=serializers.DictField())
    evaluation_id = serializers.CharField(required=False)
    rules_evaluated = serializers.IntegerField()


class EvaluateHouseholdView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["dqa"],
        summary="Evaluate intra-household DQA rules (US-S11-044)",
        description=(
            "Runs the active intra-household rule catalog (filtered by "
            "stage) against the supplied household payload and returns "
            "per-rule pass/fail/error + aggregate outcome. Pass "
            "`persist=true` with a `household_id` to record a "
            "DqaEvaluation row and emit a `dqa.household.evaluated` "
            "AuditEvent. The wizard calls this with persist=false on "
            "each field-edit batch; the pipeline (DIH ingest/promote, "
            "post-promote) calls it with persist=true."
        ),
        request=_EvaluateHouseholdRequest,
        responses={
            200: _EvaluateHouseholdResponse,
            400: OpenApiResponse(description="bad request body"),
            503: OpenApiResponse(description="feature flag disabled"),
        },
    )
    def post(self, request):
        if not _flag_enabled():
            return _disabled_response()
        ser = _EvaluateHouseholdRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        stage = ser.validated_data["stage"]
        payload = ser.validated_data["payload"]
        persist = ser.validated_data.get("persist") or False
        household_id = ser.validated_data.get("household_id") or ""
        actor = getattr(request.user, "username", "") or "system"
        # `evaluated_at` lets callers replay history deterministically;
        # absent in normal flows.
        now = ser.validated_data.get("evaluated_at")
        if isinstance(now, str):
            now = parse_datetime(now)
        if persist:
            if not household_id:
                return Response(
                    {"detail": "household_id is required when persist=true"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            eval_row = persist_household_evaluation(
                payload, stage=stage, actor=actor,
                household_id=household_id,
                household_version=ser.validated_data.get("household_version"),
                now=now,
            )
            body = {
                "stage": eval_row.stage,
                "outcome": eval_row.outcome,
                "evaluator_service_version": eval_row.evaluator_service_version,
                "results": eval_row.results,
                "evaluation_id": str(eval_row.id),
                "rules_evaluated": len(eval_row.results or []),
            }
        else:
            rules = load_active_household_rules(stage)
            aggregate = evaluate_household(
                rules, payload, stage=stage, now=now,
            )
            body = {
                "stage": aggregate["stage"],
                "outcome": aggregate["outcome"],
                "evaluator_service_version": aggregate["evaluator_service_version"],
                "results": aggregate["results"],
                "rules_evaluated": len(rules),
            }
        return Response(body)


class _DqaEvaluationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DqaEvaluation
        fields = (
            "id", "household_id", "household_version",
            "stage", "outcome", "results",
            "evaluator_service_version", "actor", "evaluated_at",
        )


class HouseholdEvaluationsView(APIView):
    """Returns the evaluation history for one household_id, newest
    first. Powers the household detail DQA panel and supports
    audit replay."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["dqa"],
        summary="List DQA evaluations for a household",
        responses={
            200: _DqaEvaluationSerializer(many=True),
            503: OpenApiResponse(description="feature flag disabled"),
        },
    )
    def get(self, request, household_id: str):
        if not _flag_enabled():
            return _disabled_response()
        qs = DqaEvaluation.objects.filter(
            household_id=household_id,
        ).order_by("-evaluated_at")
        # Optional filters — the household detail panel narrows by stage
        # ("show me the post-promote run") or outcome ("only blocks").
        stage = request.query_params.get("stage")
        if stage:
            qs = qs.filter(stage=stage)
        outcome = request.query_params.get("outcome")
        if outcome:
            qs = qs.filter(outcome=outcome)
        limit_raw = request.query_params.get("limit")
        try:
            limit = int(limit_raw) if limit_raw else 50
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))
        return Response(
            _DqaEvaluationSerializer(qs[:limit], many=True).data,
        )


class SeverityVocabularyView(APIView):
    """Returns the BLOCK / REJECT_WITH_OVERRIDE / FLAG / INFO vocabulary
    with display + design-token hints so the wizard, Rule Editor, and
    household detail panel render the same icon/colour for the same
    severity. Open to any authenticated user — it's UI metadata, not
    PII."""

    permission_classes = [permissions.IsAuthenticated]

    # Severity → (UI token, blocking?). The blocking flag tells the
    # wizard whether to gate Save / Next; the token feeds into the
    # design system's status palette per /docs/04_ui_design_brief.md.
    _VOCAB: list[dict] = [
        {
            "value": Severity.BLOCK.value, "label": "Block",
            "token": "status-danger", "blocks_save": True,
            "description": (
                "Hard stop. Save / promotion is refused until the "
                "violation is resolved."
            ),
        },
        {
            "value": Severity.REJECT_WITH_OVERRIDE.value,
            "label": "Reject with override",
            "token": "status-danger-soft", "blocks_save": True,
            "description": (
                "Refused by default. A supervisor can override with a "
                "documented reason; the override is audited."
            ),
        },
        {
            "value": Severity.FLAG.value, "label": "Flag",
            "token": "status-warning", "blocks_save": False,
            "description": (
                "Saves but opens an UPD review case. Enumerator sees the "
                "warning inline; supervisor triages."
            ),
        },
        {
            "value": Severity.INFO.value, "label": "Info",
            "token": "status-info", "blocks_save": False,
            "description": (
                "Logged for analytics. Not surfaced to enumerator unless "
                "the rule is also flagged for display."
            ),
        },
    ]

    @extend_schema(
        tags=["dqa"],
        summary="DQA severity vocabulary + UI tokens",
        responses={
            200: serializers.ListField(child=serializers.DictField()),
            503: OpenApiResponse(description="feature flag disabled"),
        },
    )
    def get(self, request):
        if not _flag_enabled():
            return _disabled_response()
        return Response({
            "severities": self._VOCAB,
            "stages": [
                {"value": v, "label": label}
                for v, label in RuleStage.choices
            ],
            "categories": [
                {"value": v, "label": label}
                for v, label in RuleCategory.choices
            ],
            "scopes": [
                {"value": v, "label": label}
                for v, label in RuleScope.choices
            ],
            "expression_types": [
                {"value": v, "label": label}
                for v, label in ExpressionType.choices
            ],
            "outcomes": [
                {"value": v, "label": label}
                for v, label in EvaluationOutcome.choices
            ],
            "evaluator_service_version": EVALUATOR_SERVICE_VERSION,
        })
