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


class TestScopeAcrossFKRelations:
    """Verify the scope_field_path mechanism — a Referral row is scoped
    by its household's sub_region_code, not by anything on the Referral
    itself. Same pattern applies to ProgrammeEnrolment."""

    def test_referral_visible_only_when_household_in_scope(
        self, db, django_user_model, two_sub_regions, households_in_each,
    ):
        from apps.referral.models import Programme
        from apps.referral.services import send_referral

        prog = Programme.objects.create(
            code="PDM-T", name="PDM (test)", webhook_url="https://x", webhook_secret="s",
        )
        # One referral per household — one in each sub-region.
        for hh in households_in_each.values():
            send_referral(programme=prog, household=hh, actor="op")

        # User scoped to BUGANDA only.
        u = django_user_model.objects.create_user(username="op-buganda", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/ref/referrals/")
        assert r.status_code == 200
        assert r.data["count"] == 1
        ids_visible = {row["household"] for row in r.data["results"]}
        assert ids_visible == {households_in_each["SR-BUGANDA"].id}

    def test_referral_invisible_to_unscoped_user(
        self, db, django_user_model, households_in_each,
    ):
        from apps.referral.models import Programme
        from apps.referral.services import send_referral

        prog = Programme.objects.create(
            code="NUSAF-T", name="NUSAF (test)", webhook_url="https://x", webhook_secret="s",
        )
        for hh in households_in_each.values():
            send_referral(programme=prog, household=hh, actor="op")

        u = django_user_model.objects.create_user(username="empty-2", password="p")
        # No OperatorScope rows -> fail-closed.
        r = _client_for(u).get("/api/v1/ref/referrals/")
        assert r.status_code == 200
        assert r.data["count"] == 0


class TestScopeViaHouseholdIdSubquery:
    """HouseholdIdScopedQuerysetMixin handles models that hold a
    household reference as a CharField (Grievance.household_id) or as a
    bare ULID (Submission/StageRecord.provisional_registry_id)."""

    def test_grievance_scoped_by_household(
        self, db, django_user_model, two_sub_regions, households_in_each,
    ):
        from apps.grievance.models import Category
        from apps.grievance.services import open_grievance

        for hh in households_in_each.values():
            open_grievance(category=Category.OTHER, description="x",
                           household_id=hh.id)

        u = django_user_model.objects.create_user(username="grm-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/grm/grievances/")
        assert r.status_code == 200
        assert r.data["count"] == 1
        assert r.data["results"][0]["household_id"] == \
            households_in_each["SR-BUGANDA"].id

    def test_grievance_with_no_household_invisible_to_scoped_user(
        self, db, django_user_model, two_sub_regions,
    ):
        from apps.grievance.models import Category
        from apps.grievance.services import open_grievance

        # Grievance with no household_id (e.g., anonymous complaint
        # about operator conduct).
        open_grievance(category=Category.OPERATOR_CONDUCT,
                       description="anonymous complaint")
        u = django_user_model.objects.create_user(username="grm-op2", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/grm/grievances/")
        # No household_id -> not in any sub-region's IN-subquery -> 0 rows.
        assert r.data["count"] == 0

    def test_stage_record_pre_promotion_invisible_to_sub_region_operator(
        self, db, django_user_model, two_sub_regions,
    ):
        # Pre-promotion StageRecords have a provisional_registry_id but
        # no corresponding Household. Sub-region operators see 0 rows;
        # only national scope (and superusers) see them.
        from datetime import date

        from apps.ingestion_hub.models import (
            Connector,
            DataProvisionAgreement,
            SourceSystem,
            SourceSystemKind,
        )
        from apps.ingestion_hub.services import (
            land_payload,
            stage_from_landing,
            start_connector_run,
        )

        src = SourceSystem.objects.create(code="ABAC-WEB", name="ABAC test",
                                          kind=SourceSystemKind.WEB)
        DataProvisionAgreement.objects.create(
            source_system=src, reference="DPA-ABAC-1",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        conn = Connector.objects.create(source_system=src, name="abac-test")
        run = start_connector_run(conn)
        landing = land_payload(run, {"members": []})
        stage_from_landing(landing, canonical_payload={"members": []})

        u = django_user_model.objects.create_user(username="parish", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/dih/stage-records/")
        assert r.status_code == 200
        assert r.data["count"] == 0

    def test_national_scope_sees_pre_promotion_stage_records(
        self, db, django_user_model,
    ):
        from datetime import date

        from apps.ingestion_hub.models import (
            Connector,
            DataProvisionAgreement,
            SourceSystem,
            SourceSystemKind,
        )
        from apps.ingestion_hub.services import (
            land_payload,
            stage_from_landing,
            start_connector_run,
        )

        src = SourceSystem.objects.create(code="ABAC-WEB-2", name="ABAC test 2",
                                          kind=SourceSystemKind.WEB)
        DataProvisionAgreement.objects.create(
            source_system=src, reference="DPA-ABAC-2",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        conn = Connector.objects.create(source_system=src, name="abac-test-2")
        run = start_connector_run(conn)
        landing = land_payload(run, {"members": []})
        stage_from_landing(landing, canonical_payload={"members": []})

        u = django_user_model.objects.create_user(username="nsr-unit", password="p")
        OperatorScope.objects.create(user=u, scope_level=ScopeLevel.NATIONAL, scope_code="")
        r = _client_for(u).get("/api/v1/dih/stage-records/")
        assert r.data["count"] >= 1
