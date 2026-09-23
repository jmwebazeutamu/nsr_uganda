"""Household's geography mirrors are the same fact as its geography FKs.

Every UBOS code is denormalised onto Household. That is only safe while
the mirror and the FK say the same thing — and a mirror that drifts is
not a cosmetic problem, because ABAC matches on these columns. A
household whose `district_code` still points at the district it moved
out of is a household shown to the wrong operator.

These pin the guarantee, not the mechanism:

  1. Every household's mirror equals its FK's code, for every level.
  2. Moving a household updates the mirror. The predecessor only filled
     a mirror when it was blank, so a move left the old code in place.
  3. ABAC's level map is DERIVED from Household, so a rung cannot land
     on one and be missed by the other.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.db.models import F

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.abac import _level_field
from apps.security.models import ScopeLevel

pytestmark = pytest.mark.django_db


@pytest.fixture
def geography():
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"),
        ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"DN-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


def _household(geography, **over):
    kwargs = dict(
        region=geography["r"], sub_region=geography["sr"],
        district=geography["d"], county=geography["c"],
        sub_county=geography["sc"], parish=geography["p"],
        village=geography["v"], urban_rural="2",
    )
    kwargs.update(over)
    return Household.objects.create(**kwargs)


def test_every_mirror_matches_its_fk_on_create(geography):
    household = _household(geography)
    household.refresh_from_db()
    for level, column in Household.GEO_CODE_FIELDS.items():
        unit = getattr(household, level)
        assert getattr(household, column) == unit.code, level


def test_every_household_in_the_database_is_in_lockstep(geography):
    """The guarantee as a whole-table assertion — the shape a data
    quality check would take against production."""
    _household(geography)
    for level, column in Household.GEO_CODE_FIELDS.items():
        drifted = (
            Household.objects
            .exclude(**{f"{level}__isnull": True})
            .exclude(**{column: F(f"{level}__code")})
        )
        assert not drifted.exists(), (
            f"{drifted.count()} household(s) whose {column} disagrees "
            f"with {level}.code"
        )


def test_moving_a_household_moves_its_mirror(geography):
    """The drift bug. sub_region_code was only ever written when blank,
    so a household that changed sub-region kept the old code — and ABAC
    kept showing it to the old sub-region's operators."""
    household = _household(geography)
    assert household.district_code == "DN-D"

    elsewhere = GeographicUnit.objects.create(
        level="district", code="DN-D-OTHER", name="Elsewhere",
        parent=geography["sr"], effective_from=date(2026, 1, 1),
    )
    household.district = elsewhere
    household.save()
    household.refresh_from_db()
    assert household.district_code == "DN-D-OTHER"


def test_an_optional_level_left_unset_has_an_empty_mirror(geography):
    """Village is the one level the UBOS frame does not always carry."""
    household = _household(geography, village=None)
    household.refresh_from_db()
    assert household.village_code == ""
    assert household.parish_code == "DN-P"


def test_a_clean_save_does_not_reread_the_geography(
    geography, django_assert_num_queries,
):
    """The mirror must not cost a query per level on every save.

    Seven levels naively re-read would be seven extra SELECTs on every
    household write, on a table heading for 12M rows. Re-saving a
    household whose FKs have not moved issues the UPDATE and nothing
    else: sync_geography_codes compares the loaded FK ids against the
    instance snapshot and short-circuits.
    """
    household = _household(geography)
    fresh = Household.objects.get(pk=household.pk)

    with django_assert_num_queries(1):
        fresh.save()


def test_a_moved_household_reads_only_the_level_that_moved(geography):
    """And when an FK does move, only that level is re-read."""
    elsewhere = GeographicUnit.objects.create(
        level="district", code="DN-D-MOVED", name="Moved",
        parent=geography["sr"], effective_from=date(2026, 1, 1),
    )
    household = _household(geography)
    fresh = Household.objects.get(pk=household.pk)
    fresh.district = elsewhere          # the object is already in hand
    fresh.sync_geography_codes()

    assert fresh.district_code == "DN-D-MOVED"
    # Nothing else shifted.
    assert fresh.county_code == "DN-C"
    assert fresh.sub_county_code == "DN-SC"


def test_abac_maps_every_geographic_scope_level():
    """ABAC's map is derived from Household, so the two cannot diverge.

    A ScopeLevel with no column here is a scope no operator can be
    granted — which is how county went missing once already.
    """
    mapped = _level_field()
    geographic = {
        level.value for level in ScopeLevel
        if level not in (ScopeLevel.NATIONAL, ScopeLevel.PARTNER)
    }
    assert geographic <= set(mapped), (
        f"ABAC cannot scope by {sorted(geographic - set(mapped))}"
    )
    # And every mapped column really exists on Household.
    columns = {f.name for f in Household._meta.get_fields()}
    assert set(mapped.values()) <= columns


def test_abac_columns_are_the_denorm_not_a_join():
    """A `__` in one of these is a join sneaking back onto the hot path
    of every scoped list query — and a second way to ask the question."""
    joins = [col for col in _level_field().values() if "__" in col]
    assert not joins, f"ABAC still traverses FKs for: {joins}"


def test_a_deferred_queryset_does_not_recurse(geography):
    """`.only(...)` must not blow the stack.

    The first cut of ``from_db`` snapshotted the geography FK ids with
    getattr. On a deferred queryset that goes through
    DeferredAttribute, which issues a fresh query, which calls
    ``from_db`` again — RecursionError, surfacing far away in the
    deduplication tests because those are what defer columns.
    """
    _household(geography)

    rows = list(Household.objects.only("id", "district_code"))
    assert len(rows) == 1
    assert rows[0].district_code == "DN-D"
    # Nothing was snapshotted for the levels that were not loaded.
    assert "county" not in rows[0]._geo_fk_snapshot


def test_saving_a_deferred_household_leaves_unloaded_mirrors_alone(geography):
    """A deferred column is not ours to rewrite — loading it to check
    would undo the caller's reason for deferring it."""
    household = _household(geography)

    partial = Household.objects.only("id", "district_id", "district_code").get(
        pk=household.pk,
    )
    partial.save()

    household.refresh_from_db()
    assert household.county_code == "DN-C"
    assert household.parish_code == "DN-P"
