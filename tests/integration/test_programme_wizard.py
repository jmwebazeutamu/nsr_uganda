"""End-to-end programme registration test — US-S25-005.

Walks the same payload shape the JSX wizard submits:
1. Create a partner + active DSA with a geographic_scope cap.
2. POST /api/v1/programmes/ with a full wizard payload.
3. Confirm the Programme row carries all coded fields, M2M geo,
   webhook hash (and only the hash), and a programme_created
   AuditEvent.
4. Confirm the canonical label fields resolve through the
   ChoiceList catalogue seeded in US-S25-001.
"""

from __future__ import annotations

from datetime import date

import pytest
from apps.partners.models import DataSharingAgreement, Partner, Programme
from apps.reference_data.models import GeographicUnit
from apps.reference_data.services import clear_resolver_cache
from apps.security.models import AuditEvent  # noqa: I001 — module ordering matches sibling tests
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(settings, db):
    settings.PARTNERS_MODULE_ENABLED = True
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="wiz", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def partner_with_dsa(db):
    p = Partner.objects.create(
        code="MGLSD", name="MGLSD", type="ministry",
        sector="social_protection", status="active", tone="primary",
    )
    karamoja, _ = GeographicUnit.objects.get_or_create(
        level="sub_region", code="SR-KARAMOJA",
        defaults={
            "name": "Karamoja", "status": "active",
            "effective_from": date(2024, 1, 1),
        },
    )
    west_nile, _ = GeographicUnit.objects.get_or_create(
        level="sub_region", code="SR-WEST-NILE",
        defaults={
            "name": "West Nile", "status": "active",
            "effective_from": date(2024, 1, 1),
        },
    )
    dsa = DataSharingAgreement.objects.create(
        reference="DSA-MGLSD-PDM-2026-001", partner=p, status="active",
        monthly_row_budget=500_000,
        entities_scope={"household": True},
        field_scope={"household": True, "member": True},
    )
    dsa.geographic_scope.set([karamoja, west_nile])
    return p, dsa, [karamoja, west_nile]


@pytest.mark.django_db
def test_programme_wizard_end_to_end(api, partner_with_dsa):
    partner, dsa, geo_units = partner_with_dsa

    payload = {
        "partner":            partner.id,
        "code":               "MGLSD-DVA",
        "name":               "Direct Income Support · vulnerable adolescents",
        "summary":            "Monthly cash to female-headed HHs in Karamoja",
        "kind":               "cash_transfer",
        "status":             "draft",
        "dsa":                dsa.id,
        "unit_of_enrolment":  "household",
        "cohort_target":      18000,
        "sex_filter":         "2",
        "age_min":            14,
        "age_max":            18,
        "pmt_bands":          ["poorest_20", "poorest_40"],
        "composition_flags":  ["female_headed"],
        "amount_ugx":         75000,
        "disbursement_cycle": "monthly",
        "duration_months":    24,
        "channel":            "MTN MoMo · agent",
        "start_month":        "Aug 2026",
        "geographic_units":   [g.id for g in geo_units],
        "exit_codes_allowed": ["10", "20", "30", "40", "50", "60", "70"],
        "auto_exit_triggers": ["age_out", "deceased", "pmt_shift"],
        "suspend_on_grievance": True,
        "webhook_url":        "https://mglsd.go.ug/nsr/programmes/dva/webhook",
    }
    r = api.post("/api/v1/programmes/", payload, format="json")
    assert r.status_code == 201, r.data

    # All coded labels resolved through the seeded ChoiceLists.
    assert r.data["kind_label"]               == "Cash transfer"
    assert r.data["status_label"]             == "Draft"
    assert r.data["unit_of_enrolment_label"]  == "Household"
    assert r.data["sex_filter_label"]         == "Female"
    assert r.data["disbursement_cycle_label"] == "Monthly"

    # JSON arrays of ChoiceOption codes — preserved verbatim, not
    # normalised into something the wizard wouldn't recognise.
    assert r.data["pmt_bands"]          == ["poorest_20", "poorest_40"]
    assert r.data["composition_flags"]  == ["female_headed"]
    assert r.data["auto_exit_triggers"] == ["age_out", "deceased", "pmt_shift"]
    assert r.data["exit_codes_allowed"] == ["10", "20", "30", "40", "50", "60", "70"]

    # Geographic M2M wired.
    assert set(r.data["geographic_units"]) == {g.id for g in geo_units}

    # Webhook cleartext returned once; only the hash persisted.
    assert r.data.get("webhook_secret_cleartext"), \
        "expected a one-shot webhook_secret_cleartext on create"
    prog = Programme.objects.get(id=r.data["id"])
    assert prog.webhook_secret_hash
    assert len(prog.webhook_secret_hash) == 64
    assert prog.webhook_secret_hash != r.data["webhook_secret_cleartext"]

    # Audit chain: programme_created with structured field_changes.
    audits = AuditEvent.objects.filter(
        entity_type="programme", action="programme_created",
        entity_id=prog.id,
    )
    assert audits.count() == 1
    evt = audits.first()
    assert evt.field_changes["partner_code"] == "MGLSD"
    assert evt.field_changes["code"] == "MGLSD-DVA"
    assert evt.field_changes["kind"] == "cash_transfer"
    assert evt.field_changes["cohort_target"] == 18000


@pytest.mark.django_db
def test_programme_wizard_rejects_duplicate_code(api, partner_with_dsa):
    partner, _, _ = partner_with_dsa
    first = api.post("/api/v1/programmes/", {
        "partner": partner.id, "code": "DUP", "name": "A", "kind": "service",
    }, format="json")
    assert first.status_code == 201, first.data

    dup = api.post("/api/v1/programmes/", {
        "partner": partner.id, "code": "DUP", "name": "B", "kind": "service",
    }, format="json")
    assert dup.status_code == 400
    assert "already exists" in str(dup.data).lower()


@pytest.mark.django_db
def test_programme_list_filtered_by_partner_through_convenience_route(
    api, partner_with_dsa,
):
    partner, _, _ = partner_with_dsa
    other = Partner.objects.create(
        code="OPM", name="OPM", type="ministry", status="active",
    )
    Programme.objects.create(partner=partner, name="P1", kind="cash_transfer")
    Programme.objects.create(partner=other, name="P2", kind="service")

    r = api.get(f"/api/v1/partners/{partner.id}/programmes/")
    assert r.status_code == 200
    names = [item["name"] for item in r.data["items"]]
    assert names == ["P1"]
