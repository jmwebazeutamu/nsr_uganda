"""DATA-EXP models — catalogue, throttle counters, query log, sessions.

Per ADR-0023:

- Catalogue (Dataset, Variable, PrivacyClass, RefreshCadence) is
  metadata-driven; rows are upserted by metadata_loader.refresh()
  on Django startup and every post_migrate signal.
- Newly-loaded / shape-changed Variable rows are seeded INACTIVE.
  Dual approval (DQA Approver + DPO) via VariableApproval flips them
  ACTIVE.
- AggregateQueryLog is the per-cell-suppression record. The
  detect_overlap_burst Celery task scans it for re-identification
  bursts.
- QueryThrottleCounter is the per-(actor, privacy_class, date_utc)
  Redis-shadow counter. Django row exists too so the throttle is
  enforceable without Redis (tests, dev).
- ExplorerSession ties a sequence of catalogue browses + aggregate
  runs to the handoff so the DRS draft can reference the discovery
  trail.

Matview-backed unmanaged Django models live in matview_models.py
(Meta.managed = False). The DDL itself ships in a data_management
migration, per CLAUDE.md "no raw SQL outside data_management".

All externally-visible IDs are ULIDs. No raw SQL in this module.
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class PrivacyClassCode(models.TextChoices):
    PUBLIC = "public", "Public"
    INTERNAL = "internal", "Internal"
    PERSONAL = "personal", "Personal"
    SENSITIVE = "sensitive", "Sensitive"


class RefreshCadenceCode(models.TextChoices):
    MANUAL = "manual", "Manual"
    HOURLY = "hourly", "Hourly"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class VariableStatus(models.TextChoices):
    INACTIVE = "inactive", "Inactive (pending approval)"
    ACTIVE = "active", "Active"
    DEPRECATED = "deprecated", "Deprecated"


class ApprovalRole(models.TextChoices):
    DQA = "dqa", "DQA Approver"
    DPO = "dpo", "Data Protection Officer"


class HandoffStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ABANDONED = "abandoned", "Abandoned"
    SUBMITTED = "submitted", "Submitted to API-DRS"


class PrivacyClass(models.Model):
    """The four locked privacy classes. ADR-0023 D3 / OPEN-3.

    `k_floor`, `daily_user_cap`, `daily_org_cap` are the suppression
    + throttle knobs. Seeded by /scripts/seed_data_explorer.py.

    `code` is the canonical key code; `label` is the user-facing
    badge string (passes through Django i18n in serialisers).
    """

    id = ULIDField(primary_key=True)
    code = models.CharField(
        max_length=24, unique=True,
        choices=PrivacyClassCode.choices,
        help_text="Canonical lookup key — public/internal/personal/sensitive.",
    )
    label = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    k_floor = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Minimum cell count before suppression. 0 = no suppression "
            "(Public). Sensitive uses 0 too but is blocked at validation."
        ),
    )
    daily_user_cap = models.PositiveIntegerField(
        null=True, blank=True,
        help_text=(
            "Per-user-per-day aggregate query cap. NULL = unlimited "
            "(Public). 0 = blocked (Sensitive)."
        ),
    )
    daily_org_cap = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Per-org-per-day aggregate query cap. NULL = unlimited.",
    )
    blocks_aggregate = models.BooleanField(
        default=False,
        help_text=(
            "If True, the aggregate endpoint refuses any query that "
            "touches a Variable in this class. Sensitive = True."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Privacy class"
        verbose_name_plural = "Privacy classes"
        indexes = [models.Index(fields=["code"])]

    def __str__(self) -> str:
        return f"{self.label} (k={self.k_floor})"


class RefreshCadence(models.Model):
    """Catalogue-driven matview refresh cadences. Per ADR-0023 OPEN-1 the
    default cadence comes from PrivacyClass; Datasets may override.

    `interval_seconds` is used by the staleness check (2x rule)."""

    id = ULIDField(primary_key=True)
    code = models.CharField(
        max_length=24, unique=True, choices=RefreshCadenceCode.choices,
    )
    label = models.CharField(max_length=64)
    interval_seconds = models.PositiveIntegerField(
        help_text=(
            "Nominal refresh period in seconds. Used by the staleness "
            "fallback (HTTP 503 when refreshed_at older than 2x this)."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Refresh cadence"
        verbose_name_plural = "Refresh cadences"

    def __str__(self) -> str:
        return self.label


class Dataset(models.Model):
    """A discoverable dataset bound to one source matview. Metadata-
    driven: rows are created/updated by metadata_loader.refresh()."""

    id = ULIDField(primary_key=True)
    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    source_matview = models.CharField(
        max_length=128, blank=True,
        help_text=(
            "Postgres mv_explorer_* name backing this dataset. Blank "
            "during catalogue-only previews; required before aggregate "
            "queries can run."
        ),
    )
    privacy_class = models.ForeignKey(
        PrivacyClass, on_delete=models.PROTECT,
        related_name="datasets",
    )
    refresh_cadence = models.ForeignKey(
        RefreshCadence, on_delete=models.PROTECT,
        related_name="datasets",
    )

    # Minimum geographic aggregation level the dataset supports.
    # ADR-0023 D4: Personal-class datasets aggregate at sub_region;
    # others bottom out at sub_county. Below that → handoff.
    geographic_floor = models.CharField(
        max_length=24,
        default="sub_county",
        help_text=(
            "One of region|sub_region|district|sub_county. Aggregate "
            "queries below this floor are refused with HTTP 422."
        ),
    )

    # Soft scope tag for ABAC; mirrors the sub_region_code convention.
    # Datasets are catalogue metadata, so most rows are nationally
    # visible — this is reserved for the partner-scoped subset.
    sub_region_code = models.CharField(
        max_length=32, blank=True, db_index=True,
    )

    has_coverage_baseline = models.BooleanField(default=False)
    has_synthetic_sample = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dataset"
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["privacy_class"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.label}"


class Variable(models.Model):
    """One field exposed for discovery. Loaded by metadata_loader from
    DAT models + ChoiceLists + apps.update_workflow.field_catalog.

    Activation requires dual approval (DQA + DPO) via VariableApproval.
    Variables whose underlying model field shape changes flip to
    INACTIVE automatically — see metadata_loader.refresh().
    """

    id = ULIDField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="variables",
    )
    code = models.CharField(
        max_length=128,
        help_text=(
            "Stable dotted code e.g. 'household.dwelling_type'. Used in "
            "Query JSON projection + handoff payload."
        ),
    )
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Source binding — drives ORM composition in query_builder.
    source_model = models.CharField(
        max_length=128, blank=True,
        help_text="Django app_label.ModelName the field lives on.",
    )
    source_field = models.CharField(max_length=128, blank=True)
    data_type = models.CharField(
        max_length=24, default="text",
        help_text=(
            "One of text|number|boolean|date|select|geo. Drives the "
            "field-picker control and aggregation behaviour."
        ),
    )

    # ADR-0010 — coded fields point at a ChoiceList by name.
    choice_list = models.CharField(max_length=128, blank=True)
    choice_kind = models.CharField(max_length=16, blank=True)

    # Free-text synonym list for tsvector search (Phase 2 → OpenSearch).
    synonyms = models.JSONField(default=list, blank=True)

    privacy_class = models.ForeignKey(
        PrivacyClass, on_delete=models.PROTECT,
        related_name="variables",
    )
    status = models.CharField(
        max_length=16, choices=VariableStatus.choices,
        default=VariableStatus.INACTIVE,
    )
    questionnaire_section = models.CharField(max_length=32, blank=True)
    has_completeness_baseline = models.BooleanField(default=False)

    # Schema-drift detector — set by metadata_loader from a hash of
    # (data_type, choice_list, source_field). When the hash changes
    # the loader flips status=INACTIVE and bumps version.
    shape_hash = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Variable"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "code"],
                name="data_explorer_variable_unique_dataset_code",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["privacy_class"]),
            models.Index(fields=["dataset", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} [{self.status}]"


class VariableApproval(models.Model):
    """One approval row per (variable, approver, approval_role). Two
    distinct (variable, role) pairs in {DQA, DPO} activate the variable.
    Mirrors DqaRule and PMTModelVersion dual-approval patterns."""

    id = ULIDField(primary_key=True)
    variable = models.ForeignKey(
        Variable, on_delete=models.CASCADE, related_name="approvals",
    )
    approver = models.CharField(max_length=64)
    approval_role = models.CharField(
        max_length=8, choices=ApprovalRole.choices,
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)
    # When a PrivacyClass override accompanies the approval, the new
    # class is recorded here so the override is audited.
    overridden_privacy_class = models.ForeignKey(
        PrivacyClass, null=True, blank=True, on_delete=models.PROTECT,
        related_name="overrides_granted",
    )

    class Meta:
        verbose_name = "Variable approval"
        constraints = [
            models.UniqueConstraint(
                fields=["variable", "approval_role"],
                name="data_explorer_variable_approval_unique_role",
            ),
        ]
        indexes = [models.Index(fields=["variable", "approval_role"])]

    def __str__(self) -> str:
        return f"{self.variable.code} ← {self.approver} ({self.approval_role})"


class CoverageSnapshot(models.Model):
    """Periodic coverage row — % completeness by (dataset, geographic
    code). Surfaced via /coverage/{dataset_id}. Loaded by an off-line
    Celery task; this model is the storage shape."""

    id = ULIDField(primary_key=True)
    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="coverage_snapshots",
    )
    geo_level = models.CharField(max_length=24)
    geo_code = models.CharField(max_length=32, db_index=True)
    geo_label = models.CharField(max_length=128, blank=True)
    completeness_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
    )
    row_count = models.PositiveIntegerField(default=0)
    captured_at = models.DateTimeField()

    class Meta:
        verbose_name = "Coverage snapshot"
        indexes = [
            models.Index(fields=["dataset", "geo_level"]),
            models.Index(fields=["dataset", "captured_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.dataset_id} {self.geo_level}={self.geo_code} "
            f"{self.completeness_pct}%"
        )


class AggregateQueryLog(models.Model):
    """One row per aggregate query executed (including suppressed ones).

    ADR-0023 R1/R2: detect_overlap_burst sweeps this nightly looking
    for re-identification patterns. The table cardinality is high so
    we keep it separate from AuditEvent (which is hash-chained and
    therefore expensive on the insert path)."""

    id = ULIDField(primary_key=True)
    actor = models.CharField(max_length=64, db_index=True)
    executed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    dataset = models.ForeignKey(
        Dataset, on_delete=models.PROTECT, related_name="query_log",
    )
    projection_variables = models.JSONField(default=list)
    filter_variables = models.JSONField(default=list)
    filter_hash = models.CharField(max_length=64, db_index=True)

    geographic_scope = models.JSONField(default=dict)
    result_row_count = models.PositiveIntegerField(default=0)
    suppressed_cell_count = models.PositiveIntegerField(default=0)
    strictest_privacy_class = models.CharField(max_length=24)
    query_hash = models.CharField(max_length=64, db_index=True)

    matview_refreshed_at = models.DateTimeField(null=True, blank=True)
    staleness_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Aggregate query log"
        indexes = [
            models.Index(fields=["actor", "executed_at"]),
            models.Index(fields=["dataset", "executed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.actor} @ {self.executed_at} ({self.dataset.code})"


class QueryThrottleCounter(models.Model):
    """Daily counter per (actor, privacy_class). Acts as the Redis
    counter's persistent shadow so the throttle is enforceable in
    environments without Redis (tests, dev)."""

    id = ULIDField(primary_key=True)
    actor = models.CharField(max_length=64)
    privacy_class = models.ForeignKey(
        PrivacyClass, on_delete=models.CASCADE,
        related_name="throttle_counters",
    )
    org_code = models.CharField(max_length=64, blank=True, db_index=True)
    date_utc = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Query throttle counter"
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "privacy_class", "date_utc"],
                name="data_explorer_throttle_unique_actor_class_day",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.actor}/{self.privacy_class_id}@{self.date_utc} = {self.count}"


class ExplorerSession(models.Model):
    """A handoff anchor — created when an aggregate run feeds the
    'Request record-level data' button. The DRS draft references this
    so the discovery trail is auditable."""

    id = ULIDField(primary_key=True)
    actor = models.CharField(max_length=64, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_query_at = models.DateTimeField(auto_now=True)
    last_query_hash = models.CharField(max_length=64, blank=True)
    handoff_status = models.CharField(
        max_length=16, choices=HandoffStatus.choices,
        default=HandoffStatus.DRAFT,
    )
    data_request_id = models.CharField(max_length=26, blank=True)
    purpose_of_use = models.TextField(blank=True)

    class Meta:
        verbose_name = "Explorer session"
        indexes = [models.Index(fields=["actor", "started_at"])]

    def __str__(self) -> str:
        return f"ExplorerSession({self.actor} @ {self.started_at})"
