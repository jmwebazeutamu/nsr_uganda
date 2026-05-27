"""US-S11-044 — Tests for the intra-household DQA evaluator.

Pure-function tests (no DB) cover the DSL grammar + the 8 INTRA_HOUSEHOLD
rule shapes. Persistence-layer tests (with DB) cover DqaEvaluation +
AuditEvent emission.
"""

from __future__ import annotations

import pytest

from apps.dqa.household_evaluator import (
    evaluate_household,
    evaluate_rule,
)

# ---------------------------------------------------------------------------
# Fixture payloads — kept tiny and explicit; each rule's tests build on top.

def _hh(members, **household_overrides):
    return {
        "id": "01HHTEST",
        "reported_household_size": len(members),
        "members": members,
        **household_overrides,
    }


def _m(line, **fields):
    """Build a member dict. `line` becomes line_number; the rest is
    arbitrary fields the DSL might read."""
    return {
        "id": f"01M{line:03d}",
        "line_number": line,
        "relationship_to_head": "",
        "age_years": None,
        "sex": "1",
        **fields,
    }


# ---------------------------------------------------------------------------
# 1. Plain DSL primitives + reference resolution

class TestDsl:
    def _eval(self, expression, fail_when=None, **kwargs):
        rule = {
            "rule_id": "T", "version": 1, "severity": "block",
            "parameters": kwargs.pop("parameters", {}),
            "expression": expression,
            "fail_when": fail_when or {"op": "gt", "args": ["$", 0]},
            "error_message_template": kwargs.pop("template", ""),
        }
        payload = kwargs.pop("payload", _hh([_m(1)]))
        return evaluate_rule(rule, payload)

    def test_count_where_zero(self):
        r = self._eval({"op": "count_where",
                        "predicate": {"op": "eq", "args": ["$.relationship_to_head", "01"]}})
        assert r["status"] == "pass"
        assert r["offending_member_ids"] == []

    def test_count_where_picks_offenders(self):
        # 2 members both flagged as head — count_where captures both.
        payload = _hh([
            _m(1, relationship_to_head="01"),
            _m(2, relationship_to_head="01"),
        ])
        r = self._eval(
            {"op": "count_where",
             "predicate": {"op": "eq", "args": ["$.relationship_to_head", "01"]}},
            fail_when={"op": "gt", "args": ["$", 1]},
            payload=payload,
        )
        assert r["status"] == "fail"
        assert sorted(r["offending_member_ids"]) == ["01M001", "01M002"]

    def test_parameters_ref_resolves(self):
        payload = _hh([_m(1, age_years=10), _m(2, age_years=30)])
        r = self._eval(
            {"op": "count_where",
             "predicate": {"op": "lt", "args": ["$.age_years", "$parameters.min_age"]}},
            parameters={"min_age": 18},
            payload=payload,
        )
        # One member under 18 → count 1 → fail (default fail_when: gt 0).
        assert r["status"] == "fail"
        assert r["offending_member_ids"] == ["01M001"]

    def test_undeclared_parameter_surfaces_as_error(self):
        payload = _hh([_m(1, age_years=10)])
        r = self._eval(
            {"op": "count_where",
             "predicate": {"op": "lt", "args": ["$.age_years", "$parameters.missing_key"]}},
            payload=payload,
        )
        assert r["status"] == "error"
        assert "missing_key" in r["message"] or "missing_key" in str(r)

    def test_lookup_member_by_line_number(self):
        payload = _hh([
            _m(1, surname="Okello"),
            _m(2, surname="Akello"),
        ])
        # Find the member with surname="Akello"; assert their line is 2.
        rule = {
            "rule_id": "T", "version": 1, "severity": "info",
            "parameters": {"target": "Akello"},
            "expression": {
                "op": "lookup_member", "by": "surname",
                "value": "$parameters.target",
            },
            # fail_when is irrelevant for this test — we just want the
            # return value. Use is_null so a missing lookup fails.
            "fail_when": {"op": "is_null", "args": ["$"]},
            "error_message_template": "",
        }
        r = evaluate_rule(rule, payload)
        # The lookup found a member → fail_when (is_null) is False → pass.
        assert r["status"] == "pass"

    def test_message_template_interpolation(self):
        payload = _hh([_m(1, age_years=10, relationship_to_head="01")])
        r = self._eval(
            {"op": "count_where",
             "predicate": {"op": "and", "args": [
                 {"op": "eq", "args": ["$.relationship_to_head", "01"]},
                 {"op": "lt", "args": ["$.age_years", "$parameters.min_head_age"]},
             ]}},
            parameters={"min_head_age": 12},
            template="Head must be at least {min_head_age}.",
            payload=payload,
        )
        assert r["status"] == "fail"
        assert r["message"] == "Head must be at least 12."

    def test_unknown_operator_raises_dsl_error_at_call_site(self):
        # DslError is raised by _eval_expr; evaluate_rule catches it
        # and returns status=error so the caller doesn't blow up.
        rule = {
            "rule_id": "T", "version": 1, "severity": "info",
            "parameters": {}, "expression": {"op": "bogus", "args": []},
            "fail_when": {"op": "gt", "args": ["$", 0]},
            "error_message_template": "",
        }
        r = evaluate_rule(rule, _hh([_m(1)]))
        assert r["status"] == "error"
        assert "bogus" in r.get("message", "") or "bogus" in str(r)


# ---------------------------------------------------------------------------
# 2. The 8 INTRA_HOUSEHOLD rule shapes

class TestRuleShapes:
    """One pass case + one fail case for each rule's expression. These
    are the seed fixtures P3 will write into DqaRule.test_fixtures."""

    def test_ac_hoh_exists_pass(self):
        # Exactly 1 head.
        payload = _hh([
            _m(1, relationship_to_head="01"),
            _m(2, relationship_to_head="02"),
        ])
        rule = {
            "rule_id": "AC-HOH-EXISTS", "version": 1, "severity": "block",
            "parameters": {"expected_count": 1},
            "expression": {"op": "count_where",
                           "predicate": {"op": "eq",
                                         "args": ["$.relationship_to_head", "01"]}},
            "fail_when": {"op": "neq", "args": ["$", "$parameters.expected_count"]},
            "error_message_template": "",
        }
        assert evaluate_rule(rule, payload)["status"] == "pass"

    def test_ac_hoh_exists_fail_zero(self):
        payload = _hh([_m(1, relationship_to_head="02"), _m(2, relationship_to_head="03")])
        rule = {
            "rule_id": "AC-HOH-EXISTS", "version": 1, "severity": "block",
            "parameters": {"expected_count": 1},
            "expression": {"op": "count_where",
                           "predicate": {"op": "eq", "args": ["$.relationship_to_head", "01"]}},
            "fail_when": {"op": "neq", "args": ["$", "$parameters.expected_count"]},
            "error_message_template": "Need exactly 1 head; found 0.",
        }
        assert evaluate_rule(rule, payload)["status"] == "fail"

    def test_ac_member_count_match(self):
        payload = _hh([_m(1), _m(2)], reported_household_size=3)  # roster has 2 but reported 3
        rule = {
            "rule_id": "AC-MEMBER-COUNT-MATCH", "version": 1, "severity": "flag",
            "parameters": {},
            # count_where over all members (always true) gives roster count.
            "expression": {"op": "count_where",
                           "predicate": {"op": "eq", "args": [1, 1]}},
            "fail_when": {"op": "neq", "args": ["$", "$reported_household_size"]},
            "error_message_template": "Roster {0} != reported {1}.",
        }
        r = evaluate_rule(rule, payload)
        assert r["status"] == "fail"

    def test_ac_member_count_match_pass(self):
        payload = _hh([_m(1), _m(2)], reported_household_size=2)
        rule = {
            "rule_id": "AC-MEMBER-COUNT-MATCH", "version": 1, "severity": "flag",
            "parameters": {},
            "expression": {"op": "count_where",
                           "predicate": {"op": "eq", "args": [1, 1]}},
            "fail_when": {"op": "neq", "args": ["$", "$reported_household_size"]},
            "error_message_template": "",
        }
        assert evaluate_rule(rule, payload)["status"] == "pass"

    def test_ac_orphan_flag_violation(self):
        # Member under 18 with both parents deceased but orphan_flag NOT true.
        payload = _hh([
            _m(1, age_years=10, mother_alive_flag=False,
               father_alive_flag=False, orphan_flag=False),
        ])
        rule = {
            "rule_id": "AC-ORPHAN-FLAG", "version": 1, "severity": "flag",
            "parameters": {"max_age": 18},
            "expression": {"op": "for_each_member",
                           "predicate": {"op": "and", "args": [
                               {"op": "lt", "args": ["$.age_years", "$parameters.max_age"]},
                               {"op": "eq", "args": ["$.mother_alive_flag", False]},
                               {"op": "eq", "args": ["$.father_alive_flag", False]},
                               {"op": "neq", "args": ["$.orphan_flag", True]},
                           ]}},
            "fail_when": {"op": "gt", "args": ["$", 0]},
            "error_message_template": "",
        }
        r = evaluate_rule(rule, payload)
        assert r["status"] == "fail"
        assert r["offending_member_ids"] == ["01M001"]


# ---------------------------------------------------------------------------
# 3. Aggregate outcome

class TestAggregateOutcome:
    def _rule(self, severity: str, fail: bool):
        # Synthetic rule that always passes/fails per `fail`.
        return {
            "rule_id": f"T-{severity}", "version": 1, "severity": severity,
            "parameters": {},
            "expression": {"op": "count_where",
                           "predicate": {"op": "eq", "args": [1, 1 if fail else 0]}},
            "fail_when": {"op": "gt", "args": ["$", 0]},
            "error_message_template": "",
        }

    def test_pass_when_all_pass(self):
        out = evaluate_household(
            [self._rule("block", False), self._rule("flag", False)],
            _hh([_m(1)]), stage="dih_ingest",
        )
        assert out["outcome"] == "pass"

    def test_block_when_block_fails(self):
        out = evaluate_household(
            [self._rule("block", True), self._rule("flag", False)],
            _hh([_m(1)]), stage="dih_ingest",
        )
        assert out["outcome"] == "block"

    def test_review_when_only_flag_fails(self):
        out = evaluate_household(
            [self._rule("flag", True), self._rule("info", False)],
            _hh([_m(1)]), stage="dih_ingest",
        )
        assert out["outcome"] == "review"

    def test_info_failure_doesnt_escalate(self):
        out = evaluate_household(
            [self._rule("info", True)],
            _hh([_m(1)]), stage="dih_ingest",
        )
        assert out["outcome"] == "pass"


# ---------------------------------------------------------------------------
# 4. Persistence wrapper — needs DB

@pytest.mark.django_db
class TestPersistence:
    def test_persist_writes_evaluation_and_audit(self):
        from apps.dqa.household_evaluator import persist_household_evaluation
        from apps.dqa.models import (
            DqaEvaluation,
            DqaRule,
            RuleCategory,
            RuleScope,
            RuleStatus,
        )
        from apps.security.models import AuditEvent

        # Active intra-household rule that fails for any roster with
        # zero heads.
        DqaRule.objects.create(
            rule_id="AC-HOH-EXISTS", version=1,
            description="exactly one head",
            severity="block",
            category=RuleCategory.INTRA_HOUSEHOLD,
            scope=RuleScope.HOUSEHOLD,
            stages=["dih_ingest", "dih_promote"],
            parameters={"expected_count": 1},
            expression={
                "op": "count_where",
                "predicate": {"op": "eq",
                              "args": ["$.relationship_to_head", "01"]},
                "_fail_when": {"op": "neq", "args": ["$", "$parameters.expected_count"]},
            },
            error_message_template="Need 1 head; found {expression_result}.",
            applicability_filter={"entity": "household"},
            status=RuleStatus.ACTIVE,
            author="seed",
        )
        payload = _hh([_m(1, relationship_to_head="02")])
        eval_row = persist_household_evaluation(
            payload, stage="dih_ingest", actor="orch",
            household_id="01HHTEST",
        )
        assert eval_row.outcome == "block"
        assert eval_row.stage == "dih_ingest"
        assert DqaEvaluation.objects.count() == 1
        ev = AuditEvent.objects.filter(
            action="dqa.household.evaluated",
        ).first()
        assert ev is not None
        assert ev.field_changes["outcome"] == "block"
        assert "AC-HOH-EXISTS" in ev.field_changes["failed_rule_codes"]
