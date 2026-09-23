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

    def test_an_explicit_partition_key_that_contradicts_the_fk_is_corrected(self, geo):
        """The mirror tracks the FK. It is not a free-text column.

        This used to assert the opposite — an explicitly-passed
        sub_region_code was left alone, so a backfill could write the
        column through the ORM without save() re-resolving it. That
        escape hatch is now unsafe and unused: ABAC matches operators
        against these columns, so a household whose sub_region_code
        disagrees with its sub_region is a household shown to the wrong
        operator and hidden from the right one. Nothing in the
        application sets one explicitly, and migration 0014's backfill
        writes in SQL rather than through the ORM.
        """
        hh = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
            urban_rural="2", sub_region_code="CUSTOM",
        )
        hh.refresh_from_db()
        assert hh.sub_region_code == geo["sr"].code

    def test_every_level_is_mirrored_not_just_the_partition_key(self, geo):
        """ADR-0005 denormalised one rung. All seven are mirrored now —
        see tests/contract/test_household_geography_denorm.py."""
        hh = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
            urban_rural="2",
        )
        hh.refresh_from_db()
        assert hh.district_code == geo["d"].code
        assert hh.county_code == geo["c"].code
        assert hh.sub_county_code == geo["sc"].code


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
