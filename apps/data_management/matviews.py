"""Refresh + introspection for the Data Explorer materialised views.

Per CLAUDE.md raw SQL is allowed only inside ``data_management`` and
``ingestion_hub``. The ``mv_explorer_*`` matviews are created (``WITH NO
DATA``) by migration ``0010_data_explorer_matviews``; this module owns
the operational raw SQL that *populates* and *introspects* them. Callers
in ``apps.data_explorer`` (the Celery beat task and ``query_builder``)
import these helpers rather than issuing ``REFRESH`` / ``pg_matviews``
SQL themselves, so the no-raw-SQL boundary stays intact.

Why this matters: a freshly-migrated Postgres matview is ``WITH NO
DATA`` and raises ``OperationalError`` on *any* SELECT until its first
``REFRESH``. Without a refresh path the aggregate endpoint 500s in
production. :func:`refresh_explorer_matviews` is the path; the beat task
(``data_explorer.refresh_matviews``) calls it on a schedule.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import connection

# The full intended Data Explorer matview set (ADR-0023 D2). Mirrors the
# unmanaged models in apps.data_explorer.matview_models. NOTE: only the
# two household-grain matviews currently have Postgres DDL in migration
# 0010; the other six exist as models + SQLite shadow tables but their
# Postgres CREATE MATERIALIZED VIEW is unbuilt backlog scope. The refresh
# below is existence-aware so it covers whatever subset actually exists —
# the remaining six auto-join once their DDL lands.
EXPLORER_MATVIEWS: tuple[str, ...] = (
    "mv_explorer_household_by_subcounty_demographics",
    "mv_explorer_household_by_subcounty_pmt",
    "mv_explorer_member_by_subcounty_education",
    "mv_explorer_member_by_subcounty_employment",
    "mv_explorer_household_shocks_subregion",
    "mv_explorer_referrals_subcounty",
    "mv_explorer_grievances_subcounty",
    "mv_explorer_health_chronic_subregion",
)


def _existing_matviews(candidates: Iterable[str]) -> set[str]:
    """Subset of ``candidates`` that exist as matviews in this database."""
    if connection.vendor != "postgresql":
        return set()
    with connection.cursor() as cur:
        cur.execute(
            "SELECT matviewname FROM pg_matviews WHERE matviewname = ANY(%s)",
            [list(candidates)],
        )
        return {r[0] for r in cur.fetchall()}


def is_matview_populated(name: str) -> bool:
    """Return True if the named matview has been refreshed at least once.

    On Postgres an unrefreshed (``WITH NO DATA``) matview raises
    ``OperationalError`` on any SELECT, so callers must gate on this
    before querying the matview. On non-Postgres backends the matview is
    shadowed by a concrete table (always selectable), so we report True.

    An unknown name reports False (defensive: the caller maps that to a
    503 "data not ready", never a 500).
    """
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ispopulated FROM pg_matviews WHERE matviewname = %s",
            [name],
        )
        row = cur.fetchone()
    return bool(row and row[0])


def refresh_explorer_matviews(
    *,
    concurrently: bool = False,
    names: Iterable[str] | None = None,
) -> list[str]:
    """``REFRESH`` the Data Explorer matviews; return the names refreshed.

    ``concurrently=True`` uses ``REFRESH MATERIALIZED VIEW CONCURRENTLY``
    (no read lock, but requires an already-populated matview with a
    unique index and *cannot* run inside a transaction). The beat task
    uses it in production; the first-ever refresh — and the per-test
    fixture, which runs inside the test transaction — must use
    ``concurrently=False``. We downgrade to a plain refresh automatically
    for any matview that is not yet populated, so the first run is safe
    even when ``concurrently=True`` is requested.

    No-op on non-Postgres backends (the SQLite shadow tables need no
    refresh; queries hit them directly).
    """
    if connection.vendor != "postgresql":
        return []
    targets = list(names) if names is not None else list(EXPLORER_MATVIEWS)
    unknown = [n for n in targets if n not in EXPLORER_MATVIEWS]
    if unknown:
        raise ValueError(f"Not Data Explorer matviews: {unknown}")

    # Refresh only those that physically exist (see EXPLORER_MATVIEWS note).
    existing = _existing_matviews(targets)
    refreshed: list[str] = []
    with connection.cursor() as cur:
        for name in targets:
            if name not in existing:
                continue
            mode = "CONCURRENTLY " if concurrently and is_matview_populated(name) else ""
            # `name` is constrained to the EXPLORER_MATVIEWS allowlist
            # above, so the interpolation is not attacker-controlled.
            cur.execute(f"REFRESH MATERIALIZED VIEW {mode}{name}")  # nosec B608
            refreshed.append(name)
    return refreshed
