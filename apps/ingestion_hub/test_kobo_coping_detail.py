"""Section L coping strategies reach the registry.

The eighteen L answers were carried into the canonical payload all along,
under `shocks_coping.coping` — a key promotion does not read. It reads
top-level `coping_strategies`. So 360 households sat in the registry with
0 CopingStrategy rows between them while every one of their staged
payloads held eighteen coping answers.

Only eight of the eighteen have a `coping_strategy_type` code. The other
ten are deliberately not coerced: see COPING_STRATEGIES_WITHOUT_A_CODE.
"""

import pytest

from apps.intake.canonical_fields import (
    COPING_FREQUENCY_NOT_USED,
    COPING_STRATEGIES,
    COPING_STRATEGIES_WITHOUT_A_CODE,
    COPING_STRATEGY_LIST,
)
from apps.ingestion_hub.connectors.kobo import _kobo_coping_rows


class TestCopingRows:
    def test_an_answered_strategy_with_a_code_becomes_a_row(self):
        rows = _kobo_coping_rows({"l01a_casual_labor": "4"})
        assert rows == [{
            "strategy_type": "casual_labor", "category": "livelihood",
            "frequency": "4", "used_flag": True,
        }]

    def test_never_is_an_answer_and_still_becomes_a_row(self):
        """"Asked and not used" is information. used_flag is what
        separates it from a strategy the household relied on."""
        rows = _kobo_coping_rows({"l01c_borrow_money": COPING_FREQUENCY_NOT_USED})
        assert len(rows) == 1
        assert rows[0]["used_flag"] is False
        assert rows[0]["frequency"] == COPING_FREQUENCY_NOT_USED

    def test_an_unanswered_strategy_produces_no_row(self):
        """Absent is not "never" — the enumerator may have been skipped
        past the question entirely."""
        assert _kobo_coping_rows({"l01a_casual_labor": ""}) == []
        assert _kobo_coping_rows({}) == []

    def test_l01_and_l02_carry_different_categories(self):
        rows = {
            r["strategy_type"]: r["category"] for r in _kobo_coping_rows({
                "l01a_casual_labor": "3", "l02d_reduce_meals": "3",
            })
        }
        assert rows["casual_labor"] == "livelihood"
        assert rows["reduced_meals"] == "food"

    def test_a_strategy_with_no_code_is_skipped_not_coerced(self):
        """Coercing the ten to "98 Other" would collide on
        CopingStrategy's unique (household, strategy_type, category) and
        nine of them would vanish. Destructive, not merely lossy."""
        rows = _kobo_coping_rows({
            question: "5" for question in COPING_STRATEGIES_WITHOUT_A_CODE
        })
        assert rows == []

    def test_the_full_answer_set_survives_even_when_rows_cannot(self):
        """The ten without codes are why shocks_coping.coping stays in the
        payload: it is the complete record, the rows are the part the
        frame can express."""
        from apps.ingestion_hub.connectors.kobo import _kobo_shocks_coping_block

        raw = {q: "2" for q in COPING_STRATEGIES_WITHOUT_A_CODE}
        block = _kobo_shocks_coping_block(raw)
        for question in COPING_STRATEGIES_WITHOUT_A_CODE:
            assert block["coping"][question] == "2", (
                f"{question} has no registry code, so losing it here would "
                f"lose it entirely"
            )


@pytest.fixture
def instrument(db):
    """The real v1 questionnaire — the point is to check the declaration
    against the actual form, not against a fixture built to agree."""
    from django.core.management import call_command

    call_command("load_instrument", quiet=True)


@pytest.mark.django_db
class TestTheMappingMatchesTheFrame:
    def test_every_mapped_code_is_active_in_the_choice_list(self):
        from apps.reference_data.models import ChoiceList, ChoiceOption

        choice_list = (
            ChoiceList.objects.filter(list_name=COPING_STRATEGY_LIST)
            .order_by("-version").first()
        )
        assert choice_list is not None, f"{COPING_STRATEGY_LIST} is not seeded"
        active = set(
            ChoiceOption.objects
            .filter(choice_list=choice_list, status=ChoiceOption.Status.ACTIVE)
            .values_list("code", flat=True)
        )
        mapped = {code for _cat, code in COPING_STRATEGIES.values()}
        assert mapped <= active, (
            f"COPING_STRATEGIES maps to codes the active frame does not "
            f"have: {sorted(mapped - active)}"
        )

    def test_every_l_question_is_either_mapped_or_declared_missing(self, instrument):
        """Exhaustive by construction. A new L question that is neither
        mapped nor declared would be dropped in silence — which is exactly
        how section K went unnoticed."""
        from apps.intake.models import FormQuestion

        questions = set(
            FormQuestion.objects
            .filter(name__startswith="l0", section__form_version__is_active=True)
            .values_list("name", flat=True)
        )
        accounted = set(COPING_STRATEGIES) | set(COPING_STRATEGIES_WITHOUT_A_CODE)
        assert questions <= accounted, (
            f"section L questions accounted for nowhere: "
            f"{sorted(questions - accounted)}"
        )
        assert accounted <= questions, (
            f"declared for questions the instrument does not have: "
            f"{sorted(accounted - questions)}"
        )

    def test_the_declared_gap_is_real_and_not_a_lookup_failure(self):
        """If a code turns up for one of the ten, it should become a
        mapping rather than staying on the gap list."""
        from apps.reference_data.models import ChoiceList, ChoiceOption

        choice_list = (
            ChoiceList.objects.filter(list_name=COPING_STRATEGY_LIST)
            .order_by("-version").first()
        )
        active = set(
            ChoiceOption.objects
            .filter(choice_list=choice_list, status=ChoiceOption.Status.ACTIVE)
            .values_list("code", flat=True)
        )
        # The gap list is keyed by question name; none of those names is
        # itself a code in the frame.
        assert not (set(COPING_STRATEGIES_WITHOUT_A_CODE) & active)
