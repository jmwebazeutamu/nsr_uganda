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

    # Band cut-offs (inclusive lower bound).
    band_cutoffs = models.JSONField(
        default=dict, blank=True,
        help_text='{"extreme_poverty": 0, "poverty": 30, "vulnerable": 60, "not_poor": 80}',
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
        help_text="dih_promote, upd_commit, manual, backfill",
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
