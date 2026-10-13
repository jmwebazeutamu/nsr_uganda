"""Regression tests for PMT-ready Kobo seed payloads."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).with_name("seed_households.py")
_SPEC = importlib.util.spec_from_file_location("kobo_seed_households", _SCRIPT)
seed = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(seed)


_LISTS = (
    "tenure", "dwelling_type", "roof_material", "wall_material",
    "floor_material", "cooking_fuel", "lighting_source", "water_source",
    "toilet_type", "waste_disposal", "asset_type", "livelihood_source",
    "ag_activity", "land_ownership", "literacy", "education_level",
)


def _choices():
    rows = []
    for name in _LISTS:
        rows.extend([
            {"list_name": name, "name": f"{name}_a"},
            {"list_name": name, "name": f"{name}_b"},
        ])
    return rows


def test_pmt_seed_has_every_questionnaire_backed_input(monkeypatch):
    monkeypatch.setattr(seed, "select_location", lambda *_: {
        "a0_region": "region", "a1_subregion": "subregion",
        "a2_district_city": "district", "a3_county_municipality": "county",
        "a4_subcounty_division_tc": "subcounty", "a5_parish_ward": "parish",
        "_labels": {"region": "Western", "district": "District", "parish": "Parish"},
    })

    record, _ = seed.household(_choices(), "Western", 1, random.Random(7))
    head = record["household_members"][0]

    assert head["e4_highest_grade"] in {"education_level_a", "education_level_b"}
    assert record["g5_roof_material"] in {"roof_material_a", "roof_material_b"}
    assert record["g6_wall_material"] in {"wall_material_a", "wall_material_b"}
    assert record["g7_floor_material"] in {"floor_material_a", "floor_material_b"}
    assert record["g9_lighting_source"] in {"lighting_source_a", "lighting_source_b"}
    assert record["g10_water_source"] in {"water_source_a", "water_source_b"}
    assert record["g11_toilet_type"] in {"toilet_type_a", "toilet_type_b"}
    assert set(record["g15_assets_owned"].split()) == {
        "asset_type_a", "asset_type_b",
    }
    assert "g15_count_motorcycle" in record
    assert "g15_count_car" in record


def test_choice_helpers_fail_when_the_form_lacks_a_required_list():
    with pytest.raises(ValueError, match="approved Questionnaire"):
        seed.choice_code([], "missing_list", random.Random(1))
    with pytest.raises(ValueError, match="approved Questionnaire"):
        seed.all_choice_codes([], "missing_list")


def test_no_facility_toilet_does_not_create_or_read_the_skipped_follow_up(
    monkeypatch,
):
    rows = _choices()
    rows = [
        ({"list_name": "toilet_type", "name": "17"}
         if row["list_name"] == "toilet_type" else row)
        for row in rows
    ]
    monkeypatch.setattr(seed, "select_location", lambda *_: {
        "a0_region": "region", "a1_subregion": "subregion",
        "a2_district_city": "district", "a3_county_municipality": "county",
        "a4_subcounty_division_tc": "subcounty", "a5_parish_ward": "parish",
        "_labels": {"region": "Western", "district": "District", "parish": "Parish"},
    })

    record, _ = seed.household(rows, "Western", 1, random.Random(7))

    assert record["g11_toilet_type"] == "17"
    assert "g12_share_toilet" not in record
    assert "g13_share_toilet_households" not in record


# --- Codes must come from the form that will receive them -------------------


_DEPLOYED_ASSET = {
    "uid": "aDEPLOYED",
    "name": "Deployed form",
    "content": {
        "survey": [
            {"type": "select_one floor_material", "name": "g7_floor_material",
             "label": ["G7. Main floor material", None], "$kuid": "abc"},
        ],
        "choices": [
            # Kobo's own shape: label is a per-language list, plus $-prefixed
            # bookkeeping the xlsx reader never sees.
            {"list_name": "floor_material", "name": "11",
             "label": ["Concrete", None], "$kuid": "k1", "$autovalue": "11"},
            {"list_name": "floor_material", "name": "19",
             "label": ["Tiles", None], "$kuid": "k2", "$autovalue": "19"},
            {"list_name": "sub_region", "name": "SR-ACHOLI-NORTHERN",
             "label": ["Acholi", None], "region": "R-NORTHERN", "$kuid": "k3"},
        ],
    },
}


class TestChoicesComeFromTheDeployedForm:
    """The defect this closes.

    Records were generated from a local XLSForm passed with --form and
    only then offered a destination, so nothing checked that a generated
    code was a code the destination offers. The local copy carried the
    retired housing frame (floor_material 1-8) while the deployed form
    has carried 11-19 since it was last published — and because these
    submissions are POSTed to /submission as OpenRosa XML, which does
    not validate against the form, 49 synthetic households entered the
    registry carrying codes no active ChoiceList contains.
    """

    def test_kobo_content_normalises_to_the_xlsx_shape(self):
        """`options`, `choice_code` and `select_location` must not care
        which source they were handed."""
        rows = seed.choices_from_asset(_DEPLOYED_ASSET)
        floor = [r for r in rows if r["list_name"] == "floor_material"]
        assert [r["name"] for r in floor] == ["11", "19"]
        # A per-language list becomes the plain label the xlsx carries.
        assert floor[0]["label"] == "Concrete"

    def test_kobo_bookkeeping_is_dropped(self):
        """`$kuid` and `$autovalue` are Kobo's, not the form's, and a
        cascade column must survive."""
        rows = seed.choices_from_asset(_DEPLOYED_ASSET)
        assert not any(k.startswith("$") for r in rows for k in r)
        sub_region = next(r for r in rows if r["list_name"] == "sub_region")
        assert sub_region["region"] == "R-NORTHERN"

    def test_a_generated_code_is_one_the_form_offers(self):
        """The invariant. Drawing from the destination's own choices
        makes an invalid code impossible rather than unlikely."""
        rows = seed.choices_from_asset(_DEPLOYED_ASSET)
        offered = {"11", "19"}
        rng = random.Random(0)
        for _ in range(40):
            assert seed.choice_code(rows, "floor_material", rng) in offered

    def test_a_form_with_no_choices_yields_nothing_to_draw_from(self):
        """Better an empty list than a silent fallback: main() exits
        rather than generate from a form it could not read."""
        assert seed.choices_from_asset({"content": {"choices": []}}) == []
        assert seed.choices_from_asset({}) == []

    def test_the_survey_is_read_from_the_same_asset(self):
        """The XML builder needs the destination's question list too, or
        it would name fields the form does not have."""
        survey = seed.survey_from_asset(_DEPLOYED_ASSET)
        assert [q["name"] for q in survey] == ["g7_floor_material"]
        assert survey[0]["label"] == "G7. Main floor material"
