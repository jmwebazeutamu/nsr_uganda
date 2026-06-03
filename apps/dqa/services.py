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

from .models import DqaRule, DqaRulePreviewRun, RuleStatus


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


# ---------------------------------------------------------------------------
# Preview — run a rule against a sample of registry households.
#
# The audit-friendly contract (DqaRulePreviewRun docstring): persist
# only sample size + counts + up to 10 failing record IDs. NEVER
# persist field values from the sample — the preview's whole point is
# to give the author a fail-rate estimate without leaking PII.
#
# Sampling is ORDER BY id LIMIT N so two consecutive runs against the
# same registry snapshot see the same households. RANDOM sampling would
# be unbiased but unreproducible; at 12 M scale a stable cursor of the
# first N households is enough to detect catastrophic rules.

_MAX_PREVIEW_FAILURES_PERSISTED = 10
_MIN_SAMPLE = 1
_MAX_SAMPLE = 10_000


@transaction.atomic
def preview_rule(
    rule: DqaRule, *, sample_size: int, actor: str = "",
) -> DqaRulePreviewRun:
    """Sweep `sample_size` registry households and count pass / fail
    for `rule`. Persist one DqaRulePreviewRun row + emit an audit
    event. Returns the persisted row.

    Retired rules are evaluated read-only — useful when authors clone
    a retired version to compare its impact against a successor.
    """
    from apps.data_management.models import Household

    from .engine import evaluate as engine_evaluate
    from .household_evaluator import evaluate_household
    from .models import RuleCategory
    from .pipeline import household_to_dqa_payload

    n = max(_MIN_SAMPLE, min(int(sample_size), _MAX_SAMPLE))
    qs = (
        Household.objects.order_by("id").prefetch_related("members")[:n]
    )
    is_intra = rule.category == RuleCategory.INTRA_HOUSEHOLD
    entity = (rule.applicability_filter or {}).get("entity", "household")

    pass_count = 0
    fail_count = 0
    failures: list[str] = []

    def _record_fail(hh_id: str) -> None:
        nonlocal fail_count
        fail_count += 1
        if len(failures) < _MAX_PREVIEW_FAILURES_PERSISTED:
            failures.append(hh_id)

    for hh in qs:
        hh_id = str(hh.id)
        try:
            if is_intra:
                rule_dict = {
                    "rule_id": rule.rule_id,
                    "version": rule.version,
                    "severity": rule.severity,
                    "parameters": rule.parameters or {},
                    "expression": rule.expression or {},
                    "fail_when": (rule.expression or {}).get(
                        "_fail_when",
                        {"op": "gt", "args": ["$", 0]},
                    ),
                    "error_message_template": rule.error_message_template,
                }
                outcome = evaluate_household(
                    [rule_dict], household_to_dqa_payload(hh), stage="PREVIEW",
                )
                results = outcome.get("results") or []
                first = results[0] if results else {"status": "error"}
                passed = first.get("status") == "pass"
            elif entity == "member":
                # Legacy member-scope rule: the household fails if any
                # of its members fails the rule. The first offender ends
                # the loop — preview only cares about pass / fail per
                # sampled record, not which member tripped it.
                passed = True
                for m in hh.members.all():
                    ev = engine_evaluate(
                        rule, m, record_type="member", record_id=str(m.id),
                    )
                    if not ev.passed:
                        passed = False
                        break
            else:
                ev = engine_evaluate(
                    rule, hh, record_type="household", record_id=hh_id,
                )
                passed = ev.passed
        except Exception:  # noqa: BLE001 - engine errors fail the record
            passed = False

        if passed:
            pass_count += 1
        else:
            _record_fail(hh_id)

    run = DqaRulePreviewRun.objects.create(
        rule=rule,
        sample_size=n,
        record_type="household",
        pass_count=pass_count,
        fail_count=fail_count,
        sample_failed_record_ids=failures,
        executed_by=actor or "system",
    )

    emit_audit(
        action="dqa.rule_version.preview",
        entity_type="dqa.rule",
        entity_id=rule.pk,
        actor=actor or "system",
        reason=f"rule_id={rule.rule_id} sample={n}",
        field_changes={
            "sample_size": n,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "preview_run_id": str(run.pk),
        },
    )

    return run
