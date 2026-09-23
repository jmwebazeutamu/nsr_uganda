"""Postgres-only tests for the Data Explorer matview refresh mechanism.

A matview created ``WITH NO DATA`` raises OperationalError on *any*
SELECT until its first REFRESH, which the aggregate endpoint surfaces as
a 503. These tests pin the contract the endpoint and the beat task
depend on: ``migrate`` leaves every matview readable, populated-detection
is honest about one that is not, and ``refresh_explorer_matviews`` flips
them all to populated.

They also pin the two shape decisions migration 0011 made for
``mv_explorer_household_shocks_subregion`` — see its module docstring.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.db import connection

from apps.data_management.matviews import (
    EXPLORER_MATVIEWS,
    _existing_matviews,
    is_matview_populated,
    refresh_explorer_matviews,
)
from apps.data_management.models import Household, Shock
from apps.reference_data.models import GeographicUnit

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]

# The matviews with Postgres DDL today: the household-grain pair from
# migration 0010 and household_shocks from 0011. The rest are unbuilt
# scope. Tests assert against what exists.
HOUSEHOLD_MATVIEWS = {
    "mv_explorer_household_by_subcounty_demographics",
    "mv_explorer_household_by_subcounty_pmt",
}
SHOCKS_MATVIEW = "mv_explorer_household_shocks_subregion"

BUILT_MATVIEWS = HOUSEHOLD_MATVIEWS | {SHOCKS_MATVIEW}


def test_existing_matviews_includes_every_built_matview():
    existing = _existing_matviews(EXPLORER_MATVIEWS)
    assert BUILT_MATVIEWS <= existing


def test_migrate_leaves_every_matview_readable():
    """No matview is left WITH NO DATA once migrations have run.

    Migration 0011 populates the whole ``mv_explorer_*`` family, not just
    the one it creates, so a freshly-migrated database never serves the
    503 that an unpopulated matview produces. Before that the 0010 pair
    were readable only because beat had since run.
    """
    for name in _existing_matviews(EXPLORER_MATVIEWS):
        assert is_matview_populated(name) is True, name


def test_is_matview_populated_detects_an_unpopulated_matview():
    """Populated-detection is honest, not a constant True.

    ``REFRESH ... WITH NO DATA`` is the only way back to the unpopulated
    state, so the test puts a matview there deliberately rather than
    leaning on migration-time state.
    """
    with connection.cursor() as cur:
        cur.execute(f"REFRESH MATERIALIZED VIEW {SHOCKS_MATVIEW} WITH NO DATA")
    assert is_matview_populated(SHOCKS_MATVIEW) is False

    refresh_explorer_matviews(names=[SHOCKS_MATVIEW])
    assert is_matview_populated(SHOCKS_MATVIEW) is True


def test_refresh_populates_existing_matviews():
    refreshed = refresh_explorer_matviews()
    existing = _existing_matviews(EXPLORER_MATVIEWS)
    assert set(refreshed) == existing
    assert BUILT_MATVIEWS <= set(refreshed)
    for name in refreshed:
        assert is_matview_populated(name) is True, name


def test_refresh_rejects_unknown_matview():
    with pytest.raises(ValueError, match="Not Data Explorer matviews"):
        refresh_explorer_matviews(names=["mv_explorer_household_by_subcounty_pmt", "pg_user"])


def test_is_matview_populated_unknown_name_is_false():
    assert is_matview_populated("mv_does_not_exist") is False


# ---------------------------------------------------------------------------
# mv_explorer_household_shocks_subregion — the two decisions in migration 0011
# ---------------------------------------------------------------------------

SUB_REGION_CODE = "SR-WEST-NILE-NORTHERN"


@pytest.fixture
def geography():
    nodes = {}
    for level, key, parent_key in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level,
            code=SUB_REGION_CODE if key == "sr" else f"MV-{key.upper()}",
            name=key.title(),
            parent=nodes.get(parent_key),
            effective_from=date(2026, 1, 1),
        )
    return nodes


def _household(geography):
    return Household.objects.create(
        region=geography["r"], sub_region=geography["sr"],
        district=geography["d"], county=geography["c"],
        sub_county=geography["sc"], parish=geography["p"],
        village=geography["v"], urban_rural="2",
    )


def _shock_rows():
    """The matview, as rows of (sub_region_code, shock_type, severity, count).

    Read through the unmanaged model so the test pins the model→column
    mapping the aggregate endpoint relies on, not just the SQL.
    """
    from apps.data_explorer.matview_models import HouseholdShocksSubregion

    refresh_explorer_matviews(names=[SHOCKS_MATVIEW])
    return {
        (r.sub_region_code, r.shock_type, r.severity): r.household_count
        for r in HouseholdShocksSubregion.objects.all()
    }


def test_household_count_counts_households_not_shock_rows(geography):
    """Section K asks K03/K04 once per livelihood, so one household can
    file several Shock rows under the same type and severity. The
    dataset is a household count — two rows from one household is one
    household, and that is what DISTINCT in the definition buys."""
    household = _household(geography)
    for livelihood in ("crops", "livestock"):
        Shock.objects.create(
            household=household, shock_type="drought", severity="3",
            livelihoods_affected=[livelihood],
        )

    rows = _shock_rows()
    assert rows[(SUB_REGION_CODE, "drought", "3")] == 1

    # A second household with the same pair moves the count — proving
    # the 1 above is DISTINCT counting, not a definition that never
    # counts past one.
    Shock.objects.create(
        household=_household(geography), shock_type="drought", severity="3",
        livelihoods_affected=["crops"],
    )
    assert _shock_rows()[(SUB_REGION_CODE, "drought", "3")] == 2


def test_sub_region_code_holds_the_code_not_the_row_id(geography):
    """The column ABAC and query_builder filter on carries codes.

    The 0010 pair project `sub_region_id::text` into this column name;
    this matview projects the code, because an OperatorScope row grants
    "SR-WEST-NILE-NORTHERN", never a GeographicUnit primary key. A
    scoped query against a row-id column matches nothing and silently
    returns an empty dataset rather than erroring.
    """
    Shock.objects.create(
        household=_household(geography), shock_type="flood", severity="2",
    )

    codes = {code for (code, _t, _s) in _shock_rows()}
    assert codes == {SUB_REGION_CODE}
    assert str(geography["sr"].pk) not in codes


# ---------------------------------------------------------------------------
# Geographic columns carry codes — migration 0012
# ---------------------------------------------------------------------------

# matview → {column: the GeographicUnit level that column names}.
# `query_builder._apply_geographic_scope` maps a request's level onto
# exactly these column names and filters `<column>__in=<codes the caller
# sent>`, so anything but a code there silently returns no rows.
GEO_COLUMNS = {
    "mv_explorer_household_by_subcounty_demographics": {
        "sub_region_code": "sub_region",
        "district_code": "district",
        "sub_county_code": "sub_county",
    },
    "mv_explorer_household_by_subcounty_pmt": {
        "sub_region_code": "sub_region",
        "district_code": "district",
        "sub_county_code": "sub_county",
    },
    SHOCKS_MATVIEW: {
        "sub_region_code": "sub_region",
    },
}


def test_geographic_columns_hold_codes_not_row_ids(geography):
    """Every geographic column of every built matview resolves to a
    GeographicUnit code at the level its name claims.

    The 0010 pair shipped projecting `h.sub_region_id::text` and friends
    into these columns — primary keys, in columns called `*_code`. A
    scoped aggregate matched nothing and returned an empty result rather
    than an error, so nothing ever complained. This asserts the values
    are codes by resolving each one against the geography table.
    """
    from apps.data_explorer.matview_models import MATVIEW_MODELS

    household = _household(geography)
    Shock.objects.create(
        household=household, shock_type="drought", severity="3",
    )
    refresh_explorer_matviews()

    checked = 0
    for matview, columns in GEO_COLUMNS.items():
        model = MATVIEW_MODELS[matview]
        rows = list(model.objects.all())
        assert rows, f"{matview} produced no rows for the seeded household"
        for row in rows:
            for column, level in columns.items():
                value = getattr(row, column)
                assert value, f"{matview}.{column} is empty"
                assert GeographicUnit.objects.filter(
                    level=level, code=value,
                ).exists(), (
                    f"{matview}.{column} = {value!r} is not a {level} code. "
                    "A GeographicUnit primary key here makes every scoped "
                    "query return nothing."
                )
                checked += 1
    assert checked == 7, f"expected 7 column checks, made {checked}"


def test_a_scoped_query_finds_the_household(geography):
    """The end the bug was at: filter the matview the way
    ``_apply_geographic_scope`` does, with the codes a caller supplies.
    """
    from apps.data_explorer.matview_models import HouseholdBySubcountyPmt
    from apps.data_explorer.query_builder import _apply_geographic_scope

    _household(geography)
    refresh_explorer_matviews(names=["mv_explorer_household_by_subcounty_pmt"])

    for level, code in [
        ("sub_region", SUB_REGION_CODE),
        ("district", geography["d"].code),
        ("sub_county", geography["sc"].code),
    ]:
        qs = _apply_geographic_scope(
            HouseholdBySubcountyPmt.objects.all(),
            {"level": level, "codes": [code]},
        )
        assert qs.exists(), f"scoping to {level}={code} returned no rows"

    # And the row id it used to hold finds nothing, which is exactly how
    # the defect stayed invisible.
    qs = _apply_geographic_scope(
        HouseholdBySubcountyPmt.objects.all(),
        {"level": "district", "codes": [str(geography["d"].pk)]},
    )
    assert not qs.exists()
