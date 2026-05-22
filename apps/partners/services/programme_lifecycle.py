"""Programme lifecycle state machine + 4-step sign-off chain (US-182).

Mirrors the shape of `apps.update_workflow.services` (state guards +
no-self-approve + audit emission) and `apps.partners.services.signature`
(multi-step chain with email-identified signers).

States carried on `Programme.status` (extended via reference_data
migration 0010):

    draft  ──submit──▶  pending_approval ──sign(4 steps)──▶  active
                              │                                │
                              ├──reject──▶ draft               ├──suspend──▶ suspended
                              │                                │
                              │                                └──close──▶ closing ──▶ closed

`hold/release`, `propose_amendment`, and the `closing → closed` step
(driven by enrolment exits) are scoped out of this slice — see the
spec's §3.3 table. The functions below are atomic, raise
`ProgrammeLifecycleError` on guard violations (the viewset converts
to 400), and emit one AuditEvent per transition per §3.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

if TYPE_CHECKING:
    from apps.partners.models import Programme

# Canonical lifecycle codes — must stay in lockstep with the
# `programme_status` ChoiceList (reference_data migration 0010).
DRAFT = "draft"
PENDING_APPROVAL = "pending_approval"
ACTIVE = "active"
SUSPENDED = "suspended"
PENDING_AMENDMENT = "pending_amendment"
CLOSING = "closing"
CLOSED = "closed"

_SIGNABLE_STATUSES = (PENDING_APPROVAL, PENDING_AMENDMENT)
_REJECT_ROLLBACK = {
    PENDING_APPROVAL: DRAFT,
    PENDING_AMENDMENT: ACTIVE,  # amendments roll back to active, not draft
}
_MIN_REJECT_REASON = 20
_MIN_SUSPEND_REASON = 20
_MIN_CLOSE_REASON = 20


class ProgrammeLifecycleError(Exception):
    """Raised by the lifecycle functions when a guard refuses the
    requested transition. The viewset surfaces the message verbatim
    as a 400 detail."""


# ───────────────────────────────────────────────────────────────
# Submit — draft → pending_approval
# ───────────────────────────────────────────────────────────────

@transaction.atomic
def submit_for_signoff(
    programme: Programme,
    *,
    actor: str,
    nsr_coordinator_email: str,
    partner_steward_email: str,
    dpo_email: str,
    director_email: str,
) -> Programme:
    """Move a draft programme into the sign-off chain.

    Creates four `ProgrammeSignOff` rows (one per role) in pending
    status and flips `programme.status` to `pending_approval`. The
    four emails MUST be distinct and MUST NOT equal `programme.created_by`
    — the no-self-approve rule (AC-PROG-NO-SELF-APPROVE) is enforced
    at submit time AND again on each sign call.

    The function is idempotent only in the negative sense: a second
    submit on a programme that's already pending_approval refuses.
    """
    from apps.partners.models import ProgrammeSignOff

    if programme.status != DRAFT:
        raise ProgrammeLifecycleError(
            f"Programme {programme.code or programme.id} is not in DRAFT "
            f"(got {programme.status!r}); use propose_amendment for an "
            f"active programme.",
        )

    emails = {
        ProgrammeSignOff.ROLE_NSR_COORDINATOR: _norm_email(nsr_coordinator_email),
        ProgrammeSignOff.ROLE_PARTNER_STEWARD: _norm_email(partner_steward_email),
        ProgrammeSignOff.ROLE_DPO:             _norm_email(dpo_email),
        ProgrammeSignOff.ROLE_DIRECTOR:        _norm_email(director_email),
    }
    if any(not e for e in emails.values()):
        raise ProgrammeLifecycleError(
            "All four approver emails are required "
            "(NSR Unit Coordinator, Partner Data Steward, DPO, Director).",
        )
    if len(set(emails.values())) < 4:
        raise ProgrammeLifecycleError(
            "Sign-off emails must be distinct across the four steps "
            "(AC-PROG-NO-SELF-APPROVE).",
        )
    creator = _norm_email(programme.created_by)
    if creator and creator in emails.values():
        raise ProgrammeLifecycleError(
            "The programme creator cannot also be one of the four approvers "
            "(AC-PROG-NO-SELF-APPROVE).",
        )

    # Wipe any earlier rows for this (programme, revision) — happens
    # when a programme was previously submitted, rejected back to
    # draft, and is now re-submitted with a fresh chain.
    ProgrammeSignOff.objects.filter(
        programme=programme, revision=programme.current_revision,
    ).delete()

    rows = []
    for step, role in enumerate(ProgrammeSignOff.ROLE_ORDER, start=1):
        rows.append(ProgrammeSignOff.objects.create(
            programme=programme,
            revision=programme.current_revision,
            step=step,
            expected_role=role,
            expected_email=emails[role],
            status=ProgrammeSignOff.PENDING,
        ))

    programme.status = PENDING_APPROVAL
    programme.save(update_fields=["status", "updated_at"])

    emit_audit(
        "programme.submit", "programme", str(programme.id),
        actor=actor,
        reason=f"submitted for sign-off · revision {programme.current_revision}",
        field_changes={"emails": list(emails.values())},
    )
    return programme


# ───────────────────────────────────────────────────────────────
# Sign — pending → active (when last step lands)
# ───────────────────────────────────────────────────────────────

@transaction.atomic
def sign_step(
    programme: Programme,
    step: int,
    *,
    actor_email: str,
    note: str = "",
) -> Programme:
    """Mark a pending step as signed by `actor_email`. Enforces the
    chain ordering (step N can only sign after step N-1) and the
    no-self-approve rule.

    The 4th sign atomically flips `programme.status` to ACTIVE and
    sets `activated_at`. Subsequent submits open a new revision.
    """
    from apps.partners.models import ProgrammeSignOff

    if programme.status not in _SIGNABLE_STATUSES:
        raise ProgrammeLifecycleError(
            f"Programme {programme.code or programme.id} is not awaiting "
            f"sign-off (got {programme.status!r}).",
        )

    actor = _norm_email(actor_email)
    if not actor:
        raise ProgrammeLifecycleError("actor_email is required.")

    creator = _norm_email(programme.created_by)
    if creator and creator == actor:
        raise ProgrammeLifecycleError(
            "The programme creator cannot sign their own programme "
            "(AC-PROG-NO-SELF-APPROVE).",
        )

    # Resolve the target row for this revision/step.
    try:
        row = ProgrammeSignOff.objects.select_for_update().get(
            programme=programme,
            revision=programme.current_revision,
            step=step,
        )
    except ProgrammeSignOff.DoesNotExist as exc:
        raise ProgrammeLifecycleError(
            f"No sign-off row for step {step} on revision "
            f"{programme.current_revision}.",
        ) from exc

    if row.status != ProgrammeSignOff.PENDING:
        raise ProgrammeLifecycleError(
            f"Step {step} is not pending (status={row.status!r}).",
        )

    # Ordering — every earlier step must be SIGNED before this one
    # can sign. SKIPPED also counts as resolved.
    earlier_unresolved = ProgrammeSignOff.objects.filter(
        programme=programme,
        revision=programme.current_revision,
        step__lt=step,
    ).exclude(status__in=(ProgrammeSignOff.SIGNED, ProgrammeSignOff.SKIPPED))
    if earlier_unresolved.exists():
        raise ProgrammeLifecycleError(
            f"Cannot sign step {step} before steps 1..{step - 1} are signed.",
        )

    # Email match — the actor must match the email the submit step
    # registered for this role.
    if row.expected_email and row.expected_email != actor:
        raise ProgrammeLifecycleError(
            f"Step {step} expects {row.expected_email}; got {actor}.",
        )

    # No-self-cross: the actor must NOT have already signed an earlier
    # step on this revision. Four distinct signers required.
    prior_signers = set(
        ProgrammeSignOff.objects
        .filter(
            programme=programme,
            revision=programme.current_revision,
            status=ProgrammeSignOff.SIGNED,
        )
        .values_list("actual_email", flat=True),
    )
    if actor in prior_signers:
        raise ProgrammeLifecycleError(
            "Sign-off steps must be signed by distinct approvers "
            "(AC-PROG-NO-SELF-APPROVE).",
        )

    row.status = ProgrammeSignOff.SIGNED
    row.actual_email = actor
    row.decided_at = timezone.now()
    row.decision_note = note
    row.save()

    audit_event = emit_audit(
        "programme.signoff.signed", "programme", str(programme.id),
        actor=actor,
        reason=f"step={step} role={row.expected_role}",
        field_changes={"note": note},
    )
    # emit_audit returns the AuditEvent row; persist its ULID (26 chars,
    # fits the 64-char column). The earlier str(audit_event) produced
    # the full repr and tripped Postgres' character_varying(64) gate.
    if audit_event is not None:
        row.audit_event_id = str(audit_event.id)
        row.save(update_fields=["audit_event_id", "updated_at"])

    # 4th sign — flip the programme to ACTIVE.
    remaining_pending = ProgrammeSignOff.objects.filter(
        programme=programme,
        revision=programme.current_revision,
        status=ProgrammeSignOff.PENDING,
    ).exists()
    if not remaining_pending:
        was_amendment = programme.status == PENDING_AMENDMENT
        programme.status = ACTIVE
        if programme.activated_at is None:
            programme.activated_at = timezone.now()
        programme.save(update_fields=["status", "activated_at", "updated_at"])
        emit_audit(
            "programme.activated", "programme", str(programme.id),
            actor=actor,
            reason=(
                "all 4 steps signed"
                if not was_amendment
                else f"amendment r{programme.current_revision} approved"
            ),
        )

    return programme


# ───────────────────────────────────────────────────────────────
# Reject — pending → draft (or active, for amendments)
# ───────────────────────────────────────────────────────────────

@transaction.atomic
def reject_step(
    programme: Programme,
    step: int,
    *,
    actor_email: str,
    reason: str,
) -> Programme:
    """Reject the chain at `step`. Rolls the programme back to its
    previous state (DRAFT for initial submissions, ACTIVE for
    amendment chains) and marks every pending row as rejected.

    Reason is mandatory (≥ 20 chars) — copied from the
    `reject_change_request` guard in update_workflow.services.
    """
    from apps.partners.models import ProgrammeSignOff

    if programme.status not in _SIGNABLE_STATUSES:
        raise ProgrammeLifecycleError(
            f"Programme {programme.code or programme.id} is not awaiting "
            f"sign-off (got {programme.status!r}).",
        )
    if not reason or len(reason.strip()) < _MIN_REJECT_REASON:
        raise ProgrammeLifecycleError(
            f"Rejection reason must be at least {_MIN_REJECT_REASON} characters.",
        )

    actor = _norm_email(actor_email)
    creator = _norm_email(programme.created_by)
    if creator and creator == actor:
        raise ProgrammeLifecycleError(
            "The programme creator cannot reject their own programme "
            "(AC-PROG-NO-SELF-APPROVE).",
        )

    try:
        row = ProgrammeSignOff.objects.select_for_update().get(
            programme=programme,
            revision=programme.current_revision,
            step=step,
        )
    except ProgrammeSignOff.DoesNotExist as exc:
        raise ProgrammeLifecycleError(
            f"No sign-off row for step {step}.",
        ) from exc
    if row.status != ProgrammeSignOff.PENDING:
        raise ProgrammeLifecycleError(
            f"Step {step} is not pending (status={row.status!r}).",
        )

    now = timezone.now()
    row.status = ProgrammeSignOff.REJECTED
    row.actual_email = actor
    row.decided_at = now
    row.decision_note = reason
    row.save()

    # Mark every other pending row as skipped so the audit chain is
    # explicit about WHY they never got signed.
    ProgrammeSignOff.objects.filter(
        programme=programme,
        revision=programme.current_revision,
        status=ProgrammeSignOff.PENDING,
    ).update(
        status=ProgrammeSignOff.SKIPPED,
        decided_at=now,
        decision_note=f"chain rejected at step {step}",
    )

    rollback = _REJECT_ROLLBACK[programme.status]
    programme.status = rollback
    programme.save(update_fields=["status", "updated_at"])

    emit_audit(
        "programme.signoff.rejected", "programme", str(programme.id),
        actor=actor,
        reason=reason,
        field_changes={"step": step, "rolled_back_to": rollback},
    )
    return programme


# ───────────────────────────────────────────────────────────────
# Suspend — active → suspended
# ───────────────────────────────────────────────────────────────

@transaction.atomic
def suspend_programme(
    programme: Programme,
    *,
    actor: str,
    reason: str,
) -> Programme:
    """Move an ACTIVE programme to SUSPENDED. Reason mandatory.

    The webhook receiver is expected to keep accepting events from
    suspended programmes but log them with status `dropped_suspended`
    — that wiring lives in apps/api_gateway and is out-of-scope for
    this slice (the lifecycle bit, the model-level state, lands here).
    """
    if programme.status != ACTIVE:
        raise ProgrammeLifecycleError(
            f"Programme {programme.code or programme.id} is not ACTIVE "
            f"(got {programme.status!r}); cannot suspend.",
        )
    if not reason or len(reason.strip()) < _MIN_SUSPEND_REASON:
        raise ProgrammeLifecycleError(
            f"Suspension reason must be at least {_MIN_SUSPEND_REASON} characters.",
        )

    programme.status = SUSPENDED
    programme.save(update_fields=["status", "updated_at"])

    emit_audit(
        "programme.suspended", "programme", str(programme.id),
        actor=actor,
        reason=reason,
    )
    return programme


# ───────────────────────────────────────────────────────────────
# Close — active → closing
# ───────────────────────────────────────────────────────────────

@transaction.atomic
def close_programme(
    programme: Programme,
    *,
    actor: str,
    reason: str,
) -> Programme:
    """Move an ACTIVE programme into CLOSING. The CLOSING → CLOSED
    transition is driven by enrolment exits — when every active
    ProgrammeEnrolment for this programme has an exit_event recorded,
    a follow-up task closes it. That wiring is out-of-scope for this
    slice (HANDOFF §3.3 row "close_programme").
    """
    if programme.status != ACTIVE:
        raise ProgrammeLifecycleError(
            f"Programme {programme.code or programme.id} is not ACTIVE "
            f"(got {programme.status!r}); cannot close.",
        )
    if not reason or len(reason.strip()) < _MIN_CLOSE_REASON:
        raise ProgrammeLifecycleError(
            f"Closure reason must be at least {_MIN_CLOSE_REASON} characters.",
        )

    programme.status = CLOSING
    programme.closed_at = timezone.now()
    programme.save(update_fields=["status", "closed_at", "updated_at"])

    emit_audit(
        "programme.closing", "programme", str(programme.id),
        actor=actor,
        reason=reason,
    )
    return programme


# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def _norm_email(value: str) -> str:
    """Normalise an email string for comparison — strip + lowercase.
    Empty strings stay empty so callers can distinguish "not set"
    from a real address."""
    if not value:
        return ""
    return value.strip().lower()
