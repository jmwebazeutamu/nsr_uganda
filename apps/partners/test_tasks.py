"""Celery-task tests for the partners module — US-S23-017."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.partners.models import (
    DataSharingAgreement,
    Partner,
    PartnerUsageDaily,
)
from apps.partners.tasks import (
    detect_dsa_budget_breaches,
    rollup_partner_usage_daily,
)
from apps.security.models import AuditEvent


@pytest.mark.django_db
class TestBreachDetector:
    def _make(self, code, *, status, budget, rows_30d):
        p = Partner.objects.create(
            code=code, name=code, type="ministry",
            status=status, tone="neutral",
        )
        if budget is not None:
            DataSharingAgreement.objects.create(
                reference=f"DSA-{code}-2026-001",
                partner=p, status="active",
                monthly_row_budget=budget,
            )
        today = date.today()
        PartnerUsageDaily.objects.create(
            partner=p, day=today,
            rows_delivered=rows_30d, requests_count=1,
        )
        return p

    def test_partner_over_budget_flips_to_alert_and_emits(self):
        p = self._make("MoH", status="active", budget=300_000, rows_30d=370_000)
        out = detect_dsa_budget_breaches()
        assert out["breached"] == ["MoH"]
        p.refresh_from_db()
        assert p.status == "alert"
        evts = AuditEvent.objects.filter(
            entity_type="partner", entity_id=p.id, action="breach_detected",
        )
        assert evts.count() == 1

    def test_partner_under_budget_untouched(self):
        p = self._make("OPM", status="active", budget=2_500_000, rows_30d=1_800_000)
        out = detect_dsa_budget_breaches()
        assert out["breached"] == []
        p.refresh_from_db()
        assert p.status == "active"

    def test_provider_partner_skipped(self):
        p = self._make("NIRA", status="provider", budget=None, rows_30d=1_000_000)
        out = detect_dsa_budget_breaches()
        assert "NIRA" not in out["breached"]
        p.refresh_from_db()
        assert p.status == "provider"

    def test_idempotent_when_already_alerted(self):
        p = self._make("MoH", status="active", budget=300_000, rows_30d=370_000)
        detect_dsa_budget_breaches()
        p.refresh_from_db()
        assert p.status == "alert"
        # Run again — already alerted, status stays, but emits a fresh
        # event each run so the activity feed reflects continuous breach.
        before = AuditEvent.objects.filter(
            entity_type="partner", entity_id=p.id, action="breach_detected",
        ).count()
        detect_dsa_budget_breaches()
        after = AuditEvent.objects.filter(
            entity_type="partner", entity_id=p.id, action="breach_detected",
        ).count()
        assert after == before + 1


@pytest.mark.django_db
class TestRollup:
    def test_skips_provider_partners(self):
        provider = Partner.objects.create(
            code="NIRA", name="NIRA", type="agency", status="provider",
        )
        AuditEvent.objects.create(
            actor_id="drs", action="data_request_delivered",
            entity_type="data_request", entity_id="r1",
            reason="NIRA · 1000 rows",
        )
        # Backdate to yesterday so the rollup picks it up.
        AuditEvent.objects.filter(actor_id="drs").update(
            occurred_at=date.today() - timedelta(days=1),
        )
        out = rollup_partner_usage_daily(target_day=date.today() - timedelta(days=1))
        # Provider was skipped → no PartnerUsageDaily row produced.
        assert PartnerUsageDaily.objects.filter(partner=provider).count() == 0
        assert out["partners_written"] == 0

    def test_writes_one_row_per_partner_per_day(self):
        p = Partner.objects.create(
            code="OPM", name="OPM", type="ministry", status="active",
        )
        yesterday = date.today() - timedelta(days=1)
        for _ in range(3):
            ev = AuditEvent.objects.create(
                actor_id="drs", action="data_request_delivered",
                entity_type="data_request", entity_id="r",
                reason="OPM · 1000 rows",
            )
            AuditEvent.objects.filter(pk=ev.pk).update(occurred_at=yesterday)
        out = rollup_partner_usage_daily(target_day=yesterday)
        # Three deliveries → three requests; row count is 0 today
        # (row-count parsing is a follow-up).
        row = PartnerUsageDaily.objects.get(partner=p, day=yesterday)
        assert row.requests_count == 3
        assert out["partners_written"] == 1
