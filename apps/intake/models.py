"""INT models — Submission and FormVersion.

Sprint 2 scope: enough to make Web on-demand intake (US-005, US-006) and
the CAPI submission contract real. The CAPI runtime decision (ADR-0004)
remains open — this module is intentionally runtime-agnostic on the
client side.

References:
- SAD §4.1, §5.1 Submission and FormVersion
- SAD §11.1 MVP Release 1 INT scope
- ADR-0002 (Submission.id is ULID — externally referenced)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Channel(models.TextChoices):
    CAPI = "capi"
    WEB = "web"
    USSD = "ussd"
    BULK = "bulk"
    PARTNER_MIS = "partner_mis"


class SubmissionResult(models.TextChoices):
    COMPLETED = "completed"
    REFUSED = "refused"
    NOT_AT_HOME = "not_at_home"
    PARTIAL = "partial"
    OTHER = "other"


class SubmissionState(models.TextChoices):
    PENDING_QA = "pending_qa"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FormVersion(models.Model):
    """Versioned questionnaire definition. Sprint 2 stores just a JSON
    schema + skip-logic snapshot; the rule pack lives in apps.dqa."""

    id = ULIDField(primary_key=True)
    version = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    schema = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)

    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form version"
        indexes = [models.Index(fields=["is_active", "effective_from"])]

    def __str__(self) -> str:
        return f"FormVersion {self.name} v{self.version}"


class Submission(models.Model):
    """Single intake event. One Submission ↔ one DIH StageRecord ↔
    (after promotion) one Household. ULID id per ADR-0002 with channel
    prefix in display per SAD §5.2."""

    id = ULIDField(primary_key=True)

    channel = models.CharField(max_length=16, choices=Channel.choices)
    form_version = models.ForeignKey(
        FormVersion, on_delete=models.PROTECT, related_name="submissions",
    )

    # Enumerator / supervisor identifiers — strings for now, FKs once
    # the User catalogue from US-S2-002 (Keycloak) lands.
    enumerator = models.CharField(max_length=64)
    supervisor = models.CharField(max_length=64, blank=True)

    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    result = models.CharField(max_length=24, choices=SubmissionResult.choices)
    state = models.CharField(
        max_length=24, choices=SubmissionState.choices, default=SubmissionState.PENDING_QA,
    )

    # Pointer to the DIH side of the pipeline. Populated by
    # apps.intake.services.submit_intake immediately on submission.
    stage_record_id = models.CharField(max_length=26, blank=True, db_index=True)
    provisional_registry_id = models.CharField(max_length=26, blank=True, db_index=True)

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Submission"
        indexes = [
            models.Index(fields=["channel", "-created_at"]),
            models.Index(fields=["state"]),
            models.Index(fields=["enumerator"]),
        ]

    def __str__(self) -> str:
        return f"Submission {self.id} [{self.channel}/{self.state}]"
