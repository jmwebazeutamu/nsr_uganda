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

US-S18-004 adds out-of-band notification: Slack webhook + email
fallback when a break is detected. Both channels default to no-op
when their settings (SLACK_WEBHOOK_URL, DPO_EMAIL) are unset so
dev/CI never accidentally fires; notify failures are swallowed so
the audit row remains the source of truth even if the webhook is
down.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

from celery import shared_task

from .audit import emit
from .integrity import ChainReport, verify_audit_chain

logger = logging.getLogger(__name__)


def _slack_payload(report: ChainReport) -> dict:
    """Compose the Slack blocks payload for a chain break alert.

    Kept small on purpose: surface count + first event id, leave
    full details on the AuditEvent. Anything richer creates a
    second source of truth.
    """
    first = report.breaks[0] if report.breaks else None
    head = (
        f":rotating_light: *chain_integrity_break* — "
        f"{len(report.breaks)} break(s) detected in audit chain "
        f"({report.rows_scanned} rows scanned)"
    )
    body = ""
    if first:
        body = (
            f"first event_id: `{first.event_id}` "
            f"at {first.occurred_at}"
        )
    return {
        "text": head,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": head}},
            *([
                {"type": "section",
                 "text": {"type": "mrkdwn", "text": body}},
            ] if body else []),
            {"type": "context",
             "elements": [
                 {"type": "mrkdwn",
                  "text": "See AuditEvent `chain_integrity_break` for the durable record."},
             ]},
        ],
    }


def _email_body(report: ChainReport) -> str:
    lines = [
        f"chain_integrity_break detected: {len(report.breaks)} break(s).",
        f"rows scanned: {report.rows_scanned}",
        f"mode: {report.mode}",
        "",
        "First five break event ids:",
    ]
    for b in report.breaks[:5]:
        lines.append(f"  - {b.event_id}  ({b.occurred_at})")
    lines += [
        "",
        "The full record is on AuditEvent action='chain_integrity_break'.",
        "Do not delete or amend AuditEvent rows — they are append-only.",
    ]
    return "\n".join(lines)


def _notify_chain_break(report: ChainReport) -> dict:
    """Send Slack + email notifications for a chain-break report.

    Both channels are independently no-op when their respective
    setting is empty. Network / SMTP failures are caught and logged
    so the celery task can still write its audit row + return
    cleanly. Returns a small status dict for the task summary +
    tests.
    """
    out = {"slack_sent": False, "email_sent": False}
    webhook = getattr(settings, "SLACK_WEBHOOK_URL", "") or ""
    dpo_email = getattr(settings, "DPO_EMAIL", "") or ""

    if webhook:
        try:
            resp = requests.post(webhook, json=_slack_payload(report), timeout=5)
            if 200 <= getattr(resp, "status_code", 500) < 300:
                out["slack_sent"] = True
            else:
                logger.warning(
                    "chain-break slack notify returned %s",
                    getattr(resp, "status_code", "?"),
                )
        except Exception as exc:
            # Webhook is fire-and-forget — never let the task crash
            # because of a flaky alerter.
            logger.warning("chain-break slack notify failed: %s", exc)
    else:
        logger.info("chain-break slack notify skipped — no SLACK_WEBHOOK_URL")

    if dpo_email:
        try:
            send_mail(
                "[NSR MIS] AUDIT CHAIN BREAK DETECTED",
                _email_body(report),
                getattr(settings, "DEFAULT_FROM_EMAIL", "nsr-mis@localhost"),
                [dpo_email],
                fail_silently=False,
            )
            out["email_sent"] = True
        except Exception as exc:
            logger.warning("chain-break email notify failed: %s", exc)
    else:
        logger.info("chain-break email notify skipped — no DPO_EMAIL")

    return out


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
        # Dev backend (SQLite) — don't emit a noisy audit row or
        # fire alerts; just log so a local dev sees it.
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
        # US-S18-004 — fire out-of-band notification. The audit row
        # above is the durable signal; this is the wake-up.
        notify_status = _notify_chain_break(report)
        summary.update(notify_status)

    return summary
