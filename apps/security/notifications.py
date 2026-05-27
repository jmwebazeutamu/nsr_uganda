"""Workflow notification helper — single entry point for transactional
email across the registry. Wraps Django's send_mail with two cross-
cutting concerns every consumer needs:

  1. **Audit emission**. Every notification attempt writes an
     AuditEvent with action `notification.sent` or
     `notification.failed`, so the audit chain captures the
     side-effect alongside the workflow event that triggered it.

  2. **Fail-silently semantics**. SMTP outages must not roll back the
     workflow transaction. PMT sign-off, DSA signing, etc. should
     complete on the audit-bearing side regardless of whether the
     courtesy email lands. The notification failure is itself
     audited, so DPO can reconcile later.

Callers pass `audit_actor` so the AuditEvent attributes the
notification to the workflow actor (e.g. the signer, the operator
who clicked Approve) rather than a generic "system" id — that
matches how the surrounding workflow audit events are attributed.

`entity_type`/`entity_id` link the notification to the originating
record (PMTModelVersion, DataSharingAgreement, etc.) so it's
queryable from the entity's audit-history view without a second
lookup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.mail import send_mail

from apps.security.audit import emit as emit_audit

logger = logging.getLogger(__name__)


def _normalise_recipients(to: str | Iterable[str] | None) -> list[str]:
    if not to:
        return []
    if isinstance(to, str):
        addrs = [to]
    else:
        addrs = list(to)
    # Strip blanks, dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for addr in addrs:
        if not addr:
            continue
        clean = addr.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def send_notification(
    *,
    to: str | Iterable[str] | None,
    subject: str,
    body: str,
    html: str | None = None,
    entity_type: str,
    entity_id: str,
    audit_actor: str,
    audit_action: str = "notification.sent",
    audit_reason: str = "",
    from_email: str | None = None,
) -> dict:
    """Send a transactional workflow email + audit the attempt.

    Returns a dict with at minimum `sent: bool`, `recipients: list[str]`,
    and `error: str` (empty on success or when there were no
    recipients). Never raises — SMTP / network failures are logged and
    audited as `notification.failed`.

    `entity_type` / `entity_id` link the AuditEvent to the originating
    record so downstream queries (audit history for a PMT model, a
    DSA, etc.) surface the notification next to the workflow event
    that triggered it. `audit_action` defaults to "notification.sent"
    but workflow callers can pass a more specific code (e.g.
    "pmt.signoff.notified") when grouping helps reporting.
    """
    recipients = _normalise_recipients(to)
    if not recipients:
        # Missing recipient is itself a workflow signal — audit it so
        # we can find the gaps later (e.g. a Partner with no
        # primary_email when a DSA delivery fires).
        emit_audit(
            "notification.skipped", entity_type, entity_id,
            actor=audit_actor, actor_kind="system",
            reason=f"no recipients — {audit_reason}".strip(" —"),
            field_changes={"subject": subject},
        )
        return {"sent": False, "recipients": [], "error": "no recipients"}

    sender = from_email or getattr(
        settings, "DEFAULT_FROM_EMAIL", "nsr-mis@localhost",
    )
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=sender,
            recipient_list=recipients,
            html_message=html,
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 — never block the workflow
        logger.warning(
            "notification failed (%s/%s → %s): %s",
            entity_type, entity_id, recipients, exc,
        )
        emit_audit(
            "notification.failed", entity_type, entity_id,
            actor=audit_actor, actor_kind="system",
            reason=f"{type(exc).__name__}: {exc}"[:255],
            field_changes={
                "subject": subject,
                "recipients": recipients,
                "audit_reason": audit_reason,
            },
        )
        return {"sent": False, "recipients": recipients, "error": str(exc)}

    emit_audit(
        audit_action, entity_type, entity_id,
        actor=audit_actor, actor_kind="system",
        reason=audit_reason,
        field_changes={
            "subject": subject,
            "recipients": recipients,
        },
    )
    return {"sent": True, "recipients": recipients, "error": ""}
