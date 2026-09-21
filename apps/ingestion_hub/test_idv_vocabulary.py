"""Every IDV outcome the backend can write must have a rendering.

The queue column compared against "Matched" / "Mismatch" — capitalised
display words the backend has never produced — so both branches were
unreachable and every outcome fell through to a default amber "Pending".
A NIRA MISMATCH, an operator's manual acceptance, and a household that
never offered a NIN all rendered identically, and all rendered as
something that had not happened yet.

The decision panel had the same fault from the other side: it tested for
"matched" where the backend writes "match", so a NIRA-confirmed record
fell past every branch to "No NIN was offered for any member".

Both are the same bug — a display vocabulary invented independently of
the one the server writes — and neither was caught by a test, because
every test that exercised IDV happened to use a value the branch chain
handled or did not assert on the rendering at all.

This is the test that catches it: enumerate what the SERVER can write,
and assert the console has a rendering for each. It reads the JSX
directly rather than mocking it, for the same reason the
PER_MEMBER_REQUIRED contract test does — two lists that drift apart are
the failure mode, so the test must read both originals.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VOCAB_JSX = ROOT / "design" / "v0.1" / "components" / "idv-outcomes.jsx"

#: Every value written to StageRecord.idv_outcome, with where from.
#:
#: Kept explicit rather than scraped: a literal list is reviewable, and
#: adding an outcome to the backend should be a deliberate edit here
#: that makes the author notice the console must learn it too.
BACKEND_OUTCOMES = {
    "": "no NIN offered — the field is never written",
    "match": "apps.identity_verification.mock.verify_nin",
    "mismatch": "apps.identity_verification.mock.verify_nin",
    "no_match": "apps.identity_verification.mock.verify_nin",
    "bad_format": "apps.identity_verification.mock.verify_nin",
    "service_unavailable": "services.process_stage_record, on NiraError",
    "unknown": "services.process_stage_record, idv.get('status', 'unknown')",
    "manual_accept": "services.resolve_idv_pending, decision='accept'",
    "nin_partial": "services.IDV_NIN_PARTIAL — card seen, last 4 only",
}


def _console_vocabulary() -> dict[str, dict]:
    """The IDV_OUTCOMES table as the console declares it."""
    source = VOCAB_JSX.read_text()
    block = re.search(r"const IDV_OUTCOMES = \{(.*?)\n\};", source, re.S)
    assert block, "IDV_OUTCOMES not found — was idv-outcomes.jsx renamed?"
    body = block.group(1)
    out: dict[str, dict] = {}
    # Keys are `""`, `match:`, `no_match:` — quoted or bare.
    for match in re.finditer(
        r'\n  (?:"([^"]*)"|(\w+)):\s*\{(.*?)\n  \},', body, re.S,
    ):
        code = match.group(1) if match.group(1) is not None else match.group(2)
        entry = match.group(3)
        label = re.search(r'label:\s*"([^"]*)"', entry)
        tone = re.search(r'tone:\s*"([^"]*)"', entry)
        out[code] = {
            "label": label.group(1) if label else "",
            "tone": tone.group(1) if tone else "",
            "detail": entry,
        }
    return out


@pytest.fixture(scope="module")
def vocabulary():
    return _console_vocabulary()


class TestEveryBackendOutcomeIsRenderable:
    def test_the_table_parses(self, vocabulary):
        assert vocabulary, "could not read IDV_OUTCOMES out of the JSX"

    @pytest.mark.parametrize("code", sorted(BACKEND_OUTCOMES))
    def test_the_console_can_render_it(self, vocabulary, code):
        assert code in vocabulary, (
            f"the backend writes idv_outcome={code!r} "
            f"({BACKEND_OUTCOMES[code]}) and the console has no rendering "
            "for it — it would fall through to the unrecognised branch"
        )

    def test_the_console_declares_nothing_the_backend_cannot_write(self, vocabulary):
        """A rendering for a value that cannot occur is dead code, and
        dead branches are how both of these bugs survived review."""
        extra = set(vocabulary) - set(BACKEND_OUTCOMES)
        assert not extra, f"renderings for outcomes nothing writes: {sorted(extra)}"

    def test_every_outcome_has_a_label_and_a_tone(self, vocabulary):
        for code, entry in vocabulary.items():
            assert entry["label"] or code == "", f"{code!r} has no label"
            assert entry["tone"], f"{code!r} has no tone"

    def test_no_two_outcomes_share_a_label(self, vocabulary):
        """The whole defect was three outcomes rendering identically."""
        labels = [e["label"] for e in vocabulary.values()]
        duplicated = sorted({x for x in labels if labels.count(x) > 1})
        assert not duplicated, f"outcomes that read the same: {duplicated}"


class TestTheOutcomesThatMustStandOut:
    """A reviewer promotes a household into the national registry off
    this panel. The outcomes that mean "a human must look" cannot be
    toned the same as the ones that mean "carry on"."""

    @pytest.mark.parametrize("code", ["mismatch", "no_match", "bad_format"])
    def test_a_failed_identity_check_is_toned_danger(self, vocabulary, code):
        assert vocabulary[code]["tone"] == "danger", (
            f"{code!r} is a failed identity check and must not be toned "
            "like routine waiting — that is exactly how a NIRA mismatch "
            "came to be displayed as amber 'Pending'"
        )

    def test_a_match_is_not_toned_danger(self, vocabulary):
        assert vocabulary["match"]["tone"] != "danger"

    def test_never_run_is_distinguishable_from_verified(self, vocabulary):
        assert vocabulary[""]["label"] != vocabulary["match"]["label"]
        assert vocabulary[""]["tone"] != vocabulary["match"]["tone"]

    def test_a_manual_acceptance_does_not_claim_a_nira_match(self, vocabulary):
        """An operator accepting paper evidence is a different fact from
        NIRA confirming the number, and the registry must not blur them."""
        assert vocabulary["manual_accept"]["label"] != vocabulary["match"]["label"]
        assert "operator" in vocabulary["manual_accept"]["label"].lower()


class TestTheStrings:
    """The two literals that were compared against and never produced."""

    def test_the_console_no_longer_tests_for_invented_spellings(self):
        screen = (ROOT / "design" / "v0.1" / "screens" / "screens-dih.jsx").read_text()
        rendered = re.sub(r"/\*.*?\*/", "", screen, flags=re.S)
        rendered = re.sub(r"^\s*//.*$", "", rendered, flags=re.M)
        for invented in ['=== "Matched"', '=== "Mismatch"', '=== "matched"']:
            assert invented not in rendered, (
                f"{invented} compares against a string the backend never "
                "writes, so the branch can never fire"
            )

    def test_the_filter_names_a_state_not_a_verdict(self):
        """'IDV pending' counted a QUEUE STATE while sitting beside a
        column of verdicts. One word, two concepts, and the obvious
        reading of 'IDV pending 0' beside a column of 'Pending' is that
        something is broken."""
        screen = (ROOT / "design" / "v0.1" / "screens" / "screens-dih.jsx").read_text()
        assert 'label: "Held for IDV"' in screen
        assert 'label: "IDV pending"' not in screen


def test_the_backend_constant_matches_this_list():
    """IDV_NIN_PARTIAL is the one outcome defined as a Python constant;
    the rest are string literals from NIRA. Pin it so a rename shows up
    here rather than as a blank column."""
    from apps.ingestion_hub.services import IDV_NIN_PARTIAL

    assert IDV_NIN_PARTIAL in BACKEND_OUTCOMES
    assert json.dumps(IDV_NIN_PARTIAL) == '"nin_partial"'
