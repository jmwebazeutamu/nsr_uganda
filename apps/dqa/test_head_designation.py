"""The head rules must agree with the payload the connectors build.

AC-HOH-EXISTS blocked every record in the DIH review queue with
"Exactly 1 member must be flagged as Head; found 0" while the roster
beside it showed a head. Both were telling the truth about different
things:

  * every connector normalises the head to `is_head: True` and blanks
    that member's own relationship code, because a head's relationship
    to themselves is not a question the form asks (kobo.py, nusaf.py,
    pdm.py all carry the same `"" if is_head else …` line);
  * the rule counted `relationship_to_head == "01"`.

On the dev registry that was 367 staged heads, none of them matching.
The rule's own fixtures used the coded shape, so it tested green against
a payload the system has never produced — which is the actual defect
here, and why these cases feed the *connector's* output to the *live*
rules rather than a dict written by hand in a test.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.dqa.household_evaluator import evaluate_household, load_active_household_rules
from apps.dqa.models import DqaRule, RuleStatus

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def head_rules(db):
    """Seed the intra-household rules and activate them.

    Activation is a direct status write, as in the existing integration
    test: the dual-approval path is exercised by apps/dqa/tests.py, and
    re-running it here would test the approval workflow rather than the
    rules.
    """
    seed_path = REPO / "scripts" / "seed_dqa_intra_household_rules.py"
    spec = importlib.util.spec_from_file_location("seed_intra", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()
    DqaRule.objects.filter(status=RuleStatus.DRAFT).update(
        status=RuleStatus.ACTIVE, approved_by="qa-lead", author="seed-bot",
    )
    return load_active_household_rules("dih_ingest")


def _failures(rules, household):
    result = evaluate_household(
        rules, household, stage="dih_ingest", now=datetime.now(UTC),
    )
    return {r["rule_code"]: r for r in result["results"] if r["status"] == "fail"}


# --- the shape the connectors actually emit --------------------------------

def _kobo_member(index: int, relationship: str, *, age: int = 40) -> dict:
    """One raw Kobo roster row. `c2_relationship` "01" is the head."""
    return {
        "member_index": index,
        "c1_full_name": f"Member {index} Test",
        "c2_relationship": relationship,
        "c4_sex": "2",
        "c6_age_years": str(age),
        "c8_nin_status": "0",
    }


def _kobo_submission(members: list[dict]) -> dict:
    return {
        "a0_region": "R-CENTRAL",
        "a1_subregion": "SR-BUGANDA-SOUTH",
        "a2_district_city": "D-WAKISO",
        "a3_county_municipality": "C-KYADONDO",
        "a4_subcounty_division_tc": "SC-NANSANA",
        "a5_parish_ward": "PAR-NABWERU",
        "a6_lc1_village_cell": "VIL-KAWANDA",
        "a7_rural_urban": "2",
        "household_members": members,
    }


def test_the_connector_blanks_the_head_relationship_code():
    """Pins the convention the rules have to match.

    If this ever fails, the connectors changed and the head rules should
    be revisited with them — that coupling is the whole finding.
    """
    from apps.ingestion_hub.connectors.kobo import kobo_to_canonical

    canonical = kobo_to_canonical(_kobo_submission([
        _kobo_member(1, "01"), _kobo_member(2, "02", age=38),
    ]))
    head = [m for m in canonical["members"] if m["is_head"]]
    assert len(head) == 1
    assert head[0]["relationship_to_head"] == "", (
        "the head's own relationship code is blank by convention"
    )


@pytest.mark.django_db
def test_a_kobo_household_with_a_head_passes(head_rules):
    """The regression. This payload came out of the connector; before
    the fix it produced "found 0" and blocked promotion."""
    from apps.ingestion_hub.connectors.kobo import kobo_to_canonical

    canonical = kobo_to_canonical(_kobo_submission([
        _kobo_member(1, "01"), _kobo_member(2, "02", age=38),
    ]))
    assert "AC-HOH-EXISTS" not in _failures(head_rules, canonical)


@pytest.mark.django_db
def test_a_kobo_household_with_no_head_still_blocks(head_rules):
    """The rule must still do its job: accepting `is_head` cannot mean
    accepting everything."""
    from apps.ingestion_hub.connectors.kobo import kobo_to_canonical

    canonical = kobo_to_canonical(_kobo_submission([
        _kobo_member(1, "02"), _kobo_member(2, "04", age=12),
    ]))
    failures = _failures(head_rules, canonical)
    assert "AC-HOH-EXISTS" in failures
    assert failures["AC-HOH-EXISTS"]["severity"] == "block"


@pytest.mark.django_db
def test_two_heads_block(head_rules):
    canonical = {"members": [
        {"id": "01M1", "line_number": 1, "is_head": True, "relationship_to_head": ""},
        {"id": "01M2", "line_number": 2, "is_head": True, "relationship_to_head": ""},
    ]}
    assert "AC-HOH-EXISTS" in _failures(head_rules, canonical)


@pytest.mark.django_db
def test_a_coded_head_without_the_flag_still_passes(head_rules):
    """A source that codes the head instead of flagging it — the shape
    the rule was written for — must keep working."""
    canonical = {"members": [
        {"id": "01M1", "line_number": 1, "relationship_to_head": "01"},
        {"id": "01M2", "line_number": 2, "relationship_to_head": "02"},
    ]}
    assert "AC-HOH-EXISTS" not in _failures(head_rules, canonical)


# --- the two age rules select the head the same way ------------------------

@pytest.mark.django_db
def test_head_age_rule_sees_a_flagged_head(head_rules):
    """AC-HOH-AGE selected the head by code too, so it was not merely
    wrong — it was silent. An 8-year-old head passed."""
    canonical = {"members": [
        {"id": "01M1", "line_number": 1, "is_head": True,
         "relationship_to_head": "", "age_years": 8},
    ]}
    assert "AC-HOH-AGE" in _failures(head_rules, canonical)


@pytest.mark.django_db
def test_child_headed_household_is_flagged_not_blocked(head_rules):
    canonical = {"members": [
        {"id": "01M1", "line_number": 1, "is_head": True,
         "relationship_to_head": "", "age_years": 15},
    ]}
    failures = _failures(head_rules, canonical)
    assert "AC-HOH-AGE-CHILD-LED" in failures
    assert failures["AC-HOH-AGE-CHILD-LED"]["severity"] == "flag"
    # 15 is above the minimum, so the blocking age rule must not fire.
    assert "AC-HOH-AGE" not in failures


@pytest.mark.django_db
def test_an_adult_head_trips_neither_age_rule(head_rules):
    canonical = {"members": [
        {"id": "01M1", "line_number": 1, "is_head": True,
         "relationship_to_head": "", "age_years": 58},
    ]}
    failures = _failures(head_rules, canonical)
    assert "AC-HOH-AGE" not in failures
    assert "AC-HOH-AGE-CHILD-LED" not in failures
    assert "AC-HOH-EXISTS" not in failures


# --- the fixtures the Rule Editor runs on save -----------------------------

@pytest.mark.django_db
def test_every_head_rule_fixture_passes_the_live_evaluator(head_rules):
    """The Rule Editor runs `test_fixtures` against the evaluator on
    every save. These fixtures were the reason the defect shipped: they
    all used the coded shape, so a rule that could never match real data
    looked correct. Each head rule now carries a connector-shaped
    fixture, and this asserts they are honest.
    """
    by_code = {r["rule_id"]: r for r in head_rules}
    for code in ("AC-HOH-EXISTS", "AC-HOH-AGE", "AC-HOH-AGE-CHILD-LED"):
        rule = DqaRule.objects.filter(rule_id=code).order_by("-version").first()
        fixtures = rule.test_fixtures or []
        assert fixtures, f"{code} has no test fixtures"
        canonical_shaped = [
            f for f in fixtures
            if any(m.get("is_head") for m in f["input"].get("members", []))
        ]
        assert canonical_shaped, (
            f"{code} has no fixture in the shape the connectors emit — "
            "which is exactly how it shipped matching nothing"
        )
        for fixture in fixtures:
            failures = _failures([by_code[code]], fixture["input"])
            fired = code in failures
            expected = fixture["expected_outcome"] == "fail"
            assert fired == expected, (
                f"{code} fixture {fixture['input']} expected "
                f"{fixture['expected_outcome']}, got "
                f"{'fail' if fired else 'pass'}"
            )


# --- publishing the correction to an environment that is already live ------

@pytest.mark.django_db
def test_revise_authors_a_new_version_and_never_approves_it():
    """An ACTIVE rule is an approved artefact.

    The correction must reach a live environment as a supersession the
    audit chain can show, not as an edit to the row an approver signed.
    `--revise` authors the next version, submits it, and stops there.
    """
    from apps.dqa.services import ApprovalError, approve

    seed_path = REPO / "scripts" / "seed_dqa_intra_household_rules.py"
    spec = importlib.util.spec_from_file_location("seed_intra_revise", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()

    # Pretend this environment approved v1 of the OLD definition.
    active = DqaRule.objects.get(rule_id="AC-HOH-EXISTS", version=1)
    active.expression = {
        "op": "count_where",
        "predicate": {"op": "eq", "args": [
            "$.relationship_to_head", "$parameters.head_code",
        ]},
        "_fail_when": {"op": "neq", "args": ["$", "$parameters.expected_count"]},
    }
    active.status = RuleStatus.ACTIVE
    active.approved_by = "qa-lead"
    active.save()

    assert mod.revise(actor="seed-bot") >= 1

    v1 = DqaRule.objects.get(rule_id="AC-HOH-EXISTS", version=1)
    v2 = DqaRule.objects.get(rule_id="AC-HOH-EXISTS", version=2)
    # v1 is untouched — still active, still what it was approved as.
    assert v1.status == RuleStatus.ACTIVE
    assert v1.expression["predicate"]["op"] == "eq"
    # v2 carries the correction and is waiting for a human.
    assert v2.status == RuleStatus.PENDING_APPROVAL
    assert v2.parent_rule_id == v1.id
    assert v2.expression["predicate"]["op"] == "or"
    assert v2.author == "seed-bot"
    assert v2.approved_by == ""

    # And the gate still holds: its author cannot be its approver.
    with pytest.raises(ApprovalError):
        approve(v2, approver="seed-bot", note="self-approval attempt")


@pytest.mark.django_db
def test_revise_is_idempotent_when_nothing_changed(head_rules):
    seed_path = REPO / "scripts" / "seed_dqa_intra_household_rules.py"
    spec = importlib.util.spec_from_file_location("seed_intra_noop", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    before = DqaRule.objects.count()
    assert mod.revise(actor="seed-bot") == 0
    assert DqaRule.objects.count() == before
