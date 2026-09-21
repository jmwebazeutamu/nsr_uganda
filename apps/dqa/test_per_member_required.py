"""P0 #3 — DQA must fail a record with unanswered required per-member
fields, and must be able to SEE them in the first place.

Reported: household 2 had 3 members. "Has chronic illness?" (marked
required) was answered for member #1 only; #2 and #3 were left blank.
The wizard let the operator walk on to section 7 and submit, and the
server-side DQA then reported "0 blocking, 0 warnings — Clean, all rules
passed".

Two separate failures, both covered here:

1. No rule could reach a per-member answer. The capture payload carries
   them in a top-level section keyed by line number, beside the roster
   rather than on it, and a rule evaluating inside `count_where` is
   scoped to one member dict.
   -> household_evaluator.attach_per_member_details

2. No rule asked for them.
   -> AC-MEMBER-DETAIL-REQUIRED (scripts/seed_dqa_intra_household_rules)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from apps.dqa.household_evaluator import (
    attach_per_member_details,
    evaluate_household,
)

ROOT = Path(__file__).resolve().parents[2]


def _seed_module():
    """Load the seed script as a module so the rule spec under test is
    the same object the seeder writes to the database — not a copy that
    can drift from it."""
    spec = importlib.util.spec_from_file_location(
        "_dqa_seed", ROOT / "scripts" / "seed_dqa_intra_household_rules.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rule():
    spec = _seed_module().AC_MEMBER_DETAIL_REQUIRED
    return {
        "rule_id": spec["rule_id"],
        "version": 1,
        "severity": spec["severity"],
        "parameters": spec["parameters"],
        "expression": spec["expression"],
        "fail_when": spec["expression"]["_fail_when"],
        "error_message_template": spec["error_message_template"],
    }


def _household(*, answered_lines, ages):
    """The capture wizard's payload shape: per-member detail in top-level
    sections keyed by line number, `health` wrapped in its own
    sub-section the way setHealthData writes it."""
    members = [
        {"id": f"01M{i}", "line_number": i, "is_head": i == 1, "age_years": age}
        for i, age in enumerate(ages, start=1)
    ]
    return {
        "members": members,
        "health": {
            str(line): {"health": {"chronic_illness_flag": "2"}, "disability": {}}
            for line in answered_lines
        },
        "education": {
            str(m["line_number"]): {"literacy_status": "1"} for m in members
        },
    }


# ---------------------------------------------------------------------------
# The join — without it, no per-member rule can see anything.


class TestPerMemberDetailIsReachable:
    def test_detail_sections_land_on_their_member(self):
        joined = attach_per_member_details(_household(
            answered_lines=[1, 2], ages=[47, 30],
        ))
        assert joined["members"][0]["health"]["chronic_illness_flag"] == "2"
        assert joined["members"][1]["health"]["chronic_illness_flag"] == "2"
        assert joined["members"][0]["education"]["literacy_status"] == "1"

    def test_wrapped_subsections_are_hoisted(self):
        """`health` arrives as {health: {...}, disability: {...}}, so a
        naive merge would put the answer two levels down."""
        joined = attach_per_member_details({
            "members": [{"line_number": 1}],
            "health": {"1": {
                "health": {"chronic_illness_flag": "1"},
                "disability": {"seeing": "03"},
            }},
        })
        member = joined["members"][0]
        assert member["health"]["chronic_illness_flag"] == "1"
        assert member["disability"]["seeing"] == "03"

    def test_int_and_str_line_numbers_both_match(self):
        """JSON object keys are always strings; line_number is an int."""
        for key in (1, "1"):
            joined = attach_per_member_details({
                "members": [{"line_number": 1}],
                "education": {key: {"literacy_status": "2"}},
            })
            assert joined["members"][0]["education"]["literacy_status"] == "2"

    def test_the_input_payload_is_not_mutated(self):
        payload = _household(answered_lines=[1], ages=[47])
        attach_per_member_details(payload)
        assert "health" not in payload["members"][0]

    @pytest.mark.parametrize("payload", [
        {}, {"members": []}, {"members": "not-a-list"},
        {"members": [{"line_number": 1}], "health": "not-a-dict"},
        {"members": [None]},
    ])
    def test_malformed_payloads_do_not_raise(self, payload):
        """This runs on the triage path; a crash costs more than a
        missed rule."""
        attach_per_member_details(payload)

    def test_a_connector_supplying_its_own_shape_keeps_it(self):
        joined = attach_per_member_details({
            "members": [{"line_number": 1, "health": {"chronic_illness_flag": "9"}}],
            "health": {"1": {"health": {"chronic_illness_flag": "1"}}},
        })
        assert joined["members"][0]["health"]["chronic_illness_flag"] == "9"


# ---------------------------------------------------------------------------
# The rule.


class TestMemberDetailRequired:
    def _run(self, rule, payload):
        return evaluate_household([rule], payload, stage="dih_ingest")["results"][0]

    def test_the_reported_case_fails_and_names_the_members(self, rule):
        """Three members, only #1 answered. Was 'Clean, all rules
        passed'."""
        result = self._run(rule, _household(answered_lines=[1], ages=[44, 38, 12]))
        assert result["status"] == "fail"
        assert result["severity"] == "block"
        assert result["offending_member_ids"] == ["01M2", "01M3"], (
            "an operator cannot act on 'some member is incomplete' — the "
            "finding has to say which"
        )

    def test_every_member_answered_passes(self, rule):
        result = self._run(rule, _household(answered_lines=[1, 2, 3], ages=[44, 38, 12]))
        assert result["status"] == "pass"

    def test_a_member_below_the_age_threshold_is_not_required_to_answer(self, rule):
        """Section D is asked of age 2+. A 1-year-old is never asked, so
        a blank is correct and must not fail."""
        result = self._run(rule, _household(answered_lines=[1], ages=[30, 1]))
        assert result["status"] == "pass"

    def test_a_member_with_no_age_is_not_excused(self, rule):
        """An absent age is caught by the roster rules; excusing a member
        here would reopen the same hole from the other end."""
        payload = _household(answered_lines=[1], ages=[30, 30])
        payload["members"][1]["age_years"] = None
        result = self._run(rule, payload)
        assert result["status"] == "fail"
        assert result["offending_member_ids"] == ["01M2"]

    def test_a_missing_literacy_status_fails_on_its_own(self, rule):
        payload = _household(answered_lines=[1, 2], ages=[40, 35])
        del payload["education"]["2"]
        result = self._run(rule, payload)
        assert result["status"] == "fail"
        assert result["offending_member_ids"] == ["01M2"]

    def test_an_empty_string_counts_as_unanswered(self, rule):
        payload = _household(answered_lines=[1, 2], ages=[40, 35])
        payload["health"]["2"]["health"]["chronic_illness_flag"] = ""
        assert self._run(rule, payload)["status"] == "fail"

    def test_it_blocks_rather_than_warns(self, rule):
        """CLAUDE.md: approval gates are not softened. A required field
        left blank is an incomplete interview, not a caveat."""
        assert rule["severity"] == "block"

    def test_every_shipped_fixture_still_holds(self, rule):
        """The rule's own test_fixtures are what the Rule Editor shows an
        approver. They have to be true."""
        for fixture in _seed_module().AC_MEMBER_DETAIL_REQUIRED["test_fixtures"]:
            got = self._run(rule, fixture["input"])["status"]
            assert got == fixture["expected_outcome"], fixture


# ---------------------------------------------------------------------------
# The wizard and the server must require the same fields.


def test_wizard_and_rule_require_the_same_fields():
    """The wizard blocks Next on PER_MEMBER_REQUIRED
    (design/v0.1/screens/screens-capture-sections.jsx); the server
    blocks promotion on AC-MEMBER-DETAIL-REQUIRED. Two lists that drift
    apart give an operator a form that passes and a record that fails.
    """
    import re

    source = (
        ROOT / "design" / "v0.1" / "screens" / "screens-capture-sections.jsx"
    ).read_text()
    block = re.search(
        r"const PER_MEMBER_REQUIRED = \{(.*?)\n\};", source, re.S,
    )
    assert block, "PER_MEMBER_REQUIRED not found — did the wizard rename it?"
    declared = set(re.findall(r'\[\"(\w+)\",', block.group(1)))
    min_ages = {int(n) for n in re.findall(r"minAge: (\d+)", block.group(1))}

    spec = _seed_module().AC_MEMBER_DETAIL_REQUIRED
    rule_fields = {
        path.rsplit(".", 1)[-1]
        for path in spec["applies_to"]["fields"]
        if path != "members.*.age_years"
    }
    assert declared == rule_fields, (
        f"wizard requires {sorted(declared)}, rule requires "
        f"{sorted(rule_fields)}"
    )
    assert min_ages == set(spec["parameters"].values()), (
        "the wizard's section age thresholds and the rule's min_age_* "
        "parameters disagree"
    )
