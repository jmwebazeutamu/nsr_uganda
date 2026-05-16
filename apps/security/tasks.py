"""Celery tasks for SEC — audit-chain integrity sweep (US-S16-004).

The scheduled task lives here so a `celery -A nsr_mis worker --beat`
process picks it up via apps.security autodiscovery. The schedule
itself is in nsr_mis/celery.py per the project pattern (single grep
answers "what's scheduled?").

On detected chain breaks the task ALSO writes a
`chain_integrity_break` AuditEvent so the DPO anomaly feed surfaces
it without polling a separate channel. The task ITSELF cannot be
the only output — if the celery process is compromised, the task
output is too; the audit row is the durable signal.
"""

from __future__ import annotations

import logging

from celery import shared_task

from .audit import emit
from .integrity import verify_audit_chain

logger = logging.getLogger(__name__)


@shared_task(name="apps.security.tasks.verify_audit_chain_task")
def verify_audit_chain_task() -> dict:
    """Walk the audit chain, log + audit the result, return a summary.

    Returns a dict (Celery-serialisable) for telemetry; the durable
    record is the AuditEvent written via emit().
    """
    report = verify_audit_chain()
    summary = {
        "ok": report.ok,
        "mode": report.mode,
        "rows_scanned": report.rows_scanned,
        "break_count": len(report.breaks),
    }

    if report.mode == "no_chain":
        # Dev backend (SQLite) — don't emit a noisy audit row; just
        # log so an operator running locally sees it.
        logger.info("audit chain verify: no_chain (sqlite or trigger missing)")
        return summary

    # Production path: write a structured AuditEvent so the DPO
    # has a tamper-resistant record of every sweep + result.
    action = "chain_integrity_verified" if report.ok else "chain_integrity_break"
    reason = (
        f"mode={report.mode} rows_scanned={report.rows_scanned} "
        f"break_count={len(report.breaks)}"
    )
    emit(
        action=action,
        entity_type="audit_chain",
        entity_id="security_auditevent",
        actor="celery-beat",
        actor_kind="system",
        reason=reason,
        # field_changes captures up to 5 break details so the DPO
        # has actionable context without re-running the sweep.
        # Full list is in the celery task return value for the
        # operator runbook to grab if more detail is needed.
        field_changes=(
            None if report.ok else {
                "breaks_preview": [
                    {
                        "event_id": b.event_id,
                        "occurred_at": b.occurred_at,
                    }
                    for b in report.breaks[:5]
                ],
            }
        ),
    )

    if not report.ok:
        logger.error(
            "audit chain verify: %s break(s) detected — see AuditEvent "
            "chain_integrity_break for details", len(report.breaks),
        )

    return summary
