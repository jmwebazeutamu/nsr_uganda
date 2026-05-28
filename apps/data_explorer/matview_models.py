"""Unmanaged Django models mapped onto the mv_explorer_* materialised
views. Meta.managed = False — the CREATE/REFRESH DDL lives in
apps.data_management migrations (CLAUDE.md: no raw SQL outside
data_management + ingestion_hub).

The query_builder composes plain ORM QuerySet ops against these models
so the no-raw-SQL rule inside apps/data_explorer is automatic.

Each matview model carries:
- a refreshed_at timestamp column (the staleness signal),
- a sub_region_code column for ABAC scoping,
- the dimensions and metrics declared in ADR-0023 §"Proposed matviews".

The columns here are intentionally narrow — they're the surface the
query_builder + suppressor reason about. Adding a dimension requires
a paired migration + a Variable row + dual approval.
"""

from __future__ import annotations

from django.db import models


class _MatviewBase(models.Model):
    """Shared columns every matview row carries."""

    # Surrogate ULID — managed=False so we never write here, but
    # Django wants a primary key on every model. Postgres matview
    # carries an idiomatic row hash; on SQLite (test/dev) it falls
    # back to a deterministic synthetic key.
    id = models.CharField(primary_key=True, max_length=64)
    refreshed_at = models.DateTimeField()
    sub_region_code = models.CharField(max_length=32, db_index=True)

    class Meta:
        abstract = True
        managed = False

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.id[:12]}…)"


class HouseholdBySubcountyDemographics(_MatviewBase):
    district_code = models.CharField(max_length=32)
    sub_county_code = models.CharField(max_length=32, db_index=True)
    head_sex_code = models.CharField(max_length=8, blank=True)
    head_age_band = models.CharField(max_length=16, blank=True)
    household_count = models.PositiveIntegerField(default=0)
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_household_by_subcounty_demographics"


class HouseholdBySubcountyPmt(_MatviewBase):
    district_code = models.CharField(max_length=32)
    sub_county_code = models.CharField(max_length=32, db_index=True)
    pmt_band = models.CharField(max_length=24, blank=True)
    household_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_household_by_subcounty_pmt"


class MemberBySubcountyEducation(_MatviewBase):
    district_code = models.CharField(max_length=32)
    sub_county_code = models.CharField(max_length=32, db_index=True)
    sex_code = models.CharField(max_length=8, blank=True)
    age_band = models.CharField(max_length=16, blank=True)
    attendance_status = models.CharField(max_length=32, blank=True)
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_member_by_subcounty_education"


class MemberBySubcountyEmployment(_MatviewBase):
    district_code = models.CharField(max_length=32)
    sub_county_code = models.CharField(max_length=32, db_index=True)
    sex_code = models.CharField(max_length=8, blank=True)
    age_band = models.CharField(max_length=16, blank=True)
    employment_status = models.CharField(max_length=32, blank=True)
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_member_by_subcounty_employment"


class HouseholdShocksSubregion(_MatviewBase):
    shock_type = models.CharField(max_length=32, blank=True)
    severity = models.CharField(max_length=24, blank=True)
    household_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_household_shocks_subregion"


class ReferralsSubcounty(_MatviewBase):
    district_code = models.CharField(max_length=32)
    sub_county_code = models.CharField(max_length=32, db_index=True)
    programme_code = models.CharField(max_length=32, blank=True)
    referral_status = models.CharField(max_length=24, blank=True)
    referral_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_referrals_subcounty"


class GrievancesSubcounty(_MatviewBase):
    district_code = models.CharField(max_length=32)
    sub_county_code = models.CharField(max_length=32, db_index=True)
    category = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=24, blank=True)
    grievance_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_grievances_subcounty"


class HealthChronicSubregion(_MatviewBase):
    """Personal-class matview — aggregates at sub_region only.

    ADR-0023 D4: Personal-class matviews aggregate one level coarser
    than the floor so geographic minimum aggregation is baked into the
    matview shape, not just the suppressor.
    """

    condition_code = models.CharField(max_length=32, blank=True)
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "mv_explorer_health_chronic_subregion"


# Map matview name → Django model — used by query_builder.
MATVIEW_MODELS = {
    "mv_explorer_household_by_subcounty_demographics": HouseholdBySubcountyDemographics,
    "mv_explorer_household_by_subcounty_pmt": HouseholdBySubcountyPmt,
    "mv_explorer_member_by_subcounty_education": MemberBySubcountyEducation,
    "mv_explorer_member_by_subcounty_employment": MemberBySubcountyEmployment,
    "mv_explorer_household_shocks_subregion": HouseholdShocksSubregion,
    "mv_explorer_referrals_subcounty": ReferralsSubcounty,
    "mv_explorer_grievances_subcounty": GrievancesSubcounty,
    "mv_explorer_health_chronic_subregion": HealthChronicSubregion,
}
