"""Celery tasks for the DIH pipeline (US-S12-004).

`process_pending_kobo_landings_task` mirrors the manual
`process_pending_landings_action` admin action: walks every Kobo
SourceSystem, drives RawLandings without a StageRecord through the
canonicalize → stage → DQA/IDV/DDUP pipeline, and runs the geo
backfill so the next promotion attempt finds the new GeographicUnit
rows. Scheduled on the beat in nsr_mis/celery.py.

The eager-mode tests in apps/ingestion_hub/test_connection_test.py
cover the admin-action body; this module shares the same
_process_one_landing helper so behaviour is identical to manual
invocation.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="apps.ingestion_hub.tasks.process_pending_kobo_landings_task")
def process_pending_kobo_landings_task(self) -> dict:
    """Process every Kobo RawLanding that doesn't have a StageRecord.

    Returns a per-source breakdown so an operator inspecting
    `celery -A nsr_mis events` (or the Django admin's ConnectorRun
    list) can see what happened on the last beat tick. Errors per
    landing are caught by `_process_one_landing` and counted; the
    task itself succeeds unless something catastrophic happens
    (e.g., a SourceSystem disappears mid-run).
    """
    from .admin_credentials import _process_one_landing
    from .connection_test import CredentialMissingError, credentials_for
    from .connectors.base import get_connector
    from .geo_backfill import backfill_missing_geo_from_stages
    from .models import RawLanding, SourceSystem, SourceSystemKind, StageRecord

    actor = "celery-beat"
    summary: dict[str, dict] = {}
    for source in SourceSystem.objects.filter(
        kind=SourceSystemKind.KOBO, is_active=True,
    ):
        connector_impl = get_connector(source.code)
        if connector_impl is None or connector_impl.canonicalize is None:
            summary[source.code] = {"skipped": "no connector"}
            continue
        try:
            credentials_for(source)
        except CredentialMissingError:
            summary[source.code] = {"skipped": "no credential"}
            continue

        pending = RawLanding.objects.filter(
            connector_run__connector__source_system=source,
            stage_record__isnull=True,
        )
        if not pending.exists():
            summary[source.code] = {"pending": 0}
            continue

        outcomes = {"staged": 0, "quarantined": 0, "error": 0}
        new_stage_ids: list[str] = []
        for landing in pending:
            outcome, _detail = _process_one_landing(
                landing, connector_impl, actor=actor,
            )
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome == "staged":
                landing.refresh_from_db()
                if hasattr(landing, "stage_record") and landing.stage_record:
                    new_stage_ids.append(landing.stage_record.id)

        backfill_total = 0
        if new_stage_ids:
            geo_result = backfill_missing_geo_from_stages(
                StageRecord.objects.filter(id__in=new_stage_ids),
            )
            backfill_total = geo_result.total_created

        summary[source.code] = {
            **outcomes,
            "geo_backfill": backfill_total,
        }
        logger.info(
            "process_pending_kobo_landings_task source=%s outcomes=%s geo_backfill=%s",
            source.code, outcomes, backfill_total,
        )

    return summary
