"""Celery tasks for UPD.

escalate_stale_change_requests_task — recurring sweep scheduled by
Celery beat (see nsr_mis/celery.py). Identical effect to the
`escalate_stale_change_requests` management command; both can coexist
so ops/runbooks can invoke one-off sweeps without touching beat.
"""

from __future__ import annotations

from celery import shared_task

from .services import escalate_stale_change_requests


@shared_task(name="apps.update_workflow.tasks.escalate_stale_change_requests_task")
def escalate_stale_change_requests_task() -> dict[str, int]:
    """Return the counts dict so monitoring can read operational
    metrics off the Celery result backend."""
    return escalate_stale_change_requests()
