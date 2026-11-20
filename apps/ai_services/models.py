"""AI services models — registry, feature switches, runs and suggestions.

ADR-0045. Three things live here and nothing else:

- AiModelVersion: the approved model registry (SSOT register row
  "AI model registry"). Same lifecycle as DdupModelVersion.
- AiFeature: the per-feature kill switch and promotion gate.
- AiRun / AiSuggestion: what a run produced. Advisory data; never
  registry state.
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class FeatureCode(models.TextChoices):
    """The AI features that exist. One per model task.

    The value is also `AiModelVersion.task`, so a model can only be
    registered for a feature that exists.
    """

    DDUP_RANK = "ddup.rank", "DDUP candidate ranking"
    DQA_ANOMALY = "dqa.anomaly", "DQA anomaly flags"


class FeatureState(models.TextChoices):
    OFF = "off", "Off"
    # Computes and stores; no screen shows it. Used to measure first.
    SHADOW = "shadow", "Shadow"
    # Screens may show the suggestion.
    ADVISORY = "advisory", "Advisory"


class ModelStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class Runtime(models.TextChoices):
    # In the application / Celery process. The only runtime ADR-0045
    # permits for personal data; an HTTP runtime needs its own ADR.
    LOCAL = "local", "Local (in-process)"


class AiModelVersion(models.Model):
    id = ULIDField(primary_key=True)
    name = models.CharField(max_length=64)
    version = models.PositiveIntegerField()
    task = models.CharField(max_length=32, choices=FeatureCode.choices)
    description = models.TextField(blank=True)

    # Who answers for this model once it is live.
    owner = models.CharField(max_length=128)
    # When a person last checked it against real reviewer decisions.
    # Null until validated; an unvalidated model cannot be approved.
    validated_on = models.DateField(null=True, blank=True)
    validation_report_ref = models.CharField(max_length=256, blank=True)

    runtime = models.CharField(max_length=16, choices=Runtime.choices, default=Runtime.LOCAL)
    # The weights themselves, as JSON. No pickle, no file path.
    artifact = models.JSONField()
    # sha256 of the canonical JSON of `artifact`, set at registration and
    # re-checked every time the model is loaded.
    artifact_sha256 = models.CharField(max_length=64)

    status = models.CharField(max_length=24, choices=ModelStatus.choices, default=ModelStatus.DRAFT)
    author = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI model version"
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name="aimodel_name_version_unique"),
            # One ACTIVE version per model name, enforced by the database
            # (same reasoning as dqarule_one_active_version_per_rule).
            models.UniqueConstraint(
                fields=["name"], condition=models.Q(status="active"),
                name="aimodel_one_active_version_per_name",
            ),
        ]
        indexes = [models.Index(fields=["task", "status"])]

    def __str__(self) -> str:
        return f"{self.name} v{self.version} [{self.status}]"


class AiFeature(models.Model):
    """Kill switch and promotion gate for one feature. Absent row = off."""

    code = models.CharField(max_length=32, primary_key=True, choices=FeatureCode.choices)
    state = models.CharField(max_length=16, choices=FeatureState.choices, default=FeatureState.OFF)
    model_version = models.ForeignKey(
        AiModelVersion, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
    )
    # Thresholds a feature must meet to enter ADVISORY. No defaults: the
    # numbers are an NSR Unit / DPO decision (ADR-0045 D6, AI-O-02).
    gate_config = models.JSONField(default=dict, blank=True)

    changed_by = models.CharField(max_length=64, blank=True)
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "AI feature"

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"


class AiRun(models.Model):
    """One batch of scoring. Carries the single audit event for the batch."""

    id = ULIDField(primary_key=True)
    feature = models.CharField(max_length=32, choices=FeatureCode.choices)
    model_version = models.ForeignKey(AiModelVersion, on_delete=models.PROTECT, related_name="runs")
    # The feature state the run executed under (shadow or advisory).
    state = models.CharField(max_length=16, choices=FeatureState.choices)
    subject_type = models.CharField(max_length=32)
    scored = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)
    # Incremental feeds (dqa.anomaly) resume from the newest `updated_at` a
    # run has covered. Null for feeds that rescan everything pending.
    watermark = models.DateTimeField(null=True, blank=True)
    actor = models.CharField(max_length=64)
    started_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI run"
        indexes = [models.Index(fields=["feature", "-started_at"])]

    def __str__(self) -> str:
        return f"AiRun {self.feature} {self.started_at:%Y-%m-%d %H:%M} ({self.scored} scored)"


class AiSuggestion(models.Model):
    """One model output about one subject. Advisory data only."""

    id = ULIDField(primary_key=True)
    run = models.ForeignKey(AiRun, on_delete=models.PROTECT, related_name="suggestions")
    feature = models.CharField(max_length=32, choices=FeatureCode.choices)
    subject_type = models.CharField(max_length=32)
    subject_id = models.CharField(max_length=26)
    score = models.FloatField()
    # Why: per-feature contributions, never raw personal data.
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI suggestion"
        indexes = [
            models.Index(fields=["feature", "subject_type", "subject_id"]),
            models.Index(fields=["run"]),
        ]

    def __str__(self) -> str:
        return f"{self.feature} {self.subject_type}:{self.subject_id} = {self.score:.3f}"
