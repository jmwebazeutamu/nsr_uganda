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


@pytest.mark.django_db
class TestDsaListFilters:
    """Filters added with the DSA management workspace: free-text
    search across reference + partner code/name, multi-status, and
    expiring-within-N-days for renewal triage.
    """

    URL_DSAS = "/api/v1/dsas/"

    @pytest.fixture
    def seeded_dsas(self, db, settings, seeded_partners):
        from datetime import date, timedelta

        from apps.partners.models import DataSharingAgreement
        settings.PARTNERS_MODULE_ENABLED = True
        opm   = next(p for p in seeded_partners if p.code == "OPM")
        ubos  = next(p for p in seeded_partners if p.code == "UBOS")
        wfp   = next(p for p in seeded_partners if p.code == "WFP")
        today = date.today()
        return {
            "opm_active": DataSharingAgreement.objects.create(
                reference="DSA-OPM-2026-001", partner=opm, status="active",
                effective_from=today, effective_to=today + timedelta(days=200),
            ),
            "ubos_draft": DataSharingAgreement.objects.create(
                reference="DSA-UBOS-2026-DRAFT", partner=ubos, status="draft",
            ),
            "wfp_expiring": DataSharingAgreement.objects.create(
                reference="DSA-WFP-2026-EXPIRY", partner=wfp, status="active",
                effective_from=today, effective_to=today + timedelta(days=20),
            ),
        }

    def test_q_filter_matches_reference_substring(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?q=WFP")
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-WFP-2026-EXPIRY"}

    def test_q_filter_matches_partner_code(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?q=ubos")  # case-insensitive
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-UBOS-2026-DRAFT"}

    def test_q_filter_matches_partner_name_words(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?q=Food")  # World Food Programme
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-WFP-2026-EXPIRY"}

    def test_status_supports_comma_separated_list(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?status=draft,active")
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {
            "DSA-OPM-2026-001",
            "DSA-UBOS-2026-DRAFT",
            "DSA-WFP-2026-EXPIRY",
        }

    def test_expiring_within_days_returns_only_dsas_inside_window(
        self, api, seeded_dsas,
    ):
        r = api.get(f"{self.URL_DSAS}?expiring_within_days=30")
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-WFP-2026-EXPIRY"}

    def test_expiring_within_days_bad_value_returns_today_window(
        self, api, seeded_dsas,
    ):
        # Garbage value clamps to 0 — empty for these DSAs (none expire
        # today). Asserts no 500, and the filter still applies (i.e.
        # the active-but-far-out DSA is excluded).
        r = api.get(f"{self.URL_DSAS}?expiring_within_days=abc")
        assert r.status_code == 200
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == set()

    def test_status_all_is_a_no_op_not_a_literal_filter(
        self, api, seeded_dsas,
    ):
        # The DSA workspace passes `?status=all` (sometimes alongside
        # `q=`) to document intent. Treating "all" as a literal status
        # code would silently filter to zero rows since no DSA has
        # status="all" — that bug bit the version-history sidebar.
        r = api.get(f"{self.URL_DSAS}?status=all")
        refs = {d["reference"] for d in r.data["results"]}
        # All three seeded DSAs come back regardless of status.
        assert refs == {
            "DSA-OPM-2026-001",
            "DSA-UBOS-2026-DRAFT",
            "DSA-WFP-2026-EXPIRY",
        }
