"""The detailed household review's two server-side contracts.

1. The console mirrors EDITABLE_PATH_PATTERNS. If the two drift, an
   operator is offered an input whose save the server refuses — which is
   worse than a read-only field, because they believe the correction
   landed.

2. The widened allowlist still cannot reach the three categories the
   policy puts out of bounds: NIN (legal identity), geographic (chain
   integrity), consent / urban_rural (legal + PMT semantics).

The allowlist was widened for this feature. Before it, the only
correctable fields were GPS and seven member name/phone/DoB fields, so a
review that let an operator SEE a wrong answer gave them no way to fix
it. These cases are what keeps the widening from having quietly opened
something it should not have.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.ingestion_hub.services import EDITABLE_PATH_PATTERNS, _path_editable

ROOT = Path(__file__).resolve().parents[2]
REVIEW_JSX = ROOT / "design" / "v0.1" / "components" / "household-review.jsx"


def _console_patterns() -> list[str]:
    """EDITABLE_PATTERNS as the console declares them."""
    source = REVIEW_JSX.read_text()
    block = re.search(r"const EDITABLE_PATTERNS = \[(.*?)\n\];", source, re.S)
    assert block, "EDITABLE_PATTERNS not found in household-review.jsx"
    return re.findall(r"^\s*/(.+)/,\s*$", block.group(1), re.M)


class TestTheConsoleMirrorsTheServer:
    def test_the_console_declares_the_same_number_of_patterns(self):
        assert len(_console_patterns()) == len(EDITABLE_PATH_PATTERNS), (
            "the console's EDITABLE_PATTERNS and the server's "
            "EDITABLE_PATH_PATTERNS have diverged — an operator will be "
            "offered a field the server will refuse, or denied one it "
            "would have accepted"
        )

    def test_each_pattern_matches_its_server_counterpart(self):
        """Compared as source strings, in order. JS and Python regex
        syntax agrees across everything used here (character classes,
        non-capturing groups, negative lookahead)."""
        console = _console_patterns()
        server = [p.pattern for p in EDITABLE_PATH_PATTERNS]
        assert console == server, (
            "pattern mismatch:\n  console: "
            + "\n           ".join(console)
            + "\n  server:  " + "\n           ".join(server)
        )


class TestWhatTheOperatorMayCorrect:
    """Paths the review offers as editable. Each is a real answer on a
    real payload shape — Kobo puts per-member detail on the member, the
    parish wizard puts it in a top-level bag keyed by line number, and
    both have to work."""

    @pytest.mark.parametrize("path", [
        # identity + location that policy allows
        "gps_lat", "gps_lng", "gps_accuracy_m", "address_narrative",
        "reported_household_size",
        "members.0.surname", "members.0.first_name", "members.0.age_years",
        "members.0.date_of_birth", "members.0.telephone_1",
        # per-member detail, Kobo shape
        "members.0.health.chronic_illness_flag",
        "members.2.education.literacy_status",
        "members.1.employment.employment_status",
        "members.0.disability.seeing",
        # per-member detail, wizard shape
        "health.1.chronic_illness_flag",
        "education.3.highest_grade",
        "employment.2.work_frequency",
        # household detail, wizard (nested) and Kobo (flat)
        "housing.dwelling.roof_material", "housing.utilities.cooking_fuel",
        "housing.livelihood.main_livelihood",
        "housing.tenure", "housing.rooms_total", "housing.asset_counts.tv",
        "agriculture.land_ownership",
        "food_shocks.food_security.ate_less",
        "food_shocks.food_consumption.staples_days",
        "food_security.fies.i1_fies",
        "food_security.food_groups.staples",
        "shocks_coping.coping.l01i_begging",
        "interview.respondent_phone", "interview.interviewer",
    ])
    def test_is_correctable(self, path):
        assert _path_editable(path), f"{path} should be correctable"


class TestWhatStaysOutOfBounds:
    """The three categories the policy excludes, plus the repeat groups.

    These are the assertions that make widening the allowlist safe. A
    future pattern that accidentally reaches one of them fails here."""

    @pytest.mark.parametrize("path", [
        # Legal identity — re-capture only.
        "members.0.nin", "members.0.nin_last4", "members.0.nin_hash",
        "members.0.nin_status",
        # Chain integrity — re-capture only.
        "geographic.region", "geographic.sub_region", "geographic.parish",
        "geographic.district", "geographic._labels.region",
        # Legal + PMT semantics.
        "consent", "consent_block.REGISTRATION", "consent_block._method",
        "urban_rural", "interview.consent",
        # Repeat-group rows: adding and removing, not editing in place.
        "housing.assets.0.count", "housing.crops.0.crop_name",
        "housing.livestock.0.count",
        # Whole containers — a correction must name a leaf.
        "members", "housing", "geographic", "members.0",
        # Lineage is append-only (AC-DIH-LANDING-IMMUTABLE).
        "_source_keys.kobo_uuid", "members.0._source_keys.c8_nin_status",
    ])
    def test_is_refused(self, path):
        assert not _path_editable(path), (
            f"{path} must not be correctable — it is outside the "
            "documented policy"
        )

    @pytest.mark.parametrize("path", [
        "members.0.nin", "members.12.nin_hash", "members.3.nin_last4",
        "members.0.nin_status",
        # A NIN leaf anywhere at all, including places one has no
        # business being: the generic patterns use `\w+` for leaf
        # segments, so one of them WOULD swallow these without the
        # structural guard. Found by this test.
        "housing.nin", "interview.nin", "agriculture.nin",
        "members.0.health.nin", "housing.dwelling.nin_hash",
    ])
    def test_a_nin_leaf_is_refused_wherever_it_appears(self, path):
        """Legal identity is re-capture only, and a regex that reached
        it would be hard to spot by eye. The guarantee is stated once in
        _PROTECTED_LEAF_PREFIXES rather than relying on twelve patterns
        each remembering a lookahead."""
        assert not _path_editable(path)

    def test_the_protection_is_structural_not_incidental(self):
        """If the guard is removed, the generic patterns let a NIN leaf
        through — so the guard is load-bearing, not decoration."""
        from apps.ingestion_hub.services import _PROTECTED_LEAF_PREFIXES

        assert "nin" in _PROTECTED_LEAF_PREFIXES
        reached = [
            p.pattern for p in EDITABLE_PATH_PATTERNS if p.match("housing.nin")
        ]
        assert reached, (
            "no pattern matches housing.nin any more, so this test no "
            "longer proves the guard is doing anything — re-check why"
        )

    def test_geographic_is_unreachable_under_every_pattern(self):
        for pattern in EDITABLE_PATH_PATTERNS:
            for path in ("geographic.region", "geographic.parish",
                         "geographic.sub_region"):
                assert not pattern.match(path), (
                    f"pattern {pattern.pattern!r} reaches {path!r}"
                )


class TestEditingRemainsGated:
    def test_a_record_awaiting_promotion_is_not_editable(self):
        """A record that has cleared its gates must not be corrected
        without re-gating — the review panel says so rather than
        offering inputs the server would refuse."""
        from apps.ingestion_hub.models import StageRecordState
        from apps.ingestion_hub.services import _EDITABLE_STATES

        assert StageRecordState.PENDING_PROMOTION not in _EDITABLE_STATES
        assert StageRecordState.PROMOTED not in _EDITABLE_STATES
        assert StageRecordState.REJECTED not in _EDITABLE_STATES

    def test_the_console_uses_the_same_editable_states(self):
        from apps.ingestion_hub.services import _EDITABLE_STATES

        screen = (ROOT / "design" / "v0.1" / "screens" / "screens-dih.jsx").read_text()
        block = re.search(
            r"const REVIEW_EDITABLE_STATES = new Set\(\[(.*?)\]\)", screen, re.S,
        )
        assert block, "REVIEW_EDITABLE_STATES not found"
        console = set(re.findall(r'"(\w+)"', block.group(1)))
        assert console == {str(s) for s in _EDITABLE_STATES}
