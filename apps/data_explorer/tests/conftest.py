"""Fixtures for the DATA-EXP catalogue integrity tests.

The catalogue is loaded from the seed by a post_migrate signal, but in a
freshly-built test database that signal fires before PrivacyClass rows
exist and logs its own failure rather than blocking migrate:

    data_explorer.metadata_loader refresh skipped after … migrate:
    insert or update on table "data_explorer_dataset" violates foreign
    key constraint …

So `Dataset.objects` is empty in tests. Any test that iterates the
catalogue to assert something about it therefore passes by iterating
nothing — which is how a guard against undeclared datasets can be green
and worthless at the same time. This fixture loads it explicitly, and
the tests assert it is non-empty before believing anything else.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def catalogue(db):
    """The seeded Dataset + Variable catalogue, loaded and ACTIVE."""
    from apps.data_explorer import catalogue as catalogue_cache
    from apps.data_explorer import metadata_loader
    from apps.data_explorer.models import Dataset

    result = metadata_loader.refresh(activate=True)
    assert not result.get("skipped"), f"catalogue did not load: {result}"
    catalogue_cache.invalidate()

    datasets = list(Dataset.objects.exclude(source_matview=""))
    assert datasets, "catalogue loaded but holds no datasets"
    return datasets
