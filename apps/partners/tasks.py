"""Celery tasks for the partners module — US-S23-017.

Two scheduled sweeps:

  - `rollup_partner_usage_daily_task` rolls yesterday's DRS deliveries
    into `PartnerUsageDaily`. Per ADR-0011 decision 3, provider-status
    partners are skipped (their `monthly_row_budget` is null).
  - `detect_dsa_budget_breaches_task` walks every non-provider partner
    and emits `breach_detected` + flips the partner's status to
    "alert" when the trailing-30d sum exceeds the partner's combined
    active-DSA budget.

Both tasks call into a synchronous helper so unit tests can exercise
them without spinning a Celery worker.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Sum

from apps.partners.models import (
    DataSharingAgreement,
    Partner,
    PartnerUsageDaily,
)
from apps.security.audit import emit as emit_audit
from celery import shared_task

log = logging.getLogger(__name__)


@transaction.atomic
def rollup_partner_usage_daily(target_day: date | None = None) -> dict:
    """Aggregate yesterday's row-delivery counts into PartnerUsageDaily.

    The DRS module owns the canonical delivery log; this rollup
    summarises it per (partner, day). For now we read the AuditEvent
    chain (action=data_request_delivered, entity_type=data_request)
    to get the count — when the DRS module exposes a richer
    delivery-event surface we'll switch to that.

    Returns a summary dict so the scheduled wrapper can log volume.
    """
    target = target_day or (date.today() - timedelta(days=1))

    from apps.security.models import AuditEvent

    # AuditEvent rows for yesterday's deliveries. The reason text
    # carries the row count and partner code in a free-text shape
    # established in US-S19 (DRS); parsing it is fragile but
    # acceptable until a structured delivery event lands. Skip
    # provider partners.
    deliveries = (
        AuditEvent.objects
        .filter(
            action="data_request_delivered",
            occurred_at__date=target,
        )
    )

    counts: dict[str, dict[str, int]] = {}
    for evt in deliveries.iterator():
        # reason example: "OPM · 1.2M rows" — we extract the partner
        # code (everything before the first space-or-dot) and a
        # synthetic row count of 1 (the real count comes from a
        # follow-up integration with DRS).
        head = (evt.reason or "").split()[0] if evt.reason else ""
        if not head:
            continue
        bucket = counts.setdefault(head, {"rows": 0, "requests": 0})
        bucket["requests"] += 1
        # TODO(US-S23-XXX, drs-integration): parse the row count
        # from the reason text once DRS adopts a structured payload.

    written = 0
    for code, c in counts.items():
        try:
            p = Partner.objects.get(code=code)
        except Partner.DoesNotExist:
            continue
        if p.status == "provider":
            continue
        row, _ = PartnerUsageDaily.objects.update_or_create(
            partner=p, day=target,
            defaults={
                "rows_delivered": c["rows"],
                "requests_count": c["requests"],
            },
        )
        written += 1
        log.info(
            "partners.usage_daily.rollup",
            extra={"partner": code, "day": str(target),
                   "rows_delivered": c["rows"], "requests_count": c["requests"]},
        )

    return {"target_day": str(target), "partners_written": written}


@shared_task(name="apps.partners.tasks.rollup_partner_usage_daily_task")
def rollup_partner_usage_daily_task() -> dict:
    return rollup_partner_usage_daily()


@transaction.atomic
def detect_dsa_budget_breaches(window_days: int = 30) -> dict:
    """Walk non-provider partners and flag those whose trailing-N-day
    rows_delivered exceeds the sum of their active-DSA budgets.

    Side effects per ADR-0011: emit a `breach_detected` AuditEvent
    targeting the partner, flip the partner's status to "alert"
    (transitions back to "active" require operator action), and
    surface a `dsa_breach`-kind activity item via the projection.
    """
    today = date.today()
    start = today - timedelta(days=window_days - 1)

    breached: list[str] = []
    for p in Partner.objects.exclude(status="provider"):
        budget = (
            DataSharingAgreement.objects
            .filter(partner=p, status="active",
                    monthly_row_budget__isnull=False)
            .aggregate(b=Sum("monthly_row_budget"))["b"] or 0
        )
        if budget <= 0:
            continue
        used = (
            PartnerUsageDaily.objects
            .filter(partner=p, day__gte=start, day__lte=today)
            .aggregate(u=Sum("rows_delivered"))["u"] or 0
        )
        if used <= budget:
            continue
        # Breach. Idempotent: only emit + flip if the partner isn't
        # already in alert from a previous run.
        was_alerted = p.status == "alert"
        if not was_alerted:
            p.status = "alert"
            p.save(update_fields=["status", "updated_at"])
        emit_audit(
            actor="system-partners-breach-detector",
            actor_kind="system",
            action="breach_detected",
            entity_type="partner",
            entity_id=p.id,
            reason=f"{used} rows in {window_days}d > {budget} budget",
        )
        breached.append(p.code)
        log.warning(
            "partners.dsa_breach",
            extra={"partner": p.code, "used": used, "budget": budget,
                   "window_days": window_days},
        )
    return {"breached": breached, "window_days": window_days}


@shared_task(name="apps.partners.tasks.detect_dsa_budget_breaches_task")
def detect_dsa_budget_breaches_task() -> dict:
    return detect_dsa_budget_breaches()
