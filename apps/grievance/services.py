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
from apps.security.notifications import send_notification

from . import assignees

from .models import (
    Category,
    CommentKind,
    Grievance,
    GrievanceComment,
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
    # A grievance either names a household that exists or names none.
    # The console used to take the Registry ID as free text with a ULID
    # as the placeholder — nobody types a ULID, and a typo produced a
    # grievance pointing at nothing, which only surfaced when someone
    # tried to open a correction from it.
    household_id = (household_id or "").strip()
    geography: dict[str, str] = {}
    if household_id:
        from apps.data_management.models import Household
        household = Household.objects.filter(
            id=household_id, is_deleted=False,
        ).only("id", *Household.GEO_CODE_FIELDS.values()).first()
        if household is None:
            raise GrievanceError(
                f"household {household_id} is not in the registry",
            )
        # Copy where it is, so the grievance can be scoped without a
        # join and without a second scope rule. Column names match
        # Household's, which is what lets scope_q_for_field filter a
        # Grievance queryset unchanged.
        geography = {
            column: getattr(household, column) or ""
            for column in Household.GEO_CODE_FIELDS.values()
        }
    if member_id and not household_id:
        raise GrievanceError(
            "a grievance about a member must name that member's household",
        )
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
        **geography,
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
    # The assignee must be a real, active MIS user. The console used to
    # offer four invented names; an invented assignee is a grievance
    # nobody is working.
    try:
        user = assignees.resolve(assigned_to)
    except assignees.UnknownAssignee as exc:
        raise GrievanceError(str(exc)) from exc

    grievance.assigned_to = user.username
    grievance.status = GrievanceStatus.IN_PROGRESS
    grievance.save(update_fields=["assigned_to", "status", "updated_at"])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="assigned",
               field_changes={"assigned_to": user.username})
    notify_assignment(grievance, user=user, actor=actor)
    return grievance


def notify_assignment(grievance: Grievance, *, user, actor: str) -> dict:
    """Tell the assignee, by email, that a grievance is theirs.

    Deliberately after the save and outside the audit-bearing decision:
    send_notification never raises and audits its own outcome, so an
    SMTP outage cannot roll back an assignment. A user with no address
    on file is recorded as `notification.skipped` rather than silently
    passed over.
    """
    deadline = (
        grievance.sla_deadline.strftime("%d %b %Y %H:%M UTC")
        if grievance.sla_deadline else "not set"
    )
    subject = f"[NSR GRM] Grievance {grievance.id} assigned to you"
    body = (
        f"{assignees.display_name(user)},\n\n"
        f"Grievance {grievance.id} has been assigned to you by {actor}.\n\n"
        f"  Category : {grievance.get_category_display()}\n"
        f"  Tier     : {grievance.get_tier_display()}\n"
        f"  Household: {grievance.household_id or '— not household-related —'}\n"
        f"  SLA due  : {deadline}\n\n"
        f"{grievance.description}\n\n"
        "Open it in the console under Grievances → Assigned to me.\n"
    )
    return send_notification(
        to=assignees.email_for(user),
        subject=subject,
        body=body,
        entity_type="grievance",
        entity_id=grievance.id,
        audit_actor=actor,
        audit_action="grm.assigned.notified",
        audit_reason=f"assigned to {user.username}",
    )


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
    grievance.resolved_by = actor
    grievance.resolution_narrative = narrative
    if linked_change_request_id:
        grievance.linked_change_request_id = linked_change_request_id
    grievance.save(update_fields=[
        "status", "resolved_at", "resolved_by", "resolution_narrative",
        "linked_change_request_id", "updated_at",
    ])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="resolved",
               field_changes={
                   "linked_change_request_id": linked_change_request_id,
                   "resolution_narrative": narrative,
               })
    return grievance


@transaction.atomic
def close(grievance: Grievance, *, actor: str, narrative: str = "") -> Grievance:
    """Move grievance from RESOLVED → CLOSED. `narrative` is the
    closing reason / note pair captured from the operator; persisted
    on Grievance.closing_narrative so the workbench can display the
    full case-closeout block."""
    if grievance.status != GrievanceStatus.RESOLVED:
        raise GrievanceError(f"can only close RESOLVED (got {grievance.status})")
    grievance.status = GrievanceStatus.CLOSED
    grievance.closed_at = timezone.now()
    grievance.closed_by = actor
    grievance.closing_narrative = narrative or ""
    grievance.save(update_fields=[
        "status", "closed_at", "closed_by", "closing_narrative",
        "updated_at",
    ])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason="closed",
               field_changes={"closing_narrative": narrative or ""})
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
def add_comment(
    grievance: Grievance, *, body: str, actor: str,
    kind: str = CommentKind.NOTE, task: GrievanceTask | None = None,
) -> GrievanceComment:
    """Append a note to a grievance's running thread.

    Allowed in every status, including CLOSED. A comment records what
    someone knew or did; refusing to store it because the case has
    moved on loses the record rather than protecting anything. Nothing
    about the grievance's state changes — this is not a transition.
    """
    body = (body or "").strip()
    if not body:
        raise GrievanceError("a comment needs something in it")
    if not actor:
        raise GrievanceError("actor required")

    comment = GrievanceComment.objects.create(
        grievance=grievance, task=task, kind=kind,
        body=body, author=actor,
    )
    emit_audit(
        "create", "grievance.comment", comment.id, actor=actor,
        reason=f"comment on {grievance.id}",
        field_changes={"grievance_id": grievance.id, "kind": kind},
    )
    return comment


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
    try:
        assignee = assignees.resolve(assigned_to)
    except assignees.UnknownAssignee as exc:
        raise GrievanceError(str(exc)) from exc
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(
            f"cannot add task to a {grievance.status} grievance",
        )
    task = GrievanceTask.objects.create(
        grievance=grievance,
        title=title, description=description or "",
        assigned_to=assignee.username,
        status=TaskStatus.OPEN, created_by=actor,
    )
    emit_audit(
        "create", "grievance.task", task.id, actor=actor,
        reason=f"task added to {grievance.id}",
        field_changes={
            "grievance_id": grievance.id,
            "assigned_to": assignee.username,
            "title": title,
        },
    )
    notify_task_assignment(task, user=assignee, actor=actor)
    return task


def notify_task_assignment(task: GrievanceTask, *, user, actor: str) -> dict:
    """Tell the assignee a task is theirs. Same fail-open contract as
    notify_assignment — the email is a courtesy, the task is the record."""
    body = (
        f"{assignees.display_name(user)},\n\n"
        f"{actor} assigned you a task on grievance {task.grievance_id}.\n\n"
        f"  {task.title}\n\n"
        f"{task.description or '(no further detail)'}\n\n"
        "The grievance cannot be resolved until every task on it is "
        "closed.\n"
    )
    return send_notification(
        to=assignees.email_for(user),
        subject=f"[NSR GRM] Task assigned: {task.title}",
        body=body,
        entity_type="grievance.task",
        entity_id=task.id,
        audit_actor=actor,
        audit_action="grm.task.assigned.notified",
        audit_reason=f"task assigned to {user.username}",
    )


@transaction.atomic
def transition_task(
    task: GrievanceTask, *, new_status: str, actor: str, note: str = "",
) -> GrievanceTask:
    """Move a task between statuses. Allowed paths: open↔in_progress,
    in_progress→closed, open→closed. Closed is terminal.

    Closing requires `note` — what was done, or why the task is being
    dropped. A grievance cannot be resolved until every task on it is
    closed, so a task closed with no explanation is how a case reaches
    resolution with nothing recorded about the work. The note is stored
    as a comment on the grievance, not as a column here, so the
    grievance keeps one timeline.
    """
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
    note = (note or "").strip()
    if new_status == TaskStatus.CLOSED and not note:
        raise GrievanceError(
            "closing a task needs a note — say what was done, or why "
            "it is being dropped",
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
    if new_status == TaskStatus.CLOSED:
        add_comment(
            task.grievance, body=note, actor=actor,
            kind=CommentKind.TASK_CLOSED, task=task,
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
