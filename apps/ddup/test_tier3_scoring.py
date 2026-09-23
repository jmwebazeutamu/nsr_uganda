"""What the first production discovery run taught the model.

Run one produced two pairs above 0.95. One was a genuine duplicate. The
other — Rebecca Akello and Rebecca Okello, two people in one household
with different NINs, different phones and birth dates three months apart
— scored 0.967, because `date_of_birth` compared only the year and
`village` is 1.0 for every pair a village-blocked model ever compares.

Had auto-merge been enabled, the registry would have collapsed two real
people into one identity overnight, inside a reversal window nobody
would have known to use.
"""

from datetime import date

import pytest

from apps.ddup.similarity import birth_date_proximity, composite_score, exact, jaro_winkler

CURRENT_WEIGHTS = {
    "surname": 0.30, "first_name": 0.30,
    "date_of_birth": 0.15, "sex": 0.10, "village": 0.15,
}
PROPOSED_WEIGHTS = {
    "surname": 0.35, "first_name": 0.35, "date_of_birth": 0.20, "sex": 0.10,
}

AUTO_MERGE_THRESHOLD = 0.95


def _score(a, b, weights):
    """Score a pair the way discover_incremental_tier3 does."""
    feats = {
        "surname": jaro_winkler(a["surname"], b["surname"]),
        "first_name": jaro_winkler(a["first_name"], b["first_name"]),
        "date_of_birth": birth_date_proximity(a["dob"], b["dob"]),
        "sex": exact(a["sex"], b["sex"]),
        # Blocking is by village, so every compared pair matches here.
        "village": 1.0,
    }
    return composite_score([(weights.get(k, 0.0), s) for k, s in feats.items()])


# The two people the first run nearly merged.
REBECCA_A = {"surname": "Akello", "first_name": "Rebecca",
             "dob": date(1993, 6, 5), "sex": "2"}
REBECCA_B = {"surname": "Okello", "first_name": "Rebecca",
             "dob": date(1993, 9, 28), "sex": "2"}

# The pair that really is one person, captured twice four months apart.
LILIAN_A = {"surname": "Kato", "first_name": "Lilian",
            "dob": date(1994, 12, 27), "sex": "2"}
LILIAN_B = dict(LILIAN_A)


class TestTheFalseMatch:
    def test_it_no_longer_reaches_the_auto_merge_threshold(self):
        score = _score(REBECCA_A, REBECCA_B, CURRENT_WEIGHTS)
        assert score < AUTO_MERGE_THRESHOLD, (
            f"two different people still score {score:.3f}, at or above the "
            f"threshold that would merge them unattended"
        )

    def test_the_proposed_weights_separate_it_further(self):
        assert (_score(REBECCA_A, REBECCA_B, PROPOSED_WEIGHTS)
                < _score(REBECCA_A, REBECCA_B, CURRENT_WEIGHTS))

    def test_it_still_surfaces_for_review(self):
        """Not a merge, but not silence either — a human should still see
        two people with the same first name and birth year in one
        household."""
        assert _score(REBECCA_A, REBECCA_B, CURRENT_WEIGHTS) > 0.5


class TestTheRealMatch:
    def test_it_is_untouched_by_the_fix(self):
        """The change must not cost the duplicate it did find."""
        for weights in (CURRENT_WEIGHTS, PROPOSED_WEIGHTS):
            assert _score(LILIAN_A, LILIAN_B, weights) == 1.0

    def test_a_transcription_slip_still_scores_above_the_review_threshold(self):
        slip = dict(LILIAN_B, dob=date(1994, 12, 27).replace(month=11, day=27))
        assert _score(LILIAN_A, slip, PROPOSED_WEIGHTS) >= 0.85


class TestVillageCarriesNoInformation:
    def test_it_is_the_same_for_every_pair_the_model_compares(self):
        """Tier 3 blocks by village, so the feature is 1.0 on every
        comparison. Weighting it adds a constant to all candidates and
        moves them together toward the threshold."""
        a_only = {k: v for k, v in CURRENT_WEIGHTS.items() if k != "village"}
        with_village = _score(REBECCA_A, REBECCA_B, CURRENT_WEIGHTS)
        without = composite_score([
            (a_only["surname"], jaro_winkler("Akello", "Okello")),
            (a_only["first_name"], 1.0),
            (a_only["date_of_birth"], birth_date_proximity(date(1993, 6, 5), date(1993, 9, 28))),
            (a_only["sex"], 1.0),
        ])
        assert with_village > without, (
            "village is meant to be inflating the score; if it is not, this "
            "test no longer describes the model"
        )

    def test_the_proposal_drops_it(self):
        assert "village" not in PROPOSED_WEIGHTS
        assert sum(PROPOSED_WEIGHTS.values()) == pytest.approx(1.0)
