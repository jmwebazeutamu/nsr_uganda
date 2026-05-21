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


class TestHeadMemberInvariant:
    """US-FIX-001 — `Household.head_member` and
    `Member.relationship_to_head = "01"` MUST agree. Audit 2026-05-21 §4
    flagged the divergence in the dev fixture; the promote path now
    enforces it at write time, and `Household.clean()` is the guard
    for any other write path.
    """

    def _make_hh(self, geo):
        return Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
            urban_rural="2",
        )

    def test_clean_passes_when_head_relationship_is_01(self, geo):
        hh = self._make_hh(geo)
        head = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="1",
            relationship_to_head="01",
        )
        hh.head_member = head
        hh.save()
        hh.full_clean()  # must not raise

    def test_clean_raises_when_head_relationship_is_not_01(self, geo):
        from django.core.exceptions import ValidationError
        hh = self._make_hh(geo)
        wrong = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="1",
            relationship_to_head="04",  # Son/Daughter — invalid for head
        )
        hh.head_member = wrong
        hh.save()
        with pytest.raises(ValidationError):
            hh.full_clean()

    def test_clean_passes_when_head_member_is_blank(self, geo):
        # The model permits creating a Household before the head is
        # known. `clean()` only constrains the case where head_member
        # is wired up.
        hh = self._make_hh(geo)
        hh.full_clean()
        Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="1",
            relationship_to_head="",  # not yet coded
        )
        hh.full_clean()

    def test_clean_passes_when_head_relationship_blank(self, geo):
        # Blank is tolerated so the post-create initialisation step in
        # promote_stage_record (which sets relationship_to_head="01"
        # after first creating the Member with the payload's value) can
        # land without a transient validation error.
        hh = self._make_hh(geo)
        m = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="1",
            relationship_to_head="",
        )
        hh.head_member = m
        hh.save()
        hh.full_clean()  # must not raise
