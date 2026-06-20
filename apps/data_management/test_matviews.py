"""Postgres-only tests for the Data Explorer matview refresh mechanism.

The matviews are created ``WITH NO DATA`` by migration 0010, so a fresh
test database has them unpopulated — any SELECT raises OperationalError
until the first REFRESH. These tests pin the contract the aggregate
endpoint and the beat task depend on: populated-detection is honest, and
``refresh_explorer_matviews`` flips every matview to populated.
"""

from __future__ import annotations

import pytest

from apps.data_management.matviews import (
    EXPLORER_MATVIEWS,
    _existing_matviews,
    is_matview_populated,
    refresh_explorer_matviews,
)

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]

# The two household-grain matviews have Postgres DDL today (migration
# 0010); the rest are unbuilt scope. Tests assert against what exists.
HOUSEHOLD_MATVIEWS = {
    "mv_explorer_household_by_subcounty_demographics",
    "mv_explorer_household_by_subcounty_pmt",
}


def test_existing_matviews_includes_the_household_pair():
    existing = _existing_matviews(EXPLORER_MATVIEWS)
    assert HOUSEHOLD_MATVIEWS <= existing


def test_matviews_start_unpopulated():
    # Freshly migrated test DB: every matview that exists is WITH NO DATA.
    for name in _existing_matviews(EXPLORER_MATVIEWS):
        assert is_matview_populated(name) is False, name


def test_refresh_populates_existing_matviews():
    refreshed = refresh_explorer_matviews()
    existing = _existing_matviews(EXPLORER_MATVIEWS)
    assert set(refreshed) == existing
    assert HOUSEHOLD_MATVIEWS <= set(refreshed)
    for name in refreshed:
        assert is_matview_populated(name) is True, name


def test_refresh_rejects_unknown_matview():
    with pytest.raises(ValueError, match="Not Data Explorer matviews"):
        refresh_explorer_matviews(names=["mv_explorer_household_by_subcounty_pmt", "pg_user"])


def test_is_matview_populated_unknown_name_is_false():
    assert is_matview_populated("mv_does_not_exist") is False
