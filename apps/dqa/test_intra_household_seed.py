"""US-S11-044 — Smoke test for the intra-household rule seed.

Runs each seeded rule against its own test_fixtures and asserts the
expected_outcome. Catches DSL typos in the seed before activation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from apps.dqa.household_evaluator import evaluate_rule

_SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts" / "seed_dqa_intra_household_rules.py"
)


def _load_seed_module():
    """Import the seed script as a module without invoking django.setup
    twice — pytest already configured Django, so we just need the
    ALL_RULES + per-rule specs."""
    spec = importlib.util.spec_from_file_location(
        "seed_dqa_intra_household_rules", _SEED_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.django_db
class TestSeededRulesAgainstOwnFixtures:
    """Each seed rule carries 1+ test_fixtures of the shape
    `{input, expected_outcome}`. The Rule Editor will run these on
    every save; we mirror that contract here so a seed regression
    fails CI before reaching the editor."""

    def _seed_module(self):
        return _load_seed_module()

    def _rule_to_eval_shape(self, spec):
        """Lift the seed spec into the dict shape evaluate_rule expects.
        Matches what load_active_household_rules pulls off the DB row."""
        expression = spec["expression"]
        fail_when = expression.get(
            "_fail_when", {"op": "gt", "args": ["$", 0]},
        )
        return {
            "rule_id": spec["rule_id"],
            "version": 1,
            "severity": spec["severity"],
            "parameters": spec["parameters"],
            "expression": expression,
            "fail_when": fail_when,
            "error_message_template": spec["error_message_template"],
        }

    def test_every_rule_fixture_matches_expected_outcome(self):
        mod = self._seed_module()
        failures = []
        for spec in mod.ALL_RULES:
            rule = self._rule_to_eval_shape(spec)
            for i, fixture in enumerate(spec.get("test_fixtures", [])):
                payload = fixture["input"]
                expected = fixture["expected_outcome"]
                result = evaluate_rule(rule, payload)
                actual = result["status"]
                if actual != expected:
                    failures.append(
                        f"{spec['rule_id']} fixture {i}: "
                        f"expected={expected}, got={actual}; "
                        f"message={result.get('message', '')!r}"
                    )
        assert not failures, "Seed rule(s) failed self-tests:\n" + "\n".join(failures)


@pytest.mark.django_db
class TestSeedRunUpsertsRows:
    """Running seed() once writes 9 rows; running it again is a no-op."""

    def test_first_run_creates_all_rules(self):
        from apps.dqa.models import DqaRule, RuleCategory, RuleStatus

        mod = _load_seed_module()
        n = mod.seed()
        assert n == len(mod.ALL_RULES)
        rows = DqaRule.objects.filter(
            category=RuleCategory.INTRA_HOUSEHOLD,
        )
        assert rows.count() == n
        # All seeded as DRAFT — activation goes through the Rule Editor.
        assert all(r.status == RuleStatus.DRAFT for r in rows)

    def test_second_run_is_idempotent(self):
        from apps.dqa.models import DqaRule, RuleCategory

        mod = _load_seed_module()
        mod.seed()
        before = DqaRule.objects.filter(
            category=RuleCategory.INTRA_HOUSEHOLD,
        ).count()
        mod.seed()
        after = DqaRule.objects.filter(
            category=RuleCategory.INTRA_HOUSEHOLD,
        ).count()
        assert before == after
