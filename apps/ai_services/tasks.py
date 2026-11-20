"""Celery tasks for the AI pipeline (ADR-0045).

Both tasks are safe to schedule while a feature is off: they check the switch
first, do nothing and write nothing. Scoring never raises into Celery for a
switched-off feature, so a kill switch does not produce a failure alert.
"""

from __future__ import annotations

from django.conf import settings

from celery import shared_task

from .services import AiDisabledError

RANK_TASK = "apps.ai_services.tasks.rank_pending_pairs_task"
ANOMALY_TASK = "apps.ai_services.tasks.score_recent_households_task"
DISCOVERY_TASK = "apps.ddup.tasks.discover_pairs_task"


def _summary(run) -> dict:
    if run is None:
        return {"status": "nothing_new"}
    return {"status": "ok", "run_id": run.id, "state": run.state, "scored": run.scored,
            "skipped": run.skipped}


@shared_task(name=RANK_TASK)
def rank_pending_pairs_task() -> dict:
    from .ddup_ranking import rank_pending_pairs

    try:
        return _summary(rank_pending_pairs(actor="ai-pipeline"))
    except AiDisabledError:
        return {"status": "off"}


@shared_task(name=ANOMALY_TASK)
def score_recent_households_task(limit: int | None = None) -> dict:
    from .dqa_anomaly import score_recent_households

    try:
        return _summary(score_recent_households(
            limit=limit or settings.AI_ANOMALY_BATCH_SIZE, actor="ai-pipeline",
        ))
    except AiDisabledError:
        return {"status": "off"}


def rank_after_discovery(sender=None, **_kwargs):
    """Celery `task_success` handler: rank right after nightly discovery.

    Chained by signal rather than a fixed beat slot so it never runs before
    discovery has finished, and so DDUP does not import ai_services.
    """
    if getattr(sender, "name", None) == DISCOVERY_TASK:
        rank_pending_pairs_task.delay()
