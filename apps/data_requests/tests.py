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


class TestBundleRendering:
    """S5-002 — DSA-scoped NDJSON bundle rendering. Validates the
    fields, sub_region_codes, and max_rows contracts from
    DSA.allowed_scopes, intersected with the request payload."""

    @pytest.fixture
    def geo_and_households(self, db):
        from datetime import date

        from apps.data_management.models import Household
        from apps.reference_data.models import GeographicUnit

        out = {}
        # Two sub-regions, two households each — 4 total.
        for sr_key in ("SR-BUGANDA", "SR-KARAMOJA"):
            nodes = {}
            parent = None
            for level in ("region", "sub_region", "district", "county",
                          "sub_county", "parish", "village"):
                node = GeographicUnit.objects.create(
                    level=level,
                    code=(f"B-{sr_key}-{level}" if level != "sub_region"
                          else f"B-{sr_key}"),
                    name=f"{sr_key}-{level}", parent=parent,
                    effective_from=date(2026, 1, 1),
                )
                nodes[level] = node
                parent = node
            out[sr_key] = []
            for _ in range(2):
                hh = Household.objects.create(
                    region=nodes["region"], sub_region=nodes["sub_region"],
                    district=nodes["district"], county=nodes["county"],
                    sub_county=nodes["sub_county"], parish=nodes["parish"],
                    village=nodes["village"], urban_rural="rural",
                )
                out[sr_key].append(hh)
        return out

    @pytest.fixture
    def open_dsa(self, partner):
        """DSA with no field/region restrictions — exports everything."""
        return DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-OPEN-1",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )

    @pytest.fixture
    def restricted_dsa(self, partner):
        """DSA restricted to BUGANDA + a subset of fields."""
        return DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-RESTRICTED-1",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={
                "fields": ["household.id", "household.sub_region_code"],
                "sub_region_codes": ["B-SR-BUGANDA"],
                "max_rows_per_request": 50,
            },
        )

    def test_open_dsa_renders_all_households_full_fields(
        self, geo_and_households, open_dsa,
    ):
        import json

        from apps.data_requests.bundles import render_bundle
        req = DataRequest.objects.create(
            dsa=open_dsa, requester="p1", request_payload={},
        )
        body, count = render_bundle(req)
        assert count == 4
        first = json.loads(body.splitlines()[0])
        # Open DSA = all default Household fields exported, plus the
        # members array (S6-002: open DSA embeds members by default).
        assert {
            "household.id", "household.sub_region_code",
            "household.urban_rural", "household.current_vulnerability_band",
            "household.current_pmt_score", "members",
        } == set(first.keys())
        # Empty households have an empty members list.
        assert first["members"] == []

    def test_restricted_dsa_clips_fields_and_geography(
        self, geo_and_households, restricted_dsa,
    ):
        import json

        from apps.data_requests.bundles import render_bundle
        req = DataRequest.objects.create(
            dsa=restricted_dsa, requester="p2", request_payload={},
        )
        body, count = render_bundle(req)
        # BUGANDA has 2 households; KARAMOJA invisible.
        assert count == 2
        first = json.loads(body.splitlines()[0])
        # Only the two whitelisted fields survive.
        assert set(first.keys()) == {
            "household.id", "household.sub_region_code",
        }
        # The visible row IS a BUGANDA one.
        assert first["household.sub_region_code"] == "B-SR-BUGANDA"

    def test_max_rows_uses_tighter_of_dsa_and_payload(
        self, geo_and_households, open_dsa,
    ):
        from apps.data_requests.bundles import render_bundle
        # DSA cap 3, request asks 5 → 3 wins.
        open_dsa.allowed_scopes = {"max_rows_per_request": 3}
        open_dsa.save(update_fields=["allowed_scopes"])
        req = DataRequest.objects.create(
            dsa=open_dsa, requester="p3",
            request_payload={"max_rows": 5},
        )
        _, count = render_bundle(req)
        assert count == 3

        # Request cap 1, DSA cap 3 → 1 wins.
        req2 = DataRequest.objects.create(
            dsa=open_dsa, requester="p4",
            request_payload={"max_rows": 1},
        )
        _, count2 = render_bundle(req2)
        assert count2 == 1

    def test_empty_cohort_renders_empty_bundle(self, open_dsa):
        from apps.data_requests.bundles import render_bundle
        req = DataRequest.objects.create(
            dsa=open_dsa, requester="p5", request_payload={},
        )
        body, count = render_bundle(req)
        assert body == b""
        assert count == 0

    def test_prepare_and_deliver_locks_hash_and_persists(
        self, geo_and_households, open_dsa, django_user_model,
    ):
        from apps.data_requests.bundles import (
            get_bundle,
            prepare_and_deliver,
        )
        req = DataRequest.objects.create(
            dsa=open_dsa, requester="p6", request_payload={},
        )
        submit_data_request(req)
        approve_data_request(req, approver="dpo-x")
        prepare_and_deliver(req, actor="render-bot")
        req.refresh_from_db()
        assert req.status == RequestStatus.DELIVERED
        assert len(req.manifest_sha256) == 64
        # Bundle retrievable by hash.
        assert get_bundle(req.manifest_sha256) is not None

    def test_render_and_deliver_via_api(
        self, geo_and_households, open_dsa, django_user_model,
    ):
        u = django_user_model.objects.create_user(
            username="ops", password="p", is_superuser=True, is_staff=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        req = DataRequest.objects.create(
            dsa=open_dsa, requester="p7", request_payload={},
        )
        submit_data_request(req)
        approve_data_request(req, approver="dpo-y")
        r = c.post(f"/api/v1/drs/requests/{req.id}/render-and-deliver/")
        assert r.status_code == 200
        assert r.data["status"] == RequestStatus.DELIVERED
        assert r.data["row_count_delivered"] == 4


class TestExpirySweep:
    """S5-006 — `expire_data_requests` management command flips
    DELIVERED rows past expires_at to EXPIRED. Idempotent + safe to
    re-run."""

    @pytest.fixture
    def delivered_past_due(self, draft_request):
        """Take a DataRequest through to DELIVERED, then back-date
        expires_at into the past so the sweep should pick it up."""
        from datetime import timedelta

        from django.utils import timezone
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(
            draft_request, manifest_sha256="a" * 64, row_count=1,
            actor="export-bot",
        )
        draft_request.expires_at = timezone.now() - timedelta(hours=1)
        draft_request.save(update_fields=["expires_at"])
        return draft_request

    def test_command_expires_past_due_delivered(
        self, delivered_past_due, capsys,
    ):
        from django.core.management import call_command
        call_command("expire_data_requests")
        delivered_past_due.refresh_from_db()
        assert delivered_past_due.status == RequestStatus.EXPIRED
        out = capsys.readouterr().out
        assert "expired=1" in out

    def test_command_skips_not_yet_due(self, draft_request, capsys):
        """A DELIVERED row whose expires_at is in the future is NOT
        touched."""
        from django.core.management import call_command
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(
            draft_request, manifest_sha256="b" * 64, row_count=2,
            actor="export-bot",
        )
        # Default TTL leaves expires_at 30 days in the future.
        call_command("expire_data_requests")
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.DELIVERED
        out = capsys.readouterr().out
        assert "expired=0" in out

    def test_command_is_idempotent_on_re_run(
        self, delivered_past_due, capsys,
    ):
        from django.core.management import call_command
        call_command("expire_data_requests")
        # Second run: the row is already EXPIRED so it's outside the
        # candidate filter (status=DELIVERED) and the sweep is a no-op.
        capsys.readouterr()  # drain first-run output
        call_command("expire_data_requests")
        out = capsys.readouterr().out
        assert "candidates=0" in out
        assert "errors=0" in out

    def test_command_records_custom_actor(self, delivered_past_due):
        from django.core.management import call_command

        from apps.security.models import AuditEvent
        call_command("expire_data_requests", "--actor", "nightly-cron")
        ev = AuditEvent.objects.filter(
            entity_type="data_request", action="expire",
        ).first()
        assert ev is not None
        assert ev.actor_id == "nightly-cron"


class TestBundleMembersEmbedding:
    """S6-002 — members array is included in each household row when
    the DSA either grants member.* explicitly or is unrestricted.
    Field-level filtering still applies to each member's columns;
    soft-deleted members are excluded."""

    @pytest.fixture
    def hh_with_members(self, db, partner):
        from datetime import date

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        parent = None
        for level in ("region", "sub_region", "district", "county",
                      "sub_county", "parish", "village"):
            node = GeographicUnit.objects.create(
                level=level,
                code=(f"M-{level}" if level != "sub_region" else "M-SR"),
                name=f"M-{level}", parent=parent,
                effective_from=date(2026, 1, 1),
            )
            nodes[level] = node
            parent = node
        hh = Household.objects.create(
            region=nodes["region"], sub_region=nodes["sub_region"],
            district=nodes["district"], county=nodes["county"],
            sub_county=nodes["sub_county"], parish=nodes["parish"],
            village=nodes["village"], urban_rural="rural",
        )
        Member.objects.create(
            household=hh, line_number=1, surname="Okello",
            first_name="James", sex="M", nin_last4="00AB",
        )
        Member.objects.create(
            household=hh, line_number=2, surname="Okello",
            first_name="Mary", sex="F",
        )
        # Soft-deleted member — must NOT appear in the bundle.
        Member.objects.create(
            household=hh, line_number=3, surname="Okello",
            first_name="Deleted", sex="M",
            is_deleted=True,
        )
        return hh

    def test_open_dsa_embeds_live_members(self, hh_with_members, partner):
        import json

        from apps.data_requests.bundles import render_bundle
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-MEM-OPEN",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="p", request_payload={},
        )
        body, _ = render_bundle(req)
        row = json.loads(body.splitlines()[0])
        members = row["members"]
        # Two live, one soft-deleted -> 2 in the export.
        assert len(members) == 2
        # Ordered by line_number.
        assert members[0]["member.line_number"] == 1
        assert members[1]["member.line_number"] == 2
        # Default member fields are present.
        assert members[0]["member.first_name"] == "James"
        assert members[0]["member.nin_last4"] == "00AB"

    def test_explicit_member_grant_filters_member_fields(
        self, hh_with_members, partner,
    ):
        import json

        from apps.data_requests.bundles import render_bundle
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-MEM-NARROW",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={
                "fields": [
                    "household.id",
                    "member.line_number", "member.first_name", "member.sex",
                ],
            },
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="p2", request_payload={},
        )
        body, _ = render_bundle(req)
        row = json.loads(body.splitlines()[0])
        assert set(row.keys()) == {"household.id", "members"}
        # Each member row carries ONLY the whitelisted member fields.
        m0 = row["members"][0]
        assert set(m0.keys()) == {
            "member.line_number", "member.first_name", "member.sex",
        }
        # NIN columns NOT present — they were not whitelisted.
        assert "member.nin_hash" not in m0
        assert "member.nin_last4" not in m0

    def test_household_only_dsa_excludes_members_key(
        self, hh_with_members, partner,
    ):
        """A DSA whose `fields` lists only household.* keys must NOT
        embed the members array at all — the partner has no scope on
        any member.* column, so the array would leak."""
        import json

        from apps.data_requests.bundles import render_bundle
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-NO-MEM",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={"fields": ["household.id"]},
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="p3", request_payload={},
        )
        body, _ = render_bundle(req)
        row = json.loads(body.splitlines()[0])
        assert "members" not in row

    def test_nin_hash_grant_renders_hex(self, hh_with_members, partner):
        """When the DSA explicitly grants member.nin_hash, the binary
        column surfaces as a hex string so the bundle stays JSON-safe."""
        import json

        from apps.data_management.models import Member
        from apps.data_requests.bundles import render_bundle
        from apps.security.hashing import nin_hash as _nh
        # Plant a NIN hash on the first member.
        m = Member.objects.filter(household=hh_with_members,
                                  line_number=1).first()
        m.nin_hash = _nh("CM1234567890AB")
        m.save(update_fields=["nin_hash"])

        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-NIN",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={
                "fields": ["household.id", "member.nin_hash"],
            },
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="p4", request_payload={},
        )
        body, _ = render_bundle(req)
        row = json.loads(body.splitlines()[0])
        m0 = row["members"][0]
        # Hash exported as 64-char hex (SHA-256), not raw bytes.
        assert len(m0["member.nin_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in m0["member.nin_hash"])

    def test_dsa_scope_validation_rejects_unknown_member_field(self, partner):
        """A request asking for member.* fields the DSA hasn't granted
        must be rejected at submit, not silently dropped."""
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-FIELD-GUARD",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={"fields": ["household.id"]},
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="p5",
            request_payload={"fields": ["household.id", "member.nin_hash"]},
        )
        with pytest.raises(DrsError, match="outside DSA scope"):
            submit_data_request(req)


class TestBundleStorageSeam:
    """S6-003 — BundleStorage Protocol with swappable backends.
    Memory backend handles dev/CI; MinIO is the prod placeholder
    that raises until DRS-O-02 closes."""

    def test_default_backend_is_memory(self, db, settings):
        from apps.data_requests.storage import (
            InMemoryBundleStorage,
            get_bundle_storage,
        )
        settings.DRS_BUNDLE_STORAGE = "memory"
        assert isinstance(get_bundle_storage(), InMemoryBundleStorage)

    def test_memory_backend_round_trips(self, db, settings):
        from apps.data_requests.storage import get_bundle_storage
        settings.DRS_BUNDLE_STORAGE = "memory"
        storage = get_bundle_storage()
        storage._reset_for_tests()
        storage.put("abc", b"hello")
        assert storage.exists("abc")
        assert storage.get("abc") == b"hello"
        assert storage.get("missing") is None

    def test_memory_put_is_idempotent(self, db, settings):
        from apps.data_requests.storage import get_bundle_storage
        settings.DRS_BUNDLE_STORAGE = "memory"
        storage = get_bundle_storage()
        storage._reset_for_tests()
        # Same hash + same bytes -> single entry (content-addressable).
        storage.put("hh1", b"contents")
        storage.put("hh1", b"contents")
        assert storage.get("hh1") == b"contents"

    def test_minio_backend_placeholder_raises(self, db, settings):
        from apps.data_requests.storage import get_bundle_storage
        settings.DRS_BUNDLE_STORAGE = "minio"
        storage = get_bundle_storage()
        with pytest.raises(NotImplementedError, match="DRS-O-02"):
            storage.put("h", b"x")
        with pytest.raises(NotImplementedError, match="DRS-O-02"):
            storage.get("h")
        with pytest.raises(NotImplementedError, match="DRS-O-02"):
            storage.exists("h")

    def test_unknown_backend_raises_value_error(self, db, settings):
        from apps.data_requests.storage import get_bundle_storage
        settings.DRS_BUNDLE_STORAGE = "s3"
        with pytest.raises(ValueError, match="DRS_BUNDLE_STORAGE"):
            get_bundle_storage()

    def test_factory_re_reads_setting_per_call(self, db, settings):
        from apps.data_requests.storage import (
            InMemoryBundleStorage,
            MinIOBundleStorage,
            get_bundle_storage,
        )
        settings.DRS_BUNDLE_STORAGE = "memory"
        assert isinstance(get_bundle_storage(), InMemoryBundleStorage)
        settings.DRS_BUNDLE_STORAGE = "minio"
        assert isinstance(get_bundle_storage(), MinIOBundleStorage)

    def test_put_bundle_routes_through_factory(self, db, settings):
        from apps.data_requests.bundles import get_bundle, put_bundle
        from apps.data_requests.storage import get_bundle_storage
        settings.DRS_BUNDLE_STORAGE = "memory"
        get_bundle_storage()._reset_for_tests()
        put_bundle("seam-hash", b"seam-bytes")
        assert get_bundle("seam-hash") == b"seam-bytes"


class TestExpiryTask:
    """S6-004 — expire_data_requests_task wraps the same logic as the
    S5-006 management command. Tests invoke .run() directly."""

    def test_task_expires_past_due(self, draft_request):
        from datetime import timedelta

        from django.utils import timezone

        from apps.data_requests.tasks import expire_data_requests_task
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(
            draft_request, manifest_sha256="c" * 64, row_count=1,
            actor="export-bot",
        )
        draft_request.expires_at = timezone.now() - timedelta(hours=1)
        draft_request.save(update_fields=["expires_at"])

        result = expire_data_requests_task.run()
        assert result == {"candidates": 1, "expired": 1, "errors": 0}
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.EXPIRED

    def test_task_skips_not_yet_due(self, draft_request):
        from apps.data_requests.tasks import expire_data_requests_task
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(
            draft_request, manifest_sha256="d" * 64, row_count=2,
            actor="export-bot",
        )
        # Default 30d TTL — still in the future.
        result = expire_data_requests_task.run()
        assert result == {"candidates": 0, "expired": 0, "errors": 0}
        draft_request.refresh_from_db()
        assert draft_request.status == RequestStatus.DELIVERED

    def test_task_audit_actor_defaults_to_celery_beat(self, draft_request):
        from datetime import timedelta

        from django.utils import timezone

        from apps.data_requests.tasks import expire_data_requests_task
        from apps.security.models import AuditEvent
        submit_data_request(draft_request)
        approve_data_request(draft_request, approver="dpo-1")
        deliver_data_request(
            draft_request, manifest_sha256="e" * 64, row_count=1,
            actor="export-bot",
        )
        draft_request.expires_at = timezone.now() - timedelta(hours=1)
        draft_request.save(update_fields=["expires_at"])

        expire_data_requests_task.run()
        ev = AuditEvent.objects.filter(
            entity_type="data_request", action="expire",
        ).first()
        assert ev.actor_id == "celery-beat"


class TestPartnerSelfService:
    """S7-004 — GET /api/v1/drs/requests/mine/ uses the same
    PartnerScopedQuerysetMixin filter as the main list, but renders
    with a slim partner-facing serializer (no admin fields)."""

    @pytest.fixture
    def two_partners_with_requests(self, db):
        p_a = Partner.objects.create(code="P-A", name="Partner A")
        p_b = Partner.objects.create(code="P-B", name="Partner B")
        d_a = DataSharingAgreement.objects.create(
            partner=p_a, reference="DSA-MINE-A",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        d_b = DataSharingAgreement.objects.create(
            partner=p_b, reference="DSA-MINE-B",
            status=DsaStatus.ACTIVE,
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        r_a = DataRequest.objects.create(
            dsa=d_a, requester="a-analyst", request_payload={},
        )
        r_b = DataRequest.objects.create(
            dsa=d_b, requester="b-analyst", request_payload={},
        )
        return p_a, p_b, r_a, r_b

    def test_partner_sees_only_own_requests(
        self, two_partners_with_requests, django_user_model,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _, r_a, _ = two_partners_with_requests
        u = django_user_model.objects.create_user(
            username="a-analyst", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/drs/requests/mine/")
        assert r.status_code == 200
        results = r.data["results"] if isinstance(r.data, dict) else r.data
        assert len(results) == 1
        assert results[0]["id"] == r_a.id

    def test_serializer_omits_admin_fields(
        self, two_partners_with_requests, django_user_model,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _, _, _ = two_partners_with_requests
        u = django_user_model.objects.create_user(
            username="a-analyst-2", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/drs/requests/mine/")
        row = (r.data["results"] if isinstance(r.data, dict) else r.data)[0]
        # Slim shape: keys explicitly include dsa_reference + download_url,
        # explicitly EXCLUDE admin/internal fields.
        assert set(row.keys()) == {
            "id", "dsa_reference", "status", "submitted_at",
            "delivered_at", "expires_at", "manifest_sha256",
            "row_count_delivered", "download_url",
        }
        assert "decision_reason" not in row
        assert "approver" not in row
        assert "requester" not in row
        assert "request_payload" not in row

    def test_download_url_null_when_not_delivered(
        self, two_partners_with_requests, django_user_model,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _, _, _ = two_partners_with_requests
        u = django_user_model.objects.create_user(
            username="a-analyst-3", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/drs/requests/mine/")
        row = (r.data["results"] if isinstance(r.data, dict) else r.data)[0]
        # DRAFT request -> no download URL.
        assert row["download_url"] is None

    def test_download_url_set_when_delivered(
        self, two_partners_with_requests, django_user_model,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _, r_a, _ = two_partners_with_requests
        # Move r_a through the lifecycle to DELIVERED.
        submit_data_request(r_a)
        approve_data_request(r_a, approver="dpo-x")
        deliver_data_request(
            r_a, manifest_sha256="f" * 64, row_count=3, actor="export",
        )
        u = django_user_model.objects.create_user(
            username="a-analyst-4", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/drs/requests/mine/")
        row = (r.data["results"] if isinstance(r.data, dict) else r.data)[0]
        assert row["status"] == RequestStatus.DELIVERED
        assert row["download_url"] == f"/api/v1/drs/requests/{r_a.id}/download/"

    def test_unaffiliated_user_sees_empty(
        self, two_partners_with_requests, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="ghost", password="p")
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get("/api/v1/drs/requests/mine/")
        assert r.status_code == 200
        results = r.data["results"] if isinstance(r.data, dict) else r.data
        assert results == []
