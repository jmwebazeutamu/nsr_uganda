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
from apps.dqa.services import ApprovalError, approve, submit_for_approval

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
        approve(draft_rule, approver="bob")
        assert draft_rule.status == RuleStatus.ACTIVE
        assert draft_rule.approved_by == "bob"
        assert draft_rule.approved_at is not None

    def test_author_cannot_approve_own_rule(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="cannot approve"):
            approve(draft_rule, approver=draft_rule.author)

    def test_cannot_approve_a_draft(self, draft_rule):
        with pytest.raises(ApprovalError, match="PENDING_APPROVAL"):
            approve(draft_rule, approver="bob")

    def test_cannot_approve_without_approver(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="approver must be supplied"):
            approve(draft_rule, approver="")


# --- US-080: re-run rules on UPD commit ------------------------------------

class TestRulesOnUpdCommit:
    """When apps.update_workflow.commit_change_request fires its
    post_change_committed signal, the dqa app subscribes and re-runs
    every ACTIVE rule applicable to the changed record. Failure rows
    land in DqaResult so the violations dashboard reflects the new
    state; an audit event captures the re-evaluation. Without this
    hook, constraints added AFTER a record was first ingested
    never get evaluated against that record."""

    @pytest.fixture
    def _geo(self, db):
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"),
            ("district", "d", "sr"), ("county", "c", "d"),
            ("sub_county", "sc", "c"), ("parish", "p", "sc"),
            ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"U-{key.upper()}", name=key.title(),
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        return nodes

    @pytest.fixture
    def _member(self, _geo):
        from apps.data_management.models import Household, Member
        hh = Household.objects.create(
            region=_geo["r"], sub_region=_geo["sr"], district=_geo["d"],
            county=_geo["c"], sub_county=_geo["sc"], parish=_geo["p"],
            village=_geo["v"], urban_rural="rural",
            address_narrative="Plot 7",
        )
        return Member.objects.create(
            household=hh, line_number=1, surname="Okot",
            first_name="James", sex="M",
        )

    @pytest.fixture
    def _failing_rule(self, db):
        # Active rule scoped to members; trips on the fixture member
        # because surname="Okot" is not null AND `tin` field is missing
        # — `is_null` op should fail.
        return DqaRule.objects.create(
            rule_id="UPD-RERUN-TEST",
            version=1,
            description="re-run smoke",
            severity=Severity.WARNING,
            expression={"field": "surname", "op": "is_null"},  # always fails on a real surname
            error_message_template="surname must be empty (test rule)",
            applicability_filter={"entity": "member"},
            effective_from=date(2026, 1, 1),
            status=RuleStatus.ACTIVE,
            author="alice",
            approved_by="bob",
        )

    def _commit_a_change(self, member, approver="bob"):
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        from apps.update_workflow.services import (
            commit_change_request,
            submit_change_request,
        )
        req = ChangeRequest.objects.create(
            entity_type=EntityType.MEMBER, entity_id=member.id,
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            changes={"first_name": {"old": "James", "new": "Joseph"}},
            source_channel=SourceChannel.PARISH, requester="alice",
        )
        submit_change_request(req)
        commit_change_request(req, approver=approver)
        return req

    def test_commit_appends_dqaresult_for_failing_rule(
        self, _member, _failing_rule,
    ):
        from apps.dqa.models import DqaResult
        before = DqaResult.objects.filter(rule=_failing_rule).count()
        self._commit_a_change(_member)
        after = DqaResult.objects.filter(rule=_failing_rule).count()
        # Exactly one new row, scoped to the member.
        assert after == before + 1
        row = DqaResult.objects.filter(rule=_failing_rule).latest("executed_at")
        assert row.passed is False
        assert row.record_type == "member"
        assert str(_member.household_id) in row.record_id  # "<hh>:<line>"

    def test_passing_rule_does_not_create_row(self, _member, db):
        """The engine returns Evaluations for every rule, but only
        failures land in DqaResult — passing rules don't bloat the
        table."""
        from apps.dqa.models import DqaResult
        DqaRule.objects.create(
            rule_id="ALWAYS-PASS", version=1, description="pass",
            severity=Severity.INFO,
            expression={"field": "surname", "op": "not_null"},
            error_message_template="",
            applicability_filter={"entity": "member"},
            effective_from=date(2026, 1, 1),
            status=RuleStatus.ACTIVE,
            author="alice", approved_by="bob",
        )
        before = DqaResult.objects.count()
        self._commit_a_change(_member)
        # No DqaResult row for the passing rule.
        assert DqaResult.objects.count() == before

    def test_commit_emits_re_evaluated_audit(self, _member, _failing_rule):
        from apps.security.models import AuditEvent
        before = AuditEvent.objects.filter(
            action="rules_re_evaluated", entity_type="dat.member",
        ).count()
        self._commit_a_change(_member)
        after = AuditEvent.objects.filter(
            action="rules_re_evaluated", entity_type="dat.member",
        ).count()
        assert after == before + 1

    def test_household_change_evaluates_household_rules(self, _member):
        """The signal handler routes by entity_type — a household
        CR triggers household-scoped rules, not member-scoped."""
        from apps.dqa.models import DqaResult
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        from apps.update_workflow.services import (
            commit_change_request,
            submit_change_request,
        )
        DqaRule.objects.create(
            rule_id="HH-RERUN-TEST", version=1, description="hh re-run",
            severity=Severity.WARNING,
            expression={"field": "urban_rural", "op": "is_null"},
            error_message_template="",
            applicability_filter={"entity": "household"},
            effective_from=date(2026, 1, 1),
            status=RuleStatus.ACTIVE,
            author="alice", approved_by="bob",
        )
        hh = _member.household
        req = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id=hh.id,
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            changes={"address_narrative": {"old": "Plot 7", "new": "Plot 7A"}},
            source_channel=SourceChannel.PARISH, requester="alice",
        )
        submit_change_request(req)
        commit_change_request(req, approver="bob")
        # Failure row keyed by record_type=household.
        assert DqaResult.objects.filter(
            rule__rule_id="HH-RERUN-TEST",
            record_type="household", record_id=str(hh.id),
        ).exists()
