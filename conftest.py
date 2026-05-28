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


@pytest.fixture(autouse=True)
def _upd_evidence_storage_isolation():
    """Mirror the DRS pattern for Open-CR evidence files. Tests use the
    in-memory backend so uploaded documents never touch
    .upd-evidence/ on disk."""
    prev = getattr(settings, "UPD_EVIDENCE_STORAGE", None)
    settings.UPD_EVIDENCE_STORAGE = "memory"
    try:
        from apps.update_workflow.evidence_storage import get_evidence_storage
        get_evidence_storage()._reset_for_tests()
    except Exception:
        pass
    yield
    if prev is None:
        if hasattr(settings, "UPD_EVIDENCE_STORAGE"):
            delattr(settings, "UPD_EVIDENCE_STORAGE")
    else:
        settings.UPD_EVIDENCE_STORAGE = prev


def pytest_collection_modifyitems(config, items):
    vendor = connection.vendor
    # DATA-EXP (US-DATA-EXP-001) — the AnalyticsReplicaRouter routes
    # apps.data_explorer.* reads to the `analytics_replica` alias.
    # pytest-django creates a separate test DB per alias and blocks
    # cross-alias reads by default. Mark every data_explorer test so
    # pytest-django seeds both. In dev/test the two aliases point at
    # the same engine, so this is effectively a flag, not a real
    # multi-DB scenario.
    enable_replica = pytest.mark.django_db(databases=["default", "analytics_replica"])
    # Aggregate-query tests run against `AggregateQueryService.execute`
    # which composes ORM queries against the matview rows. SQLite's
    # shadow tables have the matview names but only a subset of the
    # columns the variables reference; the full matview schema lives
    # only on Postgres. Mark these tests `postgres` so they auto-skip
    # on SQLite (the marker handler is in `pytest_collection_modifyitems`
    # above) and run normally on Postgres CI.
    aggregate_run = pytest.mark.postgres
    aggregate_run_names = {
        "test_returns_rows_and_metadata",
        "test_emits_aggregate_executed_audit",
        "test_over_cap_returns_429_with_retry_after",
        "test_aggregate_executed",
        "test_overlap_burst_flag",
        # Integration corpus — runs all 25 corpus queries against the
        # matview row set; needs real Postgres + populated matviews
        # per ADR-0023 Appendix A.
        "test_full_return_queries",
        "test_partial_suppression_queries",
        "test_full_suppression_queries",
    }
    for item in items:
        nodeid = item.nodeid
        if "data_explorer" in nodeid:
            item.add_marker(enable_replica)
        if any(name in nodeid for name in aggregate_run_names):
            item.add_marker(aggregate_run)

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
