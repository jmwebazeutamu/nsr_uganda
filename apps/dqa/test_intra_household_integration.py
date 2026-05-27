"""US-S11-044 — End-to-end smoke test: household with planted violations
exercises the full intra-household DQA pipeline (seed → activate →
DIH ingest evaluate → DIH promote gate → post-promote replay) and
asserts the right codes fire at the right stages with the right
audit trail.

This test is the integration mirror of the unit-level pipeline tests
in apps/dqa/test_pipeline.py: it activates the actual P3 seed rules
and walks them through a real household payload.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.utils import timezone

from apps.dqa.household_evaluator import (
    evaluate_household,
    load_active_household_rules,
)
from apps.dqa.models import DqaEvaluation, DqaRule, RuleStatus
from apps.dqa.pipeline import (
    DqaBlockError,
    DqaRejectWithOverrideError,
    run_household_gate,
)
from apps.security.models import AuditEvent


@pytest.fixture
def seeded_intra_household_rules(db):
    """Run the P3 seed bootstrap, then promote each rule from DRAFT
    to ACTIVE so the pipeline picks them up. The dual-approval
    constraint (author ≠ approver) is honoured by setting
    `approved_by` to a different actor than the seed `author`."""
    import importlib.util
    from pathlib import Path

    seed_path = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts" / "seed_dqa_intra_household_rules.py"
    )
    spec = importlib.util.spec_from_file_location(
        "seed_dqa_intra_household_rules", seed_path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()
    # Activate via direct DB update (the seed lands them as DRAFT;
    # the production flow would route through services.approve, but
    # for the smoke test we bypass with a separate approver to keep
    # the audit-bearing dual-actor contract intact).
    DqaRule.objects.filter(
        rule_id__startswith="AC-",
        status=RuleStatus.DRAFT,
    ).update(
        status=RuleStatus.ACTIVE,
        approved_by="smoke-test-approver",
        approved_at=timezone.now(),
    )
    return mod


@pytest.mark.django_db
class TestPlantedViolationsSmoke:
    """Walks a household carrying three planted violations through
    the three pipeline stages and asserts that the right rule codes
    surface with the right severity routing."""

    def _planted(self):
        """Three violations:
          1. AC-HOH-EXISTS — zero heads (BLOCK).
          2. AC-MEMBER-COUNT-MATCH — reported size 5, roster 2 (FLAG).
          3. AC-DUPLICATE-MEMBER — two members share nin_hash (BLOCK).
        All other rules pass.
        """
        return {
            "reported_household_size": 5,
            "members": [
                {
                    "id": "01M1", "line_number": 1,
                    "relationship_to_head": "spouse",  # not "head"
                    "age": 30, "sex": "F", "nin_hash": "h_dup",
                    "mother_line_number": None,
                    "father_line_number": None,
                    "orphan_flag": False, "alive": True,
                    "disability_flag": False,
                },
                {
                    "id": "01M2", "line_number": 2,
                    "relationship_to_head": "child",
                    "age": 8, "sex": "M", "nin_hash": "h_dup",  # duplicate
                    "mother_line_number": 1, "father_line_number": None,
                    "orphan_flag": False, "alive": True,
                    "disability_flag": False,
                },
            ],
        }

    def test_seed_loads_and_activates(self, seeded_intra_household_rules):
        rules = load_active_household_rules("dih_ingest")
        codes = {r["rule_id"] for r in rules}
        # Spot-check the codes we plan to trip.
        assert "AC-HOH-EXISTS" in codes
        assert "AC-MEMBER-COUNT-MATCH" in codes
        assert "AC-DUPLICATE-MEMBER" in codes

    def test_three_violations_fire_at_dih_ingest(
        self, settings, seeded_intra_household_rules,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        rules = load_active_household_rules("dih_ingest")
        result = evaluate_household(
            rules, self._planted(),
            stage="dih_ingest", now=datetime.now(UTC),
        )
        fails = {r["rule_code"]: r for r in result["results"] if r["status"] == "fail"}
        assert "AC-HOH-EXISTS" in fails, f"missing AC-HOH-EXISTS in {list(fails)}"
        assert "AC-MEMBER-COUNT-MATCH" in fails
        assert "AC-DUPLICATE-MEMBER" in fails
        assert fails["AC-HOH-EXISTS"]["severity"] == "block"
        assert fails["AC-MEMBER-COUNT-MATCH"]["severity"] == "flag"
        assert fails["AC-DUPLICATE-MEMBER"]["severity"] == "block"
        # AC-DUPLICATE-MEMBER must surface the offending member ids
        # (the duplicates_by op captures them) so the household
        # detail can hand them off to the Dedup Dashboard.
        assert set(fails["AC-DUPLICATE-MEMBER"]["offending_member_ids"]) == {"01M1", "01M2"}

    def test_block_at_dih_promote_aborts(
        self, settings, seeded_intra_household_rules,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        with pytest.raises(DqaBlockError) as excinfo:
            run_household_gate(
                self._planted(),
                stage="dih_promote",
                household_id="01HHSMOKE-PROMOTE",
                actor="smoke-operator",
            )
        # Both BLOCK rules in the codes payload.
        assert "AC-HOH-EXISTS" in excinfo.value.codes
        assert "AC-DUPLICATE-MEMBER" in excinfo.value.codes
        assert excinfo.value.evaluation_id

    def test_flag_emits_review_audit_at_dih_ingest(
        self, settings, seeded_intra_household_rules,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        before_flag = AuditEvent.objects.filter(
            action="dqa.household.flag",
        ).count()
        # Ingest never aborts → returns the persisted row.
        eval_row = run_household_gate(
            self._planted(),
            stage="dih_ingest",
            household_id="01HHSMOKE-INGEST",
            actor="smoke-operator",
        )
        assert eval_row is not None
        # AC-MEMBER-COUNT-MATCH is FLAG → audit emitted.
        after_flag = AuditEvent.objects.filter(
            action="dqa.household.flag",
        ).count()
        assert after_flag == before_flag + 1, (
            "AC-MEMBER-COUNT-MATCH should have emitted a dqa.household.flag"
        )

    def test_post_promote_records_but_does_not_abort(
        self, settings, seeded_intra_household_rules,
    ):
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        eval_row = run_household_gate(
            self._planted(),
            stage="registry_post_promote",
            household_id="01HHSMOKE-POSTPRO",
            actor="smoke-operator",
        )
        # Persists, never raises — promotion already happened.
        assert eval_row is not None
        assert eval_row.outcome == "block"
        assert DqaEvaluation.objects.filter(
            household_id="01HHSMOKE-POSTPRO",
            stage="registry_post_promote",
        ).count() == 1

    def test_override_clears_promote_block_with_audit(
        self, settings, seeded_intra_household_rules,
    ):
        """Demonstrates the operator path for clearing a
        REJECT_WITH_OVERRIDE rule. We re-author AC-HOH-EXISTS as
        REJECT_WITH_OVERRIDE for this scenario (the seed ships it
        as BLOCK by default — BLOCK is non-overridable by design)."""
        settings.DQA_INTRA_HOUSEHOLD_ENABLED = True
        # Reshape AC-HOH-EXISTS to REJECT_WITH_OVERRIDE + retire the
        # AC-DUPLICATE-MEMBER block so we have a clean overridable
        # state.
        DqaRule.objects.filter(rule_id="AC-HOH-EXISTS").update(
            severity="reject_with_override",
        )
        DqaRule.objects.filter(rule_id="AC-DUPLICATE-MEMBER").update(
            status=RuleStatus.RETIRED,
        )
        before = AuditEvent.objects.filter(
            action="dqa.household.override",
        ).count()
        # Without override_reason → still raises.
        with pytest.raises(DqaRejectWithOverrideError):
            run_household_gate(
                self._planted(),
                stage="dih_promote",
                household_id="01HHSMOKE-OVRA",
                actor="smoke-operator",
            )
        # With override_reason → proceeds + override audited.
        run_household_gate(
            self._planted(),
            stage="dih_promote",
            household_id="01HHSMOKE-OVRB",
            actor="smoke-operator",
            override_reason="Field officer verified head in person.",
        )
        after = AuditEvent.objects.filter(
            action="dqa.household.override",
        ).count()
        assert after == before + 1
