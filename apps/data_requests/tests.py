"""API-DRS tests — DSA scope validation, lifecycle, audit, API."""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_requests.models import (
    DataRequest,
    DataSharingAgreement,
    DsaStatus,
    Partner,
    RequestStatus,
)
from apps.data_requests.services import (
    DrsError,
    approve_data_request,
    deliver_data_request,
    expire_data_request,
    reject_data_request,
    submit_data_request,
    validate_against_dsa,
)
from apps.security.models import AuditEvent


@pytest.fixture
def partner(db):
    return Partner.objects.create(code="PDM-MGLSD", name="PDM Programme Office")


@pytest.fixture
def active_dsa(partner):
    return DataSharingAgreement.objects.create(
        partner=partner, reference="DSA-PDM-2026-01",
        purpose="Cohort enrolment", status=DsaStatus.ACTIVE,
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        allowed_scopes={
            "fields": ["household.id", "household.sub_region_code",
                       "household.current_vulnerability_band"],
            "sub_region_codes": ["SR-BUGANDA", "SR-KARAMOJA"],
            "programme_codes": ["PDM"],
            "max_rows_per_request": 50000,
        },
    )


@pytest.fixture
def draft_request(active_dsa):
    return DataRequest.objects.create(
        dsa=active_dsa, requester="partner-analyst-1",
        request_payload={
            "fields": ["household.id", "household.sub_region_code"],
            "sub_region_codes": ["SR-BUGANDA"],
            "programme_codes": ["PDM"],
            "max_rows": 1000,
        },
    )


class TestValidateAgainstDsa:
    def test_subset_payload_passes(self, active_dsa):
        validate_against_dsa(
            {"fields": ["household.id"], "sub_region_codes": ["SR-BUGANDA"]},
            active_dsa,
        )

    def test_extra_field_rejected(self, active_dsa):
        with pytest.raises(DrsError, match="fields="):
            validate_against_dsa(
                {"fields": ["household.id", "household.nin_hash"]}, active_dsa,
            )

    def test_extra_sub_region_rejected(self, active_dsa):
        with pytest.raises(DrsError, match="sub_region_codes="):
            validate_against_dsa(
                {"sub_region_codes": ["SR-BUGANDA", "SR-WESTNILE"]}, active_dsa,
            )

    def test_row_cap_enforced(self, active_dsa):
        with pytest.raises(DrsError, match="max_rows"):
            validate_against_dsa({"max_rows": 50001}, active_dsa)

    def test_missing_dsa_key_means_unrestricted(self, partner):
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-X", status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={"fields": ["household.id"]},
        )
        # Payload asks for sub_region_codes but DSA doesn't constrain it → ok.
        validate_against_dsa(
            {"fields": ["household.id"], "sub_region_codes": ["anywhere"]}, dsa,
        )


class TestSubmit:
    def test_submit_marks_submitted_and_audits(self, draft_request):
        submit_data_request(draft_request)
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.SUBMITTED
        assert draft_request.submitted_at is not None
        assert AuditEvent.objects.filter(
            entity_type="data_request", entity_id=draft_request.id, action="submit",
        ).exists()

    def test_cannot_resubmit(self, draft_request):
        submit_data_request(draft_request)
        with pytest.raises(DrsError, match="DRAFT"):
            submit_data_request(draft_request)

    def test_inactive_dsa_blocks_submit(self, partner, active_dsa):
        active_dsa.status = DsaStatus.SUSPENDED
        active_dsa.save(update_fields=["status"])
        req = DataRequest.objects.create(dsa=active_dsa, requester="x",
                                         request_payload={})
        with pytest.raises(DrsError, match="not ACTIVE"):
            submit_data_request(req)

    def test_expired_dsa_blocks_submit(self, partner):
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-OLD", status=DsaStatus.ACTIVE,
            valid_from=date(2020, 1, 1), valid_to=date(2024, 12, 31),
            allowed_scopes={},
        )
        req = DataRequest.objects.create(dsa=dsa, requester="x",
                                         request_payload={})
        with pytest.raises(DrsError, match="validity window"):
            submit_data_request(req)

    def test_scope_violation_blocks_submit(self, active_dsa):
        req = DataRequest.objects.create(
            dsa=active_dsa, requester="x",
            request_payload={"fields": ["household.nin_hash"]},
        )
        with pytest.raises(DrsError, match="outside DSA scope"):
            submit_data_request(req)


class TestApproveReject:
    def test_no_self_approve(self, draft_request):
        submit_data_request(draft_request)
        with pytest.raises(DrsError, match="SELF"):
            approve_data_request(draft_request, approver=draft_request.requester)

    def test_approve_records_decision(self, draft_request):
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.APPROVED
        assert draft_request.approver == "dpo-1"
        assert draft_request.decided_at is not None

    def test_reject_records_reason(self, draft_request):
        submit_data_request(draft_request)
        reject_data_request(draft_request, approver="dpo-1",
                            reason="purpose too broad")
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.REJECTED
        assert "broad" in draft_request.decision_reason

    def test_reject_requires_reason(self, draft_request):
        submit_data_request(draft_request)
        with pytest.raises(DrsError, match="non-empty"):
            reject_data_request(draft_request, approver="dpo-1", reason="")


class TestDeliver:
    def test_deliver_locks_manifest_and_sets_expiry(self, draft_request):
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        sha = "a" * 64
        deliver_data_request(draft_request, manifest_sha256=sha,
                             row_count=42, actor="export-bot")
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.DELIVERED
        assert draft_request.manifest_sha256 == sha
        assert draft_request.row_count_delivered == 42
        assert draft_request.expires_at is not None

    def test_bad_manifest_rejected(self, draft_request):
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        with pytest.raises(DrsError, match="64 hex"):
            deliver_data_request(draft_request, manifest_sha256="short",
                                 row_count=0, actor="x")

    def test_cannot_deliver_unapproved(self, draft_request):
        submit_data_request(draft_request)
        with pytest.raises(DrsError, match="APPROVED"):
            deliver_data_request(draft_request, manifest_sha256="a" * 64,
                                 row_count=1, actor="x")


class TestExpire:
    def test_expire_after_delivery(self, draft_request):
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(draft_request, manifest_sha256="a" * 64,
                             row_count=1, actor="x")
        expire_data_request(draft_request, actor="cron")
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.EXPIRED

    def test_expire_is_idempotent(self, draft_request):
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(draft_request, manifest_sha256="a" * 64,
                             row_count=1, actor="x")
        expire_data_request(draft_request)
        expire_data_request(draft_request)
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.EXPIRED


class TestApi:
    def test_full_flow_via_api(self, db, django_user_model, active_dsa):
        u = django_user_model.objects.create_user(
            username="partner-x", password="p", is_superuser=True, is_staff=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        # Create draft
        r = c.post("/api/v1/drs/requests/", data={
            "dsa": active_dsa.id,
            "request_payload": {
                "fields": ["household.id"],
                "sub_region_codes": ["SR-BUGANDA"],
                "max_rows": 100,
            },
        }, format="json")
        assert r.status_code == 201, r.data
        req_id = r.data["id"]
        # Submit
        r = c.post(f"/api/v1/drs/requests/{req_id}/submit/")
        assert r.status_code == 200
        assert r.data["status"] == RequestStatus.SUBMITTED
        # Reject self-approve
        r = c.post(f"/api/v1/drs/requests/{req_id}/approve/",
                   data={"approver": "partner-x"}, format="json")
        assert r.status_code == 400
        # Approve
        r = c.post(f"/api/v1/drs/requests/{req_id}/approve/",
                   data={"approver": "dpo-2"}, format="json")
        assert r.status_code == 200
        assert r.data["status"] == RequestStatus.APPROVED
        # Deliver
        r = c.post(f"/api/v1/drs/requests/{req_id}/deliver/",
                   data={"actor": "bot", "manifest_sha256": "b" * 64,
                         "row_count": 17}, format="json")
        assert r.status_code == 200
        assert r.data["row_count_delivered"] == 17

    def test_scope_violation_returns_400_on_submit(self, db, django_user_model, active_dsa):
        u = django_user_model.objects.create_user(
            username="partner-y", password="p", is_superuser=True, is_staff=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post("/api/v1/drs/requests/", data={
            "dsa": active_dsa.id,
            "request_payload": {"fields": ["household.nin_hash"]},
        }, format="json")
        req_id = r.data["id"]
        r = c.post(f"/api/v1/drs/requests/{req_id}/submit/")
        assert r.status_code == 400
        assert "nin_hash" in r.data["detail"]


class TestPartnerAbac:
    """Partner-affiliated users see only DataRequests under DSAs
    belonging to their Partner. NSR Unit (national) and superusers see
    all. Mirrors the geographic ABAC story for personal-data viewsets
    but uses org-affiliation as the visibility lens."""

    @pytest.fixture
    def two_partners(self, db):
        p_a = Partner.objects.create(code="PARTNER-A", name="Partner A")
        p_b = Partner.objects.create(code="PARTNER-B", name="Partner B")
        return p_a, p_b

    @pytest.fixture
    def dsas(self, two_partners):
        p_a, p_b = two_partners
        d_a = DataSharingAgreement.objects.create(
            partner=p_a, reference="DSA-A-1", status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        d_b = DataSharingAgreement.objects.create(
            partner=p_b, reference="DSA-B-1", status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        return d_a, d_b

    @pytest.fixture
    def requests_in_each(self, dsas):
        d_a, d_b = dsas
        r_a = DataRequest.objects.create(dsa=d_a, requester="a", request_payload={})
        r_b = DataRequest.objects.create(dsa=d_b, requester="b", request_payload={})
        return r_a, r_b

    def _client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_superuser_sees_both_partners_requests(
        self, db, django_user_model, requests_in_each,
    ):
        u = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = self._client_for(u).get("/api/v1/drs/requests/")
        assert r.status_code == 200
        assert r.data["count"] == 2

    def test_unaffiliated_user_sees_zero(
        self, db, django_user_model, requests_in_each,
    ):
        u = django_user_model.objects.create_user(username="ghost", password="p")
        r = self._client_for(u).get("/api/v1/drs/requests/")
        assert r.status_code == 200
        assert r.data["count"] == 0

    def test_partner_a_user_sees_only_partner_a_requests(
        self, db, django_user_model, two_partners, requests_in_each,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _ = two_partners
        r_a, _ = requests_in_each
        u = django_user_model.objects.create_user(username="partner-a-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        r = self._client_for(u).get("/api/v1/drs/requests/")
        assert r.status_code == 200
        assert r.data["count"] == 1
        assert r.data["results"][0]["id"] == r_a.id

    def test_national_scope_sees_both_partners_requests(
        self, db, django_user_model, requests_in_each,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        u = django_user_model.objects.create_user(username="dpo", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.NATIONAL, scope_code="",
        )
        r = self._client_for(u).get("/api/v1/drs/requests/")
        assert r.data["count"] == 2

    def test_partner_scope_also_filters_dsas(
        self, db, django_user_model, two_partners, dsas,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _ = two_partners
        d_a, _ = dsas
        u = django_user_model.objects.create_user(username="partner-a-dpo", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        r = self._client_for(u).get("/api/v1/drs/agreements/")
        assert r.status_code == 200
        assert r.data["count"] == 1
        assert r.data["results"][0]["id"] == d_a.id

    def test_partner_scope_also_filters_partners_list(
        self, db, django_user_model, two_partners,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _ = two_partners
        u = django_user_model.objects.create_user(username="partner-a-staff", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        r = self._client_for(u).get("/api/v1/drs/partners/")
        assert r.status_code == 200
        assert r.data["count"] == 1
        assert r.data["results"][0]["code"] == p_a.code
