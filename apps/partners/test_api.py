"""API tests for the partners module — US-S23-008."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import Partner
from apps.reference_data.services import clear_resolver_cache

URL = "/api/v1/partners/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(
        username="partners-test", password="p",
    )
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def seeded_partners(db):
    rows = [
        ("OPM", "Office of the Prime Minister", "ministry",
         "social_protection", "active", "system"),
        ("UBOS", "Uganda Bureau of Statistics", "agency",
         "statistics", "active", "reference"),
        ("MoH", "Ministry of Health", "ministry",
         "health", "alert", "danger"),
        ("WFP", "World Food Programme", "multilateral",
         "humanitarian", "renewing", "update"),
        ("NIRA", "National Identification & Registration Authority",
         "agency", "identity", "provider", "identity"),
    ]
    return [
        Partner.objects.create(
            code=c, name=n, type=t, sector=s, status=st, tone=tn,
        )
        for c, n, t, s, st, tn in rows
    ]


@pytest.mark.django_db
class TestPartnerList:
    def test_list_returns_seeded_partners(self, api, seeded_partners):
        r = api.get(URL)
        assert r.status_code == 200
        codes = {p["code"] for p in r.data["results"]}
        assert codes == {"OPM", "UBOS", "MoH", "WFP", "NIRA"}

    def test_every_coded_field_carries_label(self, api, seeded_partners):
        r = api.get(URL)
        row = next(p for p in r.data["results"] if p["code"] == "OPM")
        assert row["type"] == "ministry"
        assert row["type_label"] == "Ministry"
        assert row["sector_label"] == "Social Protection"
        assert row["status_label"] == "Active"
        assert row["tone_label"] == "System"

    def test_q_filter(self, api, seeded_partners):
        r = api.get(URL, {"q": "health"})
        codes = [p["code"] for p in r.data["results"]]
        assert codes == ["MoH"]

    def test_type_filter(self, api, seeded_partners):
        r = api.get(URL, {"type": "multilateral"})
        codes = [p["code"] for p in r.data["results"]]
        assert codes == ["WFP"]

    def test_status_filter(self, api, seeded_partners):
        r = api.get(URL, {"status": "provider"})
        codes = [p["code"] for p in r.data["results"]]
        assert codes == ["NIRA"]


@pytest.mark.django_db
class TestPartnerRetrieve:
    def test_retrieve_by_id(self, api, seeded_partners):
        p = seeded_partners[0]
        r = api.get(f"{URL}{p.id}/")
        assert r.status_code == 200
        assert r.data["code"] == "OPM"
        assert r.data["type_label"] == "Ministry"


@pytest.mark.django_db
class TestPartnerWrite:
    def test_create_when_flag_enabled(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        r = api.post(URL, {
            "code": "BRAC", "name": "BRAC Uganda",
            "type": "ngo", "sector": "livelihoods",
            "status": "onboarding", "tone": "quality",
            "primary_email": "uganda@brac.net",
        }, format="json")
        assert r.status_code == 201, r.data
        assert r.data["code"] == "BRAC"
        assert r.data["type_label"] == "NGO"
        assert Partner.objects.filter(code="BRAC").exists()

    def test_create_forbidden_when_flag_disabled(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = False
        r = api.post(URL, {
            "code": "X", "name": "X", "type": "ngo",
            "status": "onboarding",
        }, format="json")
        assert r.status_code == 403
        assert "PARTNERS_MODULE_ENABLED" in str(r.data)

    def test_patch_updates_partner(self, api, settings, seeded_partners):
        settings.PARTNERS_MODULE_ENABLED = True
        p = next(x for x in seeded_partners if x.code == "OPM")
        r = api.patch(f"{URL}{p.id}/", {"note": "in-flight migration"},
                      format="json")
        assert r.status_code == 200
        assert r.data["note"] == "in-flight migration"
