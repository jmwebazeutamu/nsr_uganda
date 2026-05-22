"""Project-wide pytest conftest.

Two backend-gated markers:

- @pytest.mark.postgres    — needs the real Postgres-only behaviour
                             (audit-chain trigger, PostGIS, partitioning).
                             Auto-skipped on sqlite.
- @pytest.mark.sqlite_only — pins a behaviour that only manifests on
                             sqlite (typically: a "no_chain" / no-trigger
                             no-op fallback). Auto-skipped on Postgres
                             where the trigger ACTIVELY rewrites the
                             outcome and the assertion would falsely fail.

Both markers are mutually exclusive — the same test should never carry
both. If a test needs to assert both branches, split into two cases.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.db import connection


@pytest.fixture(autouse=True)
def _drs_bundle_storage_isolation():
    """Force the in-process bundle backend during tests.

    Settings.py defaults to the file-backed store (BUG-S27-032 fix) so
    dev `runserver` survives restarts. Tests would otherwise litter
    .drs-bundles/ with cross-run artefacts; pinning to memory keeps
    bundles per-process and isolates them between cases.
    """
    prev = getattr(settings, "DRS_BUNDLE_STORAGE", None)
    settings.DRS_BUNDLE_STORAGE = "memory"
    try:
        from apps.data_requests.storage import get_bundle_storage
        get_bundle_storage()._reset_for_tests()
    except Exception:
        pass
    yield
    if prev is None:
        delattr(settings, "DRS_BUNDLE_STORAGE")
    else:
        settings.DRS_BUNDLE_STORAGE = prev


def pytest_collection_modifyitems(config, items):
    vendor = connection.vendor
    skip_pg = pytest.mark.skip(
        reason="needs PostgreSQL backend (see @pytest.mark.postgres)",
    )
    skip_sqlite = pytest.mark.skip(
        reason="sqlite-only behaviour (see @pytest.mark.sqlite_only) — "
               "the audit-chain trigger is installed on this backend",
    )
    for item in items:
        if "postgres" in item.keywords and vendor != "postgresql":
            item.add_marker(skip_pg)
        if "sqlite_only" in item.keywords and vendor != "sqlite":
            item.add_marker(skip_sqlite)
