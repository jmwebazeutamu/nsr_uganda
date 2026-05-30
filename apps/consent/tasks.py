"""Celery tasks for Consent Management (US-CONSENT-07).

scan_withdrawal_sla_breaches — recurring sweep (Celery beat, schedule in
nsr_mis/celery.py) that finds OPEN/IN_DPO_REVIEW withdrawal tickets past
their 30-day SLA deadline and raises an alert. Mirrors
apps.data_requests.tasks.expire_data_requests_task (the sweep shape) and
apps.security.tasks (the durable-audit-row + no-op Slack/email pattern).

The durable signal is the `consent.withdrawal.sla_breached` AuditEvent; the
Slack/email notify is the wake-up and is no-op when SLACK_WEBHOOK_URL /
DPO_EMAIL are unset, so dev/CI never fire.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.security.audit import emit
from celery import shared_task

from .models import ConsentWithdrawalTicket, TicketState

logger = logging.getLogger(__name__)

# Tickets in these states are still the DPO's to action; past the deadline
# they are in breach.
_OPEN_STATES = (TicketState.OPEN, TicketState.IN_DPO_REVIEW,
                TicketState.CLARIFICATION_REQUESTED)


def _notify_breach(count: int, ticket_ids: list[str]) -> dict:
    out = {"slack_sent": False, "email_sent": False}
    webhook = getattr(settings, "SLACK_WEBHOOK_URL", "") or ""
    dpo_email = getattr(settings, "DPO_EMAIL", "") or ""
    head = (f":rotating_light: *consent withdrawal SLA breach* — {count} "
            f"ticket(s) past their 30-day deadline")
    if webhook:
        try:
            resp = requests.post(webhook, json={"text": head}, timeout=5)
            out["slack_sent"] = 200 <= getattr(resp, "status_code", 500) < 300
        except Exception as exc:  # noqa: BLE001 — fire-and-forget alerter
            logger.warning("consent SLA slack notify failed: %s", exc)
    if dpo_email:
        try:
            send_mail(
                "[NSR MIS] Consent withdrawal SLA breach",
                f"{count} withdrawal ticket(s) are past their 30-day SLA.\n"
                f"First ids: {', '.join(ticket_ids[:10])}\n"
                "See the DPO withdrawal queue.",
                getattr(settings, "DEFAULT_FROM_EMAIL", "nsr-mis@localhost"),
                [dpo_email], fail_silently=False)
            out["email_sent"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("consent SLA email notify failed: %s", exc)
    return out


@shared_task(name="apps.consent.tasks.scan_withdrawal_sla_breaches")
def scan_withdrawal_sla_breaches(actor: str = "celery-beat") -> dict:
    """Find withdrawal tickets past their SLA deadline and alert. Each newly
    breached ticket gets one `consent.withdrawal.sla_breached` AuditEvent and
    its `sla_breached_notified_at` stamped so it is not re-alerted."""
    now = timezone.now()
    breached = (
        ConsentWithdrawalTicket.objects
        .filter(state__in=_OPEN_STATES, sla_deadline__lt=now,
                sla_breached_notified_at__isnull=True)
        .order_by("sla_deadline")
    )
    ids: list[str] = []
    for ticket in breached:
        emit(
            action="consent.withdrawal.sla_breached",
            entity_type="consent.withdrawal_ticket",
            entity_id=ticket.id,
            actor=actor, actor_kind="system",
            reason=f"sla_deadline={ticket.sla_deadline.isoformat()}",
            field_changes={"member_id": ticket.member_id,
                           "purpose_code": ticket.purpose.code,
                           "state": ticket.state})
        ticket.sla_breached_notified_at = now
        ticket.save(update_fields=["sla_breached_notified_at", "updated_at"])
        ids.append(ticket.id)

    summary = {"breached": len(ids)}
    if ids:
        logger.error("consent withdrawal SLA: %s ticket(s) breached", len(ids))
        summary.update(_notify_breach(len(ids), ids))
    return summary
