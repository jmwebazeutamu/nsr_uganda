"""End-to-end test for ADR-0013 / US-S24-005.

Threads the canonical Sprint 23 DSA through the DRS submit + render
+ deliver pipeline:

  Partner (apps.partners.Partner)
    → DataSharingAgreement (apps.partners.DataSharingAgreement)
        → DataRequest (apps.data_requests.DataRequest)
            → validate_against_dsa (canonical fields)
            → render_bundle (group-level field_scope + geo M2M)
            → deliver_data_request (structured AuditEvent)

Asserts every gate fires correctly and the structured delivery event
carries partner_code + rows_delivered so Sprint 23's usage rollup
picks it up without parsing free-text reason fields.
"""

from __future__ import annotations

from datetime import date

import pytest
from apps.data_management.models import Household
from apps.data_requests.models import DataRequest, RequestStatus
from apps.data_requests.services import (
    DrsError,
    approve_data_request,
    deliver_data_request,
    submit_data_request,
)
from apps.data_requests.test_helpers import make_dsa, make_partner
from apps.security.models import AuditEvent


@pytest.fixture
def geo_seed(db):
    from apps.reference_data.models import GeographicUnit
    nodes = {}
    for level, key, parent_key in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"),
        ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level,
            code=f"DRS-{key.upper()}",
            name=key.title(),
            parent=nodes.get(parent_key),
            effective_from=date(2026, 1, 1),
        )
    # Make the sub_region code findable by make_dsa.
    nodes["sr"].code = "SR-DRS-E2E"
    nodes["sr"].save()
    return nodes


@pytest.fixture
def household(db, geo_seed):
    return Household.objects.create(
        region=geo_seed["r"], sub_region=geo_seed["sr"],
        district=geo_seed["d"], county=geo_seed["c"],
        sub_county=geo_seed["sc"], parish=geo_seed["p"],
        village=geo_seed["v"], urban_rural="2",
        sub_region_code="SR-DRS-E2E",
    )


@pytest.mark.django_db
class TestCanonicalDsaEnforcement:
    def test_full_submit_deliver_path(self, household):
        # Canonical Partner + DSA — the SAME model the wizard creates
        # in Sprint 23.
        partner = make_partner(code="E2E-OPM", name="E2E OPM")
        dsa = make_dsa(
            partner=partner, reference="DSA-E2E-001", status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={
                "fields": [
                    "household.id", "household.sub_region_code",
                ],
                "sub_region_codes": ["SR-DRS-E2E"],
                "programme_codes": ["PDM"],
                "max_rows_per_request": 1000,
            },
        )

        # Draft → submit (validates against canonical DSA).
        req = DataRequest.objects.create(
            dsa=dsa, requester="partner-x",
            request_payload={
                "fields": ["household.id"],
                "sub_region_codes": ["SR-DRS-E2E"],
                "max_rows": 50,
            },
        )
        submit_data_request(req)
        req.refresh_from_db()
        assert req.status == RequestStatus.SUBMITTED

        # Approve.
        approve_data_request(req, approver="dpo-1")
        req.refresh_from_db()
        assert req.status == RequestStatus.APPROVED

        # Render + deliver. The structured AuditEvent matters for the
        # rollup task in apps/partners/tasks.py.
        from apps.data_requests.bundles import render_bundle
        body, count = render_bundle(req)
        assert count == 1  # the one household we seeded

        sha = "a" * 64
        deliver_data_request(
            req, manifest_sha256=sha, row_count=count, actor="bot",
        )

        # Audit chain: data_request_delivered event with structured
        # field_changes carrying partner_code.
        deliver_evt = AuditEvent.objects.get(
            entity_type="data_request",
            entity_id=req.id,
            action="data_request_delivered",
        )
        assert deliver_evt.field_changes["partner_code"] == "E2E-OPM"
        assert deliver_evt.field_changes["rows_delivered"] == 1
        assert deliver_evt.field_changes["manifest_sha256"] == sha
        assert deliver_evt.field_changes["dsa_reference"] == "DSA-E2E-001"

    def test_suspended_partner_blocks_submit(self, household):
        partner = make_partner(
            code="E2E-SUSP", name="Suspended Partner", status="suspended",
        )
        dsa = make_dsa(
            partner=partner, reference="DSA-SUSP-001", status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={"fields": ["household.id"]},
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="x", request_payload={"fields": ["household.id"]},
        )
        with pytest.raises(DrsError, match="suspended"):
            submit_data_request(req)

    def test_geographic_scope_filters_render(self, household, geo_seed):
        # A DSA scoped to a different sub_region than the household —
        # the bundle should come back empty.
        partner = make_partner(code="E2E-GEO", name="Geo Partner")
        dsa = make_dsa(
            partner=partner, reference="DSA-GEO-001", status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={
                "fields": ["household.id"],
                "sub_region_codes": ["SR-OTHER"],  # not the household's
            },
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="x", request_payload={"fields": ["household.id"]},
        )
        submit_data_request(req)
        approve_data_request(req, approver="dpo-1")
        from apps.data_requests.bundles import render_bundle
        body, count = render_bundle(req)
        assert count == 0
        assert body == b""

    def test_budget_blocks_oversized_request(self, household):
        # Trailing-30d budget gate: request asks for more than the
        # monthly budget allows → submit rejected.
        partner = make_partner(code="E2E-BUDGET", name="Budget Partner")
        dsa = make_dsa(
            partner=partner, reference="DSA-BUDGET-001", status="active",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
            allowed_scopes={
                "fields": ["household.id"],
                "max_rows_per_request": 100,
            },
        )
        req = DataRequest.objects.create(
            dsa=dsa, requester="x",
            request_payload={"fields": ["household.id"], "max_rows": 500},
        )
        with pytest.raises(DrsError, match="exceeds DSA monthly_row_budget"):
            submit_data_request(req)
        # A scope violation audit was emitted too.
        assert AuditEvent.objects.filter(
            action="dsa_scope_violation",
            entity_type="dsa", entity_id=dsa.id,
        ).exists()
