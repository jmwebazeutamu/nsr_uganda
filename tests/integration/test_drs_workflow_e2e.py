"""End-to-end DRS workflow — partner-side build → operator approval →
delivery → partner download (Sprint 27).

This test exercises the FULL chain a real partner walks when the
DRS query wizard (US-S27-010 / 011 / 012 / 013 / 014) submits a
request. It drives the live DRF surface — no mocks for the
validator, no mocks for the lifecycle services. The point is to
prove the wiring CHAIN holds, not any single seam.

  authenticate(partner_user with OperatorScope=PARTNER:E2E-OPM)
    → GET /api/v1/drs/requests/builder-schema/        (US-S27-011/013)
    → POST /api/v1/drs/requests/                       (DRAFT created)
    → POST /api/v1/drs/requests/{id}/submit/           (DRAFT→SUBMITTED)
  authenticate(operator_user, distinct user)
    → POST /api/v1/drs/requests/{id}/approve/          (SUBMITTED→APPROVED)
    → POST /api/v1/drs/requests/{id}/deliver/          (APPROVED→DELIVERED)
  authenticate(partner_user again)
    → GET  /api/v1/drs/requests/{id}/download/         (NDJSON bytes)

Plus the unhappy path: a partner POSTs a sub_region the DSA does
not cover → submit returns 400 with the validator's exact
"outside DSA scope" string and the row stays DRAFT.

The SQLite-only audit chain is not asserted (postgres-only trigger),
but the AuditEvent ROWS themselves are read directly — they are
written via emit() in both backends.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from apps.data_management.models import Household
from apps.data_requests.bundles import put_bundle
from apps.data_requests.models import DataRequest, RequestStatus
from apps.data_requests.test_helpers import make_dsa, make_partner
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent, OperatorScope, ScopeLevel
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

LIST_URL = "/api/v1/drs/requests/"
SCHEMA_URL = "/api/v1/drs/requests/builder-schema/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def geo(db):
    """Seed two sub_regions: one inside the DSA, one outside.

    The household lives in SR-DRS-IN; the unhappy path requests
    SR-DRS-OUT, which is a real GeographicUnit row so the FK side
    of the validator can resolve it, but the DSA's geographic_scope
    M2M only carries SR-DRS-IN.
    """
    region = GeographicUnit.objects.create(
        level="region", code="REG-DRS-E2E", name="DRS E2E Region",
        effective_from=date(2026, 1, 1),
    )
    sr_in = GeographicUnit.objects.create(
        level="sub_region", code="SR-DRS-IN", name="DRS Sub-region (in)",
        parent=region, effective_from=date(2026, 1, 1),
    )
    sr_out = GeographicUnit.objects.create(
        level="sub_region", code="SR-DRS-OUT", name="DRS Sub-region (out)",
        parent=region, effective_from=date(2026, 1, 1),
    )
    district = GeographicUnit.objects.create(
        level="district", code="DIST-DRS", name="DRS District",
        parent=sr_in, effective_from=date(2026, 1, 1),
    )
    county = GeographicUnit.objects.create(
        level="county", code="CTY-DRS", name="DRS County",
        parent=district, effective_from=date(2026, 1, 1),
    )
    subcounty = GeographicUnit.objects.create(
        level="sub_county", code="SCO-DRS", name="DRS Sub-county",
        parent=county, effective_from=date(2026, 1, 1),
    )
    parish = GeographicUnit.objects.create(
        level="parish", code="PAR-DRS", name="DRS Parish",
        parent=subcounty, effective_from=date(2026, 1, 1),
    )
    village = GeographicUnit.objects.create(
        level="village", code="VIL-DRS", name="DRS Village",
        parent=parish, effective_from=date(2026, 1, 1),
    )
    return {
        "region": region, "sr_in": sr_in, "sr_out": sr_out,
        "district": district, "county": county, "sub_county": subcounty,
        "parish": parish, "village": village,
    }


@pytest.fixture
def household(db, geo):
    """One household inside the DSA's sub_region. Render-bundle
    walks Household.objects so we need at least one row to make
    delivery meaningful."""
    return Household.objects.create(
        region=geo["region"], sub_region=geo["sr_in"], district=geo["district"],
        county=geo["county"], sub_county=geo["sub_county"],
        parish=geo["parish"], village=geo["village"],
        sub_region_code="SR-DRS-IN",
        urban_rural="2", current_pmt_score="0.42",
    )


@pytest.fixture
def partner_and_dsa(db, geo):
    """Canonical Partner + active DSA.

    field_scope: {"household": True} so the validator accepts
                 dotted keys household.* but rejects member.*.
    geographic_scope: {SR-DRS-IN} so SR-DRS-OUT is out of scope.
    programmes_allowed: ["PDM"] for completeness; the test payload
                        only references the household-side filters.
    monthly_row_budget: 5000 — well above the test's max_rows=50.
    """
    partner = make_partner(
        code="E2E-OPM", name="E2E Office of the Prime Minister",
    )
    dsa = make_dsa(
        partner=partner, reference="DSA-E2E-S27", status="active",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        allowed_scopes={
            # field_scope ends up as {"household": True}, which the
            # builder_schema expands into all household.* catalogue keys.
            "fields": ["household.id"],
            "sub_region_codes": ["SR-DRS-IN"],
            "programme_codes": ["PDM"],
            "max_rows_per_request": 5000,
        },
    )
    return partner, dsa


@pytest.fixture
def partner_client(db, partner_and_dsa):
    """A partner-affiliated user with OperatorScope=PARTNER:E2E-OPM.

    PartnerScopedQuerysetMixin uses this to grant visibility on
    DataRequests under DSAs belonging to partner E2E-OPM.
    """
    user_cls = get_user_model()
    user = user_cls.objects.create_user(
        username="partner-analyst-1", password="x",
    )
    OperatorScope.objects.create(
        user=user, scope_level=ScopeLevel.PARTNER, scope_code="E2E-OPM",
        active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def operator_client(db):
    """An NSR Unit operator with NATIONAL scope (wildcard visibility).

    Distinct username from the partner so AC-DRS-NO-SELF-APPROVE
    fires correctly — the lifecycle service compares
    `approver == req.requester` literally on the username string.
    """
    user_cls = get_user_model()
    user = user_cls.objects.create_user(
        username="nsr-unit-approver", password="x",
    )
    OperatorScope.objects.create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
        active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# ---------------------------------------------------------------------------
# Happy path — the wiring chain end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_drs_request_lands_end_to_end(
    partner_client, operator_client, partner_and_dsa, household,
):
    partner_api, partner_user = partner_client
    operator_api, operator_user = operator_client
    partner, dsa = partner_and_dsa

    # --- Step 1: builder-schema -----------------------------------
    # Wizard's first call (US-S27-011). Must return DSA-keyed shape
    # with non-empty fields covering both household.* and member.*
    # (member.* will be flagged disabled for this partner because
    # field_scope only granted "household").
    r = partner_api.get(SCHEMA_URL)
    assert r.status_code == 200, r.data
    schema = r.data
    assert schema["role"] == "partner"
    assert schema["dsa_id"] == str(dsa.id)
    assert schema["dsa_reference"] == "DSA-E2E-S27"
    assert isinstance(schema["fields"], list) and schema["fields"]
    assert any(f["key"].startswith("household.") for f in schema["fields"])
    assert any(f["key"].startswith("member.") for f in schema["fields"])
    # filter_operators + filter_fields + delivery_methods are the
    # three other catalogue keys the wizard depends on (US-S27-012).
    assert schema["filter_operators"], "filter_operators missing"
    assert schema["filter_fields"], "filter_fields missing"
    assert schema["delivery_methods"], "delivery_methods missing"
    # household.* fields enabled; member.* disabled with a reason.
    hh_field = next(
        f for f in schema["fields"] if f["key"] == "household.id"
    )
    member_field = next(
        f for f in schema["fields"] if f["key"] == "member.surname"
    )
    assert hh_field["disabled"] is False
    assert member_field["disabled"] is True
    assert "DSA-E2E-S27" in member_field["disabled_reason"]

    # --- Step 2: POST /requests/ -----------------------------------
    # Payload shape the wizard ships: ordered fields list, a tree-
    # shaped criteria block (BuildStepV2), plus the back-compat
    # leaf extraction the wizard performs into sub_region_codes /
    # programme_codes, plus max_rows + requester_note at top level.
    criteria_tree = {
        "type": "group",
        "op": "and",
        "rules": [
            {
                "type": "rule",
                "field": "household.sub_region_code",
                "op": "in",
                "values": ["SR-DRS-IN"],
            },
            {
                "type": "rule",
                "field": "programme",
                "op": "in",
                "values": ["PDM"],
            },
        ],
    }
    create_payload = {
        "dsa": str(dsa.id),
        "requester_note": "Quarterly PDM cohort review",
        "request_payload": {
            "fields": ["household.id", "household.sub_region_code"],
            "criteria": criteria_tree,
            "sub_region_codes": ["SR-DRS-IN"],
            "programme_codes": ["PDM"],
            "max_rows": 50,
        },
    }
    r = partner_api.post(LIST_URL, create_payload, format="json")
    assert r.status_code == 201, r.data
    body = r.data
    req_id = body["id"]
    assert body["status"] == RequestStatus.DRAFT
    assert body["dsa"] == str(dsa.id)
    # requester is auto-stamped server-side; the partner user wins.
    assert body["requester"] == partner_user.username

    # The criteria tree round-trips through request_payload intact —
    # this is what the wizard's edit-mode would read back.
    persisted = DataRequest.objects.get(id=req_id)
    assert persisted.request_payload["criteria"]["op"] == "and"
    assert len(persisted.request_payload["criteria"]["rules"]) == 2
    assert persisted.request_payload["fields"] == [
        "household.id", "household.sub_region_code",
    ]
    assert persisted.requester_note == "Quarterly PDM cohort review"

    # --- Step 3: submit -------------------------------------------
    r = partner_api.post(f"{LIST_URL}{req_id}/submit/", {}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["status"] == RequestStatus.SUBMITTED
    assert r.data["submitted_at"] is not None

    # The submit AuditEvent fires with payload_keys in field_changes.
    submit_evt = AuditEvent.objects.get(
        entity_type="data_request", entity_id=req_id, action="submit",
    )
    assert submit_evt.actor_id == partner_user.username
    assert "criteria" in submit_evt.field_changes["payload_keys"]
    assert "fields" in submit_evt.field_changes["payload_keys"]

    # --- Step 4: approve (as operator, NOT the requester) ---------
    r = operator_api.post(
        f"{LIST_URL}{req_id}/approve/",
        {"approver": operator_user.username, "reason": "PDM review approved"},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["status"] == RequestStatus.APPROVED
    assert r.data["approver"] == operator_user.username
    assert r.data["decided_at"] is not None

    # AC-DRS-NO-SELF-APPROVE: assert the partner cannot approve
    # their own request — even though the row is already APPROVED,
    # the rejection here is on a separate DRAFT we'd never persist
    # in steady state; we drive it via a fresh DRAFT below in the
    # unhappy-path test. (Skip a second self-approve assertion
    # here to keep the happy-path linear.)

    # --- Step 5: deliver ------------------------------------------
    # The deliver endpoint is the side-effect-commitment seam;
    # render+put is a separate render-and-deliver action. Here we
    # synthesise the manifest the way an ops script would, then
    # seed the bundle store directly so the download in Step 6
    # has bytes to return. This proves the deliver/download
    # contract without depending on the render layer.
    fake_body = b'{"household.id": "01EXAMPLE", "household.sub_region_code": "SR-DRS-IN"}'
    sha = hashlib.sha256(fake_body).hexdigest()
    put_bundle(sha, fake_body)

    r = operator_api.post(
        f"{LIST_URL}{req_id}/deliver/",
        {"actor": operator_user.username, "manifest_sha256": sha, "row_count": 1},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["status"] == RequestStatus.DELIVERED
    assert r.data["manifest_sha256"] == sha
    assert r.data["row_count_delivered"] == 1
    assert r.data["delivered_at"] is not None
    assert r.data["expires_at"] is not None

    # Structured delivery AuditEvent — Sprint 23 usage-rollup
    # depends on these field_changes keys, ADR-0013.
    deliver_evt = AuditEvent.objects.get(
        entity_type="data_request", entity_id=req_id,
        action="data_request_delivered",
    )
    assert deliver_evt.field_changes["partner_code"] == "E2E-OPM"
    assert deliver_evt.field_changes["dsa_reference"] == "DSA-E2E-S27"
    assert deliver_evt.field_changes["rows_delivered"] == 1
    assert deliver_evt.field_changes["manifest_sha256"] == sha

    # --- Step 6: partner downloads --------------------------------
    # Re-authenticate as the original partner. ABAC scope on
    # DataRequest is dsa__partner_id; the partner sees their own.
    r = partner_api.get(f"{LIST_URL}{req_id}/download/")
    assert r.status_code == 200, (r.status_code, getattr(r, "data", r.content))
    assert r["Content-Type"] == "application/x-ndjson"
    assert f"data-request-{req_id}.ndjson" in r["Content-Disposition"]
    assert r.content == fake_body

    # And one per-call download AuditEvent.
    assert AuditEvent.objects.filter(
        entity_type="data_request", entity_id=req_id, action="download",
        actor_id=partner_user.username,
    ).exists()


# ---------------------------------------------------------------------------
# Unhappy path — out-of-scope sub_region rejected at submit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_drs_submit_rejects_out_of_scope_sub_region(
    partner_client, partner_and_dsa, household,
):
    """Partner asks for a sub_region the DSA does not cover →
    submit fails with the validator's exact error string and the
    row stays DRAFT. An audit row for the scope violation is
    persisted so the breach-detector picks it up."""
    partner_api, partner_user = partner_client
    _, dsa = partner_and_dsa

    create_payload = {
        "dsa": str(dsa.id),
        "request_payload": {
            "fields": ["household.id"],
            "sub_region_codes": ["SR-DRS-OUT"],   # outside DSA scope
            "max_rows": 50,
        },
    }
    r = partner_api.post(LIST_URL, create_payload, format="json")
    assert r.status_code == 201, r.data
    req_id = r.data["id"]
    assert r.data["status"] == RequestStatus.DRAFT

    r = partner_api.post(f"{LIST_URL}{req_id}/submit/", {}, format="json")
    assert r.status_code == 400, r.data
    # The validator's exact phrasing — services.py:_violation
    # formats this as `<key>=<sorted-list> outside DSA scope ...`.
    detail = r.data["detail"]
    assert "sub_region_codes" in detail
    assert "SR-DRS-OUT" in detail
    assert "outside DSA scope" in detail

    # Row stays DRAFT; no submitted_at; no submit AuditEvent.
    persisted = DataRequest.objects.get(id=req_id)
    assert persisted.status == RequestStatus.DRAFT
    assert persisted.submitted_at is None
    assert not AuditEvent.objects.filter(
        entity_type="data_request", entity_id=req_id, action="submit",
    ).exists()

    # Scope-violation audit row IS written (validator runs outside
    # the atomic state transition so this survives the rejection).
    violation = AuditEvent.objects.filter(
        action="dsa_scope_violation", entity_type="dsa", entity_id=dsa.id,
    ).first()
    assert violation is not None
    assert "sub_region_codes" in violation.reason
    assert "SR-DRS-OUT" in violation.reason


# ---------------------------------------------------------------------------
# Unhappy path — partner cannot self-approve their own submission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_drs_partner_cannot_self_approve(
    partner_client, partner_and_dsa, household,
):
    """AC-DRS-NO-SELF-APPROVE: the requester string == approver
    string check in services.approve_data_request must reject the
    partner trying to approve their own SUBMITTED request."""
    partner_api, partner_user = partner_client
    _, dsa = partner_and_dsa

    create_payload = {
        "dsa": str(dsa.id),
        "request_payload": {
            "fields": ["household.id"],
            "sub_region_codes": ["SR-DRS-IN"],
            "max_rows": 25,
        },
    }
    r = partner_api.post(LIST_URL, create_payload, format="json")
    req_id = r.data["id"]
    r = partner_api.post(f"{LIST_URL}{req_id}/submit/", {}, format="json")
    assert r.status_code == 200, r.data

    # Now the same partner tries to approve. AC-DRS-NO-SELF-APPROVE
    # fires inside approve_data_request and the endpoint returns
    # 400 with the rule name in the detail string.
    r = partner_api.post(
        f"{LIST_URL}{req_id}/approve/",
        {"approver": partner_user.username, "reason": "trying"},
        format="json",
    )
    assert r.status_code == 400, r.data
    assert "AC-DRS-NO-SELF-APPROVE" in r.data["detail"]
    persisted = DataRequest.objects.get(id=req_id)
    assert persisted.status == RequestStatus.SUBMITTED
