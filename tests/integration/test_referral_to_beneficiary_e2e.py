"""End-to-end referral → enrolment → beneficiary flow (US-S26-008).

Walks every persisted state transition through the canonical
Programme model (apps.partners.Programme) plus the referral state
machine (apps.referral.services), asserting the beneficiary
listing endpoint surfaces each state correctly:

  send_referral (sent)
    └─ accept_referral (accepted)
         └─ enrol_household → ProgrammeEnrolment status='active'
              └─ exit_enrolment (exited)

At each stage we query GET /api/v1/beneficiaries/ and check the
synthesised row: count, status, status_label, exit info.

This test seals ADR-0015 — it proves the schema swap (US-S26-005)
plus the beneficiary listing (US-S26-006) joined cleanly with the
referral state machine after the TextChoices removal (US-S26-003).
"""

from __future__ import annotations

from datetime import date

import pytest
from apps.data_management.models import Household, Member
from apps.partners.models import Partner, Programme
from apps.reference_data.models import GeographicUnit
from apps.reference_data.services import clear_resolver_cache
from apps.referral.services import (
    accept_referral,
    enrol_household,
    exit_enrolment,
    send_referral,
)
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

URL = "/api/v1/beneficiaries/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def superuser(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="su26", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def geo(db):
    nodes = {}
    parents = {"sr": "r", "d": "sr", "c": "d", "sc": "c", "p": "sc", "v": "p"}
    for level, key in [
        ("region", "r"), ("sub_region", "sr"), ("district", "d"),
        ("county", "c"), ("sub_county", "sc"),
        ("parish", "p"), ("village", "v"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"E2E-{key.upper()}", name=key.title(),
            effective_from=date(2026, 1, 1),
            parent=nodes.get(parents.get(key)),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    hh = Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
        urban_rural="2", current_pmt_score="0.3900",
    )
    head = Member.objects.create(
        household=hh, line_number=1,
        surname="Nsubuga", first_name="Ruth",
        relationship_to_head="01", sex="2",
    )
    hh.head_member = head
    hh.save(update_fields=["head_member"])
    return hh


@pytest.fixture
def programme(db):
    opm = Partner.objects.create(
        code="OPM", name="Office of the Prime Minister",
        type="ministry", status="active",
    )
    return Programme.objects.create(
        partner=opm, code="OPM-PDM", name="Parish Development Model",
        kind="cash_transfer", status="active",
        unit_of_enrolment="household",
        channel="Kibalinga SACCO",
        webhook_url="https://opm.example/incoming",
        webhook_secret_encrypted=b"e2e-secret",
    )


@pytest.mark.django_db
def test_full_lifecycle_threads_through_beneficiary_listing(
    superuser, household, programme,
):
    # --- Step 1: send_referral — listing should surface as pending ---
    referral = send_referral(
        programme=programme, household=household, actor="op-1",
    )
    assert referral.status == "sent"

    r = superuser.get(URL)
    assert r.status_code == 200, r.data
    assert r.data["count"] == 1
    row = r.data["results"][0]
    assert row["status"] == "pending"
    assert row["status_label"] == "Pending"
    assert row["programme_code"] == "OPM-PDM"
    assert row["household_head_name"] == "Nsubuga Ruth"
    assert row["enrolled_at"] is None

    # --- Step 2: accept_referral — still pending (no enrolment yet) ---
    accept_referral(referral, actor="opm-system", programme_side_id="PDM-99")
    r = superuser.get(URL)
    assert r.data["count"] == 1
    assert r.data["results"][0]["status"] == "pending"

    # --- Step 3: enrol_household — flips to active ---
    enrolment = enrol_household(
        referral, actor="opm-system",
        effective_date=date(2026, 4, 10),
        payment_metadata={
            "cohort": "2026·Q2-C4",
            "last_pay_at": "2026-05-15",
            "last_pay_amt": 250000,
            "total_paid": 500000,
            "next_pay_at": "2026-08-15",
        },
    )
    assert enrolment.status == "active"

    r = superuser.get(URL)
    assert r.data["count"] == 1
    row = r.data["results"][0]
    assert row["status"] == "active"
    assert row["status_label"] == "Active"
    assert row["cohort"] == "2026·Q2-C4"
    assert row["last_pay_amt"] == 250000
    assert row["total_paid"] == 500000

    # --- Step 4: exit_enrolment — flips to exited, exit_note carried ---
    exit_enrolment(
        enrolment, actor="opm-system",
        reason="Met PDM enterprise milestone — full repayment",
    )
    enrolment.refresh_from_db()
    # Carry an exit_code into payment_metadata via the model (the
    # endpoint surfaces exit_code from payment_metadata.exit_code).
    enrolment.payment_metadata = {
        **enrolment.payment_metadata, "exit_code": "10",
    }
    enrolment.save(update_fields=["payment_metadata"])

    r = superuser.get(URL)
    assert r.data["count"] == 1
    row = r.data["results"][0]
    assert row["status"] == "exited"
    assert row["status_label"] == "Exited"
    assert row["exit_code"] == "10"
    assert row["exit_code_label"] == "Graduated"
    assert "Met PDM enterprise milestone" in (row["exit_note"] or "")


@pytest.mark.django_db
def test_status_filter_narrows_after_enrol(
    superuser, household, programme,
):
    # Two households, two referrals: one accepted but not enrolled
    # (stays pending), one fully enrolled (active).
    other_hh = Household.objects.create(
        region=household.region, sub_region=household.sub_region,
        district=household.district, county=household.county,
        sub_county=household.sub_county, parish=household.parish,
        village=household.village, urban_rural="2",
    )
    other_head = Member.objects.create(
        household=other_hh, line_number=1,
        surname="Byaruhanga", first_name="Charles",
        relationship_to_head="01", sex="1",
    )
    other_hh.head_member = other_head
    other_hh.save(update_fields=["head_member"])

    r1 = send_referral(programme=programme, household=household, actor="op")
    accept_referral(r1, actor="opm")
    enrol_household(r1, actor="opm")

    send_referral(programme=programme, household=other_hh, actor="op")

    # No filter — both rows visible.
    r = superuser.get(URL)
    assert r.data["count"] == 2

    # status=active picks the enrolled one.
    r = superuser.get(URL, {"status": "active"})
    assert r.data["count"] == 1
    assert r.data["results"][0]["household_head_name"] == "Nsubuga Ruth"

    # status=pending picks the unenrolled referral.
    r = superuser.get(URL, {"status": "pending"})
    assert r.data["count"] == 1
    assert r.data["results"][0]["household_head_name"] == "Byaruhanga Charles"
