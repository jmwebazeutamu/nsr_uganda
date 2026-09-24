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

from . import assignees, reasons

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

def sla_for(tier: str) -> timedelta:
    """The window this tier gets, from the configured ladder.

    These four numbers were a module constant — 24/48/72/168 hours —
    beside a tier-to-role mapping that existed only inside the Tier
    enum's value strings. Both are policy, and policy that needs a
    deploy to change is policy operations cannot see. They live
    together in GrmTierRule now (see apps/grievance/models.py).
    """
    from .assignees import tier_rule

    return timedelta(hours=tier_rule(tier).sla_hours)


class GrievanceError(Exception):
    """A GRM transition is forbidden under current state."""


def _set_sla(grievance: Grievance) -> None:
    """Give the CURRENT tier its full window, from when it received the
    case.

    This measured from `opened_at` regardless of tier, so escalating a
    case that had already blown its L1 deadline handed L2 a deadline in
    the past — the receiving tier never got the 48 hours the matrix
    promises it. On production, cases sat 2,900 hours "overdue" at a
    tier they had only just reached.
    """
    started = grievance.tier_started_at or grievance.opened_at
    grievance.sla_deadline = started + sla_for(grievance.tier)


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

    # "abc123" was stored as a reporter phone. The registry already has
    # one normaliser — apps.ddup.phone.to_e164, which tier 2 matches on
    # — so the grievance reporter's number is held to the same shape
    # rather than a second rule with its own idea of a valid number.
    reporter_phone = (reporter_phone or "").strip()
    if reporter_phone:
        from apps.ddup.phone import to_e164

        normalised = to_e164(reporter_phone)
        if normalised is None:
            raise GrievanceError(
                f"{reporter_phone!r} is not a Ugandan mobile number — "
                "use 07XXXXXXXX or +2567XXXXXXXX",
            )
        reporter_phone = normalised
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
    # ESCALATED is assignable — it is the state a case is IN while it
    # waits for the receiving tier to pick it up. Refusing to assign it
    # meant an escalated case could never be worked: the tier it was
    # escalated to could not take it.
    if grievance.status not in (
        GrievanceStatus.OPEN,
        GrievanceStatus.IN_PROGRESS,
        GrievanceStatus.ESCALATED,
    ):
        raise GrievanceError(
            f"cannot assign a {grievance.status} grievance — "
            "reopen it first",
        )
    # The assignee must be a real, active MIS user who can actually
    # carry this case. The console used to offer four invented names;
    # an invented assignee is a grievance nobody is working. Then it
    # offered the whole user directory, which is the same problem
    # wearing real names — an L3 case handed to an enumerator in
    # another sub-region reaches someone with neither the authority to
    # decide it nor the scope to open it.
    try:
        user = assignees.resolve_for(
            assigned_to, tier=grievance.tier,
            household_id=grievance.household_id or "",
        )
    except (assignees.UnknownAssignee, assignees.IneligibleAssignee) as exc:
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



def _validated_narrative(action: str, *, reason_code: str, note: str) -> tuple:
    """(Reason, narrative) for a transition, or raise.

    The reason list used to live in the console, so the server accepted
    whatever string arrived — "ab" resolved a case. The claim is now
    checked against the catalogue, the operator's own note has to say
    something, and a reason that asserts a fact about the world is
    verified by the caller via `Reason.requires`.
    """
    reason = reasons.lookup(action, reason_code)
    if reason is None:
        allowed = ", ".join(r.code for r in reasons.BY_ACTION.get(action, ()))
        raise GrievanceError(
            f"unknown {action} reason {reason_code!r}. One of: {allowed}",
        )
    note = (note or "").strip()
    if len(note) < reasons.MIN_NOTE_LENGTH:
        raise GrievanceError(
            f"a {action} note must be at least "
            f"{reasons.MIN_NOTE_LENGTH} characters — say what happened",
        )
    return reason, reasons.narrative_for(reason, note)


def _require_grace_elapsed(grievance: Grievance) -> None:
    from django.conf import settings

    days = int(getattr(settings, "GRM_CLOSE_GRACE_DAYS", 30))
    if grievance.resolved_at is None:
        raise GrievanceError("the case has no resolution date to count from")
    elapsed = timezone.now() - grievance.resolved_at
    if elapsed < timedelta(days=days):
        remaining = timedelta(days=days) - elapsed
        raise GrievanceError(
            f"the {days}-day grace period has not expired — "
            f"{remaining.days}d {remaining.seconds // 3600}h remaining. "
            "Close it with a different reason if the reporter has "
            "confirmed.",
        )


def _require_linked_cr_applied(grievance: Grievance) -> None:
    from apps.update_workflow.models import ChangeRequest, ChangeStatus

    if not grievance.linked_change_request_id:
        raise GrievanceError(
            "this reason claims a correction was committed, but no "
            "change request is linked to the grievance",
        )
    cr = ChangeRequest.objects.filter(
        id=grievance.linked_change_request_id,
    ).first()
    if cr is None:
        raise GrievanceError(
            f"linked change request {grievance.linked_change_request_id} "
            "does not exist",
        )
    # COMMITTED is the only state in which the correction has actually
    # reached the registry. A draft, a submission and a pending
    # approval are all intentions.
    if cr.status != ChangeStatus.COMMITTED:
        raise GrievanceError(
            f"the linked change request is {cr.status}, not committed — "
            "a draft is not a correction",
        )


_REQUIREMENT_CHECKS = {
    "grace_elapsed": _require_grace_elapsed,
    "linked_cr_applied": _require_linked_cr_applied,
}


def _enforce(reason, grievance: Grievance) -> None:
    check = _REQUIREMENT_CHECKS.get(reason.requires)
    if check is not None:
        check(grievance)


@transaction.atomic
def escalate(
    grievance: Grievance, *, actor: str,
    reason_code: str = "", note: str = "", reason: str = "",
) -> Grievance:
    """Bump the grievance one tier up. L4 cannot be escalated further.

    `reason_code` + `note` are validated against the catalogue. `reason`
    is the system path — the SLA sweep escalates with its own sentence
    and no operator behind it.
    """
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(f"cannot escalate {grievance.status}")
    if reason_code:
        _, reason = _validated_narrative(
            "escalate", reason_code=reason_code, note=note,
        )
    if not reason:
        raise GrievanceError("escalation requires a reason")
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
    # The receiving tier's window starts now, not when the case was
    # first opened.
    grievance.tier_started_at = timezone.now()
    _set_sla(grievance)
    grievance.save(update_fields=[
        "tier", "status", "assigned_to", "tier_started_at",
        "sla_deadline", "updated_at",
    ])
    emit_audit("update", "grievance", grievance.id, actor=actor,
               reason=f"escalated: {reason}",
               field_changes={"from": prev_tier, "to": next_tier})
    return grievance


@transaction.atomic
def resolve(
    grievance: Grievance, *, actor: str, narrative: str = "",
    reason_code: str = "", note: str = "",
    linked_change_request_id: str = "",
) -> Grievance:
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise GrievanceError(f"already {grievance.status}")
    if linked_change_request_id:
        # Link it before the requirement check, so "committed via
        # linked UPD" can be satisfied by the CR named in this call.
        grievance.linked_change_request_id = linked_change_request_id
    if reason_code:
        reason, narrative = _validated_narrative(
            "resolve", reason_code=reason_code, note=note,
        )
        _enforce(reason, grievance)
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
def close(
    grievance: Grievance, *, actor: str, narrative: str = "",
    reason_code: str = "", note: str = "",
) -> Grievance:
    """Move grievance from RESOLVED → CLOSED. `narrative` is the
    closing reason / note pair captured from the operator; persisted
    on Grievance.closing_narrative so the workbench can display the
    full case-closeout block."""
    if grievance.status != GrievanceStatus.RESOLVED:
        raise GrievanceError(f"can only close RESOLVED (got {grievance.status})")
    if reason_code:
        reason, narrative = _validated_narrative(
            "close", reason_code=reason_code, note=note,
        )
        _enforce(reason, grievance)
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
    # A task is work at the case's tier, so it takes the case's rule.
    try:
        assignee = assignees.resolve_for(
            assigned_to, tier=grievance.tier,
            household_id=grievance.household_id or "",
        )
    except (assignees.UnknownAssignee, assignees.IneligibleAssignee) as exc:
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
