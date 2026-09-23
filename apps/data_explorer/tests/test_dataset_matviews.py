"""Every declared dataset must resolve to a matview that exists.

This is the guard that was missing. ``household_shocks`` was declared in
three places — the unmanaged model, the privacy-class seed, and the
refresh list — and the refresh list is deliberately existence-aware, so
a dataset whose ``CREATE MATERIALIZED VIEW`` never landed looked exactly
like one that was simply empty. It resolved to a table that does not
exist, and only a caller querying it would have found out.

The test does not demand that every declared dataset be built; five are
honest backlog. It demands that the unbuilt set be *named here*, so
"declared but not built" is a line in a file somebody has to delete
rather than a silence.
"""

from __future__ import annotations

import pytest

from apps.data_explorer.matview_models import MATVIEW_MODELS
from apps.data_explorer.models import Dataset
from apps.data_management.matviews import (
    EXPLORER_MATVIEWS,
    _existing_matviews,
    is_matview_populated,
)

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]

# Datasets declared in the catalogue whose Postgres DDL is still backlog
# scope (ADR-0023 D2). Delete a line here when its migration lands — the
# test then requires the matview to exist.
UNBUILT_MATVIEWS = {
    "mv_explorer_member_by_subcounty_education",
    "mv_explorer_member_by_subcounty_employment",
    "mv_explorer_referrals_subcounty",
    "mv_explorer_grievances_subcounty",
    "mv_explorer_health_chronic_subregion",
}


def _declared_matviews() -> set[str]:
    return set(
        Dataset.objects.exclude(source_matview="")
        .values_list("source_matview", flat=True),
    )


def test_every_declared_dataset_names_a_known_matview():
    """A dataset may not point at a matview nothing else knows about."""
    unknown = _declared_matviews() - set(EXPLORER_MATVIEWS)
    assert not unknown, f"Dataset.source_matview not in EXPLORER_MATVIEWS: {unknown}"


def test_every_declared_dataset_has_a_model():
    missing = _declared_matviews() - set(MATVIEW_MODELS)
    assert not missing, f"No matview_models entry for: {missing}"


def test_built_datasets_resolve_to_a_populated_matview():
    """Anything not on the unbuilt list must be queryable right now."""
    should_exist = _declared_matviews() - UNBUILT_MATVIEWS
    existing = _existing_matviews(EXPLORER_MATVIEWS)

    missing = should_exist - existing
    assert not missing, (
        f"Declared datasets with no matview in Postgres: {missing}. "
        "Either the migration is missing or the name belongs in "
        "UNBUILT_MATVIEWS."
    )
    for name in should_exist:
        assert is_matview_populated(name) is True, name


def test_unbuilt_list_does_not_name_a_matview_that_exists():
    """The list must shrink, not rot.

    Once a migration builds one of these, this fails until the line is
    removed — which is the point.
    """
    stale = UNBUILT_MATVIEWS & _existing_matviews(EXPLORER_MATVIEWS)
    assert not stale, f"Built, but still listed as unbuilt: {stale}"


def test_declared_variables_match_the_matview_columns():
    """The dataset's variables are the matview's columns, not a parallel
    vocabulary — a Variable naming a column the matview does not project
    returns an error at query time, not at declaration time."""
    from django.db import connection

    existing = _existing_matviews(EXPLORER_MATVIEWS)
    for dataset in Dataset.objects.exclude(source_matview=""):
        if dataset.source_matview not in existing:
            continue
        with connection.cursor() as cur:
            cur.execute(
                "SELECT attname FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped",
                [dataset.source_matview],
            )
            columns = {r[0] for r in cur.fetchall()}
        declared = set(dataset.variables.values_list("code", flat=True))
        assert declared <= columns, (
            f"{dataset.code}: variables not projected by "
            f"{dataset.source_matview}: {declared - columns}"
        )
