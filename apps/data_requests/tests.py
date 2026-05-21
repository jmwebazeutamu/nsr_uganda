"""API-DRS tests — DSA scope validation, lifecycle, audit, API."""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_requests.models import DataRequest, RequestStatus
from apps.data_requests.services import (
    DrsError,
    approve_data_request,
    deliver_data_request,
    expire_data_request,
    reject_data_request,
    submit_data_request,
    validate_against_dsa,
)
from apps.data_requests.test_helpers import make_dsa, make_partner
from apps.security.models import AuditEvent


@pytest.fixture
def partner(db):
    return make_partner(code="PDM-MGLSD", name="PDM Programme Office")


@pytest.fixture
def active_dsa(partner):
    return make_dsa(
        partner=partner, reference="DSA-PDM-2026-01",
        purpose="Cohort enrolment", status="active",
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

    def test_extra_group_rejected(self, active_dsa):
        # Per ADR-0013 field_scope gates at group level. DSA grants
        # `household` group; asking for `member` triggers a violation.
        with pytest.raises(DrsError, match="fields="):
            validate_against_dsa(
                {"fields": ["household.id", "member.surname"]}, active_dsa,
            )

    def test_extra_sub_region_rejected(self, active_dsa):
        with pytest.raises(DrsError, match="sub_region_codes="):
            validate_against_dsa(
                {"sub_region_codes": ["SR-BUGANDA", "SR-WESTNILE"]}, active_dsa,
            )

    def test_extra_district_rejected(self, active_dsa):
        # US-S27-016 — the validator walks every UBOS level on the
        # DSA's geographic_scope. A DSA may scope at any level
        # (ADR-0011 §4); the wizard now lets the partner build
        # queries on each. Set up two district-level units; only
        # one is in scope; payload asks for both → reject.
        from apps.reference_data.models import GeographicUnit
        d1 = GeographicUnit.objects.create(
            level="district", code="DST-KAMPALA", name="Kampala",
            effective_from=date(2026, 1, 1),
        )
        GeographicUnit.objects.create(
            level="district", code="DST-MOROTO", name="Moroto",
            effective_from=date(2026, 1, 1),
        )
        active_dsa.geographic_scope.add(d1)
        with pytest.raises(DrsError, match="district_codes="):
            validate_against_dsa(
                {"district_codes": ["DST-KAMPALA", "DST-MOROTO"]},
                active_dsa,
            )

    def test_district_unrestricted_when_dsa_silent(self, active_dsa):
        # DSA has sub_region scope but no district-level rows.
        # A payload asking for district codes must pass — the DSA
        # didn't constrain that level.
        validate_against_dsa(
            {"district_codes": ["DST-WHATEVER", "DST-OTHER"]},
            active_dsa,
        )

    def test_row_cap_enforced(self, active_dsa):
        with pytest.raises(DrsError, match="max_rows"):
            validate_against_dsa({"max_rows": 50001}, active_dsa)

    def test_missing_dsa_key_means_unrestricted(self, partner):
        dsa = make_dsa(
            partner=partner, reference="DSA-X", status="active",
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
        active_dsa.status = "suspended"
        active_dsa.save(update_fields=["status"])
        req = DataRequest.objects.create(dsa=active_dsa, requester="x",
                                         request_payload={})
        with pytest.raises(DrsError, match="not active"):
            submit_data_request(req)

    def test_expired_dsa_blocks_submit(self, partner):
        dsa = make_dsa(
            partner=partner, reference="DSA-OLD", status="active",
            valid_from=date(2020, 1, 1), valid_to=date(2024, 12, 31),
            allowed_scopes={},
        )
        req = DataRequest.objects.create(dsa=dsa, requester="x",
                                         request_payload={})
        with pytest.raises(DrsError, match="effective window"):
            submit_data_request(req)

    def test_scope_violation_blocks_submit(self, active_dsa):
        # Cross-group violation per ADR-0013's coarser field_scope.
        req = DataRequest.objects.create(
            dsa=active_dsa, requester="x",
            request_payload={"fields": ["member.surname"]},
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
            "request_payload": {"fields": ["member.surname"]},
        }, format="json")
        req_id = r.data["id"]
        r = c.post(f"/api/v1/drs/requests/{req_id}/submit/")
        assert r.status_code == 400
        # Per ADR-0013 the validator gates at group level; the offender
        # is the `member` group, not the specific field name.
        assert "member" in r.data["detail"]


class TestPartnerAbac:
    """Partner-affiliated users see only DataRequests under DSAs
    belonging to their Partner. NSR Unit (national) and superusers see
    all. Mirrors the geographic ABAC story for personal-data viewsets
    but uses org-affiliation as the visibility lens."""

    @pytest.fixture
    def two_partners(self, db):
        p_a = make_partner(code="PARTNER-A", name="Partner A")
        p_b = make_partner(code="PARTNER-B", name="Partner B")
        return p_a, p_b

    @pytest.fixture
    def dsas(self, two_partners):
        p_a, p_b = two_partners
        d_a = make_dsa(
            partner=p_a, reference="DSA-A-1", status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        d_b = make_dsa(
            partner=p_b, reference="DSA-B-1", status="active",
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
        self, db, django_user_model, two_partners, dsas, settings,
    ):
        # Per ADR-0013 the DSA endpoint moved to /api/v1/dsas/
        # (apps.partners.api.DsaViewSet). Reads stay open under the
        # PartnerScopedQuerysetMixin sourced through apps.security.abac.
        settings.PARTNERS_MODULE_ENABLED = True
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _ = two_partners
        d_a, _ = dsas
        u = django_user_model.objects.create_user(username="partner-a-dpo", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        r = self._client_for(u).get("/api/v1/dsas/")
        assert r.status_code == 200
        ids = [d["id"] for d in r.data["results"]]
        assert d_a.id in ids
        # ABAC enforces partner scope — partner A should not see partner B's DSAs.
        from apps.partners.models import DataSharingAgreement
        other_id = (
            DataSharingAgreement.objects.exclude(partner=p_a)
            .values_list("id", flat=True).first()
        )
        if other_id:
            assert other_id not in ids

    def test_partner_scope_also_filters_partners_list(
        self, db, django_user_model, two_partners,
    ):
        # Partner listing moved to /api/v1/partners/ per ADR-0013.
        from apps.security.models import OperatorScope, ScopeLevel
        p_a, _ = two_partners
        u = django_user_model.objects.create_user(username="partner-a-staff", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_a.code,
        )
        r = self._client_for(u).get("/api/v1/partners/")
        assert r.status_code == 200
        codes = [p["code"] for p in r.data["results"]]
        assert p_a.code in codes


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
                    village=nodes["village"], urban_rural="2",
                )
                out[sr_key].append(hh)
        return out

    @pytest.fixture
    def open_dsa(self, partner):
        """DSA with no field/region restrictions — exports everything."""
        return make_dsa(
            partner=partner, reference="DSA-OPEN-1",
            status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )

    @pytest.fixture
    def restricted_dsa(self, partner):
        """DSA restricted to BUGANDA + a subset of fields."""
        return make_dsa(
            partner=partner, reference="DSA-RESTRICTED-1",
            status="active",
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
        # Per ADR-0013 field_scope gates at group level — every
        # household.* field appears since the DSA granted the
        # `household` group. Cross-group fields stay clipped.
        assert all(k.startswith("household.") for k in first if k != "members")
        assert "members" not in first
        # The visible row IS a BUGANDA one.
        assert first["household.sub_region_code"] == "B-SR-BUGANDA"

    def test_max_rows_uses_tighter_of_dsa_and_payload(
        self, geo_and_households, open_dsa,
    ):
        from apps.data_requests.bundles import render_bundle
        # DSA cap 3, request asks 5 → 3 wins.
        open_dsa.monthly_row_budget = 3
        open_dsa.save(update_fields=["monthly_row_budget"])
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
            village=nodes["village"], urban_rural="2",
        )
        Member.objects.create(
            household=hh, line_number=1, surname="Okello",
            first_name="James", sex="1", nin_last4="00AB",
        )
        Member.objects.create(
            household=hh, line_number=2, surname="Okello",
            first_name="Mary", sex="2",
        )
        # Soft-deleted member — must NOT appear in the bundle.
        Member.objects.create(
            household=hh, line_number=3, surname="Okello",
            first_name="Deleted", sex="1",
            is_deleted=True,
        )
        return hh

    def test_open_dsa_embeds_live_members(self, hh_with_members, partner):
        import json

        from apps.data_requests.bundles import render_bundle
        dsa = make_dsa(
            partner=partner, reference="DSA-MEM-OPEN",
            status="active",
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
        dsa = make_dsa(
            partner=partner, reference="DSA-MEM-NARROW",
            status="active",
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
        # Per ADR-0013 field_scope is group-level: granting `household`
        # + `member` groups means every household.* + member.* field
        # from the FIELD_CATALOGUE appears. Cross-group keys stay
        # absent.
        assert all(k.startswith("household.") or k == "members" for k in row)
        assert "members" in row
        m0 = row["members"][0]
        # Every member.* field in the catalogue is present.
        assert all(k.startswith("member.") for k in m0)
        # The granted fields specifically appear (subset check).
        assert {"member.line_number", "member.first_name", "member.sex"} <= set(m0.keys())

    def test_household_only_dsa_excludes_members_key(
        self, hh_with_members, partner,
    ):
        """A DSA whose `fields` lists only household.* keys must NOT
        embed the members array at all — the partner has no scope on
        any member.* column, so the array would leak."""
        import json

        from apps.data_requests.bundles import render_bundle
        dsa = make_dsa(
            partner=partner, reference="DSA-NO-MEM",
            status="active",
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

        dsa = make_dsa(
            partner=partner, reference="DSA-NIN",
            status="active",
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
        dsa = make_dsa(
            partner=partner, reference="DSA-FIELD-GUARD",
            status="active",
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
        p_a = make_partner(code="P-A", name="Partner A")
        p_b = make_partner(code="P-B", name="Partner B")
        d_a = make_dsa(
            partner=p_a, reference="DSA-MINE-A",
            status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        d_b = make_dsa(
            partner=p_b, reference="DSA-MINE-B",
            status="active",
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


class TestPartnerDownload:
    """S8-003 — /api/v1/drs/requests/{id}/download/ returns the
    rendered NDJSON bundle bytes for DELIVERED requests, scoped by
    PartnerScope and audit-logged."""

    @pytest.fixture
    def partner_with_dsa(self, db, partner):
        from apps.data_management.models import Household
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        parent = None
        for level in ("region", "sub_region", "district", "county",
                      "sub_county", "parish", "village"):
            n = GeographicUnit.objects.create(
                level=level,
                code=(f"DL-{level}" if level != "sub_region" else "DL-SR"),
                name=level, parent=parent,
                effective_from=date(2026, 1, 1),
            )
            nodes[level] = n
            parent = n
        Household.objects.create(
            region=nodes["region"], sub_region=nodes["sub_region"],
            district=nodes["district"], county=nodes["county"],
            sub_county=nodes["sub_county"], parish=nodes["parish"],
            village=nodes["village"], urban_rural="2",
        )
        dsa = make_dsa(
            partner=partner, reference="DSA-DL-1",
            status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={},
        )
        return dsa

    def _client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_download_returns_ndjson_for_delivered(
        self, partner_with_dsa, django_user_model,
    ):
        from apps.data_requests.bundles import prepare_and_deliver
        from apps.security.models import OperatorScope, ScopeLevel
        req = DataRequest.objects.create(
            dsa=partner_with_dsa, requester="p", request_payload={},
        )
        submit_data_request(req)
        approve_data_request(req, approver="dpo-x")
        prepare_and_deliver(req, actor="render-bot")

        u = django_user_model.objects.create_user(
            username="partner-analyst", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER,
            scope_code=partner_with_dsa.partner.code,
        )
        r = self._client_for(u).get(f"/api/v1/drs/requests/{req.id}/download/")
        assert r.status_code == 200
        assert r["content-type"] == "application/x-ndjson"
        assert f"data-request-{req.id}.ndjson" in r["content-disposition"]
        # NDJSON: each line is a JSON object.
        assert b'"household.id"' in r.content

    def test_download_404_when_not_delivered(
        self, partner_with_dsa, django_user_model,
    ):
        from apps.security.models import OperatorScope, ScopeLevel
        req = DataRequest.objects.create(
            dsa=partner_with_dsa, requester="p2", request_payload={},
        )
        # DRAFT — no bundle.
        u = django_user_model.objects.create_user(
            username="partner-analyst-2", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER,
            scope_code=partner_with_dsa.partner.code,
        )
        r = self._client_for(u).get(f"/api/v1/drs/requests/{req.id}/download/")
        assert r.status_code == 404
        assert "DELIVERED" in r.data["detail"]

    def test_download_scoped_to_partner(
        self, partner_with_dsa, django_user_model,
    ):
        """A partner-A user must NOT download a partner-B request's
        bundle. PartnerScopedQuerysetMixin already gates the list;
        get_object() therefore 404s on the detail route."""
        from apps.data_requests.bundles import prepare_and_deliver
        from apps.security.models import OperatorScope, ScopeLevel

        # Take partner-A's request to DELIVERED.
        req = DataRequest.objects.create(
            dsa=partner_with_dsa, requester="p", request_payload={},
        )
        submit_data_request(req)
        approve_data_request(req, approver="dpo-x")
        prepare_and_deliver(req, actor="render-bot")

        # A different partner.
        p_b = make_partner(code="P-OTHER", name="Other Partner")
        u = django_user_model.objects.create_user(
            username="other-partner-analyst", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code=p_b.code,
        )
        r = self._client_for(u).get(f"/api/v1/drs/requests/{req.id}/download/")
        # Out of scope -> 404 (the row simply isn't in this user's queryset).
        assert r.status_code == 404

    def test_download_throttled_when_rate_exceeded(
        self, partner_with_dsa, django_user_model,
    ):
        """S9-003 — the bundle-download action carries a scoped
        DownloadRateThrottle. Patch its class-level THROTTLE_RATES
        to 2/min so the third call within the window 429s. DRF
        caches THROTTLE_RATES on the throttle class at import time,
        so a settings override alone doesn't propagate."""
        from django.core.cache import cache

        from apps.data_requests.api import DownloadRateThrottle
        from apps.data_requests.bundles import prepare_and_deliver
        from apps.security.models import OperatorScope, ScopeLevel

        cache.clear()
        original = DownloadRateThrottle.THROTTLE_RATES
        DownloadRateThrottle.THROTTLE_RATES = {
            **original, "drs-download": "2/min",
        }
        try:
            req = DataRequest.objects.create(
                dsa=partner_with_dsa, requester="p", request_payload={},
            )
            submit_data_request(req)
            approve_data_request(req, approver="dpo-x")
            prepare_and_deliver(req, actor="render-bot")

            u = django_user_model.objects.create_user(
                username="hammer", password="p",
            )
            OperatorScope.objects.create(
                user=u, scope_level=ScopeLevel.PARTNER,
                scope_code=partner_with_dsa.partner.code,
            )
            c = self._client_for(u)
            url = f"/api/v1/drs/requests/{req.id}/download/"
            assert c.get(url).status_code == 200  # call 1
            assert c.get(url).status_code == 200  # call 2
            # Third call within the same minute -> 429.
            r = c.get(url)
            assert r.status_code == 429
        finally:
            DownloadRateThrottle.THROTTLE_RATES = original
            cache.clear()

    def test_download_emits_audit_event(
        self, partner_with_dsa, django_user_model,
    ):
        from apps.data_requests.bundles import prepare_and_deliver
        from apps.security.models import AuditEvent, OperatorScope, ScopeLevel
        req = DataRequest.objects.create(
            dsa=partner_with_dsa, requester="p", request_payload={},
        )
        submit_data_request(req)
        approve_data_request(req, approver="dpo-x")
        prepare_and_deliver(req, actor="render-bot")

        u = django_user_model.objects.create_user(
            username="auditing-partner", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER,
            scope_code=partner_with_dsa.partner.code,
        )
        self._client_for(u).get(f"/api/v1/drs/requests/{req.id}/download/")

        ev = AuditEvent.objects.filter(
            entity_type="data_request", entity_id=req.id,
            action="download",
        ).first()
        assert ev is not None
        assert ev.actor_id == "auditing-partner"
        # Manifest fingerprint logged (first 8 chars only — full hash
        # is in the row, no need to duplicate in the audit reason).
        assert "manifest=" in ev.reason


# --- BUG-S11-002a — builder-schema endpoint + role parity -------------


class TestBuilderSchema:
    """Contract: /api/v1/drs/builder-schema/ returns the SAME top-level
    keys for every role. Values differ (partner sees disabled flags
    based on DSA; operator sees everything enabled) but the structure
    is invariant — frontend renders one component regardless of role."""

    EXPECTED_TOP_LEVEL_KEYS = {
        "role", "dsa_id", "dsa_reference", "fields",
        "filter_operators", "filter_fields", "delivery_methods",
    }
    EXPECTED_FILTER_FIELD_KEYS = {
        "key", "label", "operators", "value_source", "value_type",
        "payload_key", "value_code_field", "value_label_field",
    }
    # US-S27-013: a builder-schema field carries these keys at minimum.
    # `label`, `type` are required; `options` / `options_source` appear
    # on enum-typed fields only.
    REQUIRED_FIELD_KEYS = {
        "group", "key", "label", "sensitivity", "type",
        "disabled", "disabled_reason",
    }
    OPTIONAL_FIELD_KEYS = {"options", "options_source", "requires_special_scope"}

    @pytest.fixture
    def operator_client(self, db, django_user_model):
        u = django_user_model.objects.create_user(
            username="nsr-unit-op", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    @pytest.fixture
    def partner_with_narrow_dsa(self, db):
        partner = make_partner(code="PARTNER-N", name="Narrow Partner")
        make_dsa(
            partner=partner, reference="DSA-NARROW-1",
            status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={"fields": [
                "household.id", "household.sub_region_code",
                "member.first_name", "member.sex",
            ]},
        )
        return partner

    @pytest.fixture
    def partner_client(self, db, partner_with_narrow_dsa, django_user_model):
        from apps.security.models import OperatorScope, ScopeLevel
        u = django_user_model.objects.create_user(
            username="partner-analyst-x", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER,
            scope_code=partner_with_narrow_dsa.code,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def test_operator_response_top_level_shape(self, operator_client):
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        assert r.status_code == 200
        assert set(r.data.keys()) == self.EXPECTED_TOP_LEVEL_KEYS

    def test_partner_response_top_level_shape(self, partner_client):
        r = partner_client.get("/api/v1/drs/requests/builder-schema/")
        assert r.status_code == 200
        assert set(r.data.keys()) == self.EXPECTED_TOP_LEVEL_KEYS

    def test_role_parity_top_level_keys_identical(
        self, operator_client, partner_client,
    ):
        """The contract — same key set on the response. Values
        differ; structure must not. A regression here breaks the
        unified frontend builder (BUG-S11-002b)."""
        op_keys = set(operator_client.get("/api/v1/drs/requests/builder-schema/").data.keys())
        p_keys = set(partner_client.get("/api/v1/drs/requests/builder-schema/").data.keys())
        assert op_keys == p_keys

    def test_role_parity_field_count_identical(
        self, operator_client, partner_client,
    ):
        """The fields list has the same length and same keys for
        both roles — the partner just sees `disabled: true` on
        fields outside their DSA, never a missing entry."""
        op_fields = operator_client.get("/api/v1/drs/requests/builder-schema/").data["fields"]
        p_fields = partner_client.get("/api/v1/drs/requests/builder-schema/").data["fields"]
        assert len(op_fields) == len(p_fields)
        assert [f["key"] for f in op_fields] == [f["key"] for f in p_fields]

    def test_each_field_has_expected_keys(self, operator_client):
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        allowed = self.REQUIRED_FIELD_KEYS | self.OPTIONAL_FIELD_KEYS
        for f in r.data["fields"]:
            keys = set(f.keys())
            assert self.REQUIRED_FIELD_KEYS <= keys, (
                f"{f.get('key')}: missing {self.REQUIRED_FIELD_KEYS - keys}"
            )
            assert keys <= allowed, (
                f"{f.get('key')}: unknown {keys - allowed}"
            )
            # Type must be one the wizard knows how to render.
            assert f["type"] in {"text", "enum", "enum-multi",
                                  "number", "date", "bool"}

    def test_every_enum_field_advertises_options(self, operator_client):
        # Enum-typed fields must carry either inline `options` (a
        # static list) or `options_source` (a slug the wizard
        # translates to a fetch URL). One or the other; not both.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        for f in r.data["fields"]:
            if f["type"] not in ("enum", "enum-multi"):
                continue
            has_inline = "options" in f
            has_source = "options_source" in f
            assert has_inline ^ has_source, (
                f"{f['key']}: enum needs exactly one of options / options_source"
            )

    def test_catalogue_covers_household_and_member(self, operator_client):
        # The wizard relies on both household.* and member.* fields
        # being available. US-S27-013 expanded the catalogue to
        # cover both levels.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        keys = {f["key"] for f in r.data["fields"]}
        assert any(k.startswith("household.") for k in keys)
        assert any(k.startswith("member.") for k in keys)

    def test_catalogue_exposes_every_geo_level(self, operator_client):
        # US-S27-016 — every UBOS administrative level is a
        # selectable predicate in the DRS query builder.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        keys = {f["key"] for f in r.data["fields"]}
        for level in (
            "region", "sub_region", "district", "county",
            "sub_county", "parish", "village",
        ):
            assert f"household.{level}_code" in keys, (
                f"missing household.{level}_code in builder-schema"
            )

    def test_catalogue_exposes_detail_entity_columns(self, operator_client):
        # US-S22-DE-09 — the detail-entity tail is selectable from the
        # DRS query builder. One spot-check per detail surface so the
        # contract test fails if the catalogue regresses.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        keys = {f["key"] for f in r.data["fields"]}
        for key in (
            "household.dwelling.tenure",
            "household.utilities.cooking_fuel",
            "household.livelihood.land_hectares",
            "household.food_security.fies_raw_score",
            "household.food_consumption.fcs_score",
            "member.health.chronic_illness_flag",
            "member.disability.wg_disability_flag",
            "member.education.highest_grade",
            "member.employment.sector",
        ):
            assert key in keys, f"missing {key} in builder-schema"

    def test_member_coded_fields_are_enum_with_choice_list_source(
        self, operator_client,
    ):
        # BUG-S27-022 — every Member-level coded field declared in
        # apps/data_management/choice_field_map.py:MEMBER_FIELDS must
        # ship as type:enum with options_source:"choice_list?name=…",
        # NOT as type:text. The list_name in the options_source must
        # match the field-map entry exactly so the wizard's
        # /choice-list-bundle/ fetch picks up the right options.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        by_key = {f["key"]: f for f in r.data["fields"]}
        # Mapping mirrors apps/data_management/choice_field_map.py
        # MEMBER_FIELDS — keep them in sync if either side changes.
        expected = {
            "member.relationship_to_head":   "relationship",
            "member.marital_status":         "marital_status",
            "member.nationality":            "nationality",
            "member.residency_status":       "residency_status",
            "member.birth_certificate_status": "birth_certificate",
            "member.nin_status":             "nin_status",
        }
        for key, list_name in expected.items():
            f = by_key.get(key)
            assert f is not None, f"missing {key} from catalogue"
            assert f["type"] == "enum", (
                f"{key}: expected type=enum (coded field), got {f['type']}"
            )
            assert f.get("options_source") == f"choice_list?name={list_name}", (
                f"{key}: expected options_source=choice_list?name={list_name}, "
                f"got {f.get('options_source')!r}"
            )

    def test_sensitive_columns_require_special_scope(self, operator_client):
        # US-S22-DE-09 — HIV-relevant and NIN-derived columns carry
        # requires_special_scope=True so the wizard surfaces a
        # scope-expansion prompt. DPPA 2019 + ADR-0021.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        by_key = {f["key"]: f for f in r.data["fields"]}
        for key in (
            "member.nin_hash",
            "member.nin_last4",
            "member.health.chronic_illness_types",
        ):
            assert by_key[key].get("requires_special_scope") is True, (
                f"{key}: expected requires_special_scope=True"
            )

    def test_partner_dsa_id_is_populated(
        self, partner_client, partner_with_narrow_dsa,
    ):
        # US-S27-010: the wizard needs the DSA's ULID to POST a
        # DataRequest (the reference alone isn't enough). Partner
        # roles get the active DSA's id; the reference travels
        # alongside it for human-readable display.
        r = partner_client.get("/api/v1/drs/requests/builder-schema/")
        assert r.status_code == 200
        assert r.data["dsa_id"]
        assert r.data["dsa_reference"] == "DSA-NARROW-1"
        dsa = partner_with_narrow_dsa.dsas.get(reference="DSA-NARROW-1")
        assert r.data["dsa_id"] == str(dsa.id)

    def test_operator_dsa_id_is_empty(self, operator_client):
        # Operators don't have a partner DSA — the field is present
        # but empty. Frontend uses this to gate the submit action.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        assert r.status_code == 200
        assert r.data["dsa_id"] == ""

    def test_filter_fields_catalogue_shape(self, operator_client):
        # US-S27-012: builder-schema advertises the predicates the
        # backend actually validates. Each entry tells the query
        # builder where to fetch values from and where the resulting
        # values land in request_payload.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        assert r.status_code == 200
        assert isinstance(r.data["filter_fields"], list)
        assert len(r.data["filter_fields"]) >= 2
        for entry in r.data["filter_fields"]:
            assert set(entry.keys()) == self.EXPECTED_FILTER_FIELD_KEYS
            assert isinstance(entry["operators"], list)
            assert all(isinstance(o, str) for o in entry["operators"])

    def test_filter_fields_payload_keys_match_validator(
        self, operator_client,
    ):
        # The payload_key on each filter_field must be a key the
        # apps.data_requests.services.validate_against_dsa function
        # actually reads. US-S27-016 expanded the geographic
        # predicates to every UBOS level — add to this set as the
        # validator gains a new predicate.
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        keys = {f["payload_key"] for f in r.data["filter_fields"]}
        assert keys <= {
            "region_codes", "sub_region_codes", "district_codes",
            "county_codes", "sub_county_codes", "parish_codes",
            "village_codes",
            "programme_codes",
        }

    def test_operator_sees_all_fields_enabled(self, operator_client):
        r = operator_client.get("/api/v1/drs/requests/builder-schema/")
        for f in r.data["fields"]:
            assert f["disabled"] is False
            assert f["disabled_reason"] == ""
        assert r.data["role"] == "operator"
        assert r.data["dsa_reference"] == ""

    def test_partner_sees_dsa_disabled_flags(self, partner_client):
        # Per ADR-0013 field_scope is group-level. The narrow DSA
        # above granted `household` + `member` groups, so every
        # household.* and member.* field in the catalogue is enabled.
        # Cross-group fields (none in the current catalogue) would
        # be disabled. Tighter per-field gating is OI-S24-3.
        r = partner_client.get("/api/v1/drs/requests/builder-schema/")
        assert r.data["role"] == "partner"
        assert r.data["dsa_reference"] == "DSA-NARROW-1"
        by_key = {f["key"]: f for f in r.data["fields"]}
        # In scope: enabled.
        assert by_key["household.id"]["disabled"] is False
        assert by_key["member.sex"]["disabled"] is False
        # Same group, same coarseness — also enabled under group-level scope.
        assert by_key["member.nin_hash"]["disabled"] is False
        assert by_key["household.gps_lat"]["disabled"] is False

    def test_partner_delivery_methods_filtered(self, partner_client):
        r = partner_client.get("/api/v1/drs/requests/builder-schema/")
        # All returned methods must include 'partner-analyst' in
        # their available_to list; the operator-only ones (if any
        # land later) shouldn't surface here.
        for m in r.data["delivery_methods"]:
            assert "partner-analyst" in m["available_to"]

    def test_filter_operators_invariant_across_roles(
        self, operator_client, partner_client,
    ):
        """Filter operators are intentionally role-agnostic — the
        partner can compose any predicate the operator can; the
        DSA limits FIELDS, not OPS."""
        op = operator_client.get("/api/v1/drs/requests/builder-schema/").data["filter_operators"]
        p = partner_client.get("/api/v1/drs/requests/builder-schema/").data["filter_operators"]
        assert [x["op"] for x in op] == [x["op"] for x in p]

    def test_audit_event_emitted_on_schema_read(
        self, operator_client,
    ):
        from apps.security.models import AuditEvent
        operator_client.get("/api/v1/drs/requests/builder-schema/")
        ev = AuditEvent.objects.filter(
            entity_type="drs_builder_schema", action="schema_read",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert "role=" in ev.reason
