"""Data-management model invariants."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit


@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"PK-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


class TestSubRegionCodeInvariant:
    """ADR-0005: sub_region_code denormalised partition key MUST track
    sub_region.code on every Household and propagate to every Member."""

    def test_household_save_populates_sub_region_code(self, geo):
        hh = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
            urban_rural="2",
        )
        hh.refresh_from_db()
        assert hh.sub_region_code == geo["sr"].code

    def test_member_inherits_household_sub_region_code(self, geo):
        hh = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
            urban_rural="2",
        )
        m = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="1",
        )
        m.refresh_from_db()
        assert m.sub_region_code == hh.sub_region_code

    def test_explicit_partition_key_not_overwritten(self, geo):
        # Allows the backfill migration to populate the column via the ORM
        # without the save() override silently re-resolving from the FK.
        hh = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
            urban_rural="2", sub_region_code="CUSTOM",
        )
        hh.refresh_from_db()
        assert hh.sub_region_code == "CUSTOM"
