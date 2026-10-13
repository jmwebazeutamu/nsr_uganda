"""Regression coverage for scheduled Admin Console operations."""

import pytest
from nsr_mis.celery import app


def test_pmt_dashboard_snapshot_task_is_scheduled_nightly():
    entry = app.conf.beat_schedule["recompute-pmt-dashboard-snapshots"]
    assert entry["task"] == (
        "apps.admin_console.tasks.recompute_dashboard_snapshots_task"
    )
    assert entry["schedule"].minute == {0}
    assert entry["schedule"].hour == {2}


@pytest.mark.django_db
def test_pmt_dashboard_snapshot_task_runs_full_projection(monkeypatch):
    from apps.admin_console import tasks

    observed = {}

    class Run:
        id = "run-1"
        status = "ok"
        rows_written = 7
        sample_size = 5

    def _recompute(*, actor):
        observed["actor"] = actor
        return Run()

    monkeypatch.setattr(tasks, "recompute_dashboard_snapshots", _recompute)

    assert tasks.recompute_dashboard_snapshots_task() == {
        "run_id": "run-1", "status": "ok", "rows_written": 7,
        "sample_size": 5,
    }
    assert observed["actor"] == "celery-beat"
