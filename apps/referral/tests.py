"""Programme referral tests."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.referral.models import Programme, Referral
from apps.referral.services import (
    ENROL_ACTIVE,
    ENROL_EXITED,
    REF_ACCEPTED,
    REF_ENROLLED,
    REF_EXITED,
    REF_REJECTED,
    REF_SENT,
    ReferralError,
    accept_referral,
    enrol_household,
    exit_enrolment,
    reject_referral,
    send_referral,
    send_referral_webhook,
    sign_payload,
)


@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"REF-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"], urban_rural="2",
    )


@pytest.fixture
def programme(db):
    return Programme.objects.create(
        code="PDM", name="Parish Development Model",
        webhook_url="https://pdm.example/incoming",
        webhook_secret="test-secret",
        dsa_reference="DSA-OPM-PDM-2026-001",
    )


# --- send_referral ---------------------------------------------------------

class TestSendReferral:
    def test_creates_with_status_sent(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        assert r.status == REF_SENT
        assert r.programme_id == programme.id
        assert r.household_id == household.id

    def test_inactive_programme_refused(self, household, programme):
        programme.is_active = False
        programme.save()
        with pytest.raises(ReferralError, match="inactive"):
            send_referral(programme=programme, household=household, actor="op-1")


# --- webhook signing -------------------------------------------------------

class TestWebhookSign:
    def test_deterministic_signature_per_payload(self):
        s1 = sign_payload({"a": 1, "b": 2}, "secret")
        s2 = sign_payload({"b": 2, "a": 1}, "secret")  # key order doesn't matter
        assert s1 == s2

    def test_different_payload_different_signature(self):
        a = sign_payload({"a": 1}, "secret")
        b = sign_payload({"a": 2}, "secret")
        assert a != b


class TestSendWebhook:
    def test_records_delivery_id_and_timestamp(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        delivery_id = send_referral_webhook(r)
        r.refresh_from_db()
        assert r.last_delivery_id == delivery_id
        assert r.last_delivery_id.startswith("dly-")
        assert r.last_delivery_at is not None


# --- state machine ---------------------------------------------------------

class TestAccept:
    def test_accept_moves_sent_to_accepted(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        accept_referral(r, actor="programme-1", programme_side_id="PDM-12345")
        r.refresh_from_db()
        assert r.status == REF_ACCEPTED
        assert r.programme_side_id == "PDM-12345"
        assert r.accepted_at is not None

    def test_cannot_accept_non_sent(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        reject_referral(r, actor="programme-1", reason="not eligible")
        with pytest.raises(ReferralError, match="only SENT"):
            accept_referral(r, actor="programme-1")


class TestReject:
    def test_reject_with_reason(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        reject_referral(r, actor="programme-1", reason="not eligible")
        r.refresh_from_db()
        assert r.status == REF_REJECTED
        assert r.reason == "not eligible"

    def test_reject_requires_reason(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        with pytest.raises(ReferralError, match="non-empty reason"):
            reject_referral(r, actor="programme-1", reason="")


class TestEnrol:
    def test_enrol_creates_enrolment_and_advances_referral(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        accept_referral(r, actor="programme-1")
        e = enrol_household(r, actor="programme-1")
        r.refresh_from_db()
        assert r.status == REF_ENROLLED
        assert r.enrolled_at is not None
        assert e.status == ENROL_ACTIVE
        assert e.household_id == household.id

    def test_cannot_enrol_without_accept(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        with pytest.raises(ReferralError, match="only ACCEPTED"):
            enrol_household(r, actor="programme-1")


class TestExit:
    def test_exit_propagates_to_referral(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        accept_referral(r, actor="programme-1")
        e = enrol_household(r, actor="programme-1")
        exit_enrolment(e, actor="programme-1", reason="moved out of catchment")
        e.refresh_from_db()
        r.refresh_from_db()
        assert e.status == ENROL_EXITED
        assert r.status == REF_EXITED
        assert "moved out" in r.reason


# --- HTTP surface ----------------------------------------------------------

class TestApi:
    def test_send_via_drf(self, household, programme, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="op", password="p", is_superuser=True, is_staff=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post("/api/v1/ref/referrals/send/", data={
            "programme_id": programme.id, "household_id": household.id,
            "actor": "op-1",
        }, format="json")
        assert r.status_code == 200, r.content
        assert r.data["status"] == REF_SENT
        assert Referral.objects.filter(pk=r.data["id"]).exists()
        # Webhook stub recorded a delivery id.
        assert r.data["last_delivery_id"]
