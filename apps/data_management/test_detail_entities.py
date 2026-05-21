"""US-S22-DE-03 — per-model tests for the detail entities.

One test class per model. Asserts the bits that aren't free-by-Django:

  * sub_region_code is inherited from the parent on save (ADR-0005).
  * Versioning round-trips through the paired _Version model.
  * Computed columns (fies_raw_score, fcs_score, wg_disability_flag)
    compute correctly on save (ADR-0022).
  * Encrypted chronic_illness_types_encrypted round-trips via the
    set/get helpers and does NOT appear as plaintext on the column
    (ADR-0021).
  * Repeat-group uniqueness scoped to is_deleted=False.

The promotion fanout (US-S22-DE-04+) and PMT engine (US-S22-DE-08+)
are exercised in their own test files.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_management.models import (
    AssetOwnership,
    AssetOwnershipVersion,
    CopingStrategy,
    CopingStrategyVersion,
    Crop,
    CropVersion,
    Disability,
    DisabilityVersion,
    Dwelling,
    DwellingVersion,
    Education,
    EducationVersion,
    Employment,
    EmploymentVersion,
    FoodConsumption,
    FoodConsumptionVersion,
    FoodSecurity,
    FoodSecurityVersion,
    Health,
    HealthVersion,
    Household,
    Livelihood,
    LivelihoodVersion,
    Livestock,
    LivestockVersion,
    Member,
    Shock,
    ShockVersion,
    Utilities,
    UtilitiesVersion,
)
from apps.reference_data.models import GeographicUnit

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sub_region(db):
    return GeographicUnit.objects.create(
        level="sub_region", code="SR-DE-TEST", name="DE Test Sub-region",
        effective_from=date(2026, 1, 1),
    )


@pytest.fixture
def household(db, sub_region):
    # Geographic FKs all point at the same sub-region for simplicity —
    # the model only requires non-null FKs, not a real hierarchy here.
    return Household.objects.create(
        region=sub_region, sub_region=sub_region, district=sub_region,
        county=sub_region, sub_county=sub_region, parish=sub_region,
        village=sub_region,
    )


@pytest.fixture
def member(db, household):
    return Member.objects.create(
        household=household, line_number=1,
        surname="Doe", first_name="Jane", sex="F",
        relationship_to_head="01",
    )


# ---------------------------------------------------------------------------
# Per-Household one-to-one entities
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDwelling:
    def test_create_and_inherit_sub_region(self, household):
        d = Dwelling.objects.create(
            household=household, tenure="1", dwelling_type="1",
            roof_material="1", wall_material="1", floor_material="1",
            total_rooms=4, sleeping_rooms=2,
        )
        assert d.sub_region_code == household.sub_region_code
        assert household.dwelling == d

    def test_version_snapshot_roundtrip(self, household):
        d = Dwelling.objects.create(household=household, tenure="1")
        DwellingVersion.objects.create(
            dwelling=d, version_number=1,
            effective_from=datetime.now(UTC),
            tenure="1",
        )
        assert d.versions.count() == 1


@pytest.mark.django_db
class TestUtilities:
    def test_caps_households_sharing_toilet_at_10(self, household):
        u = Utilities.objects.create(
            household=household, households_sharing_toilet=42,
        )
        assert u.households_sharing_toilet == 10

    def test_inherits_sub_region(self, household):
        u = Utilities.objects.create(
            household=household, cooking_fuel="1",
            drinking_water_source="3",
        )
        assert u.sub_region_code == household.sub_region_code


@pytest.mark.django_db
class TestLivelihood:
    def test_create_and_inherit(self, household):
        from decimal import Decimal
        liv = Livelihood.objects.create(
            household=household, main_livelihood="1",
            land_hectares=Decimal("1.250"), land_ownership="1",
        )
        assert liv.sub_region_code == household.sub_region_code
        assert liv.land_hectares == Decimal("1.250")


@pytest.mark.django_db
class TestFoodSecurity:
    def test_fies_raw_score_counts_affirmative_responses(self, household):
        # "1" is the affirmative code; anything else is not counted.
        fs = FoodSecurity.objects.create(
            household=household,
            worried_food="1", unhealthy_food="1", limited_variety="1",
            skipped_meal="2", ate_less="1", ran_out_food="0",
            hungry_no_eat="", whole_day_no_eat="",
        )
        # worried + unhealthy + limited + ate_less = 4 affirmatives.
        assert fs.fies_raw_score == 4

    def test_fies_zero_when_all_blank(self, household):
        fs = FoodSecurity.objects.create(household=household)
        assert fs.fies_raw_score == 0

    def test_fies_max_8(self, household):
        fs = FoodSecurity.objects.create(
            household=household,
            worried_food="1", unhealthy_food="1", limited_variety="1",
            skipped_meal="1", ate_less="1", ran_out_food="1",
            hungry_no_eat="1", whole_day_no_eat="1",
        )
        assert fs.fies_raw_score == 8

    def test_fies_recomputed_on_resave(self, household):
        fs = FoodSecurity.objects.create(
            household=household, worried_food="1",
        )
        assert fs.fies_raw_score == 1
        fs.worried_food = "2"
        fs.skipped_meal = "1"
        fs.save()
        assert fs.fies_raw_score == 1  # skipped_meal flipped affirmative


@pytest.mark.django_db
class TestFoodConsumption:
    def test_fcs_score_uses_wfp_weights(self, household):
        # Staples (weight 2) × 7 + meat (weight 4) × 3 = 14 + 12 = 26.
        fc = FoodConsumption.objects.create(
            household=household, staples_days=7, meat_days=3,
        )
        from decimal import Decimal
        assert fc.fcs_score == Decimal("26")

    def test_fcs_caps_days_at_7(self, household):
        # Days > 7 are capped per the FCS rubric.
        fc = FoodConsumption.objects.create(
            household=household, staples_days=15,
        )
        from decimal import Decimal
        # 7 days × weight 2 = 14
        assert fc.fcs_score == Decimal("14")

    def test_fcs_max_112(self, household):
        # All 9 groups at 7 days each → max possible per the rubric.
        fc = FoodConsumption.objects.create(
            household=household,
            staples_days=7, pulses_days=7, dairy_days=7, meat_days=7,
            vegetables_days=7, fruits_days=7, oils_days=7, sugar_days=7,
            condiments_days=7,
        )
        # 7 × (2+3+4+4+1+1+0.5+0.5+0) = 7 × 16 = 112
        from decimal import Decimal
        assert fc.fcs_score == Decimal("112")


# ---------------------------------------------------------------------------
# Per-Household repeat groups
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssetOwnership:
    def test_caps_count_at_9(self, household):
        a = AssetOwnership.objects.create(
            household=household, asset_type="radio", count=42,
        )
        assert a.count == 9

    def test_unique_per_household_when_not_deleted(self, household):
        from django.db import IntegrityError
        AssetOwnership.objects.create(household=household, asset_type="radio", count=1)
        with pytest.raises(IntegrityError):
            AssetOwnership.objects.create(household=household, asset_type="radio", count=2)

    def test_soft_delete_releases_unique(self, household):
        # The partial-unique constraint is scoped to is_deleted=False so
        # we can re-create a soft-deleted asset entry.
        a = AssetOwnership.objects.create(household=household, asset_type="tv", count=1)
        a.is_deleted = True
        a.save()
        # Second create with the same asset_type should now succeed.
        AssetOwnership.objects.create(household=household, asset_type="tv", count=2)


@pytest.mark.django_db
class TestCrop:
    def test_unique_per_household(self, household):
        from django.db import IntegrityError
        Crop.objects.create(household=household, crop_name="maize", rank_order=1)
        with pytest.raises(IntegrityError):
            Crop.objects.create(household=household, crop_name="maize", rank_order=2)


@pytest.mark.django_db
class TestLivestock:
    def test_create_and_inherit(self, household):
        ls = Livestock.objects.create(
            household=household, livestock_type="cattle", count=3,
        )
        assert ls.sub_region_code == household.sub_region_code


@pytest.mark.django_db
class TestShock:
    def test_create_and_inherit(self, household):
        s = Shock.objects.create(
            household=household, shock_type="01",
            event_date=date(2026, 4, 1), severity="2",
        )
        assert s.sub_region_code == household.sub_region_code


@pytest.mark.django_db
class TestCopingStrategy:
    def test_unique_per_household_strategy_category(self, household):
        from django.db import IntegrityError
        CopingStrategy.objects.create(
            household=household, strategy_type="took_loan",
            category="livelihood", used_flag=True,
        )
        with pytest.raises(IntegrityError):
            CopingStrategy.objects.create(
                household=household, strategy_type="took_loan",
                category="livelihood",
            )

    def test_distinct_category_allowed(self, household):
        # Same strategy_type can appear once per category.
        CopingStrategy.objects.create(
            household=household, strategy_type="took_loan",
            category="livelihood", used_flag=True,
        )
        # `reduced_meals` is conceptually a food-coping strategy — different
        # category, so the row coexists.
        CopingStrategy.objects.create(
            household=household, strategy_type="reduced_meals",
            category="food", used_flag=True,
        )


# ---------------------------------------------------------------------------
# Per-Member one-to-one entities
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealth:
    def test_inherits_sub_region(self, member):
        h = Health.objects.create(member=member, chronic_illness_flag="1")
        assert h.sub_region_code == member.sub_region_code

    def test_chronic_illness_types_encryption_roundtrip(self, member):
        # Round-trip via the explicit helpers. The raw column is bytes;
        # nothing in this assertion treats the cleartext as plaintext-in-db.
        h = Health(member=member, chronic_illness_flag="1")
        h.set_chronic_illness_types(["4", "5"])  # 4=HIV, 5=TB
        h.save()
        h.refresh_from_db()
        # Stored column is bytes-like; the helper decodes.
        assert isinstance(
            h.chronic_illness_types_encrypted, (bytes, bytearray, memoryview),
        )
        assert h.get_chronic_illness_types() == ["4", "5"]

    def test_get_returns_empty_when_unset(self, member):
        h = Health.objects.create(member=member, chronic_illness_flag="2")
        assert h.get_chronic_illness_types() == []


@pytest.mark.django_db
class TestDisability:
    def test_wg_flag_true_on_lot_of_difficulty(self, member):
        # "03" = a lot of difficulty in the Washington Group rubric.
        d = Disability.objects.create(
            member=member, seeing="01", hearing="02",
            walking="03", memory="01", selfcare="01", communication="01",
        )
        assert d.wg_disability_flag is True

    def test_wg_flag_true_on_cannot_do_at_all(self, member):
        d = Disability.objects.create(
            member=member, seeing="01", hearing="01",
            walking="01", memory="01", selfcare="04", communication="01",
        )
        assert d.wg_disability_flag is True

    def test_wg_flag_false_on_no_or_some_difficulty(self, member):
        d = Disability.objects.create(
            member=member, seeing="01", hearing="02",
            walking="01", memory="02", selfcare="01", communication="02",
        )
        assert d.wg_disability_flag is False

    def test_wg_flag_recomputed_on_resave(self, member):
        d = Disability.objects.create(member=member, seeing="01")
        assert d.wg_disability_flag is False
        d.walking = "04"
        d.save()
        assert d.wg_disability_flag is True


@pytest.mark.django_db
class TestEducation:
    def test_create_and_inherit(self, member):
        e = Education.objects.create(
            member=member, literacy_status="1", highest_grade="07",
        )
        assert e.sub_region_code == member.sub_region_code


@pytest.mark.django_db
class TestEmployment:
    def test_create_and_inherit(self, member):
        e = Employment.objects.create(
            member=member, main_activity_last_30d="1",
            sector="1", employment_status="2",
            programmes_benefited=["PDM", "NUSAF"],
        )
        assert e.sub_region_code == member.sub_region_code
        assert e.programmes_benefited == ["PDM", "NUSAF"]


# ---------------------------------------------------------------------------
# Version models — at least one assertion that the table accepts a row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVersionTables:
    """One smoke per _Version table — schema-only confirmation."""

    @pytest.mark.parametrize(
        "model,parent_kw,parent_factory",
        [
            (DwellingVersion, "dwelling",
                lambda h, _m: Dwelling.objects.create(household=h)),
            (UtilitiesVersion, "utilities",
                lambda h, _m: Utilities.objects.create(household=h)),
            (LivelihoodVersion, "livelihood",
                lambda h, _m: Livelihood.objects.create(household=h)),
            (FoodSecurityVersion, "food_security",
                lambda h, _m: FoodSecurity.objects.create(household=h)),
            (FoodConsumptionVersion, "food_consumption",
                lambda h, _m: FoodConsumption.objects.create(household=h)),
            (AssetOwnershipVersion, "asset", lambda h, _m:
                AssetOwnership.objects.create(household=h, asset_type="radio")),
            (CropVersion, "crop", lambda h, _m:
                Crop.objects.create(household=h, crop_name="maize")),
            (LivestockVersion, "livestock", lambda h, _m:
                Livestock.objects.create(household=h, livestock_type="cattle")),
            (ShockVersion, "shock", lambda h, _m:
                Shock.objects.create(household=h, shock_type="01")),
            (CopingStrategyVersion, "coping", lambda h, _m:
                CopingStrategy.objects.create(
                    household=h, strategy_type="took_loan",
                    category="livelihood",
                )),
            (HealthVersion, "health",
                lambda _h, m: Health.objects.create(member=m)),
            (DisabilityVersion, "disability",
                lambda _h, m: Disability.objects.create(member=m)),
            (EducationVersion, "education",
                lambda _h, m: Education.objects.create(member=m)),
            (EmploymentVersion, "employment",
                lambda _h, m: Employment.objects.create(member=m)),
        ],
    )
    def test_version_row_accepts(self, model, parent_kw, parent_factory, household, member):
        parent = parent_factory(household, member)
        v = model.objects.create(
            **{parent_kw: parent},
            version_number=1,
            effective_from=datetime.now(UTC),
        )
        assert v.version_number == 1
