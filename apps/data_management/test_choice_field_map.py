"""Unit tests for apps/data_management/choice_field_map.py.

The field map is the single source of truth for every coded field
on Household/Member and inside source_payload (ADR-0010 §4). These
tests pin the map's contract — exhaustive coverage, multi-select
detection, JSON-path walking — so future edits do not silently
break the household-detail render path.
"""

from __future__ import annotations

import pytest

from apps.data_management.choice_field_map import (
    HOUSEHOLD_FIELDS,
    MEMBER_FIELDS,
    PAYLOAD_FIELDS,
    apply_payload_labels,
    iter_payload_choice_values,
)
from apps.reference_data.services import (
    clear_resolver_cache,
    resolve_label,
)


@pytest.fixture(autouse=True)
def _flush_cache():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


class TestMapShape:
    """The map's keys must be syntactically reachable. These tests
    don't hit the database — they assert the shape only."""

    def test_household_fields_pairs(self):
        for field, value in HOUSEHOLD_FIELDS.items():
            assert isinstance(field, str)
            list_name, kind = value
            assert isinstance(list_name, str)
            assert kind in ("single", "multi")

    def test_member_fields_pairs(self):
        for field, value in MEMBER_FIELDS.items():
            assert isinstance(field, str)
            list_name, kind = value
            assert isinstance(list_name, str)
            assert kind in ("single", "multi")

    def test_payload_paths_are_tuples_of_strings(self):
        for path, (list_name, kind) in PAYLOAD_FIELDS.items():
            assert isinstance(path, tuple)
            assert all(isinstance(p, str) for p in path)
            assert isinstance(list_name, str)
            assert kind in ("single", "multi")

    def test_no_path_is_empty(self):
        for path in PAYLOAD_FIELDS:
            assert len(path) >= 1

    def test_choice_trace_uses_the_same_canonical_paths_as_label_resolution(self):
        payload = {
            "housing": {"tenure": "2"},
            "members": [{"sex": "M"}, {"sex": "F"}],
        }

        # The trace names the CANONICAL list. "2" is a legacy code and
        # resolves through dwelling_tenure at label time
        # (LEGACY_FRAME_FALLBACK), but the field's list is `tenure` —
        # the trace says which field was read, not which frame happened
        # to own the value.
        assert list(iter_payload_choice_values(payload)) == [
            (("housing", "tenure"), "tenure", "single", "2"),
            (("members", "0", "sex"), "sex", "single", "M"),
            (("members", "1", "sex"), "sex", "single", "F"),
        ]


@pytest.mark.django_db
class TestApplyPayloadLabels:
    """End-to-end behaviour of the JSON-path walker against the
    seeded ChoiceList catalogue. The payload mirrors what Kobo
    actually lands for Nsubuga Ruth (see project memory)."""

    def test_housing_block_resolves(self):
        payload = {
            "housing": {
                "tenure": "13",
                "roof_material": "14",
                "wall_material": "11",
                "floor_material": "15",
                "cooking_fuel": "02",
                "lighting_source": "11",
                "water_source": "10",
                "toilet_type": "15",
                "waste_disposal": "18",
                "livelihood_source": "12",
                "assets_owned": "radio phone bicycle",
                "rooms_total": 4,  # not coded — should be ignored
            },
        }
        out = apply_payload_labels(payload, resolve_label)
        h = out["housing"]
        assert h["tenure"] == "Free - private"
        assert h["roof_material"] == "Concrete"
        assert h["wall_material"] == "Concrete/Stones"
        assert h["floor_material"] == "Rammed earth"
        assert h["cooking_fuel"] == "Electric stove"
        assert h["lighting_source"] == "Candle"
        assert h["water_source"] == "Piped water into dwelling"
        assert h["toilet_type"] == "Uncovered Pit Latrine without a slab"
        assert h["waste_disposal"] == "Bush"
        assert h["livelihood_source"] == "Commercial Farming"
        assert h["assets_owned"] == ["Radio", "Mobile phone", "Bicycle"]
        # Non-coded keys pass through untouched.
        assert "rooms_total" not in h

    def test_legacy_housing_codes_resolve_via_their_original_choice_lists(self):
        payload = {
            "housing": {
                "tenure": "2", "roof_material": "1", "wall_material": "3",
                "floor_material": "2", "cooking_fuel": "1",
                "lighting_source": "3", "water_source": "2",
                "toilet_type": "2", "waste_disposal": "3",
                "livelihood_source": "3",
            },
        }
        housing = apply_payload_labels(payload, resolve_label)["housing"]
        assert housing == {
            "tenure": "Renting", "roof_material": "Iron sheets",
            "wall_material": "Wood", "floor_material": "Tiles",
            "cooking_fuel": "Firewood", "lighting_source": "Generator",
            "water_source": "Piped — public tap",
            "toilet_type": "Flush — septic tank", "waste_disposal": "Buried",
            "livelihood_source": "Livestock keeping",
        }

    def test_missing_block_skipped(self):
        payload = {"agriculture": {"land_ownership": "4"}}
        out = apply_payload_labels(payload, resolve_label)
        assert "housing" not in out
        assert out["agriculture"]["land_ownership"] == "Doesn't own"

    def test_per_member_block_resolves_positionally(self):
        payload = {
            "members": [
                {"line_number": 1, "marital_status": "11"},
                {"line_number": 2, "marital_status": "20"},
            ],
        }
        out = apply_payload_labels(payload, resolve_label)
        assert out["members"][0]["marital_status"] == "Married - Christian"
        assert out["members"][1]["marital_status"] == "Never married"

    def test_empty_payload_returns_empty_dict(self):
        assert apply_payload_labels(None, resolve_label) == {}
        assert apply_payload_labels({}, resolve_label) == {}

    def test_unknown_code_returns_raw_in_payload(self, caplog):
        payload = {"housing": {"tenure": "999"}}
        with caplog.at_level("WARNING"):
            out = apply_payload_labels(payload, resolve_label)
        assert out["housing"]["tenure"] == "999"
        assert any(r.message == "ref_data.unmapped_code" for r in caplog.records)
