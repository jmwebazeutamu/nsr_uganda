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
    # US-S22-003 — bundle submissions can target every member of a
    # household in one request. Commit-time fan-out is a follow-up;
    # for now the value is accepted on the API surface so the React
    # modal can expose it without lying to the operator.
    ALL_MEMBERS = "all_members"


class ChangeType(models.TextChoices):
    CORRECTION = "correction"
    ADDITION = "addition"
    REMOVAL = "removal"
    VITAL_EVENT = "vital_event"        # NIRA push (system-named life event)
    PROGRAMME_STATE = "programme_state"  # partner MIS push
    RECERTIFICATION = "recertification"
    # US-S22-003 — operator-named change_type vocabulary used by the
    # rich Open-CR modal. Distinct from the existing system-event
    # types above: LIFE_EVENT is the operator-driven counterpart of
    # VITAL_EVENT; VERIFICATION, ADDRESS_MOVE, ROSTER_CHANGE,
    # ASSET_CHANGE are new categories the operator picks consciously.
    LIFE_EVENT = "life_event"
    VERIFICATION = "verification"
    ADDRESS_MOVE = "address_move"
    ROSTER_CHANGE = "roster_change"
    ASSET_CHANGE = "asset_change"


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

    # SAD §4.4.4 1% sample policy: a deterministic fraction of auto-
    # committed VITAL_EVENT / PROGRAMME_STATE requests are flagged here
    # so the QA team can audit auto-commit decisions retrospectively.
    sampled_for_audit = models.BooleanField(default=False)

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


class UpdRoutingRule(models.Model):
    """Operations-managed routing for (change_type, pmt_relevant) tuples.

    Per UPD-O-01, the SAD's hardcoded matrix is a stopgap. This table
    lets operations rebalance load (e.g., raise CORRECTION SLA from 72h
    to 96h during a backlog) without a deploy. `apps.update_workflow.
    routing.route()` reads the active row here and falls back to the
    DEFAULT_MATRIX constants when no row exists, so removing all rows
    cannot break the system.

    Active rule is unique per (change_type, pmt_relevant); inactive
    rules are retained for audit / version history.
    """

    change_type = models.CharField(max_length=24, choices=ChangeType.choices)
    pmt_relevant = models.BooleanField()
    required_role = models.CharField(max_length=32)
    sla_hours = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "UPD routing rule"
        verbose_name_plural = "UPD routing rules"
        constraints = [
            models.UniqueConstraint(
                fields=["change_type", "pmt_relevant"],
                condition=models.Q(is_active=True),
                name="upd_routing_unique_active_per_tuple",
            ),
        ]
        indexes = [
            models.Index(fields=["change_type", "pmt_relevant", "is_active"]),
        ]

    def __str__(self) -> str:
        return (f"{self.change_type}/pmt={self.pmt_relevant} "
                f"-> {self.required_role} ({self.sla_hours}h)")
