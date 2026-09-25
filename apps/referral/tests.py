"""Programme referral tests."""

from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.partners.models import DataSharingAgreement, Partner, Programme
from apps.reference_data.models import GeographicUnit
from apps.referral.models import ProgrammeEnrolment, Referral
from apps.security.models import AuditEvent
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
    # Canonical Programme (ADR-0015) requires a Partner FK and uses
    # `status` instead of `is_active`. Webhook secret cleartext lives
    # in webhook_secret_encrypted; the field's prep code accepts str.
    opm = Partner.objects.create(
        code="OPM", name="Office of the Prime Minister",
        type="ministry", status="active",
    )
    return Programme.objects.create(
        partner=opm,
        code="PDM", name="Parish Development Model",
        kind="cash_transfer",
        status="active",
        webhook_url="https://pdm.example/incoming",
        webhook_secret_encrypted=b"test-secret",
        dsa_reference_legacy="DSA-OPM-PDM-2026-001",
    )


# --- send_referral ---------------------------------------------------------

class TestSendReferral:
    def test_creates_with_status_sent(self, household, programme):
        r = send_referral(programme=programme, household=household, actor="op-1")
        assert r.status == REF_SENT
        assert r.programme_id == programme.id
        assert r.household_id == household.id

    def test_inactive_programme_refused(self, household, programme):
        programme.status = "draft"
        programme.save(update_fields=["status"])
        with pytest.raises(ReferralError, match="not active"):
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

    def test_household_filters_return_only_that_households_rows(
        self, household, programme, geo, django_user_model,
    ):
        """A household projection must not receive another household's rows."""
        other_household = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        referral = send_referral(
            programme=programme, household=household, actor="op-1",
        )
        other_referral = send_referral(
            programme=programme, household=other_household, actor="op-1",
        )
        accept_referral(referral, actor="programme-1")
        accept_referral(other_referral, actor="programme-1")
        enrolment = enrol_household(referral, actor="programme-1")
        other_enrolment = enrol_household(other_referral, actor="programme-1")

        user = django_user_model.objects.create_user(
            username="household-reader", password="p", is_superuser=True,
            is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        enrolments = client.get("/api/v1/ref/enrolments/", {
            "household": household.id,
        })
        assert enrolments.status_code == 200, enrolments.content
        enrolment_ids = {row["id"] for row in enrolments.data["results"]}
        assert enrolment_ids == {str(enrolment.id)}
        assert str(other_enrolment.id) not in enrolment_ids

        referrals = client.get("/api/v1/ref/referrals/", {
            "household": household.id,
        })
        assert referrals.status_code == 200, referrals.content
        assert {row["id"] for row in referrals.data["results"]} == {str(referral.id)}

    def test_direct_enrolment_uses_active_dsa_programme_geography_and_atomic_selection(
        self, household, programme, geo, django_user_model,
    ):
        """Direct enrolment can only create the canonical scoped rows."""
        dsa = DataSharingAgreement.objects.create(
            partner=programme.partner, reference="DSA-OPM-2026-001", version=1,
            status="active", effective_from=date(2026, 1, 1),
            entities_scope={"household": True}, field_scope={},
        )
        dsa.geographic_scope.add(geo["r"])
        household.current_vulnerability_band = "vulnerable"
        household.save(update_fields=["current_vulnerability_band"])
        programme.dsa = dsa
        programme.unit_of_enrolment = "household"
        programme.pmt_bands = ["middle_40"]
        programme.sex_filter = "any"
        programme.geographic_units.add(geo["r"])
        programme.save(update_fields=["dsa", "unit_of_enrolment", "pmt_bands", "sex_filter"])

        outside_region = GeographicUnit.objects.create(
            level="region", code="REF-OUTSIDE", name="Outside",
            effective_from=date(2026, 1, 1),
        )
        outside_household = Household.objects.create(
            region=outside_region, sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        user = django_user_model.objects.create_user(
            username="direct-enroller", password="p", is_superuser=True,
            is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        programme.code = "OPM-GEO-TEST-02"
        programme.save(update_fields=["code"])

        eligible = client.get("/api/v1/ref/enrolments/eligible-households/", {
            "programme": programme.id,
        })
        assert eligible.status_code == 200, eligible.data
        assert {row["id"] for row in eligible.data["results"]} == {str(household.id)}
        eligible_row = eligible.data["results"][0]
        assert {
            key: eligible_row[key]
            for key in (
                "region_name", "sub_region_name", "district_name", "county_name",
                "sub_county_name", "parish_name", "village_name",
            )
        } == {
            "region_name": "R", "sub_region_name": "Sr", "district_name": "D",
            "county_name": "C", "sub_county_name": "Sc", "parish_name": "P",
            "village_name": "V",
        }

        refused = client.post("/api/v1/ref/enrolments/enrol-direct/", {
            "programme_id": programme.id,
            "household_ids": [household.id, outside_household.id],
        }, format="json")
        assert refused.status_code == 422, refused.data
        assert refused.data["detail"].startswith("No households were enrolled")
        assert refused.data["rejections"] == [{
            "household_id": str(outside_household.id), "code": "not_eligible",
            "reason": "Household is outside saved programme geography or does not meet its configured eligibility.",
        }]
        assert ProgrammeEnrolment.objects.count() == 0

        created = client.post("/api/v1/ref/enrolments/enrol-direct/", {
            "programme_id": programme.id,
            "household_ids": [household.id],
        }, format="json")
        assert created.status_code == 201, created.data
        assert created.data["summary"] == {
            "requested_count": 1, "created_count": 1, "programme_id": str(programme.id),
        }
        enrolment_id = created.data["enrolments"][0]["id"]
        assert ProgrammeEnrolment.objects.filter(
            programme=programme, household=household,
        ).exists()
        assert AuditEvent.objects.filter(
            entity_type="programme_enrolment_batch", entity_id=str(programme.id),
        ).exists()

        # The household detail and programme roster read the exact same
        # persisted ProgrammeEnrolment row, not a client-side roster copy.
        household_rows = client.get("/api/v1/ref/enrolments/", {"household": household.id})
        programme_rows = client.get("/api/v1/ref/enrolments/", {"programme": programme.id})
        assert household_rows.status_code == programme_rows.status_code == 200
        assert {row["id"] for row in household_rows.data["results"]} == {enrolment_id}
        assert {row["id"] for row in programme_rows.data["results"]} == {enrolment_id}

        duplicate = client.post("/api/v1/ref/enrolments/enrol-direct/", {
            "programme_id": programme.id, "household_ids": [household.id],
        }, format="json")
        assert duplicate.status_code == 422, duplicate.data
        assert duplicate.data["rejections"][0]["code"] == "already_enrolled"

    def test_programme_enrolment_constraint_prevents_duplicate_pairs(self, household, programme):
        """The database remains the concurrency backstop for direct batches."""
        ProgrammeEnrolment.objects.create(
            programme=programme, household=household, status="active",
            effective_date=date(2026, 9, 25),
        )
        with pytest.raises(IntegrityError):
            ProgrammeEnrolment.objects.create(
                programme=programme, household=household, status="active",
                effective_date=date(2026, 9, 25),
            )

    def test_direct_enrolment_fails_closed_for_unmapped_choice_rules(
        self, household, programme, geo, django_user_model,
    ):
        dsa = DataSharingAgreement.objects.create(
            partner=programme.partner, reference="DSA-REF-SCHEMA", version=1,
            status="active", effective_from=date(2026, 1, 1),
            entities_scope={"household": True}, field_scope={},
        )
        dsa.geographic_scope.add(geo["r"])
        programme.dsa = dsa
        programme.unit_of_enrolment = "household"
        # A configured code without an approved ChoiceOption canonical_code
        # binding is rejected. Real active PMT mappings (such as middle_40 →
        # vulnerable) are covered by the successful OPM test above.
        programme.pmt_bands = ["unmapped_pmt_option"]
        programme.geographic_units.add(geo["r"])
        programme.save(update_fields=["dsa", "unit_of_enrolment", "pmt_bands"])
        user = django_user_model.objects.create_user(
            username="schema-enroller", password="p", is_superuser=True,
            is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get("/api/v1/ref/enrolments/eligible-households/", {
            "programme": programme.id,
        })
        assert response.status_code == 422
        assert response.data["code"] == "schema_dependency"
        assert "unmapped_pmt_option" in response.data["schema_dependencies"][0]
