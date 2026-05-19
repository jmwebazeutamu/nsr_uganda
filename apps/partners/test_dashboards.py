"""Dashboard aggregation tests — US-S23-009."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import (
    DataSharingAgreement,
    Partner,
    PartnerUsageDaily,
)
from apps.reference_data.services import clear_resolver_cache


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="dash-test", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def seeded(db):
    """Three partners (active / alert-with-breach / provider) +
    DSAs + usage rows in the trailing 30 days."""
    today = date.today()
    opm = Partner.objects.create(
        code="OPM", name="OPM", type="ministry", sector="social_protection",
        status="active", tone="system",
    )
    moh = Partner.objects.create(
        code="MoH", name="MoH", type="ministry", sector="health",
        status="alert", tone="danger",
    )
    nira = Partner.objects.create(
        code="NIRA", name="NIRA", type="agency", sector="identity",
        status="provider", tone="identity",
    )

    DataSharingAgreement.objects.create(
        reference="DSA-OPM-2026-001", partner=opm,
        status="active", monthly_row_budget=2_500_000,
        effective_to=today + timedelta(days=100),  # in renewal window
    )
    DataSharingAgreement.objects.create(
        reference="DSA-MoH-2026-001", partner=moh,
        status="active", monthly_row_budget=300_000,
        effective_to=today + timedelta(days=10),  # expiring soon
    )
    DataSharingAgreement.objects.create(
        reference="DSA-NIRA-2026-001", partner=nira,
        status="active", monthly_row_budget=None,  # provider — no cap
    )

    # OPM under budget (1.8M of 2.5M); MoH over budget (370k of 300k).
    PartnerUsageDaily.objects.create(
        partner=opm, day=today, rows_delivered=1_800_000, requests_count=10,
    )
    PartnerUsageDaily.objects.create(
        partner=moh, day=today, rows_delivered=370_000, requests_count=4,
    )

    return {"opm": opm, "moh": moh, "nira": nira}


@pytest.mark.django_db
class TestSummary:
    URL = "/api/v1/partners/summary/"

    def test_kpi_counts(self, api, seeded):
        r = api.get(self.URL)
        assert r.status_code == 200
        assert r.data["active_partners"] == 2  # OPM + MoH (NIRA is provider)
        assert r.data["active_dsas"] == 3
        assert r.data["dsas_expiring_30d"] == 1  # MoH effective_to in 10d
        assert r.data["rows_delivered_30d"] == 1_800_000 + 370_000
        assert r.data["active_requesters_30d"] == 2
        assert r.data["dsas_over_budget_30d"] == 1  # MoH

    def test_provider_partners_excluded_from_breach_count(self, api, seeded):
        # NIRA's null budget means it never counts as over-budget.
        r = api.get(self.URL)
        assert r.data["dsas_over_budget_30d"] == 1


@pytest.mark.django_db
class TestRenewals:
    URL = "/api/v1/partners/renewals/"

    def test_default_window_120d(self, api, seeded):
        r = api.get(self.URL)
        assert r.status_code == 200
        codes = [item["partner_code"] for item in r.data["items"]]
        assert codes == ["MoH", "OPM"]  # ordered by effective_to ascending

    def test_narrower_window(self, api, seeded):
        r = api.get(self.URL, {"days": 30})
        codes = [item["partner_code"] for item in r.data["items"]]
        assert codes == ["MoH"]


@pytest.mark.django_db
class TestSectorMix:
    URL = "/api/v1/partners/sector-mix/"

    def test_returns_one_row_per_sector(self, api, seeded):
        r = api.get(self.URL)
        assert r.status_code == 200
        sectors = {item["sector_code"] for item in r.data["items"]}
        assert sectors == {"social_protection", "health", "identity"}

    def test_carries_partner_count_and_rows(self, api, seeded):
        r = api.get(self.URL)
        by_code = {item["sector_code"]: item for item in r.data["items"]}
        assert by_code["social_protection"]["partner_count"] == 1
        assert by_code["social_protection"]["rows_delivered_30d"] == 1_800_000
        assert by_code["identity"]["rows_delivered_30d"] == 0  # NIRA, no usage


@pytest.mark.django_db
class TestTopConsumers:
    URL = "/api/v1/partners/top-consumers/"

    def test_orders_by_rows_descending(self, api, seeded):
        r = api.get(self.URL)
        assert r.status_code == 200
        codes = [item["partner_code"] for item in r.data["items"]]
        assert codes[:2] == ["OPM", "MoH"]

    def test_n_param_limits_results(self, api, seeded):
        r = api.get(self.URL, {"n": "1"})
        assert len(r.data["items"]) == 1
        assert r.data["items"][0]["partner_code"] == "OPM"
