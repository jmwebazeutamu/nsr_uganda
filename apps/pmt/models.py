"""PMT models — versioned formula + per-household result.

Sprint 1 scope: enough scaffold to drive the recompute event-flow.
The actual formula (variables, weights, validation R²) is open item O-03;
the engine here uses a placeholder weighted sum so the pipeline is
exercised end-to-end. PMTModelVersion follows the same dual-approval
pattern as DqaRule and DdupModelVersion.

References:
- SAD §5.1 (PMTModelVersion, PMTResult), §11.1 (MVP scope)
- ADR-0002 (PMTModelVersion.id and PMTResult.id are ULIDs)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class ModelStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    RETIRED = "retired"


class Band(models.TextChoices):
    EXTREME_POVERTY = "extreme_poverty"
    POVERTY = "poverty"
    VULNERABLE = "vulnerable"
    NOT_POOR = "not_poor"


class PMTModelVersion(models.Model):
    """Versioned PMT formula. Activation requires dual approval per
    AC-PMT-MODEL-VERSION (analogous to DQA + DDUP)."""

    id = ULIDField(primary_key=True)
    version = models.PositiveIntegerField(unique=True)
    description = models.TextField(blank=True)

    # Placeholder formula until O-03 resolves: a list of
    # {"variable": "<path>", "weight": float, "transform": "<name>"}
    # plus a constant intercept. apps.pmt.engine reads this.
    variables = models.JSONField(default=list)
    intercept = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    validation_r_squared = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True,
    )

    # Band cut-offs. Semantics depend on band_strategy: when
    # band_strategy="threshold" the values are score thresholds
    # (inclusive lower bound); when band_strategy="percentile" the
    # values are population percentile ranks (0–100) and the actual
    # score thresholds live in PMTBandThreshold, recomputed daily.
    band_cutoffs = models.JSONField(
        default=dict, blank=True,
        help_text=(
            '{"extreme_poverty": 0, "poverty": 30, ...} — score thresholds '
            'when band_strategy="threshold"; percentile ranks (0–100) when '
            'band_strategy="percentile" (defaults from MGLSD policy: '
            '{extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100}).'
        ),
    )
    # Configuration knob for the band classifier. "threshold" reads
    # band_cutoffs as fixed score cuts (legacy behaviour); "percentile"
    # reads the daily-recomputed PMTBandThreshold rows. Spec §4.7.
    band_strategy = models.CharField(
        max_length=24, default="threshold",
        help_text=(
            "Either 'threshold' (legacy fixed cutoffs read off "
            "band_cutoffs) or 'percentile' (daily-recomputed "
            "PMTBandThreshold rows). ADR-0024 sets percentile as the "
            "policy default once the band-threshold job has populated."
        ),
    )

    # Calibration provenance — pinned to the source dataset so the
    # recalibration cadence (ADR-0023) is queryable. calibration_
    # year_end is the trigger field the staleness alert reads.
    calibration_dataset = models.CharField(
        max_length=128, blank=True,
        help_text="e.g. 'UNHS 2023/24'.",
    )
    calibration_year_end = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text=(
            "Latest year of the calibration dataset. Used by the "
            "model-staleness check (recalibrate every 3 years per "
            "ADR-0023)."
        ),
    )

    status = models.CharField(max_length=24, choices=ModelStatus.choices, default=ModelStatus.DRAFT)
    author = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PMT model version"
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"PMT v{self.version} [{self.status}]"


class PMTResult(models.Model):
    """One score per (household, model_version). Recomputes append a new
    row rather than overwriting so the history is queryable."""

    id = ULIDField(primary_key=True)
    household = models.ForeignKey(
        "data_management.Household", on_delete=models.PROTECT, related_name="pmt_results",
    )
    model_version = models.ForeignKey(
        PMTModelVersion, on_delete=models.PROTECT, related_name="results",
    )
    score = models.DecimalField(max_digits=8, decimal_places=4)
    band = models.CharField(max_length=24, choices=Band.choices)

    inputs_snapshot = models.JSONField(default=dict, blank=True)
    triggered_by = models.CharField(
        max_length=32, default="manual",
        help_text=(
            "ChoiceOption code from the seeded `pmt_trigger_source` "
            "ChoiceList (US-PMT-014). Canonical codes in "
            "apps.pmt.constants — do not hardcode."
        ),
    )

    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "PMT result"
        indexes = [
            models.Index(fields=["household", "-computed_at"]),
            models.Index(fields=["model_version", "-computed_at"]),
        ]

    def __str__(self) -> str:
        return f"PMTResult {self.household_id} {self.score} [{self.band}]"


class PMTBandThreshold(models.Model):
    """Empirical score threshold for one band under one model version
    (US-S22-PMT-BAND-THRESHOLD).

    MGLSD policy fixes eligibility cutoffs at population percentiles
    (e.g. "bottom 30%"), not at score values. The score that lands at
    the 30th percentile drifts as the registry grows and as recalibrations
    shift the distribution. Storing the score-threshold here, recomputed
    daily, lets `derive_band` pin-classify a single score in O(1) without
    running a percentile over the full population on every call.

    Reads
    -----
    `apps.pmt.engine.derive_band` loads the latest row per band for the
    target model version and picks the band whose score_threshold is the
    largest one not exceeding the score (inclusive lower-bound semantics).

    Writes
    ------
    `apps.pmt.tasks.recompute_band_thresholds_task` is the only writer
    in production. The job is append-only — every recompute writes a
    new row per band so the history is queryable for audit +
    calibration-drift tracking. Lookup convention: ORDER BY
    computed_at DESC LIMIT 1 per (model_version, band_name).

    Boundary semantics
    ------------------
    A score exactly equal to a band's score_threshold lands in that
    band (poorer side wins, inclusive lower bound). This expands
    eligibility marginally at the boundary — consistent with MGLSD's
    default; revisit only on policy directive.
    """

    id = ULIDField(primary_key=True)
    model_version = models.ForeignKey(
        PMTModelVersion, on_delete=models.PROTECT, related_name="band_thresholds",
    )
    band_name = models.CharField(max_length=32)
    # The score value below which the band applies. Decimal-precision
    # matches the underlying PMTResult.score field (max_digits=8,
    # decimal_places=4) plus two extra decimal places of headroom for
    # the percentile interpolation result.
    score_threshold = models.DecimalField(max_digits=10, decimal_places=6)
    # The percentile rank this threshold was computed at (0-100). The
    # mapping comes from PMTModelVersion.band_cutoffs.
    percentile_rank = models.PositiveSmallIntegerField()
    # Count of PMTResult rows the percentile was computed across. A
    # sample of 0 means the model has no scores yet — `derive_band`
    # treats that as a fallback case (see its docstring).
    sample_size = models.PositiveIntegerField()
    computed_at = models.DateTimeField(auto_now_add=True)
    computed_by = models.CharField(max_length=64, default="celery-beat")

    class Meta:
        verbose_name = "PMT band threshold"
        indexes = [
            models.Index(fields=["model_version", "band_name", "-computed_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"PMTBandThreshold v{self.model_version.version} "
            f"{self.band_name}@p{self.percentile_rank} "
            f"= {self.score_threshold}"
        )


class PMTModelSignOff(models.Model):
    """One row per step in the 3-step PMT model approval chain
    (HANDOFF — Admin Console + PMT §4.3).

    Same shape as `apps.partners.models.ProgrammeSignOff` (US-182)
    so the lifecycle service can reuse the proven no-self-approve
    + distinct-signers + chain-ordering logic. Email-identified
    signers; FK-to-User upgrade arrives when the admin-side role
    bindings (HANDOFF §3.3 group resolution) get wired.

    Chain (3 steps, fewer than the DSA chain because PMT calibration
    is a narrower audience):
        1. Author submission        (the analyst who built the model)
        2. MGLSD Steward            (policy team confirmation)
        3. Director General · UBOS  (statistical authority sign-off)

    `revision` increments per submit cycle; a rejected-and-resubmitted
    chain opens revision N+1. Statuses + role codes follow the
    ProgrammeSignOff vocabulary so the operator-facing chain widget
    is shared across modules.
    """

    PENDING = "pending"
    SIGNED = "signed"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    HOLD = "on_hold"

    ROLE_AUTHOR = "pmt_author"
    ROLE_MGLSD_STEWARD = "mglsd_steward"
    ROLE_UBOS_DG = "ubos_director_general"
    ROLE_ORDER = (
        ROLE_AUTHOR,
        ROLE_MGLSD_STEWARD,
        ROLE_UBOS_DG,
    )

    id = ULIDField(primary_key=True)
    model_version = models.ForeignKey(
        PMTModelVersion, on_delete=models.PROTECT, related_name="signoffs",
    )
    revision = models.PositiveIntegerField(default=1)
    step = models.PositiveSmallIntegerField()  # 1..3
    expected_role = models.CharField(max_length=64)
    expected_email = models.CharField(max_length=254, blank=True)
    actual_email = models.CharField(max_length=254, blank=True)
    # Plain CharField per ADR-0010 — canonical codes seeded as
    # `programme_signoff_status` ChoiceList (same vocabulary as
    # ProgrammeSignOff; partners-lint rejects inline choices=[...]).
    status = models.CharField(max_length=24, default=PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    audit_event_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PMT model sign-off"
        verbose_name_plural = "PMT model sign-offs"
        constraints = [
            models.UniqueConstraint(
                fields=["model_version", "revision", "step"],
                name="pmt_signoff_step_unique",
            ),
        ]
        ordering = ["model_version", "revision", "step"]
        indexes = [
            models.Index(fields=["model_version", "revision"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return (
            f"PMT v{self.model_version.version} "
            f"r{self.revision}/step{self.step} ({self.status})"
        )
