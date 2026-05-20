"""End-to-end test for GET /api/v1/beneficiaries/ (US-S26-006).

Walks the four status paths the endpoint synthesises:
  • active    — explicit ProgrammeEnrolment row
  • suspended — explicit ProgrammeEnrolment row
  • exited    — explicit ProgrammeEnrolment row
  • pending   — Referral in sent/accepted with no enrolment

Plus ABAC: a partner-scoped UNICEF user sees only UNICEF
programmes; an unscoped user gets an empty list; a superuser
sees everything.
"""

from __future__ import annotations

from datetime import date

import pytest
from apps.data_management.models import Household, Member
from apps.partners.models import Partner, Programme
from apps.reference_data.models import GeographicUnit
from apps.reference_data.services import clear_resolver_cache
from apps.referral.models import ProgrammeEnrolment, Referral
from apps.security.models import OperatorScope, ScopeLevel
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

URL = "/api/v1/beneficiaries/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def geo(db):
    nodes = {}
    for level, key in [
        ("region", "r"), ("sub_region", "sr"), ("district", "d"),
        ("county", "c"), ("sub_county", "sc"),
        ("parish", "p"), ("village", "v"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"BEN-{key.upper()}", name=key.title(),
            effective_from=date(2026, 1, 1),
            parent=nodes.get(
                {"sr":"r","d":"sr","c":"d","sc":"c","p":"sc","v":"p"}.get(key),
            ),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    hh = Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
        urban_rural="2", current_pmt_score="0.4200",
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
def opm_partner(db):
    return Partner.objects.create(
        code="OPM", name="OPM", type="ministry", status="active",
    )


@pytest.fixture
def opm_programme(db, opm_partner):
    return Programme.objects.create(
        partner=opm_partner,
        code="OPM-PDM", name="Parish Development Model",
        kind="cash_transfer", status="active",
        unit_of_enrolment="household",
        channel="Kibalinga SACCO",
    )


@pytest.fixture
def unicef_partner(db):
    return Partner.objects.create(
        code="UNICEF", name="UNICEF Uganda", type="agency",
        status="active",
    )


@pytest.fixture
def unicef_programme(db, unicef_partner):
    return Programme.objects.create(
        partner=unicef_partner,
        code="UN-CGK", name="Child Grant — Karamoja pilot",
        kind="cash_transfer", status="active",
        unit_of_enrolment="member",
        channel="Caregiver MoMo",
    )


@pytest.fixture
def superuser(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="su", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


# --- Status synthesis ------------------------------------------------------


@pytest.mark.django_db
def test_active_enrolment_row_carries_labels_and_pmt(
    superuser, household, opm_programme,
):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
        payment_metadata={
            "cohort": "2026·Q2-C4",
            "last_pay_at": "2026-05-15",
            "last_pay_amt": 250000,
            "total_paid": 500000,
            "next_pay_at": "2026-08-15",
        },
    )
    r = superuser.get(URL)
    assert r.status_code == 200, r.data
    assert r.data["count"] == 1
    row = r.data["results"][0]
    assert row["status"] == "active"
    assert row["status_label"] == "Active"
    assert row["programme_code"] == "OPM-PDM"
    assert row["programme_kind_label"] == "Cash transfer"
    assert row["unit_of_enrolment_label"] == "Household"
    assert row["household_head_name"] == "Nsubuga Ruth"
    assert row["cohort"] == "2026·Q2-C4"
    assert row["last_pay_amt"] == 250000
    assert row["total_paid"] == 500000
    assert row["pmt_score"] == pytest.approx(0.42, rel=1e-3)


@pytest.mark.django_db
def test_pending_state_is_synthesized_from_referral(
    superuser, household, opm_programme,
):
    Referral.objects.create(
        programme=opm_programme, household=household,
        status="accepted", reason="MoU pending",
    )
    r = superuser.get(URL)
    assert r.status_code == 200
    assert r.data["count"] == 1
    row = r.data["results"][0]
    assert row["status"] == "pending"
    assert row["status_label"] == "Pending"
    assert row["enrolled_at"] is None
    assert row["note"] == "MoU pending"


@pytest.mark.django_db
def test_referral_with_enrolment_does_not_double_count(
    superuser, household, opm_programme,
):
    ref = Referral.objects.create(
        programme=opm_programme, household=household, status="enrolled",
    )
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household, referral=ref,
        status="active", effective_date=date(2026, 4, 10),
    )
    r = superuser.get(URL)
    assert r.data["count"] == 1
    assert r.data["results"][0]["status"] == "active"


@pytest.mark.django_db
def test_exited_row_carries_exit_code_label(
    superuser, household, opm_programme,
):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="exited", effective_date=date(2025, 1, 1),
        exit_reason="Programme objective met",
        payment_metadata={"exit_code": "10"},
    )
    r = superuser.get(URL)
    row = r.data["results"][0]
    assert row["status"] == "exited"
    assert row["exit_code"] == "10"
    assert row["exit_code_label"] == "Graduated"


# --- Filters ---------------------------------------------------------------


@pytest.mark.django_db
def test_filter_by_status(
    superuser, household, opm_programme, unicef_programme,
):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )
    ProgrammeEnrolment.objects.create(
        programme=unicef_programme, household=household,
        status="suspended", effective_date=date(2026, 4, 10),
        payment_metadata={"suspend_reason": "Caregiver unreachable"},
    )
    r = superuser.get(URL, {"status": "suspended"})
    assert r.data["count"] == 1
    assert r.data["results"][0]["status"] == "suspended"
    assert r.data["results"][0]["suspend_reason"] == "Caregiver unreachable"


@pytest.mark.django_db
def test_filter_by_programme_code(
    superuser, household, opm_programme, unicef_programme,
):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )
    ProgrammeEnrolment.objects.create(
        programme=unicef_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )
    r = superuser.get(URL, {"programme_code": "UN-CGK"})
    assert r.data["count"] == 1
    assert r.data["results"][0]["programme_code"] == "UN-CGK"


# --- ABAC ------------------------------------------------------------------


@pytest.mark.django_db
def test_partner_scoped_user_sees_only_their_partner(
    db, household, opm_programme, unicef_programme, unicef_partner,
):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )
    ProgrammeEnrolment.objects.create(
        programme=unicef_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )

    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="unicef-analyst", password="p")
    OperatorScope.objects.create(
        user=u, scope_level=ScopeLevel.PARTNER, scope_code="UNICEF",
    )
    c = APIClient()
    c.force_authenticate(user=u)

    r = c.get(URL)
    assert r.status_code == 200
    assert r.data["count"] == 1
    assert r.data["results"][0]["programme_code"] == "UN-CGK"


@pytest.mark.django_db
def test_unscoped_user_sees_empty(db, household, opm_programme):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="nobody", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    r = c.get(URL)
    assert r.status_code == 200
    assert r.data["count"] == 0


@pytest.mark.django_db
def test_geo_scoped_user_sees_their_sub_region(
    db, household, opm_programme, geo,
):
    ProgrammeEnrolment.objects.create(
        programme=opm_programme, household=household,
        status="active", effective_date=date(2026, 4, 10),
    )
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="cdo", password="p")
    OperatorScope.objects.create(
        user=u, scope_level=ScopeLevel.SUB_REGION,
        scope_code=geo["sr"].code,
    )
    c = APIClient()
    c.force_authenticate(user=u)
    r = c.get(URL)
    assert r.status_code == 200
    assert r.data["count"] == 1
