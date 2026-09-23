"""The geographic ladder is one ladder, and every dataset serves all of it.

The defect this pins: `query_builder.field_map` listed sub_region,
district and sub_county. A county-scoped request — county is above the
sub-county floor, so the validator accepted it — found no column and
fell through to an *unfiltered* queryset, handing back the national
aggregate labelled as one county. A nonsense code did the same.

Two invariants:

  1. The ladder has one definition, derived from ScopeLevel, and it
     matches the UBOS frame: region → sub_region → district → county →
     sub_county → parish → village.
  2. Every dataset can be filtered at every level from national down to
     its own declared `geographic_floor`. Anything else is refused, not
     silently widened.
"""

from __future__ import annotations

import pytest

from apps.data_explorer.geography import (
    LADDER,
    LEVEL_COLUMN,
    LEVEL_RANK,
    levels_down_to,
    normalise_level,
    scopable_levels,
)
from apps.data_explorer.matview_models import MATVIEW_MODELS
from apps.data_explorer.models import Dataset
from apps.data_management.matviews import EXPLORER_MATVIEWS, _existing_matviews
from apps.reference_data.models import GeographicUnit

# The UBOS frame, written out once here on purpose: this is the
# assertion, so it must not be derived from the thing under test.
UBOS_FRAME = (
    "region", "sub_region", "district", "county",
    "sub_county", "parish", "village",
)


def test_ladder_is_the_ubos_frame_under_national():
    assert LADDER == ("national", *UBOS_FRAME)


def test_ladder_is_derived_from_the_ubos_frame():
    """The ladder's source is GeographicUnit.Level, the frame itself.

    It used to be derived from ScopeLevel, which mirrors the frame for
    ABAC — and committed ScopeLevel has no COUNTY, so county silently
    dropped out of the ladder in production. Asserting against
    GeographicUnit.Level here keeps the derivation honest; the
    ScopeLevel agreement is asserted separately below.
    """
    assert set(UBOS_FRAME) == {lv.value for lv in GeographicUnit.Level}
    assert set(UBOS_FRAME) <= set(LEVEL_RANK)


def test_abac_can_express_every_level_the_explorer_serves():
    """A level the Data Explorer can filter by, but ScopeLevel cannot
    name, is a level no operator can be scoped to.

    ScopeLevel briefly lacked COUNTY while the frame had it, which is
    how county fell out of the ladder in the first place. No gap is
    tolerated now.
    """
    from apps.security.models import ScopeLevel

    missing = set(UBOS_FRAME) - {lv.value for lv in ScopeLevel}
    assert not missing, (
        f"ScopeLevel cannot express {sorted(missing)}; ABAC cannot "
        "scope an operator to those levels."
    )


def test_county_sits_between_district_and_sub_county():
    assert LEVEL_RANK["district"] < LEVEL_RANK["county"] < LEVEL_RANK["sub_county"]


def test_every_level_but_national_has_a_column():
    assert set(LEVEL_COLUMN) == set(UBOS_FRAME)
    assert LEVEL_COLUMN["county"] == "county_code"
    assert "national" not in LEVEL_COLUMN


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("County", "county"), ("sub-county", "sub_county"),
        ("subcounty", "sub_county"), ("SubRegion", "sub_region"),
        ("sub-region", "sub_region"), ("country", "national"),
        ("", ""), (None, ""),
    ],
)
def test_normalise_level(raw, expected):
    assert normalise_level(raw) == expected


@pytest.mark.django_db
@pytest.mark.postgres
def test_built_datasets_are_scopable_down_to_their_floor(catalogue):
    """The invariant. A dataset that claims a floor must be filterable
    at every level down to it — otherwise a request the validator
    accepts has no column to filter on."""
    existing = _existing_matviews(EXPLORER_MATVIEWS)
    checked = 0
    for dataset in catalogue:
        if dataset.source_matview not in existing:
            continue
        model = MATVIEW_MODELS[dataset.source_matview]
        required = levels_down_to(dataset.geographic_floor or "sub_county")
        missing = required - scopable_levels(model)
        assert not missing, (
            f"{dataset.code} declares floor "
            f"{dataset.geographic_floor!r} but {dataset.source_matview} "
            f"cannot be scoped by {sorted(missing)}. A request at that "
            "level is accepted by the validator and then matches every "
            "row in the country."
        )
        checked += 1
    assert checked >= 3, f"expected the 3 built datasets, checked {checked}"


@pytest.mark.django_db
@pytest.mark.postgres
def test_county_is_scopable_on_the_household_datasets():
    """Named explicitly, because county is the rung that was missing."""
    for matview in (
        "mv_explorer_household_by_subcounty_demographics",
        "mv_explorer_household_by_subcounty_pmt",
    ):
        levels = scopable_levels(MATVIEW_MODELS[matview])
        assert "county" in levels, matview
        assert {"region", "sub_region", "district", "sub_county"} <= levels


# ---------------------------------------------------------------------------
# Fail closed — the branch that used to return everything
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.postgres
def test_unscopable_level_raises_instead_of_returning_everything():
    """The predecessor of this behaviour was `return qs`.

    A matview with no column for the requested level handed back every
    row it had. Here the shocks matview — sub-region grain, no
    district column — is asked for a district.
    """
    from apps.data_explorer.query_builder import (
        UnscopableLevel,
        _apply_geographic_scope,
    )

    model = MATVIEW_MODELS["mv_explorer_household_shocks_subregion"]
    with pytest.raises(UnscopableLevel) as excinfo:
        _apply_geographic_scope(
            model.objects.all(), {"level": "district", "codes": ["102"]},
        )
    assert excinfo.value.level == "district"


@pytest.mark.django_db
@pytest.mark.postgres
def test_national_still_passes_through_unfiltered():
    """national is the one level with no column, and it legitimately
    means 'do not filter' — the fail-closed change must not break it."""
    from apps.data_explorer.query_builder import _apply_geographic_scope

    model = MATVIEW_MODELS["mv_explorer_household_by_subcounty_pmt"]
    base = model.objects.all()
    scoped = _apply_geographic_scope(base, {"level": "national", "codes": ["UG"]})
    assert str(scoped.query) == str(base.query)


@pytest.mark.django_db
@pytest.mark.postgres
def test_county_filters_rather_than_widening(catalogue):
    """The whole point, at the query layer: a county scope must narrow."""
    from apps.data_explorer.query_builder import _apply_geographic_scope

    model = MATVIEW_MODELS["mv_explorer_household_by_subcounty_pmt"]
    scoped = _apply_geographic_scope(
        model.objects.all(), {"level": "county", "codes": ["NOT-A-COUNTY"]},
    )
    # Nothing matches a nonsense code. Before the fix this returned the
    # entire national result set.
    assert scoped.count() == 0
    assert "county_code" in str(scoped.query)
