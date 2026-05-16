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
    BLOCKING = "blocking", "Blocking"
    WARNING = "warning", "Warning"
    INFO = "info", "Info"


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
    severity = models.CharField(max_length=16, choices=Severity.choices)

    # Filter that decides whether a rule applies to a given record. Keys
    # the engine understands today: entity (household|member), channel,
    # geography (sub_region code prefix), age_band, form_version. Empty
    # means "applies to everything that matches the entity type".
    applicability_filter = models.JSONField(default=dict, blank=True)

    # The DSL tree; see apps.dqa.engine for grammar.
    expression = models.JSONField()
    error_message_template = models.CharField(max_length=256)

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


class DqaResult(models.Model):
    """Outcome of evaluating one DqaRule against one record."""

    rule = models.ForeignKey(DqaRule, on_delete=models.PROTECT, related_name="results")
    record_type = models.CharField(max_length=64)
    record_id = models.CharField(max_length=64)

    passed = models.BooleanField()
    severity = models.CharField(max_length=16, choices=Severity.choices)
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
