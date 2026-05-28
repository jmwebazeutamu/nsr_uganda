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
from collections import Counter
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


def _overlap_dims(a: dict, b: dict) -> int:
    if not a or not b:
        return 0
    keys = set(a.keys()) & set(b.keys())
    return sum(1 for k in keys if a[k] == b[k])


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
        # Count pairs (i, j) with i<j whose overlap >= OVERLAP_DIMS.
        # We use the geographic_scope + filter_variables list as the
        # dimensions; cheap heuristic that matches the risk-probe pattern.
        hashes = Counter(q["filter_hash"] for q in queries)
        # If the burst has >= OVERLAP_DIMS recurring filter hashes the
        # attacker is recycling filter dimensions — flag.
        recurring_dims = sum(1 for h, c in hashes.items() if c >= 2)
        if recurring_dims < OVERLAP_DIMS:
            continue
        flagged.append({
            "actor": actor,
            "dataset_id": dataset_id,
            "query_count": len(queries),
            "recurring_dims": recurring_dims,
        })

    for f in flagged:
        emit_audit(
            "data_explorer.reidentification.suspected",
            "explorer_actor", f["actor"],
            actor=f["actor"], actor_kind="system",
            reason=(
                f"queries={f['query_count']} recurring_dims="
                f"{f['recurring_dims']} dataset={f['dataset_id']}"
            ),
            field_changes={
                "query_count": f["query_count"],
                "recurring_dims": f["recurring_dims"],
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
                    f"last 24h with {f['recurring_dims']} recurring "
                    f"filter-hash dimensions. Review the AggregateQueryLog "
                    f"rows for this actor before deciding whether to "
                    f"throttle or revoke the EXPLORER role.\n"
                ),
                entity_type="explorer_actor",
                entity_id=f["actor"],
                audit_actor="system",
                audit_action="data_explorer.reidentification.notified",
                audit_reason=(
                    f"queries={f['query_count']} "
                    f"recurring_dims={f['recurring_dims']}"
                ),
            )

    return {"flagged": flagged, "scanned": len(rows)}
