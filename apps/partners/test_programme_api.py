"""Programme CRUD endpoint tests — US-S25-003."""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import DataSharingAgreement, Partner, Programme
from apps.partners.services.programme_scope import programme_geography_contract
from apps.reference_data.models import GeographicUnit
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
    def _dsa(self, partner, reference="DSA-TEST", *, units=()):
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference=reference, version=1, status="active",
            effective_from=date(2026, 1, 1), effective_to=date(2030, 12, 31),
            field_scope={}, entities_scope={}, sensitive_data_handling="none",
            retention_days=180, breach_sla_hours=72,
        )
        dsa.geographic_scope.set(units)
        return dsa

    def _unit(self, level, code, name, parent=None):
        return GeographicUnit.objects.create(
            level=level, code=code, name=name, parent=parent,
            effective_from=date(2026, 1, 1),
        )

    def test_limited_dsa_geography_is_inherited_and_persisted(self, api, partner):
        c, _ = api
        western = self._unit("region", "R-WESTERN", "Western")
        dsa = self._dsa(partner, units=[western])

        contract = c.get(f"/api/v1/dsas/{dsa.id}/programme-geography/")
        assert contract.status_code == 200
        assert contract.data["is_national"] is False
        assert contract.data["units"] == [{
            "id": str(western.id), "code": "R-WESTERN",
            "name": "Western", "level": "region",
        }]

        created = c.post(URL_LIST, {
            "partner": partner.id, "dsa": dsa.id, "name": "Western programme",
            "kind": "cash_transfer",
        }, format="json")
        assert created.status_code == 201, created.data
        programme = Programme.objects.get(id=created.data["id"])
        assert list(programme.geographic_units.values_list("code", flat=True)) == ["R-WESTERN"]

    def test_rejects_programme_geography_outside_dsa(self, api, partner):
        c, _ = api
        western = self._unit("region", "R-WESTERN", "Western")
        western_sub_region = self._unit("sub_region", "SR-WESTERN", "Western sub-region", western)
        central = self._unit("region", "R-CENTRAL", "Central")
        dsa = self._dsa(partner, units=[western])
        descendant = c.post(URL_LIST, {
            "partner": partner.id, "dsa": dsa.id, "name": "Western sub-region programme",
            "kind": "cash_transfer", "geographic_units": [western_sub_region.id],
        }, format="json")
        assert descendant.status_code == 201, descendant.data
        response = c.post(URL_LIST, {
            "partner": partner.id, "dsa": dsa.id, "name": "Outside scope",
            "kind": "cash_transfer", "geographic_units": [central.id],
        }, format="json")
        assert response.status_code == 400
        assert "outside DSA" in str(response.data["geographic_units"])
        assert "Western" in str(response.data["geographic_units"])

    def test_national_region_sub_region_and_district_contracts(self, api, partner):
        national = self._dsa(partner, "DSA-NATIONAL")
        region = self._unit("region", "R-WEST", "West")
        sub_region = self._unit("sub_region", "SR-WEST", "West sub-region", region)
        district = self._unit("district", "DST-WEST", "West district", sub_region)
        assert programme_geography_contract(national)["is_national"] is True
        assert programme_geography_contract(self._dsa(partner, "DSA-REGION", units=[region]))["units"][0]["level"] == "region"
        assert programme_geography_contract(self._dsa(partner, "DSA-SUBREGION", units=[sub_region]))["units"][0]["level"] == "sub_region"
        assert programme_geography_contract(self._dsa(partner, "DSA-DISTRICT", units=[district]))["units"][0]["level"] == "district"

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


# --- US-S11-039 — DELETE Programme (drafts only) --------------------------

@pytest.mark.django_db
class TestProgrammeDelete:
    """DELETE /api/v1/programmes/{id}/ — only allowed when status=draft.
    Active+ Programmes have enrolments + sign-offs that hard-delete
    would orphan, so they must use the /close/ lifecycle action."""

    def test_delete_draft_succeeds_with_audit(self, api, partner):
        c, _ = api
        prog = Programme.objects.create(
            partner=partner, code="DRAFT-1", name="Draft to bin",
            kind="cash_transfer", status="draft",
        )
        r = c.delete(f"{URL_LIST}{prog.id}/")
        assert r.status_code == 204
        assert not Programme.objects.filter(id=prog.id).exists()
        ev = AuditEvent.objects.filter(
            action="partners.programme.deleted", entity_id=str(prog.id),
        ).first()
        assert ev is not None
        assert ev.field_changes.get("code") == "DRAFT-1"

    def test_delete_non_draft_is_rejected(self, api, partner):
        c, _ = api
        prog = Programme.objects.create(
            partner=partner, code="LIVE-1", name="Live cohort",
            kind="cash_transfer", status="active",
        )
        r = c.delete(f"{URL_LIST}{prog.id}/")
        assert r.status_code == 400
        assert "status is 'active'" in r.json()["detail"]
        # Row survives.
        assert Programme.objects.filter(id=prog.id).exists()

    def test_delete_closed_is_rejected(self, api, partner):
        c, _ = api
        prog = Programme.objects.create(
            partner=partner, code="DONE-1", name="Closed cohort",
            kind="cash_transfer", status="closed",
        )
        r = c.delete(f"{URL_LIST}{prog.id}/")
        assert r.status_code == 400
        assert Programme.objects.filter(id=prog.id).exists()

    def test_delete_gated_by_write_flag(self, api, partner, settings):
        c, _ = api
        prog = Programme.objects.create(
            partner=partner, code="DRAFT-2", name="Draft",
            kind="cash_transfer", status="draft",
        )
        settings.PARTNERS_MODULE_ENABLED = False
        r = c.delete(f"{URL_LIST}{prog.id}/")
        assert r.status_code == 403
