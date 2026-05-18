"""DAT-DQA approval workflow service.

Single source of truth for the status transitions on a DqaRule. Admin
actions, REST endpoints, and management commands all go through here.

The author-cannot-approve rule (SAD §4.2.1, §4.2.3) is enforced here so it
cannot be bypassed by talking directly to the ORM.

DQA-2 (this revision):
- Persist approve.note → DqaRule.approval_note and reject.reason →
  DqaRule.rejection_reason; require both to be non-blank.
- submit_for_approval stamps DqaRule.submitted_at.
- Each successful transition emits one AuditEvent
  (entity_type="dqa.rule", entity_id=rule.id, action
  "dqa.rule_version.<verb>") with before/after state plus the
  note/reason payload where applicable. Failed transitions emit
  nothing — the @transaction.atomic decorator ensures the audit
  write rolls back alongside the rule update.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import DqaRule, RuleStatus


class ApprovalError(Exception):
    """The approval transition is forbidden."""


def _emit(rule: DqaRule, *, action: str, actor: str,
          before: str, after: str, payload: dict | None = None) -> None:
    """Write one AuditEvent for a successful rule transition.

    Mapping from the slice brief's vocabulary to the project's
    AuditEvent shape:
    - target_type → entity_type ("dqa.rule")
    - target_id   → entity_id (rule.id, a ULID)
    - before / after / payload → field_changes JSON blob
    - timestamp   → AuditEvent.occurred_at (auto-populated)
    """
    changes = {"before": before, "after": after}
    if payload:
        changes.update(payload)
    emit_audit(
        action=action,
        entity_type="dqa.rule",
        entity_id=rule.id,
        actor=actor or "system",
        actor_kind="user" if actor else "system",
        reason=f"rule_id={rule.rule_id} version={rule.version}",
        field_changes=changes,
    )


@transaction.atomic
def submit_for_approval(rule: DqaRule, *, actor: str = "") -> DqaRule:
    if rule.status != RuleStatus.DRAFT:
        raise ApprovalError(f"can only submit a DRAFT rule (got {rule.status})")
    before = rule.status
    rule.status = RuleStatus.PENDING_APPROVAL
    rule.submitted_at = timezone.now()
    rule.save(update_fields=["status", "submitted_at", "updated_at"])
    _emit(
        rule, action="dqa.rule_version.submitted_for_approval",
        actor=actor or rule.author, before=before, after=rule.status,
    )
    return rule


@transaction.atomic
def approve(rule: DqaRule, *, approver: str, note: str = "",
            actor: str = "") -> DqaRule:
    if rule.status != RuleStatus.PENDING_APPROVAL:
        raise ApprovalError(f"can only approve a PENDING_APPROVAL rule (got {rule.status})")
    if not approver:
        raise ApprovalError("approver must be supplied")
    if approver == rule.author:
        raise ApprovalError(
            f"the author of a rule cannot approve it (author={rule.author})"
        )
    if not note or not note.strip():
        raise ApprovalError("approval note is required")
    before = rule.status
    rule.status = RuleStatus.ACTIVE
    rule.approved_by = approver
    rule.approved_at = timezone.now()
    rule.approval_note = note.strip()
    rule.save(update_fields=[
        "status", "approved_by", "approved_at", "approval_note", "updated_at",
    ])
    _emit(
        rule, action="dqa.rule_version.approved",
        actor=actor or approver, before=before, after=rule.status,
        payload={"approver": approver, "note": rule.approval_note},
    )
    return rule


@transaction.atomic
def reject(rule: DqaRule, *, approver: str, reason: str = "",
           actor: str = "") -> DqaRule:
    if rule.status != RuleStatus.PENDING_APPROVAL:
        raise ApprovalError(f"can only reject a PENDING_APPROVAL rule (got {rule.status})")
    if approver == rule.author:
        raise ApprovalError("the author of a rule cannot reject it")
    if not reason or not reason.strip():
        raise ApprovalError("rejection reason is required")
    before = rule.status
    rule.status = RuleStatus.REJECTED
    rule.rejection_reason = reason.strip()
    rule.save(update_fields=["status", "rejection_reason", "updated_at"])
    _emit(
        rule, action="dqa.rule_version.rejected",
        actor=actor or approver, before=before, after=rule.status,
        payload={"approver": approver, "reason": rule.rejection_reason},
    )
    return rule


@transaction.atomic
def retire(rule: DqaRule, *, actor: str = "") -> DqaRule:
    if rule.status != RuleStatus.ACTIVE:
        raise ApprovalError(f"can only retire an ACTIVE rule (got {rule.status})")
    before = rule.status
    rule.status = RuleStatus.RETIRED
    rule.save(update_fields=["status", "updated_at"])
    _emit(
        rule, action="dqa.rule_version.retired",
        actor=actor or "system", before=before, after=rule.status,
    )
    return rule
