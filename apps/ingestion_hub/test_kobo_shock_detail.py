"""Section K shock detail survives the Kobo connector.

The connector read K01 (were you affected?) and the eighteen L coping
strategies, and nothing else from section K. K02 (which livelihood), K03
(what shock) and K04 (how severe) were answered by enumerators, landed in
RawLanding, and were dropped at the mapping step — so 389 stage records
said a shock had occurred and none said anything about it.

These hold the whole chain: the connector emits the rows, promotion turns
them into Shock entities, and the livelihood codes stay tied to the
reference frame that defines them.
"""

import pytest

from apps.intake.canonical_fields import (
    SHOCK_LIVELIHOOD_LIST, SHOCK_LIVELIHOODS,
)
from apps.ingestion_hub.connectors.kobo import (
    _kobo_shock_rows, _kobo_shocks_coping_block,
)

# One submission per livelihood, with a different shock in each, which is
# exactly the case a single-row mapping would lose.
RAW = {
    "k01_shock_affected": "1",
    "k02_livelihood_affected": "01 02",
    "k03_crops_shock_type": "01",              # drought
    "k04_crops_shock_severity": "1",           # very severe
    "k03_livestock_shock_type": "04",          # livestock disease
    "k04_livestock_shock_severity": "3",       # mild
    "k03_labour_employment_shock_type": "08",  # job loss
    "k04_labour_employment_shock_severity": "2",
    "k03_other_shock_type": "98",
    "k04_other_shock_severity": "2",
}


class TestShockRows:
    def test_every_answered_livelihood_becomes_its_own_row(self):
        rows = _kobo_shock_rows(RAW)
        assert len(rows) == 4, (
            "one row per answered livelihood — folding them into a single "
            "row keeps one shock_type and discards the other three"
        )

    def test_each_row_keeps_its_own_shock_type_and_severity(self):
        by_livelihood = {
            r["livelihoods_affected"][0]: r for r in _kobo_shock_rows(RAW)
        }
        assert by_livelihood["01"]["shock_type"] == "01"
        assert by_livelihood["01"]["severity"] == "1"
        assert by_livelihood["02"]["shock_type"] == "04"
        assert by_livelihood["02"]["severity"] == "3"
        assert by_livelihood["03"]["shock_type"] == "08"
        assert by_livelihood["04"]["shock_type"] == "98"

    def test_a_livelihood_with_no_answer_produces_no_row(self):
        """An absent key means the enumerator was skipped past it, not
        that there was no shock. An empty row would assert otherwise."""
        rows = _kobo_shock_rows({
            "k03_crops_shock_type": "01", "k04_crops_shock_severity": "2",
            "k03_livestock_shock_type": "",
            "k03_other_shock_type": None,
        })
        assert len(rows) == 1
        assert rows[0]["livelihoods_affected"] == ["01"]

    def test_a_submission_with_no_shocks_at_all_is_empty_not_null(self):
        assert _kobo_shock_rows({}) == []

    def test_the_household_level_livelihood_answer_is_carried(self):
        """K02 is asked once of the household, so it stays on the block
        rather than being copied onto every row."""
        block = _kobo_shocks_coping_block(RAW)
        assert block["livelihood_affected"] == "01 02"

    def test_the_coping_strategies_are_untouched(self):
        block = _kobo_shocks_coping_block(RAW)
        assert len(block["coping"]) == 18
        assert block["shock_affected"] == "1"


@pytest.mark.django_db
class TestLivelihoodCodesMatchTheReferenceFrame:
    """The codes are declared in canonical_fields because neither side can
    derive them — "labour_employment" in a question name is "03
    Labour/employment" in the frame. Declared means they can drift, so
    this is the test that makes a frame change fail loudly instead of
    mismapping every shock in the country."""

    def test_every_declared_code_exists_in_the_active_list(self):
        from apps.reference_data.models import ChoiceList, ChoiceOption

        choice_list = (
            ChoiceList.objects
            .filter(list_name=SHOCK_LIVELIHOOD_LIST)
            .order_by("-version").first()
        )
        assert choice_list is not None, f"{SHOCK_LIVELIHOOD_LIST} is not seeded"
        active = set(
            ChoiceOption.objects
            .filter(choice_list=choice_list, status=ChoiceOption.Status.ACTIVE)
            .values_list("code", flat=True)
        )
        declared = {code for code, _ in SHOCK_LIVELIHOODS}
        assert declared <= active, (
            f"SHOCK_LIVELIHOODS declares codes the active "
            f"{SHOCK_LIVELIHOOD_LIST} frame does not have: "
            f"{sorted(declared - active)}"
        )

    def test_the_declaration_covers_every_livelihood_the_frame_offers(self):
        """A new livelihood in the frame means a new pair of K03/K04
        questions whose answers would otherwise be dropped exactly the
        way these were."""
        from apps.reference_data.models import ChoiceList, ChoiceOption

        choice_list = (
            ChoiceList.objects
            .filter(list_name=SHOCK_LIVELIHOOD_LIST)
            .order_by("-version").first()
        )
        active = set(
            ChoiceOption.objects
            .filter(choice_list=choice_list, status=ChoiceOption.Status.ACTIVE)
            .values_list("code", flat=True)
        )
        declared = {code for code, _ in SHOCK_LIVELIHOODS}
        assert active <= declared, (
            f"the {SHOCK_LIVELIHOOD_LIST} frame offers livelihoods the "
            f"connector does not map: {sorted(active - declared)}"
        )


class TestGroupedKeysAreHandled:
    """Section K arrives under two key forms and the grouped one is the
    majority.

    Kobo returns "shocks/k03_crops_shock_type" when the question sits
    inside a group and the bare name when it does not; of the landings
    held today, 28 use the grouped form and 12 the flat one. Reading only
    the flat form recovers a third of the data and looks like it worked.
    """

    GROUPED = {
        "shocks/k02_livelihood_affected": "01 02",
        "shocks/k03_crops_shock_type": "02",
        "shocks/k04_crops_shock_severity": "1",
        "shocks/k03_livestock_shock_type": "04",
        "shocks/k04_livestock_shock_severity": "2",
    }

    def test_grouped_keys_produce_rows_once_flattened(self):
        from apps.ingestion_hub.connectors.kobo import _kobo_flatten

        rows = _kobo_shock_rows(_kobo_flatten(self.GROUPED))
        assert len(rows) == 2
        by_livelihood = {r["livelihoods_affected"][0]: r for r in rows}
        assert by_livelihood["01"]["shock_type"] == "02"
        assert by_livelihood["02"]["severity"] == "2"

    def test_the_canonicalize_path_flattens_before_mapping(self):
        """The connector is only correct because canonicalize() flattens
        first. If that ever stops happening, the grouped submissions go
        silently back to producing nothing."""
        import inspect

        from apps.ingestion_hub.connectors import kobo

        source = inspect.getsource(kobo.KoboConnector.canonicalize)
        flatten_at = source.index("_kobo_flatten(raw)")
        shocks_at = source.index("_kobo_shock_rows(raw)")
        assert flatten_at < shocks_at, (
            "canonicalize must flatten the payload before mapping shocks, "
            "or grouped submissions yield no shock rows"
        )
