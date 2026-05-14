"""UPD models — change-request lifecycle.

Sprint 1 scope: ChangeRequest + its decision history. Covers AC-UPD-DIFF,
AC-UPD-NO-SELF-APPROVE, and the dual-approval shape that AC-UPD-PMT-PREVIEW
will hook into when apps.pmt lands. NIRA vital-event auto-commit and
recertification waves remain Sprint 2.

References:
- SAD §4.4 (sources, types, routing, commit, SLA, ACs)
- ADR-0002 (ChangeRequest.id is ULID, externally referenced as the citizen
  reference code)
- ADR-0003 (paired *Version rows preserved on commit)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class EntityType(models.TextChoices):
    HOUSEHOLD = "household"
    MEMBER = "member"


class ChangeType(models.TextChoices):
    CORRECTION = "correction"
    ADDITION = "addition"
    REMOVAL = "removal"
    VITAL_EVENT = "vital_event"        # NIRA push
    PROGRAMME_STATE = "programme_state"  # partner MIS push
    RECERTIFICATION = "recertification"


class SourceChannel(models.TextChoices):
    PARISH = "parish"
    CAPI = "capi"
    WEB = "web"
    NIRA = "nira"
    PARTNER_MIS = "partner_mis"
    CITIZEN_PORTAL = "citizen_portal"
    GRM = "grm"


class ChangeStatus(models.TextChoices):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING_APPROVAL = "pending_approval"
    COMMITTED = "committed"
    REJECTED = "rejected"
    REVERSED = "reversed"
    ON_HOLD = "on_hold"


class ChangeRequest(models.Model):
    """A proposed change to a Household or Member.

    `changes` is the field-level diff as a JSON dict shaped
    {field_name: {"old": <value>, "new": <value>}}. The diff is computed
    against the current row at capture time; the commit step re-checks
    against the live row to detect concurrent edits (AC-UPD-CONCURRENT).
    """

    id = ULIDField(primary_key=True)

    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    entity_id = models.CharField(max_length=26, db_index=True)

    change_type = models.CharField(max_length=24, choices=ChangeType.choices)
    pmt_relevant = models.BooleanField(default=False)

    changes = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)

    source_channel = models.CharField(max_length=24, choices=SourceChannel.choices)
    requester = models.CharField(max_length=64)
    requester_note = models.TextField(blank=True)

    status = models.CharField(
        max_length=24, choices=ChangeStatus.choices, default=ChangeStatus.DRAFT,
    )

    # Routing per SAD §4.4.4 — captured at submit time. UPD-O-01 will firm
    # this up; defaults applied in apps.update_workflow.routing.
    required_role = models.CharField(max_length=32, blank=True)

    approver = models.CharField(max_length=64, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)

    # SLA per SAD §4.4.7 — populated at submit; the breach dashboard
    # filters by this value.
    sla_deadline = models.DateTimeField(null=True, blank=True)

    # PMT preview snapshot (AC-UPD-PMT-PREVIEW). Recorded at submit
    # time; the actual recompute is post-commit in apps.pmt.
    pmt_preview = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Change request"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["status", "sla_deadline"]),
            models.Index(fields=["change_type", "pmt_relevant"]),
        ]

    def __str__(self) -> str:
        return f"CR {self.id} {self.entity_type}:{self.entity_id} [{self.status}]"
