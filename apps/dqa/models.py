"""DAT-DQA models — versioned JSON-DSL rule engine.

Sprint 0 item 4 per CLAUDE.md and SAD §4.2.

- DqaRule: one row per (rule_id, version). New versions are new rows; the
  effective_from/to window plus status selects what is "active". Each row
  carries author + approved_by + approved_at, with the constraint that
  author != approved_by enforced at the service layer (apps.dqa.services).
- DqaResult: one row per evaluation. record_type + record_id point at the
  evaluated entity (e.g. household, member). High-volume internal-only,
  so BIGINT pk per ADR-0002.

References:
- SAD §4.2.1 rule shape
- SAD §4.2.2 severity model
- ADR-0002 (DqaRule is externally referenced via admin; DqaResult is not)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Severity(models.TextChoices):
    # US-S11-044 — four-value vocabulary aligned with the
    # intra-household DQA spec. Migration 0004 rewrites existing
    # rows from the legacy three-value vocabulary
    # (`blocking`, `warning`, `info`) into this one. The legacy
    # constants stay on this enum during the transition window so
    # ~40 existing call-sites in tests + services compile unchanged;
    # the P2 cleanup commit strips them once every caller has moved
    # to the new vocabulary.
    BLOCK = "block", "Block"
    REJECT_WITH_OVERRIDE = "reject_with_override", "Reject with override"
    FLAG = "flag", "Flag"
    INFO = "info", "Info"
    # --- legacy aliases (deprecated; remove in P2 cleanup) -------------
    BLOCKING = "blocking", "Blocking (deprecated → block)"
    WARNING = "warning", "Warning (deprecated → flag)"


# Severity bucket classifier — collapses both the legacy
# {blocking, warning, info} vocabulary and the US-S11-044 vocabulary
# {block, reject_with_override, flag, info} into three pipeline-facing
# buckets. Callers that need to "is this a flag, a block, or info?"
# read through here so a new-vocabulary `flag` rule and a legacy
# `warning` rule both route to the same UPD reactor. Lives next to
# Severity so the mapping evolves alongside the enum.
SEVERITY_BUCKETS = {
    "block": "block",
    "blocking": "block",                # legacy alias
    "reject_with_override": "block",    # promotion-time block unless overridden
    "flag": "flag",
    "warning": "flag",                  # legacy alias
    "info": "info",
}


def severity_bucket(severity: str) -> str:
    """Return one of {'block', 'flag', 'info'} for any rule severity
    string (old or new vocabulary). Unknown / empty input collapses
    to 'info' rather than raising — pipeline code should not crash
    on a malformed Rule row."""
    return SEVERITY_BUCKETS.get(severity or "info", "info")


class RuleCategory(models.TextChoices):
    """High-level grouping; the Rule Editor filter chip + the
    intra-household evaluator both key off this. New categories add
    here without a schema change as long as the string fits in 32 chars."""
    INTRA_HOUSEHOLD = "intra_household", "Intra-household"
    FIELD_LEVEL = "field_level", "Field-level"
    GEOGRAPHIC = "geographic", "Geographic"
    IDENTITY = "identity", "Identity"
    DUPLICATE = "duplicate", "Duplicate"


class RuleScope(models.TextChoices):
    """Selects which evaluator runs the rule. HOUSEHOLD is new in
    US-S11-044; CROSS_HOUSEHOLD is reserved for the next slice."""
    FIELD = "field", "Field"
    RECORD = "record", "Record"
    HOUSEHOLD = "household", "Household"
    CROSS_HOUSEHOLD = "cross_household", "Cross-household"


class ExpressionType(models.TextChoices):
    """Language the `expression` JSON is interpreted as. v1 honours
    only DSL — Python and SQL are schema-ready for future ADRs (see
    ADR-0022)."""
    DSL = "dsl", "JSON DSL"
    PYTHON_CALLABLE = "python_callable", "Python callable"
    SQL = "sql", "SQL"


class RuleStage(models.TextChoices):
    """Pipeline stages a rule applies to. A rule can carry any subset.
    Persisted as a JSON array on DqaRule.stages."""
    DIH_INGEST = "dih_ingest", "DIH ingest (pre-promotion)"
    DIH_PROMOTE = "dih_promote", "DIH promote"
    REGISTRY_POST_PROMOTE = "registry_post_promote", "Registry post-promote"


class EvaluationOutcome(models.TextChoices):
    """Aggregate outcome across all rules in one household evaluation."""
    PASS = "pass", "Pass"
    REVIEW = "review", "Review (any FLAG)"
    BLOCK = "block", "Block (any BLOCK / REJECT_WITH_OVERRIDE)"


class RuleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"
    REJECTED = "rejected", "Rejected"


class DqaRule(models.Model):
    """Versioned DQA rule. `rule_id` is the logical identifier (e.g.
    AC-MANDATORY); `version` increments on each approved revision."""

    id = ULIDField(primary_key=True)
    rule_id = models.CharField(max_length=64, db_index=True)
    version = models.PositiveIntegerField(default=1)

    description = models.TextField()
    severity = models.CharField(max_length=24, choices=Severity.choices)

    # US-S11-044 — category groups rules in the Rule Editor + drives
    # which evaluator picks them up. The intra-household evaluator
    # filters on `category=intra_household`. Empty string for legacy
    # rules; the data migration backfills the sprint-0 record-scope
    # ones to `field_level`.
    category = models.CharField(
        max_length=32, choices=RuleCategory.choices,
        default="", blank=True, db_index=True,
    )

    # US-S11-044 — what the rule operates on. RECORD is the sprint-0
    # default (mandatory / format / GPS); HOUSEHOLD enables the
    # intra-household evaluator.
    scope = models.CharField(
        max_length=24, choices=RuleScope.choices,
        default=RuleScope.RECORD,
    )

    # US-S11-044 — expression language the JSON tree is interpreted as.
    # v1 honours only DSL (ADR-0022).
    expression_type = models.CharField(
        max_length=24, choices=ExpressionType.choices,
        default=ExpressionType.DSL,
    )

    # US-S11-044 — pipeline stages this rule applies to. A rule with
    # `stages=["dih_ingest"]` runs at landing but not at promote.
    # JSON array so the Rule Editor can edit it as a multi-select
    # without a join table.
    stages = models.JSONField(default=list, blank=True)

    # Filter that decides whether a rule applies to a given record. Keys
    # the engine understands today: entity (household|member), channel,
    # geography (sub_region code prefix), age_band, form_version. Empty
    # means "applies to everything that matches the entity type".
    applicability_filter = models.JSONField(default=dict, blank=True)

    # US-S11-044 — `applies_to` enumerates the canonical-payload paths
    # the rule reads (e.g. `members.*.age_years`,
    # `members.*.relationship_to_head`). The wizard reads this list
    # to decide which field edits should trigger a live re-evaluation.
    # `applicability_filter` is for SELECTION (does this rule run?);
    # `applies_to` is for WATCHED FIELDS (does the wizard re-run me?).
    applies_to = models.JSONField(default=dict, blank=True)

    # The DSL tree; see apps.dqa.engine + apps.dqa.household_evaluator.
    expression = models.JSONField()

    # US-S11-044 — every threshold / numeric constant the rule reads
    # lives here (no magic numbers in the DSL). The evaluator refuses
    # to run a rule whose expression references a parameter not
    # declared in this dict.
    parameters = models.JSONField(default=dict, blank=True)

    # US-S11-044 — array of {input, expected_outcome} the Rule Editor
    # runs against the live evaluator on every save. Catches author
    # typos before the dual-approval submit.
    test_fixtures = models.JSONField(default=list, blank=True)

    # US-S11-044 — i18n key + default English string. The wizard pulls
    # the i18n key for Django's translation framework and falls back
    # to the EN string for un-translated locales. Parameter
    # interpolation uses `{key}` syntax filled from `parameters`.
    error_message_template = models.CharField(max_length=256)
    message_template_i18n_key = models.CharField(
        max_length=128, blank=True, default="",
    )

    # US-S11-044 — self-FK so version history is a real chain. v1 of
    # a rule has parent_rule=None; v2 points at v1; v3 at v2. The
    # Rule Editor's diff viewer walks this chain.
    parent_rule = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="child_versions",
    )

    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=24, choices=RuleStatus.choices, default=RuleStatus.DRAFT)
    author = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    # Lifecycle audit (DQA-1). approval_note explains WHY a rule was
    # approved; rejection_reason explains why one was rejected — both
    # surface in the version-history tab (US-076) and in the AuditEvent
    # field_changes payload (DQA-2). submitted_at completes the
    # lifecycle timestamps so latency dashboards can compute
    # draft → pending → active intervals.
    approval_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "DQA rule"
        verbose_name_plural = "DQA rules"
        constraints = [
            models.UniqueConstraint(fields=["rule_id", "version"], name="dqarule_id_version_unique"),
        ]
        indexes = [
            models.Index(fields=["status", "rule_id"]),
            models.Index(fields=["severity"]),
        ]

    def __str__(self) -> str:
        return f"{self.rule_id} v{self.version} [{self.severity}]"


class DqaRulePreviewRun(models.Model):
    """Audit trail of preview runs (US-077 / DQA-4).

    Each row records one /preview/ call: the rule version, the
    requested sample size, pass / fail counts, and the IDs (only IDs)
    of up to 10 failing records. Record VALUES are never persisted —
    the preview's whole point is to show the rule author the impact
    without leaking the underlying personal data.
    """

    id = ULIDField(primary_key=True)
    rule = models.ForeignKey(
        DqaRule, on_delete=models.PROTECT, related_name="preview_runs",
    )
    sample_size = models.PositiveIntegerField()
    record_type = models.CharField(max_length=32)
    pass_count = models.PositiveIntegerField()
    fail_count = models.PositiveIntegerField()
    sample_failed_record_ids = models.JSONField(default=list, blank=True)

    executed_at = models.DateTimeField(auto_now_add=True)
    executed_by = models.CharField(max_length=64)

    class Meta:
        verbose_name = "DQA rule preview run"
        verbose_name_plural = "DQA rule preview runs"
        indexes = [
            models.Index(fields=["rule", "-executed_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"preview {self.rule.rule_id} v{self.rule.version} "
            f"by {self.executed_by} @ {self.executed_at:%Y-%m-%d %H:%M}"
        )


class DqaResult(models.Model):
    """Outcome of evaluating one DqaRule against one record."""

    rule = models.ForeignKey(DqaRule, on_delete=models.PROTECT, related_name="results")
    record_type = models.CharField(max_length=64)
    record_id = models.CharField(max_length=64)

    passed = models.BooleanField()
    severity = models.CharField(max_length=24, choices=Severity.choices)
    reason = models.TextField(blank=True)

    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DQA result"
        verbose_name_plural = "DQA results"
        indexes = [
            models.Index(fields=["record_type", "record_id"]),
            models.Index(fields=["rule", "executed_at"]),
            models.Index(fields=["passed", "severity"]),
        ]

    def __str__(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return f"{verdict} {self.rule.rule_id} on {self.record_type}:{self.record_id}"


class DqaEvaluation(models.Model):
    """Per-household aggregate evaluation (US-S11-044).

    One row per (household_id, stage, evaluator_service_version) run.
    `results` is the per-rule outcome array; offending member ids are
    captured INSIDE that JSON, NOT in a side table — DQA persistence
    is audit-by-id-only and never stores rule input payloads.

    Distinct from `DqaResult` which is per-rule per-record; this is
    the aggregate the household-detail "DQA" section + the wizard
    panel render off, and what `GET /dqa/evaluations/{household_id}`
    returns.

    `household_id` is a CharField (not FK) because the evaluator runs
    at the DIH_INGEST stage when no Household row exists yet — only
    a provisional_registry_id. Resolving FKs lazily lets one model
    serve both pre- and post-promotion stages.
    """

    id = ULIDField(primary_key=True)
    household_id = models.CharField(max_length=26, db_index=True)
    household_version = models.PositiveIntegerField(null=True, blank=True)

    stage = models.CharField(
        max_length=32, choices=RuleStage.choices,
    )
    outcome = models.CharField(
        max_length=16, choices=EvaluationOutcome.choices,
    )
    # Array of per-rule result dicts. Shape mirrors the API contract
    # in /docs/openapi/dqa.yaml:
    #   { rule_code, rule_version, status, severity, message,
    #     offending_member_ids[], parameters_used }
    results = models.JSONField(default=list, blank=True)

    # Identifies the evaluator code that ran the rules — bumped on
    # any breaking change to the DSL interpreter. Lets a historical
    # evaluation be reproduced against the same evaluator + rule
    # version.
    evaluator_service_version = models.CharField(max_length=32, default="1.0")
    actor = models.CharField(max_length=64, blank=True)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DQA evaluation"
        verbose_name_plural = "DQA evaluations"
        indexes = [
            models.Index(fields=["household_id", "-evaluated_at"]),
            models.Index(fields=["stage", "-evaluated_at"]),
            models.Index(fields=["outcome", "-evaluated_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"DqaEvaluation {self.household_id} @ {self.stage} "
            f"-> {self.outcome} ({self.evaluated_at:%Y-%m-%d %H:%M})"
        )
