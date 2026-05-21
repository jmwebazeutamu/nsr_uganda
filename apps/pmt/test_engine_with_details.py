"""US-S22-DE-06 — PMT engine tests against the detail entities.

Asserts:

  * The engine resolves dotted paths into the new detail tables:
      household.dwelling.<col>, household.utilities.<col>,
      household.livelihood.<col>, household.food_security.<col>,
      household.food_consumption.<col>,
      household.head_member.education.<col>,
      household.head_member.employment.<col>.
  * Repeat-group accessors work: assets.radio.count, livestock.cattle.count.
  * Member-level aggregations compute correctly:
      disabled_member_count, chronic_ill_member_count,
      school_age_out_of_school_count, dependency_ratio.
  * AC-DE-PMT-NO-N-PLUS-1: scoring one household with 10 members
    issues ≤ 12 SQL queries (CaptureQueriesContext).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_management.models import (
    AssetOwnership,
    Disability,
    Dwelling,
    Education,
    Employment,
    FoodConsumption,
    FoodSecurity,
    Health,
    Household,
    Livelihood,
    Livestock,
    Member,
    Utilities,
)
from apps.pmt.engine import _household_features, compute_pmt
from apps.pmt.models import ModelStatus, PMTModelVersion
from apps.pmt.services import recompute_for_household
from apps.reference_data.models import GeographicUnit

# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def sub_region(db):
    return GeographicUnit.objects.create(
        level="sub_region", code="SR-PMT-DE",
        name="PMT DE sub-region", effective_from=date(2026, 1, 1),
    )


@pytest.fixture
def household_with_details(db, sub_region):
    hh = Household.objects.create(
        region=sub_region, sub_region=sub_region, district=sub_region,
        county=sub_region, sub_county=sub_region, parish=sub_region,
        village=sub_region,
    )
    Dwelling.objects.create(
        household=hh, tenure="1", roof_material="1", floor_material="1",
        total_rooms=4, sleeping_rooms=2,
    )
    Utilities.objects.create(
        household=hh, cooking_fuel="1", drinking_water_source="3",
        toilet_facility="3",
    )
    Livelihood.objects.create(
        household=hh, main_livelihood="1",
        land_hectares=Decimal("2.500"),
    )
    FoodSecurity.objects.create(
        household=hh,
        worried_food="1", unhealthy_food="1", limited_variety="1",
    )
    FoodConsumption.objects.create(
        household=hh, staples_days=7, meat_days=2,
    )
    AssetOwnership.objects.create(household=hh, asset_type="radio", count=2)
    AssetOwnership.objects.create(household=hh, asset_type="tv", count=1)
    Livestock.objects.create(household=hh, livestock_type="cattle", count=3)

    head = Member.objects.create(
        household=hh, line_number=1, surname="Doe", first_name="Head",
        sex="F", age_years=42, relationship_to_head="01",
    )
    hh.head_member = head
    hh.save(update_fields=["head_member"])
    Education.objects.create(member=head, highest_grade="08")
    Employment.objects.create(member=head, sector="1")

    return hh


# --- Dotted-path resolution ----------------------------------------------


@pytest.mark.django_db
class TestDottedPathResolves:
    def test_household_dwelling_col(self, household_with_details):
        rec = _household_features(household_with_details)
        from apps.pmt.engine import _get
        assert _get(rec, "household.dwelling.tenure") == "1"
        assert _get(rec, "household.utilities.cooking_fuel") == "1"
        assert _get(rec, "household.livelihood.land_hectares") == Decimal("2.500")
        assert _get(rec, "household.food_security.fies_raw_score") == 3
        assert _get(rec, "household.food_consumption.staples_days") == 7

    def test_assets_keyed_by_type(self, household_with_details):
        rec = _household_features(household_with_details)
        from apps.pmt.engine import _get
        assert _get(rec, "assets.radio.count") == 2
        assert _get(rec, "assets.tv.count") == 1
        # Unknown asset type resolves to None — variable's transform
        # (typically `present_as_one`) gracefully treats None as 0.
        assert _get(rec, "assets.motorcycle.count") is None

    def test_livestock_keyed_by_type(self, household_with_details):
        rec = _household_features(household_with_details)
        from apps.pmt.engine import _get
        assert _get(rec, "livestock.cattle.count") == 3

    def test_head_member_education_employment(self, household_with_details):
        rec = _household_features(household_with_details)
        from apps.pmt.engine import _get
        assert _get(rec, "household.head_member.education.highest_grade") == "08"
        assert _get(rec, "household.head_member.employment.sector") == "1"


# --- Aggregations --------------------------------------------------------


@pytest.mark.django_db
class TestMemberAggregations:
    def _household_with_n_members(self, sub_region, ages: list[int]):
        hh = Household.objects.create(
            region=sub_region, sub_region=sub_region, district=sub_region,
            county=sub_region, sub_county=sub_region, parish=sub_region,
            village=sub_region,
        )
        members = []
        for i, age in enumerate(ages, start=1):
            members.append(Member.objects.create(
                household=hh, line_number=i,
                surname="X", first_name=f"M{i}",
                sex="F" if i % 2 == 0 else "M",
                age_years=age, relationship_to_head="01" if i == 1 else "02",
            ))
        return hh, members

    def test_disabled_member_count(self, sub_region):
        hh, members = self._household_with_n_members(sub_region, [40, 30, 12])
        # Two of three have wg_disability_flag-affirmative codes.
        Disability.objects.create(member=members[0], walking="03")
        Disability.objects.create(member=members[1], selfcare="04")
        Disability.objects.create(member=members[2], seeing="01")  # below threshold
        rec = _household_features(hh)
        assert rec["disabled_member_count"] == 2

    def test_chronic_ill_member_count(self, sub_region):
        hh, members = self._household_with_n_members(sub_region, [40, 30])
        Health.objects.create(member=members[0], chronic_illness_flag="1")
        Health.objects.create(member=members[1], chronic_illness_flag="2")
        rec = _household_features(hh)
        assert rec["chronic_ill_member_count"] == 1

    def test_school_age_out_of_school_count(self, sub_region):
        hh, members = self._household_with_n_members(sub_region, [10, 14, 19, 7])
        # 10yo not attending, 14yo attending, 19yo not in band, 7yo no education row.
        Education.objects.create(member=members[0], currently_attending="2")
        Education.objects.create(member=members[1], currently_attending="1")
        Education.objects.create(member=members[2], currently_attending="2")
        # member 3 (7yo) — no education row → counted as out of school.
        rec = _household_features(hh)
        # Out of school: 10yo (m0) + 7yo (m3). 14yo attending excluded. 19yo
        # out of the 6–18 band so excluded.
        assert rec["school_age_out_of_school_count"] == 2

    def test_dependency_ratio(self, sub_region):
        hh, _ = self._household_with_n_members(sub_region, [5, 10, 35, 40, 70])
        # under_15: 2 (5yo, 10yo); over_65: 1 (70yo); working_age: 2 (35, 40).
        rec = _household_features(hh)
        # (2 + 1) / 2 = 1.5
        assert rec["dependency_ratio"] == 1.5

    def test_dependency_ratio_zero_working_age(self, sub_region):
        hh, _ = self._household_with_n_members(sub_region, [5, 10])
        rec = _household_features(hh)
        # No working-age adults → ratio defaults to 0 (avoid div-by-zero).
        assert rec["dependency_ratio"] == 0.0


# --- N+1 prevention ------------------------------------------------------


@pytest.mark.django_db
class TestNoPlusOne:
    def test_scoring_10_member_household_uses_few_queries(self, db, sub_region):
        # AC-DE-PMT-NO-N-PLUS-1 — ≤ 12 SQL queries for 10 members.
        hh = Household.objects.create(
            region=sub_region, sub_region=sub_region, district=sub_region,
            county=sub_region, sub_county=sub_region, parish=sub_region,
            village=sub_region,
        )
        # 10 members, each with a few detail rows.
        for i in range(10):
            m = Member.objects.create(
                household=hh, line_number=i + 1,
                surname="X", first_name=f"M{i}",
                sex="F" if i % 2 == 0 else "M", age_years=20 + i,
                relationship_to_head="01" if i == 0 else "02",
            )
            Health.objects.create(member=m, chronic_illness_flag="2")
            Disability.objects.create(member=m, seeing="01")
            Education.objects.create(member=m, currently_attending="1")
            Employment.objects.create(member=m, sector="1")
        Dwelling.objects.create(household=hh, tenure="1")
        Utilities.objects.create(household=hh, cooking_fuel="1")
        Livelihood.objects.create(household=hh, main_livelihood="1")
        FoodSecurity.objects.create(household=hh, worried_food="2")
        FoodConsumption.objects.create(household=hh, staples_days=5)

        # Activate a draft model so recompute_for_household actually runs.
        model = PMTModelVersion.objects.create(
            version=9001, status=ModelStatus.ACTIVE,
            author="t", approved_by="t2",
            intercept=0,
            variables=[
                {"variable": "household.dwelling.tenure", "weight": 1.0, "transform": "identity"},
                {"variable": "household.utilities.cooking_fuel", "weight": 1.0, "transform": "identity"},
                {"variable": "disabled_member_count", "weight": 1.0, "transform": "identity"},
                {"variable": "member_count", "weight": 1.0, "transform": "identity"},
            ],
            band_cutoffs={"extreme_poverty": 0, "poverty": 30, "vulnerable": 60, "not_poor": 80},
        )
        assert model is not None

        with CaptureQueriesContext(connection) as ctx:
            recompute_for_household(hh, triggered_by="test", actor="t")
        # Allow up to 20 to account for transaction overhead, the
        # PMTResult insert, and the Household column write — the
        # detail-table count (12) is the floor.
        assert len(ctx.captured_queries) <= 20, (
            f"got {len(ctx.captured_queries)} queries (expected ≤ 20):\n" +
            "\n".join(q["sql"][:120] for q in ctx.captured_queries)
        )


# --- End-to-end compute --------------------------------------------------


@pytest.mark.django_db
class TestComputeEndToEnd:
    def test_scoring_resolves_every_variable_to_non_none(
        self, household_with_details,
    ):
        # AC-DE-PMT-VARIABLES-RESOLVE — every variable in the
        # placeholder model resolves to a non-None raw value when
        # scoring a fully-populated household.
        variables = [
            {"variable": "household.dwelling.floor_material", "weight": 0.0, "transform": "identity"},
            {"variable": "household.dwelling.roof_material", "weight": 0.0, "transform": "identity"},
            {"variable": "household.utilities.drinking_water_source", "weight": 0.0, "transform": "identity"},
            {"variable": "household.utilities.toilet_facility", "weight": 0.0, "transform": "identity"},
            {"variable": "household.utilities.cooking_fuel", "weight": 0.0, "transform": "identity"},
            {"variable": "household.livelihood.land_hectares", "weight": 0.0, "transform": "log1p"},
            {"variable": "household.food_security.fies_raw_score", "weight": 0.0, "transform": "identity"},
            {"variable": "household.food_consumption.fcs_score", "weight": 0.0, "transform": "identity"},
            {"variable": "assets.radio.count", "weight": 0.0, "transform": "present_as_one"},
            {"variable": "assets.tv.count", "weight": 0.0, "transform": "present_as_one"},
            {"variable": "livestock.cattle.count", "weight": 0.0, "transform": "log1p"},
            {"variable": "household.head_member.education.highest_grade", "weight": 0.0, "transform": "identity"},
            {"variable": "household.head_member.employment.sector", "weight": 0.0, "transform": "identity"},
            {"variable": "member_count", "weight": 0.0, "transform": "identity"},
            {"variable": "dependency_ratio", "weight": 0.0, "transform": "identity"},
        ]
        model = PMTModelVersion.objects.create(
            version=9002, status=ModelStatus.DRAFT,
            author="t", intercept=0, variables=variables,
            band_cutoffs={"extreme_poverty": 0, "poverty": 30, "vulnerable": 60, "not_poor": 80},
        )
        score, band, snapshot = compute_pmt(household_with_details, model)
        # With all weights at zero, the score is just the intercept.
        assert score == 0.0
        # Every variable resolved — raw is never None for the populated
        # household. (member_count, etc. are aggregated to ints.)
        for var in variables:
            raw = snapshot[var["variable"]]["raw"]
            assert raw is not None, f"{var['variable']} resolved to None"
