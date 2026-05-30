"""Consent Management service layer — the single source of truth for every
consent state transition (US-CONSENT-01..18).

Mirrors apps.dqa.services: dual-approval (author != approver) is enforced
here so it cannot be bypassed via the ORM; each successful transition is
@transaction.atomic and emits exactly one AuditEvent (SEC), which is the
hash-chained record of record. State changes on ConsentRecord additionally
write an append-only ConsentRecordVersion row carrying the id of the emitted
AuditEvent (US-CONSENT-10 integrity link).

The module-level helper ``consent_state(member_id, purpose_code)`` is the
public contract DAT, PMT, REF, DRS, GRM, IDV and UPD call. When
``settings.CONSENT_MODULE_ENABLED`` is False every gate short-circuits to a
transparent-allow sentinel so existing functionality is unchanged.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import (
    ConsentEvidence,
    ConsentPurpose,
    ConsentRecord,
    ConsentRecordVersion,
    ConsentState,
    ConsentStatementVersion,
    ConsentWithdrawalTicket,
    LifecycleStatus,
    StatementStatus,
    TicketState,
    WithdrawalDecision,
    WithdrawalDecisionType,
)

# Audit entity_type constants (lowercased-comparable per the contract-test
# convention in tests/contract/data_explorer/test_audit_sweep.py).
ENTITY_PURPOSE = "consent.purpose"
ENTITY_STATEMENT = "consent.statement"
ENTITY_RECORD = "consent.record"
ENTITY_TICKET = "consent.withdrawal_ticket"


class ConsentError(Exception):
    """A consent transition is forbidden or invalid."""


class ApprovalError(ConsentError):
    """A dual-approval transition is forbidden (e.g. author self-approval)."""


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def module_enabled() -> bool:
    return bool(getattr(settings, "CONSENT_MODULE_ENABLED", False))


# Sentinel returned by consent_state() when the module is off — every gate
# treats this as "do not block".
TRANSPARENT_ALLOW = "TRANSPARENT_ALLOW"


def consent_state(member_id: str, purpose_code: str) -> str:
    """Return the current consent state for (member, purpose).

    - Module flag off  → TRANSPARENT_ALLOW (callers must not block).
    - No record yet    → ConsentState.PENDING_REVIEW (nothing captured).
    - Otherwise        → the stored ConsentRecord.state.

    This is the one helper downstream modules call; keeping the flag check
    here means no caller can accidentally hard-gate while the module is dark.
    """
    if not module_enabled():
        return TRANSPARENT_ALLOW
    rec = (
        ConsentRecord.objects
        .filter(member_id=member_id, purpose__code=purpose_code)
        .values_list("state", flat=True)
        .first()
    )
    return rec or ConsentState.PENDING_REVIEW


def is_granted(member_id: str, purpose_code: str) -> bool:
    """True when the purpose is granted OR the module is off (transparent
    allow). Convenience wrapper for boolean gates."""
    state = consent_state(member_id, purpose_code)
    return state in (TRANSPARENT_ALLOW, ConsentState.GRANTED)


# States that actively block a consent-gated action. PENDING_REVIEW
# (un-captured) is deliberately NOT blocking, so downstream gates stay inert
# until a citizen actively withholds consent — existing single-MIS flows keep
# working before consent is captured for a purpose.
_BLOCKING_STATES = (ConsentState.WITHDRAWN, ConsentState.REFUSED)


def is_blocked(member_id: str, purpose_code: str) -> bool:
    """True only when consent for (member, purpose) is explicitly WITHDRAWN or
    REFUSED. Un-captured records and the flag-off case both return False."""
    if not module_enabled():
        return False
    return consent_state(member_id, purpose_code) in _BLOCKING_STATES


def blocked_member_ids(purpose_code: str):
    """Return a queryset of member ids whose consent for ``purpose_code`` is
    WITHDRAWN or REFUSED. Intended as a SQL-layer exclude clause for
    candidate-list / extract queries (US-CONSENT-13/14) so an application-layer
    bug cannot leak un-consented rows. Empty when the flag is off."""
    if not module_enabled():
        return ConsentRecord.objects.none().values_list("member_id", flat=True)
    return (
        ConsentRecord.objects
        .filter(purpose__code=purpose_code, state__in=_BLOCKING_STATES)
        .values_list("member_id", flat=True)
    )


# ---------------------------------------------------------------------------
# Audit + version helpers
# ---------------------------------------------------------------------------


def _emit(action: str, entity_type: str, entity_id: str, *, actor: str,
          field_changes: dict | None = None, reason: str = "") -> str:
    """Emit one AuditEvent and return its id (a ULID)."""
    ev = emit_audit(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        actor=actor or "system",
        actor_kind="user" if actor else "system",
        reason=reason,
        field_changes=field_changes,
    )
    return ev.id


def _write_version(record: ConsentRecord, *, state_from: str, reason: str,
                   audit_event_id: str) -> ConsentRecordVersion:
    """Append a ConsentRecordVersion row capturing the new state, and close
    the previous open version's effective_to window."""
    now = timezone.now()
    (
        ConsentRecordVersion.objects
        .filter(consent_record=record, effective_to__isnull=True)
        .update(effective_to=now)
    )
    return ConsentRecordVersion.objects.create(
        consent_record=record,
        member_id=record.member_id,
        purpose_code=record.purpose.code,
        state=record.state,
        state_from=state_from or "",
        statement_version_id=record.statement_version_id or "",
        captured_via=record.captured_via,
        capture_method=record.capture_method,
        captured_by=record.captured_by,
        reason=reason[:128],
        audit_event_id=audit_event_id,
    )


# ---------------------------------------------------------------------------
# Purpose catalogue lifecycle (US-CONSENT-01) — dual-approval
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_purpose_for_approval(purpose: ConsentPurpose, *, actor: str = "") -> ConsentPurpose:
    if purpose.status != LifecycleStatus.DRAFT:
        raise ApprovalError(f"can only submit a DRAFT purpose (got {purpose.status})")
    before = purpose.status
    purpose.status = LifecycleStatus.PENDING_APPROVAL
    purpose.submitted_at = timezone.now()
    purpose.save(update_fields=["status", "submitted_at", "updated_at"])
    _emit("consent.purpose.created", ENTITY_PURPOSE, purpose.id,
          actor=actor or purpose.author,
          field_changes={"before": before, "after": purpose.status,
                         "purpose_code": purpose.code})
    return purpose


@transaction.atomic
def activate_purpose(purpose: ConsentPurpose, *, approver: str,
                     note: str = "", actor: str = "") -> ConsentPurpose:
    """Activate a purpose. Enforces author != approver (DPPA accountability)
    and a non-blank approval note, mirroring apps.dqa.services.approve."""
    if purpose.status != LifecycleStatus.PENDING_APPROVAL:
        raise ApprovalError(
            f"can only activate a PENDING_APPROVAL purpose (got {purpose.status})")
    if not approver:
        raise ApprovalError("approver must be supplied")
    if approver == purpose.author:
        raise ApprovalError(
            f"the author of a purpose cannot approve it (author={purpose.author})")
    if not note or not note.strip():
        raise ApprovalError("approval note is required")
    before = purpose.status
    purpose.status = LifecycleStatus.ACTIVE
    purpose.approved_by = approver
    purpose.approved_at = timezone.now()
    purpose.approval_note = note.strip()
    purpose.save(update_fields=[
        "status", "approved_by", "approved_at", "approval_note", "updated_at",
    ])
    _emit("consent.purpose.activated", ENTITY_PURPOSE, purpose.id,
          actor=actor or approver,
          field_changes={"before": before, "after": purpose.status,
                         "purpose_code": purpose.code, "approver": approver,
                         "note": purpose.approval_note})
    return purpose


@transaction.atomic
def reject_purpose(purpose: ConsentPurpose, *, approver: str,
                   reason: str = "", actor: str = "") -> ConsentPurpose:
    if purpose.status != LifecycleStatus.PENDING_APPROVAL:
        raise ApprovalError(
            f"can only reject a PENDING_APPROVAL purpose (got {purpose.status})")
    if approver == purpose.author:
        raise ApprovalError("the author of a purpose cannot reject it")
    if not reason or not reason.strip():
        raise ApprovalError("rejection reason is required")
    purpose.status = LifecycleStatus.REJECTED
    purpose.rejection_reason = reason.strip()
    purpose.save(update_fields=["status", "rejection_reason", "updated_at"])
    _emit("consent.purpose.rejected", ENTITY_PURPOSE, purpose.id,
          actor=actor or approver,
          field_changes={"after": purpose.status, "purpose_code": purpose.code,
                         "reason": purpose.rejection_reason})
    return purpose


@transaction.atomic
def retire_purpose(purpose: ConsentPurpose, *, actor: str = "") -> ConsentPurpose:
    if purpose.status != LifecycleStatus.ACTIVE:
        raise ApprovalError(f"can only retire an ACTIVE purpose (got {purpose.status})")
    purpose.status = LifecycleStatus.RETIRED
    purpose.save(update_fields=["status", "updated_at"])
    _emit("consent.purpose.retired", ENTITY_PURPOSE, purpose.id,
          actor=actor or "system",
          field_changes={"after": purpose.status, "purpose_code": purpose.code})
    return purpose


# ---------------------------------------------------------------------------
# Statement version lifecycle (US-CONSENT-02) — dual-approval + supersession
# ---------------------------------------------------------------------------


def pending_reconsent_count(purpose: ConsentPurpose) -> int:
    """How many GRANTED records would be flagged Pending re-consent if a
    material statement activated on this purpose (CR2 — shown before commit)."""
    return ConsentRecord.objects.filter(
        purpose=purpose, state=ConsentState.GRANTED,
    ).count()


@transaction.atomic
def submit_statement_for_approval(stmt: ConsentStatementVersion, *, actor: str = "") -> ConsentStatementVersion:
    if stmt.status != StatementStatus.DRAFT:
        raise ApprovalError(f"can only submit a DRAFT statement (got {stmt.status})")
    stmt.status = StatementStatus.PENDING_APPROVAL
    stmt.submitted_at = timezone.now()
    stmt.save(update_fields=["status", "submitted_at", "updated_at"])
    _emit("consent.statement.created", ENTITY_STATEMENT, stmt.id,
          actor=actor or stmt.author,
          field_changes={"after": stmt.status, "purpose_code": stmt.purpose.code,
                         "statement_version": stmt.version})
    return stmt


@transaction.atomic
def activate_statement(stmt: ConsentStatementVersion, *, approver: str,
                       note: str = "", actor: str = "") -> ConsentStatementVersion:
    """Activate a statement version. Supersedes the prior ACTIVE version for
    the purpose. If ``is_material``, every GRANTED record on the purpose is
    flagged PENDING_RE_CONSENT (CR2). Enforces author != approver."""
    if stmt.status != StatementStatus.PENDING_APPROVAL:
        raise ApprovalError(
            f"can only activate a PENDING_APPROVAL statement (got {stmt.status})")
    if not approver:
        raise ApprovalError("approver must be supplied")
    if approver == stmt.author:
        raise ApprovalError(
            f"the author of a statement cannot approve it (author={stmt.author})")
    if not note or not note.strip():
        raise ApprovalError("approval note is required")

    today = timezone.now().date()
    # Supersede the current ACTIVE version (if any) for this purpose.
    superseded = (
        ConsentStatementVersion.objects
        .filter(purpose=stmt.purpose, status=StatementStatus.ACTIVE)
        .exclude(pk=stmt.pk)
    )
    for prior in superseded:
        prior.status = StatementStatus.SUPERSEDED
        prior.effective_to = today
        prior.save(update_fields=["status", "effective_to", "updated_at"])
        _emit("consent.statement.superseded", ENTITY_STATEMENT, prior.id,
              actor=actor or approver,
              field_changes={"after": prior.status,
                             "purpose_code": prior.purpose.code,
                             "statement_version": prior.version,
                             "superseded_by": stmt.version})

    stmt.status = StatementStatus.ACTIVE
    stmt.approved_by = approver
    stmt.approved_at = timezone.now()
    stmt.approval_note = note.strip()
    stmt.effective_from = today
    stmt.save(update_fields=[
        "status", "approved_by", "approved_at", "approval_note",
        "effective_from", "updated_at",
    ])

    reconsent_flagged = 0
    if stmt.is_material:
        granted = ConsentRecord.objects.filter(
            purpose=stmt.purpose, state=ConsentState.GRANTED,
        )
        for rec in granted:
            state_from = rec.state
            rec.state = ConsentState.PENDING_RE_CONSENT
            rec.save(update_fields=["state", "updated_at"])
            aid = _emit("consent.record.pending_reconsent", ENTITY_RECORD, rec.id,
                        actor=actor or approver,
                        field_changes={"before": state_from, "after": rec.state,
                                       "purpose_code": stmt.purpose.code,
                                       "reason": "material_statement_supersession"})
            _write_version(rec, state_from=state_from,
                           reason="material_statement_supersession",
                           audit_event_id=aid)
            reconsent_flagged += 1

    _emit("consent.statement.activated", ENTITY_STATEMENT, stmt.id,
          actor=actor or approver,
          field_changes={"after": stmt.status, "purpose_code": stmt.purpose.code,
                         "statement_version": stmt.version,
                         "is_material": stmt.is_material,
                         "reconsent_flagged": reconsent_flagged,
                         "approver": approver, "note": stmt.approval_note})
    return stmt


# ---------------------------------------------------------------------------
# Capture (US-CONSENT-03/04/11/16) + withdrawal (US-CONSENT-06/07)
# ---------------------------------------------------------------------------


def active_statement_for(purpose: ConsentPurpose) -> ConsentStatementVersion | None:
    return (
        ConsentStatementVersion.objects
        .filter(purpose=purpose, status=StatementStatus.ACTIVE)
        .order_by("-version")
        .first()
    )


@transaction.atomic
def capture_consent(*, member, purpose: ConsentPurpose, state: str,
                    captured_via: str, capture_method: str = "",
                    captured_by: str = "", statement_version: ConsentStatementVersion | None = None,
                    proxy_member_id: str = "", proxy_relationship: str = "",
                    reason: str = "") -> ConsentRecord:
    """Create or update the ConsentRecord for (member, purpose) to ``state``.

    Emits the matching audit event (consent.granted / consent.refused /
    consent.withdrawn / generic consent.captured) and writes a
    ConsentRecordVersion row. Idempotent upsert on (member, purpose).
    """
    if statement_version is None and state == ConsentState.GRANTED:
        statement_version = active_statement_for(purpose)

    rec, _created = ConsentRecord.objects.select_for_update().get_or_create(
        member=member, purpose=purpose,
        defaults={
            "state": state,
            "captured_via": captured_via,
            "capture_method": capture_method,
            "captured_by": captured_by,
            "statement_version": statement_version,
            "proxy_member_id": proxy_member_id,
            "proxy_relationship": proxy_relationship,
        },
    )
    state_from = "" if _created else rec.state
    if not _created:
        rec.state = state
        rec.captured_via = captured_via
        rec.capture_method = capture_method
        rec.captured_by = captured_by
        if statement_version is not None:
            rec.statement_version = statement_version
        rec.proxy_member_id = proxy_member_id
        rec.proxy_relationship = proxy_relationship
        rec.save(update_fields=[
            "state", "captured_via", "capture_method", "captured_by",
            "statement_version", "proxy_member_id", "proxy_relationship",
            "updated_at",
        ])

    action = {
        ConsentState.GRANTED: "consent.granted",
        ConsentState.REFUSED: "consent.refused",
        ConsentState.WITHDRAWN: "consent.withdrawn",
    }.get(state, "consent.captured")

    aid = _emit(action, ENTITY_RECORD, rec.id, actor=captured_by,
                field_changes={"before": state_from, "after": state,
                               "purpose_code": purpose.code,
                               "member_id": member.id,
                               "captured_via": captured_via,
                               "capture_method": capture_method})
    _write_version(rec, state_from=state_from, reason=reason, audit_event_id=aid)
    return rec


def attach_evidence(*, record: ConsentRecord, evidence_type: str,
                    object_key: str = "", thumbprint_sha256: str = "",
                    witness_name: str = "", witness_role: str = "") -> ConsentEvidence:
    return ConsentEvidence.objects.create(
        consent_record=record,
        evidence_type=evidence_type,
        object_key=object_key,
        thumbprint_sha256=thumbprint_sha256,
        witness_name=witness_name,
        witness_role=witness_role,
    )


@transaction.atomic
def open_withdrawal_ticket(*, member, purpose: ConsentPurpose,
                           requested_by: str, reason_code: str = "",
                           reason_note: str = "") -> ConsentWithdrawalTicket:
    """Open a withdrawal ticket (US-CONSENT-06). Idempotent on
    (member, purpose, requested_at_day): a repeat request the same day returns
    the existing ticket rather than opening a second one. Raises ConsentError
    if the purpose is not withdrawable."""
    if not purpose.withdrawable:
        raise ConsentError(
            f"purpose {purpose.code} is not withdrawable "
            f"(lawful basis {purpose.lawful_basis})")

    now = timezone.now()
    today = now.date()
    sla_days = int(getattr(settings, "CONSENT_WITHDRAWAL_SLA_DAYS", 30))
    record = (
        ConsentRecord.objects
        .filter(member=member, purpose=purpose).first()
    )
    ticket, created = ConsentWithdrawalTicket.objects.get_or_create(
        member=member, purpose=purpose, requested_at_day=today,
        defaults={
            "consent_record": record,
            "state": TicketState.OPEN,
            "reason_code": reason_code,
            "reason_note": reason_note,
            "requested_by": requested_by,
            "sla_deadline": now + timedelta(days=sla_days),
        },
    )
    if created:
        _emit("consent.withdrawal.ticket_opened", ENTITY_TICKET, ticket.id,
              actor=requested_by,
              field_changes={"member_id": member.id, "purpose_code": purpose.code,
                             "sla_deadline": ticket.sla_deadline.isoformat(),
                             "reason_code": reason_code})
    return ticket


@transaction.atomic
def decide_withdrawal(ticket: ConsentWithdrawalTicket, *, decision: str,
                      rationale: str, decided_by: str,
                      second_approver: str = "") -> WithdrawalDecision:
    """Record a DPO decision on a withdrawal ticket (US-CONSENT-07) and move
    the ticket + (on CONFIRM/OVERRIDE) the underlying consent record."""
    if not rationale or not rationale.strip():
        raise ConsentError("a decision rationale is required")

    dec = WithdrawalDecision.objects.create(
        ticket=ticket, decision=decision, rationale=rationale.strip(),
        decided_by=decided_by, second_approver=second_approver,
    )

    new_state = {
        WithdrawalDecisionType.CONFIRM: TicketState.CONFIRMED,
        WithdrawalDecisionType.OVERRIDE_PUBLIC_TASK: TicketState.PUBLIC_TASK_OVERRIDE,
        WithdrawalDecisionType.REQUEST_CLARIFICATION: TicketState.CLARIFICATION_REQUESTED,
        WithdrawalDecisionType.HOLD: TicketState.IN_DPO_REVIEW,
    }[decision]
    ticket.state = new_state
    if new_state in (TicketState.CONFIRMED, TicketState.PUBLIC_TASK_OVERRIDE):
        ticket.closed_at = timezone.now()
    ticket.save(update_fields=["state", "closed_at", "updated_at"])

    # On CONFIRM, withdraw the underlying consent record.
    if decision == WithdrawalDecisionType.CONFIRM and ticket.consent_record_id:
        rec = ticket.consent_record
        if rec.state != ConsentState.WITHDRAWN:
            state_from = rec.state
            rec.state = ConsentState.WITHDRAWN
            rec.save(update_fields=["state", "updated_at"])
            aid = _emit("consent.withdrawn", ENTITY_RECORD, rec.id,
                        actor=decided_by,
                        field_changes={"before": state_from, "after": rec.state,
                                       "purpose_code": rec.purpose.code,
                                       "ticket_id": ticket.id})
            _write_version(rec, state_from=state_from,
                           reason=f"withdrawal_confirmed:{ticket.id}",
                           audit_event_id=aid)

    _emit("consent.withdrawal.ticket_decided", ENTITY_TICKET, ticket.id,
          actor=decided_by,
          field_changes={"decision": decision, "after": ticket.state,
                         "rationale": dec.rationale,
                         "second_approver": second_approver})
    return dec


# ---------------------------------------------------------------------------
# DDUP merge reconciliation (US-CONSENT-15)
# ---------------------------------------------------------------------------


@transaction.atomic
def reconcile_consent_on_merge(*, surviving, loser, actor: str = "") -> dict:
    """Reconcile the consent records of two members being merged (DDUP).

    - Union of GRANTED per purpose.
    - Any WITHDRAWN on either side makes the survivor WITHDRAWN for that purpose.
    - A conflict (one side GRANTED, the other REFUSED) raises ConsentError,
      which rolls back the enclosing merge transaction so the dedup review
      queue can surface it for manual reconciliation.

    Inert (no-op) when the module flag is off — there are no consent records
    to reconcile, so existing DDUP behaviour is unchanged.
    """
    if not module_enabled():
        return {"reconciled": 0}

    loser_recs = {
        r.purpose_id: r for r in
        ConsentRecord.objects.filter(member=loser).select_related("purpose")
    }
    surv_recs = {
        r.purpose_id: r for r in
        ConsentRecord.objects.filter(member=surviving).select_related("purpose")
    }
    reconciled = 0
    for pid in set(loser_recs) | set(surv_recs):
        ls = loser_recs.get(pid)
        ss = surv_recs.get(pid)
        present = [x for x in (ls, ss) if x]
        states = {x.state for x in present}
        purpose = present[0].purpose

        if ConsentState.GRANTED in states and ConsentState.REFUSED in states:
            raise ConsentError(
                f"consent conflict on purpose {purpose.code}: one side GRANTED, "
                f"the other REFUSED — resolve before merging members "
                f"{surviving.id}/{loser.id}")

        if ConsentState.WITHDRAWN in states:
            target = ConsentState.WITHDRAWN
        elif ConsentState.GRANTED in states:
            target = ConsentState.GRANTED
        else:
            target = present[0].state

        if ss is None:
            ss = ConsentRecord.objects.create(
                member=surviving, purpose=purpose, state=target,
                captured_via=ls.captured_via, capture_method=ls.capture_method,
                captured_by=actor, statement_version=ls.statement_version)
            state_from = ""
        elif ss.state != target:
            state_from = ss.state
            ss.state = target
            ss.save(update_fields=["state", "updated_at"])
        else:
            continue

        aid = _emit("consent.merge.reconciled", ENTITY_RECORD, ss.id, actor=actor,
                    field_changes={"purpose_code": purpose.code, "after": target,
                                   "surviving": surviving.id, "loser": loser.id})
        _write_version(ss, state_from=state_from,
                       reason=f"ddup_merge:{loser.id}", audit_event_id=aid)
        reconciled += 1
    return {"reconciled": reconciled}


# ---------------------------------------------------------------------------
# UPD head-change re-consent (US-CONSENT-16)
# ---------------------------------------------------------------------------


@transaction.atomic
def require_head_registration_consent(*, head_member, actor: str = "") -> bool:
    """When a household's head changes, the new head must carry active
    REGISTRATION consent. If they do not, set their REGISTRATION record to
    PENDING_RE_CONSENT (the re-capture sub-task) and emit a routing event for
    the Parish Chief. Returns True if a re-capture was opened.

    Inert (returns False) when the module flag is off.
    """
    if not module_enabled():
        return False
    if consent_state(head_member.id, "REGISTRATION") == ConsentState.GRANTED:
        return False
    try:
        purpose = ConsentPurpose.objects.get(code="REGISTRATION")
    except ConsentPurpose.DoesNotExist:
        return False
    capture_consent(
        member=head_member, purpose=purpose,
        state=ConsentState.PENDING_RE_CONSENT,
        captured_via="UPD_RECAPTURE", captured_by=actor,
        reason="upd_head_change_recapture")
    _emit("consent.upd.recapture_required", ENTITY_RECORD, head_member.id,
          actor=actor,
          field_changes={"member_id": head_member.id,
                         "purpose_code": "REGISTRATION", "route_to": "parish_chief"})
    return True
