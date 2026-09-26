"""Scheduled Admin Console operations."""

from __future__ import annotations

import logging

from celery import shared_task

from .snapshots import recompute_dashboard_snapshots

log = logging.getLogger(__name__)


@shared_task(name="apps.admin_console.tasks.recompute_dashboard_snapshots_task")
def recompute_dashboard_snapshots_task() -> dict:
    """Refresh every PMT dashboard projection in one authoritative run.

    ``recompute_dashboard_snapshots`` also recomputes empirical PMT band
    thresholds, so the dashboard's coverage, distribution, sub-region rates,
    and threshold sample all describe the same population.
    """
    run = recompute_dashboard_snapshots(actor="celery-beat")
    log.info(
        "pmt dashboard snapshot refresh %s: rows=%s sample=%s",
        run.status, run.rows_written, run.sample_size,
    )
    return {
        "run_id": str(run.id),
        "status": run.status,
        "rows_written": run.rows_written,
        "sample_size": run.sample_size,
    }
