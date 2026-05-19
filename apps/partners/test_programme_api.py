"""Programme CRUD endpoint tests — US-S25-003."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import Partner, Programme
from apps.reference_data.services import clear_resolver_cache
from apps.security.models import AuditEvent

URL_LIST = "/api/v1/programmes/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(settings, db):
    settings.PARTNERS_MODULE_ENABLED = True
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="prog-tester", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c, u


@pytest.fixture
def partner(db):
    return Partner.objects.create(
        code="MGLSD", name="MGLSD", type="ministry",
        sector="social_protection", status="active", tone="primary",
    )


@pytest.mark.django_db
class TestProgrammeCreate:
    def test_create_emits_audit_and_returns_cleartext_secret(self, api, partner):
        c, _ = api
        payload = {
            "partner": partner.id,
            "code": "MGLSD-DVA",
            "name": "Direct Income Support · vulnerable adolescents",
            "summary": "Monthly cash to adolescent-girl HHs in Karamoja",
            "kind": "cash_transfer",
            "status": "draft",
            "unit_of_enrolment": "household",
            "cohort_target": 18000,
            "sex_filter": "2",
            "age_min": 14,
            "age_max": 18,
            "pmt_bands": ["poorest_20", "poorest_40"],
            "composition_flags": ["female_headed"],
            "amount_ugx": 75000,
            "disbursement_cycle": "monthly",
            "duration_months": 24,
            "channel": "MTN MoMo · agent",
            "start_month": "Aug 2026",
            "exit_codes_allowed": ["10", "20", "30", "40", "50", "60", "70"],
            "auto_exit_triggers": ["age_out", "deceased", "pmt_shift"],
            "suspend_on_grievance": True,
            "webhook_url": "https://mglsd.go.ug/nsr/programmes/dva/webhook",
        }
        r = c.post(URL_LIST, payload, format="json")
        assert r.status_code == 201, r.data

        # Cleartext secret surfaced once
        assert "webhook_secret_cleartext" in r.data
        assert r.data["webhook_secret_cleartext"]
        secret = r.data["webhook_secret_cleartext"]

        # Hash persisted, cleartext not
        prog = Programme.objects.get(id=r.data["id"])
        assert prog.webhook_secret_hash
        assert prog.webhook_secret_hash != secret  # it's the hash
        assert len(prog.webhook_secret_hash) == 64  # sha256 hex

        # Labels resolved
        assert r.data["kind_label"] == "Cash transfer"
        assert r.data["unit_of_enrolment_label"] == "Household"
        assert r.data["sex_filter_label"] == "Female"
        assert r.data["disbursement_cycle_label"] == "Monthly"
        assert r.data["status_label"] == "Draft"

        # Audit event captured
        audits = AuditEvent.objects.filter(
            entity_type="programme", action="programme_created",
            entity_id=prog.id,
        )
        assert audits.count() == 1
        evt = audits.first()
        assert evt.field_changes["partner_code"] == "MGLSD"
        assert evt.field_changes["cohort_target"] == 18000

    def test_create_with_minimal_payload(self, api, partner):
        c, _ = api
        r = c.post(URL_LIST, {
            "partner": partner.id,
            "name": "Tiny pilot",
            "kind": "service",
        }, format="json")
        assert r.status_code == 201, r.data
        assert r.data["status"] == "draft"

    def test_unique_code_per_partner(self, api, partner):
        c, _ = api
        first = c.post(URL_LIST, {
            "partner": partner.id, "code": "X", "name": "A", "kind": "cash_transfer",
        }, format="json")
        assert first.status_code == 201, first.data
        dup = c.post(URL_LIST, {
            "partner": partner.id, "code": "X", "name": "B", "kind": "cash_transfer",
        }, format="json")
        assert dup.status_code == 400


@pytest.mark.django_db
class TestProgrammeList:
    def test_filter_by_partner(self, api, partner):
        c, _ = api
        other = Partner.objects.create(
            code="OPM", name="OPM", type="ministry", status="active",
        )
        Programme.objects.create(partner=partner, name="A", kind="cash_transfer")
        Programme.objects.create(partner=other, name="B", kind="service")
        r = c.get(URL_LIST, {"partner": partner.id})
        codes = [p["partner_code"] for p in r.data["results"]]
        assert set(codes) == {"MGLSD"}

    def test_partner_programmes_convenience_endpoint(self, api, partner):
        c, _ = api
        Programme.objects.create(partner=partner, name="A", kind="cash_transfer")
        r = c.get(f"/api/v1/partners/{partner.id}/programmes/")
        assert r.status_code == 200
        assert len(r.data["items"]) == 1
        assert r.data["items"][0]["partner_code"] == "MGLSD"


@pytest.mark.django_db
class TestProgrammePatch:
    def test_patch_updates_cohort(self, api, partner):
        c, _ = api
        prog = Programme.objects.create(
            partner=partner, name="A", kind="cash_transfer",
            cohort_target=1000,
        )
        r = c.patch(f"{URL_LIST}{prog.id}/", {"cohort_target": 2500}, format="json")
        assert r.status_code == 200
        prog.refresh_from_db()
        assert prog.cohort_target == 2500


@pytest.mark.django_db
class TestProgrammeWriteFlag:
    def test_write_gated(self, api, partner, settings):
        c, _ = api
        settings.PARTNERS_MODULE_ENABLED = False
        r = c.post(URL_LIST, {
            "partner": partner.id, "name": "X", "kind": "cash_transfer",
        }, format="json")
        assert r.status_code == 403

    def test_read_open(self, api, partner, settings):
        c, _ = api
        Programme.objects.create(partner=partner, name="A", kind="cash_transfer")
        settings.PARTNERS_MODULE_ENABLED = False
        r = c.get(URL_LIST)
        assert r.status_code == 200
