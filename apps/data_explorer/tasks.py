"""Celery tasks for DATA-EXP.

detect_overlap_burst — nightly sweep over AggregateQueryLog flagging
(actor, dataset) pairs with > BURST_THRESHOLD queries whose filter_
hash overlaps by >= OVERLAP_DIMS dimensions in the trailing 24h. Per
ADR-0023 D3 / R1 each flag fires:
  - an AuditEvent action='data_explorer.reidentification.suspected'
  - a DPO notification via apps.security.notifications.send_notification
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings

from apps.security.audit import emit as emit_audit
from apps.security.notifications import send_notification
from celery import shared_task

logger = logging.getLogger(__name__)


# Thresholds — kept here rather than in models so the build agent can
# tune them via env without a migration. ADR-0023 sets defaults: 50
# queries × 3 overlapping filter dimensions.
BURST_THRESHOLD = 50
OVERLAP_DIMS = 3


@shared_task(name="data_explorer.refresh_matviews")
def refresh_matviews():
    """Populate the ``mv_explorer_*`` matviews from the live registry.

    The matviews are created ``WITH NO DATA`` (migration 0010), so until
    this runs the aggregate endpoint has nothing to serve — and a never-
    refreshed Postgres matview raises OperationalError on any SELECT.
    The raw ``REFRESH`` SQL lives in ``apps.data_management.matviews``
    (the no-raw-SQL boundary); this task is just the schedule hook.
    """
    from apps.data_management.matviews import refresh_explorer_matviews

    refreshed = refresh_explorer_matviews(concurrently=True)
    logger.info("Refreshed %d Data Explorer matviews", len(refreshed))
    return {"refreshed": refreshed}


@shared_task(name="data_explorer.detect_overlap_burst")
def detect_overlap_burst():
    """Sweep the last 24h of AggregateQueryLog rows. Flag any actor
    with > BURST_THRESHOLD queries whose filter dimensions overlap by
    >= OVERLAP_DIMS with at least one previous query in the window.
    """
    # Lazy imports — the task module is imported at autodiscover time.
    from .models import AggregateQueryLog

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    rows = list(
        AggregateQueryLog.objects
        .filter(executed_at__gte=cutoff)
        .order_by("actor", "dataset_id", "executed_at")
        .values("actor", "dataset_id", "filter_variables",
                "geographic_scope", "filter_hash", "executed_at")
    )

    flagged = []
    bucket: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (r["actor"], r["dataset_id"])
        bucket.setdefault(key, []).append(r)

    for (actor, dataset_id), queries in bucket.items():
        if len(queries) <= BURST_THRESHOLD:
            continue
        # Cell-probing recycles a narrow filter (same filter_hash) across
        # many queries; that filter's dimension count is the length of its
        # filter_variables. ADR-0023: flag an actor with >BURST_THRESHOLD
        # queries that recycle a filter spanning >= OVERLAP_DIMS dimensions.
        # Legitimate wide-ranging exploration recycles no single filter, so
        # its dominant cluster stays size 1 and is not flagged.
        hash_groups: dict[str, list[dict]] = {}
        for q in queries:
            hash_groups.setdefault(q["filter_hash"], []).append(q)
        _dominant_hash, dominant = max(
            hash_groups.items(), key=lambda kv: len(kv[1]),
        )
        overlap_dimensions = max(
            (len(q.get("filter_variables") or []) for q in dominant),
            default=0,
        )
        if len(dominant) < 2 or overlap_dimensions < OVERLAP_DIMS:
            continue
        flagged.append({
            "actor": actor,
            "dataset_id": dataset_id,
            "query_count": len(queries),
            "overlap_dimensions": overlap_dimensions,
        })

    flagged_at = datetime.now(UTC).isoformat()
    for f in flagged:
        emit_audit(
            "data_explorer.reidentification.suspected",
            "User", f["actor"],
            actor=f["actor"], actor_kind="system",
            reason=(
                f"queries={f['query_count']} overlap_dimensions="
                f"{f['overlap_dimensions']} dataset={f['dataset_id']}"
            ),
            field_changes={
                "flagged_at": flagged_at,
                "overlap_dimensions": f["overlap_dimensions"],
                "query_count": f["query_count"],
                "dataset_id": f["dataset_id"],
            },
        )
        dpo_email = getattr(settings, "DPO_EMAIL", "") or ""
        if dpo_email:
            send_notification(
                to=dpo_email,
                subject=(
                    f"[NSR MIS] Data Explorer re-identification flag · "
                    f"{f['actor']}"
                ),
                body=(
                    f"Actor {f['actor']} ran {f['query_count']} aggregate "
                    f"queries against dataset {f['dataset_id']} in the "
                    f"last 24h recycling a filter spanning "
                    f"{f['overlap_dimensions']} dimensions. Review the "
                    f"AggregateQueryLog rows for this actor before deciding "
                    f"whether to throttle or revoke the EXPLORER role.\n"
                ),
                entity_type="User",
                entity_id=f["actor"],
                audit_actor="system",
                audit_action="data_explorer.reidentification.notified",
                audit_reason=(
                    f"queries={f['query_count']} "
                    f"overlap_dimensions={f['overlap_dimensions']}"
                ),
            )

    return {"flagged": flagged, "scanned": len(rows)}
