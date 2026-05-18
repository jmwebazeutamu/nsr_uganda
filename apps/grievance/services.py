"""GRM services — open / assign / escalate / resolve / close.

SLA defaults match SAD §4.4.7 (UPD) framing extended to GRM tiers:
- L1 Parish Chief: 24h
- L2 CDO: 48h
- L3 District: 72h
- L4 NSR Unit: 7d

Per SAD AC: a grievance resolved to a data correction opens a linked
UPD ChangeRequest. The link is recorded here; the auto-open workflow
lands in Sprint 2.5.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import (
    Category,
    Grievance,
    GrievanceStatus,
    GrievanceTask,
    TaskStatus,
    Tier,
)

SLA_BY_TIER = {
    Tier.L1_PARISH_CHIEF: timedelta(hours=24),
    Tier.L2_CDO: timedelta(hours=48),
    Tier.L3_DISTRICT: timedelta(hours=72),
    Tier.L4_NSR_UNIT: timedelta(days=7),
}


class GrievanceError(Exception):
    """A GRM transition is forbidden under current state."""


def _set_sla(grievance: Grievance) -> None:
    grievance.sla_deadline = grievance.opened_at + SLA_BY_TIER[grievance.tier]


@transaction.atomic
def open_grievance(
    *,
    category: str,
    description: str,
    household_id: str = "",
    member_id: str = "",
    reporter_name: str = "",
    reporter_phone: str = "",
    reporter_relationship: str = "",
    tier: str = Tier.L1_PARISH_CHIEF,
    assigned_to: str = "",
    actor: str = "",
    sub_category: str = "",
) -> Grievance:
    if category not in Category.values:
        raise GrievanceError(f"unknown category: {category!r}")
    g = Grievance.objects.create(
        category=category,
        sub_category=sub_category,
        description=description,
        household_id=household_id,
        member_id=member_id,
        reporter_name=reporter_name,
        reporter_phone=reporter_phone,
        reporter_relationship=reporter_relationship,
        tier=tier,
        status=GrievanceStatus.OPEN,
        assigned_to=assigned_to,
    )
    _set_sla(g)
    g.save(update_fields=["sla_deadline"])
    emit_audit(
        "create", "grievance", g.id, actor=actor or reporter_name or "anonymous",
        reason=f"category={category} tier={tier}",
        field_changes={"household_id": household_id, "member_id": member_id},
    )
    return g


@transaction.atomic
def assign(grievance: Grievance, *, assigned_to: str, actor: str) -> Grievance:
    if grievance.status not in (GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS):
        raise GrievanceError(f"cannot assign from {grievance.status}")
    grievance.assigned_to = assigned_to
    grievance.status = GrievanceStatus.IN_PROGRESS
    grievance.save(update_fields=["assigned_to", "status", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="assigned",
               field_changes={"assigned_to": assigned_to})
    return grievance


@transaction.atomic
def escalate(grievance: Grievance, *, actor: str, reason: str) -> Grievance:
    """Bump the grievance one tier up. L4 cannot be escalated further."""
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(f"cannot escalate {grievance.status}")
    if not reason:
        raise GrievanceError("escalation requires a non-empty reason")
    next_tier = {
        Tier.L1_PARISH_CHIEF: Tier.L2_CDO,
        Tier.L2_CDO: Tier.L3_DISTRICT,
        Tier.L3_DISTRICT: Tier.L4_NSR_UNIT,
        Tier.L4_NSR_UNIT: None,
    }[grievance.tier]
    if next_tier is None:
        raise GrievanceError("already at L4 — cannot escalate further")
    prev_tier = grievance.tier
    grievance.tier = next_tier
    grievance.status = GrievanceStatus.ESCALATED
    grievance.assigned_to = ""  # the receiving tier reassigns
    _set_sla(grievance)
    grievance.save(update_fields=["tier", "status", "assigned_to", "sla_deadline", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason=f"escalated: {reason}",
               field_changes={"from": prev_tier, "to": next_tier})
    return grievance


@transaction.atomic
def resolve(
    grievance: Grievance, *, actor: str, narrative: str,
    linked_change_request_id: str = "",
) -> Grievance:
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(f"already {grievance.status}")
    if not narrative:
        raise GrievanceError("resolution requires a narrative")
    # US-S21-003 — every task must be CLOSED before a grievance can
    # resolve. Operators can't side-step the work that was scoped
    # out (and audited) when the tasks were created.
    open_tasks = grievance.tasks.exclude(status=TaskStatus.CLOSED)
    open_count = open_tasks.count()
    if open_count:
        raise GrievanceError(
            f"cannot resolve: {open_count} task(s) still open. "
            "Close every task first.",
        )
    grievance.status = GrievanceStatus.RESOLVED
    grievance.resolved_at = timezone.now()
    grievance.resolution_narrative = narrative
    if linked_change_request_id:
        grievance.linked_change_request_id = linked_change_request_id
    grievance.save(update_fields=[
        "status", "resolved_at", "resolution_narrative",
        "linked_change_request_id", "updated_at",
    ])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="resolved",
               field_changes={"linked_change_request_id": linked_change_request_id})
    return grievance


@transaction.atomic
def close(grievance: Grievance, *, actor: str) -> Grievance:
    if grievance.status != GrievanceStatus.RESOLVED:
        raise GrievanceError(f"can only close RESOLVED (got {grievance.status})")
    grievance.status = GrievanceStatus.CLOSED
    grievance.closed_at = timezone.now()
    grievance.save(update_fields=["status", "closed_at", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor, reason="closed")
    return grievance


# --- US-S21-003 — GrievanceTask service layer ------------------------------

# Allowed task status transitions. Keep it linear: open → in_progress →
# closed. Re-opening a closed task should be rare and is a separate
# follow-up — for now we enforce strict forward motion so the audit
# trail is clean.
_TASK_TRANSITIONS = {
    TaskStatus.OPEN: {TaskStatus.IN_PROGRESS, TaskStatus.CLOSED},
    TaskStatus.IN_PROGRESS: {TaskStatus.CLOSED, TaskStatus.OPEN},
    TaskStatus.CLOSED: set(),  # terminal
}


@transaction.atomic
def create_task(
    grievance: Grievance, *,
    title: str, description: str, assigned_to: str, actor: str,
) -> GrievanceTask:
    """Open a new task on `grievance`. Tasks can be added in any
    pre-resolved status — a freshly-resolved grievance with no tasks
    is the happy path, but a long-running L3 case may collect tasks
    as it works."""
    if not title:
        raise GrievanceError("task title required")
    if not assigned_to:
        raise GrievanceError("task must be assigned to someone")
    if not actor:
        raise GrievanceError("actor required")
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(
            f"cannot add task to a {grievance.status} grievance",
        )
    task = GrievanceTask.objects.create(
        grievance=grievance,
        title=title, description=description or "",
        assigned_to=assigned_to,
        status=TaskStatus.OPEN, created_by=actor,
    )
    emit_audit(
        "create", "grievance.task", task.id, actor=actor,
        reason=f"task added to {grievance.id}",
        field_changes={
            "grievance_id": grievance.id,
            "assigned_to": assigned_to,
            "title": title,
        },
    )
    return task


@transaction.atomic
def transition_task(
    task: GrievanceTask, *, new_status: str, actor: str,
) -> GrievanceTask:
    """Move a task between statuses. Allowed paths: open↔in_progress,
    in_progress→closed, open→closed. Closed is terminal."""
    if not actor:
        raise GrievanceError("actor required")
    if new_status not in TaskStatus.values:
        raise GrievanceError(f"unknown task status: {new_status!r}")
    if new_status == task.status:
        return task  # no-op
    allowed = _TASK_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise GrievanceError(
            f"task transition {task.status!r}→{new_status!r} not allowed",
        )
    prev_status = task.status
    task.status = new_status
    if new_status == TaskStatus.CLOSED:
        task.closed_at = timezone.now()
        task.closed_by = actor
        task.save(update_fields=[
            "status", "closed_at", "closed_by", "updated_at",
        ])
    else:
        # Re-opening clears the close-stamp so a future close re-stamps.
        task.closed_at = None
        task.closed_by = ""
        task.save(update_fields=[
            "status", "closed_at", "closed_by", "updated_at",
        ])
    emit_audit(
        "update", "grievance.task", task.id, actor=actor,
        reason=f"{prev_status}→{new_status}",
        field_changes={"status": [new_status, prev_status]},
    )
    return task


@transaction.atomic
def open_change_request_for_grievance(
    grievance: Grievance,
    *,
    requester: str,
    changes: dict,
    sub_category: str = "",
    auto_submit: bool = False,
):
    """Auto-open a ChangeRequest from a DATA_CORRECTION grievance.

    Per SAD §4.4: "A grievance that resolves to a data correction opens
    a linked UPD." Returns the new ChangeRequest. When `auto_submit` is
    True (default False), the CR transitions DRAFT -> PENDING_APPROVAL
    in the same call — useful when the resolver already knows the field
    changes and there's nothing more to capture before approver review.

    On the linked CR's commit, the GRM signal handler in
    apps.grievance.signals closes the grievance.
    """
    from apps.update_workflow.models import (
        ChangeRequest,
        ChangeType,
        EntityType,
        SourceChannel,
    )
    from apps.update_workflow.services import submit_change_request

    if grievance.category != Category.DATA_CORRECTION:
        raise GrievanceError(
            "only DATA_CORRECTION grievances can auto-open a ChangeRequest"
        )
    if grievance.member_id:
        entity_type = EntityType.MEMBER
        entity_id = grievance.member_id
    elif grievance.household_id:
        entity_type = EntityType.HOUSEHOLD
        entity_id = grievance.household_id
    else:
        raise GrievanceError("grievance must point at a household or member")
    if grievance.linked_change_request_id:
        raise GrievanceError(
            f"grievance already linked to ChangeRequest {grievance.linked_change_request_id}"
        )

    cr = ChangeRequest.objects.create(
        entity_type=entity_type, entity_id=entity_id,
        change_type=ChangeType.CORRECTION, pmt_relevant=False,
        changes=changes or {},
        source_channel=SourceChannel.GRM,
        requester=requester,
        requester_note=f"Auto-opened from grievance {grievance.id}",
    )
    grievance.linked_change_request_id = cr.id
    grievance.save(update_fields=["linked_change_request_id", "updated_at"])
    emit_audit(
        "create", "change_request", cr.id, actor=requester,
        reason="grm-auto-open", field_changes={"grievance_id": grievance.id},
    )

    if auto_submit:
        submit_change_request(cr)
        cr.refresh_from_db()
    return cr
