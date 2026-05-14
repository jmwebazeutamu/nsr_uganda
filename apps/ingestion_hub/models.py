"""DIH (Data Integration Hub) models.

Sprint 0 scope: the framework scaffold. SourceSystem + DPA + Connector +
ConnectorRun + RawLanding + MappingRule(Version) + StageRecord +
PromotionDecision + PromotionBatch + Quarantine. The promotion path is
end-to-end functional; the pipeline orchestration (DQA/DDUP/IDV calls,
fast-track auto-promote, retention job) lands when those callers are
finalised.

References:
- SAD §4.6 pipeline, ACs, edge cases
- ADR-0001 (separately deployable; in this monorepo it lives in apps/
  ingestion_hub and talks to the registry via the promote API)
- ADR-0002 (StageRecord.provisional_registry_id, ConnectorRun.id, etc.
  are ULIDs per the externally-referenced list)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField

# --- Source systems and DPAs ----------------------------------------------

class SourceSystemKind(models.TextChoices):
    UBOS = "ubos", "UBOS bulk"
    CAPI_WALKIN = "capi_walkin", "CAPI walk-in"
    WEB = "web", "Web on-demand"
    KOBO = "kobo", "KoboToolbox"
    WFP_SCOPE = "wfp_scope", "WFP SCOPE"
    ODK = "odk", "ODK forms"
    PARTNER_MIS = "partner_mis", "Partner programme MIS"


class SourceSystem(models.Model):
    """A registered upstream system that may feed records into DIH."""

    id = ULIDField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=24, choices=SourceSystemKind.choices)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Source system"

    def __str__(self) -> str:
        return f"{self.code} ({self.kind})"


class DataProvisionAgreement(models.Model):
    """Inbound counterpart of a DSA. AC-DIH-DPA-REQUIRED forbids a connector
    run when no active DPA covers the source."""

    id = ULIDField(primary_key=True)
    source_system = models.ForeignKey(
        SourceSystem, on_delete=models.PROTECT, related_name="dpas",
    )
    reference = models.CharField(max_length=64, unique=True)
    scope = models.JSONField(default=dict, blank=True)
    purpose = models.TextField(blank=True)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=64, blank=True)
    residence_policy_days = models.PositiveIntegerField(default=30)  # DIH-O-01

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Data provision agreement"
        verbose_name_plural = "Data provision agreements"

    def __str__(self) -> str:
        return f"DPA {self.reference} ({self.source_system.code})"


# --- Connectors and runs --------------------------------------------------

class Connector(models.Model):
    id = ULIDField(primary_key=True)
    source_system = models.ForeignKey(
        SourceSystem, on_delete=models.PROTECT, related_name="connectors",
    )
    name = models.CharField(max_length=128)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Connector"

    def __str__(self) -> str:
        return f"{self.source_system_id}/{self.name}"


class ConnectorRunStatus(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class ConnectorRun(models.Model):
    id = ULIDField(primary_key=True)
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT, related_name="runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=ConnectorRunStatus.choices,
                              default=ConnectorRunStatus.PENDING)

    records_received = models.PositiveIntegerField(default=0)
    records_landed = models.PositiveIntegerField(default=0)
    records_staged = models.PositiveIntegerField(default=0)
    records_promoted = models.PositiveIntegerField(default=0)
    records_quarantined = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)

    note = models.TextField(blank=True)

    class Meta:
        verbose_name = "Connector run"
        indexes = [
            models.Index(fields=["connector", "started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"run {self.id} [{self.status}]"


# --- Mapping rules --------------------------------------------------------

class MappingRule(models.Model):
    """A logical mapping rule keyed by code. New versions are new
    MappingRuleVersion rows."""

    id = ULIDField(primary_key=True)
    source_system = models.ForeignKey(
        SourceSystem, on_delete=models.PROTECT, related_name="mapping_rules",
    )
    code = models.CharField(max_length=64)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source_system", "code"],
                                    name="mapping_rule_code_per_source"),
        ]

    def __str__(self) -> str:
        return f"{self.source_system_id}:{self.code}"


class MappingRuleVersion(models.Model):
    id = ULIDField(primary_key=True)
    rule = models.ForeignKey(MappingRule, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    spec = models.JSONField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mapping rule version"
        constraints = [
            models.UniqueConstraint(fields=["rule", "version"], name="mapping_version_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.rule_id} v{self.version}"


# --- Raw landing and staging ----------------------------------------------

class RawLanding(models.Model):
    """Tier 1 of the pipeline. Append-only per AC-DIH-LANDING-IMMUTABLE.
    Postgres-side enforcement is a follow-up migration; admin enforces
    today and the integrity trigger pattern from AuditEvent will be
    reused."""

    id = ULIDField(primary_key=True)
    connector_run = models.ForeignKey(
        ConnectorRun, on_delete=models.PROTECT, related_name="landings",
    )
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    source_reference = models.CharField(max_length=128, blank=True)

    class Meta:
        verbose_name = "Raw landing"
        indexes = [
            models.Index(fields=["connector_run", "received_at"]),
        ]

    def __str__(self) -> str:
        return f"landing {self.id} ({self.connector_run_id})"


class StageRecordState(models.TextChoices):
    PROVISIONAL = "provisional"
    QUALITY_FAILED = "quality_failed"
    IDV_PENDING = "idv_pending"
    DDUP_REVIEW = "ddup_review"
    PENDING_PROMOTION = "pending_promotion"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class StageRecord(models.Model):
    """Tier 2 of the pipeline. Canonical NSR-shaped record with a
    provisional Registry ID. Editable until promotion.

    provisional_registry_id is THE Registry ID once promoted — no churn,
    no re-issue (per AC-DIH-PROVISIONAL-ID and SAD §4.6.3).
    """

    id = ULIDField(primary_key=True)
    provisional_registry_id = ULIDField(unique=True)

    raw_landing = models.OneToOneField(
        RawLanding, on_delete=models.PROTECT, related_name="stage_record", null=True, blank=True,
    )
    connector_run = models.ForeignKey(
        ConnectorRun, on_delete=models.PROTECT, related_name="stage_records",
    )
    mapping_rule_version = models.ForeignKey(
        MappingRuleVersion, on_delete=models.PROTECT, related_name="stage_records",
        null=True, blank=True,
    )

    canonical_payload = models.JSONField()
    state = models.CharField(max_length=24, choices=StageRecordState.choices,
                             default=StageRecordState.PROVISIONAL)

    dqa_summary = models.JSONField(default=dict, blank=True)
    ddup_candidates = models.JSONField(default=list, blank=True)
    idv_outcome = models.CharField(max_length=32, blank=True)

    promoted_household_id = models.CharField(max_length=26, blank=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.TextField(blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.CharField(max_length=64, blank=True)

    sla_deadline = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stage record"
        indexes = [
            models.Index(fields=["state", "created_at"]),
            models.Index(fields=["connector_run"]),
        ]

    def __str__(self) -> str:
        return f"stage {self.provisional_registry_id} [{self.state}]"


# --- Decisions and quarantine ---------------------------------------------

class PromotionBatch(models.Model):
    """Groups multiple StageRecord promotions. AC-DIH-BATCH-DUAL: batches
    over 10,000 records require two distinct NSR Unit approvers."""

    id = ULIDField(primary_key=True)
    label = models.CharField(max_length=128, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    approver_a = models.CharField(max_length=64, blank=True)
    approver_b = models.CharField(max_length=64, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    finalised_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"batch {self.label or self.id} ({self.record_count} records)"


class PromotionAction(models.TextChoices):
    PROMOTE = "promote"
    PROMOTE_AS_MERGE = "promote_as_merge"
    REJECT = "reject"
    HOLD = "hold"
    AUTO_PROMOTE = "auto_promote"


class PromotionDecision(models.Model):
    id = ULIDField(primary_key=True)
    stage_record = models.ForeignKey(
        StageRecord, on_delete=models.PROTECT, related_name="decisions",
    )
    batch = models.ForeignKey(
        PromotionBatch, on_delete=models.PROTECT, related_name="decisions",
        null=True, blank=True,
    )
    action = models.CharField(max_length=24, choices=PromotionAction.choices)
    actor = models.CharField(max_length=64)
    reason = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.action} on {self.stage_record_id} by {self.actor}"


class Quarantine(models.Model):
    """Records that failed mapping or hit an out-of-DPA-scope situation.
    SAD §4.6.10 edge cases reference this."""

    id = ULIDField(primary_key=True)
    connector_run = models.ForeignKey(
        ConnectorRun, on_delete=models.PROTECT, related_name="quarantine",
    )
    raw_landing = models.ForeignKey(
        RawLanding, on_delete=models.PROTECT, related_name="quarantine", null=True, blank=True,
    )
    reason = models.CharField(max_length=64)
    detail = models.TextField(blank=True)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    escalated = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"quarantine {self.id} [{self.reason}]"
