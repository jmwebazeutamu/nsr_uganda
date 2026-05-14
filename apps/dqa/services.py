"""DAT-DQA approval workflow service.

Single source of truth for the status transitions on a DqaRule. Admin
actions, REST endpoints, and management commands all go through here.

The author-cannot-approve rule (SAD §4.2.1, §4.2.3) is enforced here so it
cannot be bypassed by talking directly to the ORM.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import DqaRule, RuleStatus


class ApprovalError(Exception):
    """The approval transition is forbidden."""


@transaction.atomic
def submit_for_approval(rule: DqaRule) -> DqaRule:
    if rule.status != RuleStatus.DRAFT:
        raise ApprovalError(f"can only submit a DRAFT rule (got {rule.status})")
    rule.status = RuleStatus.PENDING_APPROVAL
    rule.save(update_fields=["status", "updated_at"])
    return rule


@transaction.atomic
def approve(rule: DqaRule, *, approver: str) -> DqaRule:
    if rule.status != RuleStatus.PENDING_APPROVAL:
        raise ApprovalError(f"can only approve a PENDING_APPROVAL rule (got {rule.status})")
    if not approver:
        raise ApprovalError("approver must be supplied")
    if approver == rule.author:
        raise ApprovalError(
            f"the author of a rule cannot approve it (author={rule.author})"
        )
    rule.status = RuleStatus.ACTIVE
    rule.approved_by = approver
    rule.approved_at = timezone.now()
    rule.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return rule


@transaction.atomic
def reject(rule: DqaRule, *, approver: str, reason: str = "") -> DqaRule:
    if rule.status != RuleStatus.PENDING_APPROVAL:
        raise ApprovalError(f"can only reject a PENDING_APPROVAL rule (got {rule.status})")
    if approver == rule.author:
        raise ApprovalError("the author of a rule cannot reject it")
    rule.status = RuleStatus.REJECTED
    rule.save(update_fields=["status", "updated_at"])
    return rule


@transaction.atomic
def retire(rule: DqaRule) -> DqaRule:
    if rule.status != RuleStatus.ACTIVE:
        raise ApprovalError(f"can only retire an ACTIVE rule (got {rule.status})")
    rule.status = RuleStatus.RETIRED
    rule.save(update_fields=["status", "updated_at"])
    return rule
