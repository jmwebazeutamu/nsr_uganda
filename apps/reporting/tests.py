"""RPT dashboard tests — ABAC scope pre-applied to aggregates, audit
emitted per call."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance.models import Category, GrievanceStatus, Tier
from apps.grievance.services import open_grievance
from apps.pmt.models import Band, ModelStatus, PMTModelVersion, PMTResult
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent, OperatorScope, ScopeLevel


@pytest.fixture
def two_sub_regions(db):
    out = {}
    for sr_key in ["SR-BUGANDA", "SR-KARAMOJA"]:
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"R-{sr_key}-{key.upper()}", name=f"{sr_key}-{key}",
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        out[sr_key] = nodes
    return out


@pytest.fixture
def households(two_sub_regions):
    out = {}
    for sr_key, nodes in two_sub_regions.items():
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
            county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="rural",
        )
        out[sr_key] = hh
    return out


@pytest.fixture
def pmt_seeded(db, households):
    model = PMTModelVersion.objects.create(
        version=1, intercept=Decimal("50"), variables=[],
        band_cutoffs={
            Band.EXTREME_POVERTY: 0, Band.POVERTY: 30,
            Band.VULNERABLE: 60, Band.NOT_POOR: 80,
        },
        author="a", status=ModelStatus.ACTIVE,
    )
    for sr_key, hh in households.items():
        band = Band.POVERTY if sr_key == "SR-BUGANDA" else Band.VULNERABLE
        PMTResult.objects.create(
            household=hh, model_version=model,
            score=Decimal("55"), band=band, triggered_by="manual",
        )
        hh.current_vulnerability_band = band
        hh.save(update_fields=["current_vulnerability_band"])
    return model


def _client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestHouseholdsBySubRegion:
    def test_superuser_sees_both_buckets(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert len(buckets) == 2
        assert all(c == 1 for c in buckets.values())

    def test_sub_region_operator_sees_only_their_bucket(
        self, db, households, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["count"] == 1

    def test_unscoped_user_sees_zero_buckets(
        self, db, households, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="ghost", password="p")
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        assert r.data == []

    def test_emits_audit_event(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su2", password="p", is_superuser=True,
        )
        _client_for(su).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard", entity_id="households_by_sub_region",
        ).first()
        assert ev is not None
        assert ev.actor_id == "su2"
        assert ev.action == "dashboard_read"


class TestHouseholdsByPmtBand:
    def test_groups_by_band(self, db, pmt_seeded, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/households-by-pmt-band/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Band.POVERTY: 1, Band.VULNERABLE: 1}

    def test_scope_filtered_before_aggregation(
        self, db, pmt_seeded, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-pmt-band/")
        assert r.status_code == 200
        # Operator sees only the BUGANDA household — POVERTY band.
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Band.POVERTY: 1}


class TestOpenGrievancesByTier:
    def test_open_grievances_grouped(
        self, db, households, two_sub_regions, django_user_model,
    ):
        # Two open grievances in Buganda, one resolved, one in Karamoja.
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id,
                       tier=Tier.L1_PARISH_CHIEF)
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-BUGANDA"].id,
                       tier=Tier.L2_CDO)
        g_closed = open_grievance(category=Category.OTHER, description="c",
                                  household_id=households["SR-BUGANDA"].id)
        g_closed.status = GrievanceStatus.CLOSED
        g_closed.save(update_fields=["status"])
        open_grievance(category=Category.DATA_CORRECTION, description="d",
                       household_id=households["SR-KARAMOJA"].id,
                       tier=Tier.L1_PARISH_CHIEF)

        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/open-grievances-by-tier/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Tier.L1_PARISH_CHIEF: 2, Tier.L2_CDO: 1}

    def test_scope_filtered(
        self, db, households, two_sub_regions, django_user_model,
    ):
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id)
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-KARAMOJA"].id)
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/open-grievances-by-tier/")
        assert r.status_code == 200
        assert sum(row["count"] for row in r.data) == 1
