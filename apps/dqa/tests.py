"""DQA engine + approval workflow tests.

Covers:
- Each of the three Sprint 0 wired rules (AC-MANDATORY*, AC-NIN-FORMAT,
  AC-GPS-ACCURACY) at the pass and fail boundary.
- The author != approved_by constraint at the service layer.
- Unknown operator raises DSLError.

References:
- SAD §4.2 acceptance criteria
- CLAUDE.md "Tests first for any change touching ... DAT-DQA"
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.dqa.engine import DSLError, evaluate, evaluate_expression
from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.dqa.services import (
    ApprovalError,
    approve,
    reject,
    retire,
    submit_for_approval,
)
from apps.security.models import AuditEvent

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def draft_rule(db):
    return DqaRule.objects.create(
        rule_id="TEST-RULE",
        version=1,
        description="for tests",
        severity=Severity.BLOCKING,
        expression={"field": "surname", "op": "not_null"},
        error_message_template="missing",
        applicability_filter={"entity": "member"},
        effective_from=date(2026, 1, 1),
        author="alice",
    )


# --- Engine: AC-MANDATORY ---------------------------------------------------

class TestMandatory:
    def test_passes_when_fields_present(self):
        expr = {"all_of": [
            {"field": "surname", "op": "not_null"},
            {"field": "first_name", "op": "not_null"},
        ]}
        assert evaluate_expression(expr, {"surname": "Okot", "first_name": "James"}) is True

    def test_fails_when_field_missing(self):
        expr = {"all_of": [
            {"field": "surname", "op": "not_null"},
            {"field": "first_name", "op": "not_null"},
        ]}
        assert evaluate_expression(expr, {"surname": "Okot", "first_name": ""}) is False
        assert evaluate_expression(expr, {"surname": "Okot"}) is False


# --- Engine: AC-NIN-FORMAT --------------------------------------------------

class TestNinFormat:
    PATTERN = r"^(CM|CF)[A-Z0-9]{12}$"

    @pytest.mark.parametrize("nin", [
        "CM1234567890AB",
        "CFABCDEFGHIJKL",
        "CM00000000000A",
    ])
    def test_passes_valid(self, nin):
        expr = {"field": "nin", "op": "regex", "value": self.PATTERN}
        assert evaluate_expression(expr, {"nin": nin}) is True

    @pytest.mark.parametrize("nin", [
        "CM12345",                # too short
        "XM12345678901A",         # wrong prefix
        "cm1234567890ab",         # lowercase
        "CM12345 67890AB",        # whitespace
        "",                       # empty
    ])
    def test_fails_invalid(self, nin):
        expr = {"field": "nin", "op": "regex", "value": self.PATTERN}
        assert evaluate_expression(expr, {"nin": nin}) is False

    def test_passes_when_optional_field_missing(self):
        # The seeded rule uses any_of(is_null, regex_match) so a NULL NIN passes.
        expr = {"any_of": [
            {"field": "nin", "op": "is_null"},
            {"field": "nin", "op": "regex", "value": self.PATTERN},
        ]}
        assert evaluate_expression(expr, {"nin": None}) is True


# --- Engine: AC-GPS-ACCURACY ------------------------------------------------

class TestGpsAccuracy:
    @pytest.mark.parametrize("accuracy", [0, 5, 9.99, 10])
    def test_passes_within_threshold(self, accuracy):
        expr = {"field": "acc", "op": "le", "value": 10}
        assert evaluate_expression(expr, {"acc": accuracy}) is True

    @pytest.mark.parametrize("accuracy", [10.01, 15, 100])
    def test_fails_above_threshold(self, accuracy):
        expr = {"field": "acc", "op": "le", "value": 10}
        assert evaluate_expression(expr, {"acc": accuracy}) is False

    def test_passes_when_gps_missing_via_any_of(self):
        expr = {"any_of": [
            {"field": "acc", "op": "is_null"},
            {"field": "acc", "op": "le", "value": 10},
        ]}
        assert evaluate_expression(expr, {"acc": None}) is True


# --- Engine: error paths ----------------------------------------------------

class TestEngineErrors:
    def test_unknown_operator_raises(self):
        with pytest.raises(DSLError):
            evaluate_expression({"field": "x", "op": "weird_op", "value": 1}, {"x": 1})

    def test_all_of_requires_list(self):
        with pytest.raises(DSLError):
            evaluate_expression({"all_of": "not-a-list"}, {})


# --- Engine: full evaluate() ------------------------------------------------

class TestEvaluateProducesResult:
    def test_pass_produces_empty_reason(self, draft_rule):
        ev = evaluate(draft_rule, {"surname": "Okot"}, record_type="member", record_id="m-1")
        assert ev.passed is True
        assert ev.reason == ""

    def test_fail_renders_reason(self, draft_rule):
        ev = evaluate(draft_rule, {"surname": ""}, record_type="member", record_id="m-1")
        assert ev.passed is False
        assert "missing" in ev.reason


# --- Approval workflow: author != approver ----------------------------------

class TestApprovalWorkflow:
    def test_full_flow(self, draft_rule):
        assert draft_rule.status == RuleStatus.DRAFT
        submit_for_approval(draft_rule)
        assert draft_rule.status == RuleStatus.PENDING_APPROVAL
        approve(draft_rule, approver="bob", note="ok")
        assert draft_rule.status == RuleStatus.ACTIVE
        assert draft_rule.approved_by == "bob"
        assert draft_rule.approved_at is not None

    def test_author_cannot_approve_own_rule(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="cannot approve"):
            approve(draft_rule, approver=draft_rule.author, note="not relevant")

    def test_cannot_approve_a_draft(self, draft_rule):
        with pytest.raises(ApprovalError, match="PENDING_APPROVAL"):
            approve(draft_rule, approver="bob", note="ok")

    def test_cannot_approve_without_approver(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="approver must be supplied"):
            approve(draft_rule, approver="", note="ok")


# --- DQA-2: lifecycle fields, audit emission, note/reason persistence -------

class TestLifecycleFields:
    def test_new_rule_has_empty_lifecycle_audit_fields(self, draft_rule):
        assert draft_rule.approval_note == ""
        assert draft_rule.rejection_reason == ""
        assert draft_rule.submitted_at is None

    def test_submit_sets_submitted_at(self, draft_rule):
        submit_for_approval(draft_rule)
        draft_rule.refresh_from_db()
        assert draft_rule.submitted_at is not None

    def test_approve_persists_note(self, draft_rule):
        submit_for_approval(draft_rule)
        approve(draft_rule, approver="bob",
                note="matches AC-MANDATORY for member surname")
        draft_rule.refresh_from_db()
        assert draft_rule.approval_note == "matches AC-MANDATORY for member surname"

    def test_approve_rejects_blank_note(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="note"):
            approve(draft_rule, approver="bob", note="")
        with pytest.raises(ApprovalError, match="note"):
            approve(draft_rule, approver="bob", note="   ")

    def test_reject_persists_reason(self, draft_rule):
        submit_for_approval(draft_rule)
        reject(draft_rule, approver="bob",
               reason="expression conflicts with AC-NIN-FORMAT")
        draft_rule.refresh_from_db()
        assert draft_rule.rejection_reason == "expression conflicts with AC-NIN-FORMAT"
        assert draft_rule.status == RuleStatus.REJECTED

    def test_reject_requires_non_blank_reason(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="reason"):
            reject(draft_rule, approver="bob", reason="")
        with pytest.raises(ApprovalError, match="reason"):
            reject(draft_rule, approver="bob", reason="   ")


class TestAuditEmission:
    """One AuditEvent per successful transition; none on failed transitions.
    entity_type="dqa.rule"; entity_id=rule.id (ULID); action names
    namespaced under dqa.rule_version.<verb>; field_changes carries
    before/after plus note/reason payload where applicable.
    """

    def _by_action(self, rule_id, action):
        return AuditEvent.objects.filter(
            entity_type="dqa.rule", entity_id=rule_id, action=action,
        )

    def test_submit_emits_one_event(self, draft_rule):
        before = AuditEvent.objects.count()
        submit_for_approval(draft_rule, actor="alice")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.submitted_for_approval",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "alice"
        assert ev.field_changes["before"] == RuleStatus.DRAFT
        assert ev.field_changes["after"] == RuleStatus.PENDING_APPROVAL

    def test_approve_emits_one_event_with_note(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before = AuditEvent.objects.count()
        approve(draft_rule, approver="bob", note="ok",
                actor="bob")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.approved",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "bob"
        assert ev.field_changes["approver"] == "bob"
        assert ev.field_changes["note"] == "ok"
        assert ev.field_changes["after"] == RuleStatus.ACTIVE

    def test_reject_emits_one_event_with_reason(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before = AuditEvent.objects.count()
        reject(draft_rule, approver="bob",
               reason="conflicts with AC-NIN-FORMAT", actor="bob")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.rejected",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.field_changes["reason"] == "conflicts with AC-NIN-FORMAT"
        assert ev.field_changes["after"] == RuleStatus.REJECTED

    def test_retire_emits_one_event(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        approve(draft_rule, approver="bob", note="ok", actor="bob")
        before = AuditEvent.objects.count()
        retire(draft_rule, actor="carol")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.retired",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "carol"
        assert ev.field_changes["after"] == RuleStatus.RETIRED

    def test_failed_transition_emits_no_event(self, draft_rule):
        # Draft → approve must raise; no audit row should land.
        before = AuditEvent.objects.count()
        with pytest.raises(ApprovalError):
            approve(draft_rule, approver="bob", note="ok")
        assert AuditEvent.objects.count() == before

    def test_blank_note_failure_emits_no_event(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before_count = AuditEvent.objects.count()
        with pytest.raises(ApprovalError):
            approve(draft_rule, approver="bob", note="   ")
        assert AuditEvent.objects.count() == before_count

    def test_self_approval_attempt_emits_no_event(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before_count = AuditEvent.objects.count()
        with pytest.raises(ApprovalError, match="cannot approve"):
            approve(draft_rule, approver=draft_rule.author, note="trying")
        assert AuditEvent.objects.count() == before_count
