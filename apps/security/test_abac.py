"""ABAC scope enforcement tests."""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.models import OperatorScope, ScopeLevel


@pytest.fixture
def two_sub_regions(db):
    """Build two parallel 7-level ladders so we have two distinct
    sub_region_codes to test scoping against."""
    out = {}
    for _region_key, sr_key in [("R-CENTRAL", "SR-BUGANDA"), ("R-NORTHERN", "SR-KARAMOJA")]:
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            code = f"A-{sr_key}-{key.upper()}" if level == "sub_region" else f"A-{sr_key}-{key.upper()}"
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=code, name=f"{sr_key}-{key}",
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        out[sr_key] = nodes
    return out


@pytest.fixture
def households_in_each(two_sub_regions):
    """One Household in each of the two sub-regions."""
    result = {}
    for sr_key, nodes in two_sub_regions.items():
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
            county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"], village=nodes["v"],
            urban_rural="rural",
        )
        result[sr_key] = hh
    return result


def _client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestSuperuserSeesAll:
    def test_superuser_sees_both_sub_regions(self, db, django_user_model, households_in_each):
        su = django_user_model.objects.create_user(username="su", password="p", is_superuser=True)
        r = _client_for(su).get("/api/v1/data-management/households/")
        assert r.status_code == 200
        assert r.data["count"] == 2


class TestNoScopeFailsClosed:
    def test_regular_user_with_no_scope_sees_zero_rows(self, db, django_user_model, households_in_each):
        u = django_user_model.objects.create_user(username="empty", password="p")
        r = _client_for(u).get("/api/v1/data-management/households/")
        assert r.status_code == 200
        assert r.data["count"] == 0


class TestSubRegionScope:
    def test_user_scoped_to_one_sub_region_sees_only_that_region(
        self, db, django_user_model, two_sub_regions, households_in_each,
    ):
        u = django_user_model.objects.create_user(username="parish-chief", password="p")
        # Grant scope for the Buganda sub-region.
        sr_code = two_sub_regions["SR-BUGANDA"]["sr"].code
        OperatorScope.objects.create(user=u, scope_level=ScopeLevel.SUB_REGION,
                                     scope_code=sr_code)
        r = _client_for(u).get("/api/v1/data-management/households/")
        assert r.status_code == 200
        assert r.data["count"] == 1
        # The visible household is the Buganda one.
        ids = {row["id"] for row in r.data["results"]}
        assert ids == {households_in_each["SR-BUGANDA"].id}

    def test_user_with_two_scopes_sees_both(
        self, db, django_user_model, two_sub_regions, households_in_each,
    ):
        u = django_user_model.objects.create_user(username="multi", password="p")
        for sr_key in ["SR-BUGANDA", "SR-KARAMOJA"]:
            OperatorScope.objects.create(
                user=u, scope_level=ScopeLevel.SUB_REGION,
                scope_code=two_sub_regions[sr_key]["sr"].code,
            )
        r = _client_for(u).get("/api/v1/data-management/households/")
        assert r.data["count"] == 2

    def test_inactive_scope_is_ignored(
        self, db, django_user_model, two_sub_regions, households_in_each,
    ):
        u = django_user_model.objects.create_user(username="dormant", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
            active=False,
        )
        r = _client_for(u).get("/api/v1/data-management/households/")
        assert r.data["count"] == 0


class TestNationalScope:
    def test_national_scope_acts_as_wildcard(
        self, db, django_user_model, households_in_each,
    ):
        u = django_user_model.objects.create_user(username="dpo", password="p")
        OperatorScope.objects.create(user=u, scope_level=ScopeLevel.NATIONAL, scope_code="")
        r = _client_for(u).get("/api/v1/data-management/households/")
        assert r.data["count"] == 2
