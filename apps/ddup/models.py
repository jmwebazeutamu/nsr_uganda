"""DAT-DDUP models — deduplication and record matching.

Sprint 0 scope: tier 1 (deterministic NIN match) end-to-end. Tier 2 (phone)
and tier 3 (probabilistic) wire in follow-ups; the model is ready for them.

References:
- SAD §4.3 matching strategy, merge operation, ACs
- ADR-0002 (MatchPair.id and MergeDecision.id are externally-referenced ULIDs)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class ModelStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    RETIRED = "retired"


class PairStatus(models.TextChoices):
    PENDING = "pending"
    MERGED = "merged"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"
    CROSS_HOUSEHOLD = "cross_household"


class MergeAction(models.TextChoices):
    MERGE = "merge"
    REJECT = "reject"
    ON_HOLD = "on_hold"
    CROSS_HOUSEHOLD = "cross_household"
    # Both records ARE the same person, but one is bad data (test entry,
    # double-submission, garbled re-capture). Survivor's fields stay
    # untouched; loser is soft-deleted exactly like a MERGE loser.
    # Reversible through the same 30-day window since the on-disk
    # effect mirrors merge.
    DISCARD_LOSER = "discard_loser"


class DdupModelVersion(models.Model):
    """Versioned match model. Tier 1 is deterministic; weights and similarity
    functions for tier 3 live here. Activation requires dual approval
    (SAD AC-DDUP-MODEL-VERSION)."""

    id = ULIDField(primary_key=True)
    version = models.PositiveIntegerField(unique=True)
    description = models.TextField(blank=True)
    config = models.JSONField()
    status = models.CharField(max_length=24, choices=ModelStatus.choices, default=ModelStatus.DRAFT)

    author = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "DDUP model version"
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"DdupModelVersion v{self.version} [{self.status}]"

    # --- Computed feedback counters (US-S10-002) -----------------------
    # The strongest signal that the auto-merge confidence threshold for
    # this model_version was wrong is auto-merges that got reversed.
    # We compute these live (no denormalised counter columns) so the
    # numbers never drift from the audit reality.
    #
    # An auto-merge is identified by MergeDecision.reason — the
    # auto_merge_high_confidence_pairs service sets it to a string
    # starting with "auto-merge tier-3 composite=...". Manual merges
    # don't share that prefix.

    AUTO_MERGE_REASON_PREFIX = "auto-merge tier-3"

    @property
    def _merge_decisions(self):
        return MergeDecision.objects.filter(
            match_pair__model_version=self, action=MergeAction.MERGE,
        )

    @property
    def auto_merge_count(self) -> int:
        return self._merge_decisions.filter(
            reason__startswith=self.AUTO_MERGE_REASON_PREFIX,
        ).count()

    @property
    def manual_merge_count(self) -> int:
        return self._merge_decisions.exclude(
            reason__startswith=self.AUTO_MERGE_REASON_PREFIX,
        ).count()

    @property
    def auto_reverse_count(self) -> int:
        return self._merge_decisions.filter(
            reason__startswith=self.AUTO_MERGE_REASON_PREFIX,
            reversed_at__isnull=False,
        ).count()

    @property
    def manual_reverse_count(self) -> int:
        return self._merge_decisions.exclude(
            reason__startswith=self.AUTO_MERGE_REASON_PREFIX,
        ).filter(reversed_at__isnull=False).count()

    @property
    def auto_reverse_rate(self) -> float | None:
        """Fraction of auto-merges that got reversed. None if no
        auto-merges have happened yet (avoids 0/0 nonsense in the
        admin / API)."""
        denom = self.auto_merge_count
        if denom == 0:
            return None
        return self.auto_reverse_count / denom


class MatchPair(models.Model):
    """A pair of records suspected of being duplicates.

    Member-level and household-level pairs share this table; record_type
    disambiguates. record_a_id is always the lexicographically smaller ULID
    so the (a, b) and (b, a) duplicates collapse to a single row.
    """

    id = ULIDField(primary_key=True)
    record_type = models.CharField(max_length=16)  # 'member' | 'household'
    record_a_id = models.CharField(max_length=26)
    record_b_id = models.CharField(max_length=26)

    tier = models.PositiveSmallIntegerField()  # 1=NIN/head-NIN+village, 2=phone, 3=probabilistic
    match_reason = models.CharField(max_length=64)
    composite_score = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    per_field_scores = models.JSONField(null=True, blank=True)

    model_version = models.ForeignKey(
        DdupModelVersion, on_delete=models.PROTECT, related_name="pairs",
    )
    status = models.CharField(max_length=24, choices=PairStatus.choices, default=PairStatus.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Match pair"
        constraints = [
            models.UniqueConstraint(
                fields=["record_type", "record_a_id", "record_b_id"],
                name="match_pair_uniqueness",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "tier"]),
            models.Index(fields=["record_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"MatchPair {self.record_type}: {self.record_a_id} <-> {self.record_b_id} [{self.status}]"


class MergeDecision(models.Model):
    """Records the operator decision for a MatchPair: merge, reject, hold,
    or cross_household. Decisions are immutable except for the reverse
    fields, which are set within the 30-day un-merge window
    (SAD §4.3.2). DDUP-O-02 considers extending beyond 30 days."""

    id = ULIDField(primary_key=True)
    match_pair = models.OneToOneField(
        MatchPair, on_delete=models.PROTECT, related_name="decision",
    )

    action = models.CharField(max_length=24, choices=MergeAction.choices)
    surviving_record_id = models.CharField(max_length=26, blank=True)
    losing_record_id = models.CharField(max_length=26, blank=True)
    chosen_field_values = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)

    decided_by = models.CharField(max_length=64)
    decided_at = models.DateTimeField(auto_now_add=True)

    reverse_window_until = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.CharField(max_length=64, blank=True)
    reversed_reason = models.TextField(blank=True)
    # Snapshot captured at merge time so reverse can restore the loser
    # and any side-effects (head_member re-points). Shape:
    #   {"surviving_overrides": {field: old_value, ...},
    #    "households_repointed_to_survivor": [household_id, ...]}
    pre_merge_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Merge decision"
        indexes = [
            models.Index(fields=["decided_at"]),
            models.Index(fields=["action", "decided_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} on pair {self.match_pair_id} by {self.decided_by}"
