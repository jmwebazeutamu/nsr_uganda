"""Default PrivacyClass assignment per (catalog category, field name).

ADR-0023 D5: DPO may override these via the dual-approval flow; the
override is audited. This file is the *default* mapping; activation
records the actual class on the Variable row.

Categories match apps.update_workflow.field_catalog.CATEGORIES keys
so the same metadata feed drives both the editable surface (UPD) and
the discoverable surface (DATA-EXP).

The four canonical classes are defined as PrivacyClassCode constants
in models.py; here we use the string codes for portability between
the migration seed, the management command, and tests.
"""

from __future__ import annotations

PUBLIC = "public"
INTERNAL = "internal"
PERSONAL = "personal"
SENSITIVE = "sensitive"


# Default — when a (category, field) isn't enumerated below.
DEFAULT_CLASS = INTERNAL


# Special-category and direct-identity columns (DPPA 2019). The
# catalogue surfaces the dictionary entry but the aggregate endpoint
# refuses any query that projects or filters on these.
#
# NOTE: these pairs are (field_catalog section key, model field name) and
# MUST track the live model field names — when the models are renamed or
# extended this map needs updating, or fields silently fall through to
# the INTERNAL default. This is the *default* classification only; the
# DPO confirms/overrides it via the dual-approval flow (ADR-0023 D5).
SENSITIVE_FIELDS: set[tuple[str, str]] = {
    # Health — special-category data.
    ("health", "chronic_illness_flag"),
    ("health", "chronic_illness_types_encrypted"),
    # Identity documents collected against the member.
    ("member", "identification_documents"),
}


# Personal — direct identifiers / fine-grained location. Aggregates
# allowed at the sub_region floor (k=10).
PERSONAL_FIELDS: set[tuple[str, str]] = {
    ("member", "surname"),
    ("member", "first_name"),
    ("member", "other_name"),
    ("member", "date_of_birth"),
    ("member", "telephone_1"),
    ("member", "telephone_2"),
    ("household", "address_narrative"),
    ("household", "gps_lat"),
    ("household", "gps_lng"),
    ("household", "gps_accuracy_m"),
    # Washington Group disability items — sensitive in nature, kept at
    # the Personal floor so disability-prevalence aggregates remain
    # possible at sub_region (DPO may tighten to Sensitive).
    ("disability", "seeing"),
    ("disability", "hearing"),
    ("disability", "walking"),
    ("disability", "memory"),
    ("disability", "selfcare"),
    ("disability", "communication"),
    ("disability", "wg_disability_flag"),
}


# Public — coarse geography only (at/above sub-county). Parish/village
# stay INTERNAL so fine-grained location is never k=0.
PUBLIC_FIELDS: set[tuple[str, str]] = {
    ("household", "region"),
    ("household", "sub_region"),
    ("household", "district"),
    ("household", "county"),
    ("household", "sub_county"),
    ("household", "urban_rural"),
}


def classify(category: str, field: str) -> str:
    pair = (category, field)
    if pair in SENSITIVE_FIELDS:
        return SENSITIVE
    if pair in PERSONAL_FIELDS:
        return PERSONAL
    if pair in PUBLIC_FIELDS:
        return PUBLIC
    return DEFAULT_CLASS


# Dataset-level defaults — each catalog category becomes a Dataset row
# with its own privacy class + matview + refresh cadence.
DATASET_DEFAULTS: list[dict] = [
    {
        "code": "household_core",
        "label": "Household — core attributes",
        "category": "household",
        "matview": "mv_explorer_household_by_subcounty_demographics",
        "privacy_class": INTERNAL,
        "refresh": "daily",
        "geographic_floor": "sub_county",
    },
    {
        "code": "household_pmt",
        "label": "Household — PMT score & band",
        "category": "household",
        "matview": "mv_explorer_household_by_subcounty_pmt",
        "privacy_class": INTERNAL,
        "refresh": "daily",
        "geographic_floor": "sub_county",
    },
    {
        "code": "member_education",
        "label": "Member — education",
        "category": "education",
        "matview": "mv_explorer_member_by_subcounty_education",
        "privacy_class": INTERNAL,
        "refresh": "weekly",
        "geographic_floor": "sub_county",
    },
    {
        "code": "member_employment",
        "label": "Member — employment",
        "category": "employment",
        "matview": "mv_explorer_member_by_subcounty_employment",
        "privacy_class": INTERNAL,
        "refresh": "weekly",
        "geographic_floor": "sub_county",
    },
    {
        "code": "household_shocks",
        "label": "Household — shocks",
        "category": "household",
        "matview": "mv_explorer_household_shocks_subregion",
        "privacy_class": PUBLIC,
        "refresh": "weekly",
        "geographic_floor": "sub_region",
    },
    {
        "code": "referrals",
        "label": "Referrals — by sub-county",
        "category": "household",
        "matview": "mv_explorer_referrals_subcounty",
        "privacy_class": INTERNAL,
        "refresh": "daily",
        "geographic_floor": "sub_county",
    },
    {
        "code": "grievances",
        "label": "Grievances — by sub-county",
        "category": "household",
        "matview": "mv_explorer_grievances_subcounty",
        "privacy_class": INTERNAL,
        "refresh": "daily",
        "geographic_floor": "sub_county",
    },
    {
        "code": "health_chronic",
        "label": "Member — chronic-condition counts",
        "category": "health",
        "matview": "mv_explorer_health_chronic_subregion",
        "privacy_class": PERSONAL,
        "refresh": "weekly",
        "geographic_floor": "sub_region",
    },
]


# Default per-class caps (ADR-0023 D3 / OPEN-3). Hardcoded only in
# this single seed module; everywhere else reads from PrivacyClass rows.
PRIVACY_CLASS_DEFAULTS: list[dict] = [
    {
        "code": PUBLIC,
        "label": "Public",
        "description": "No suppression. Aggregates may be exported.",
        "k_floor": 0,
        "daily_user_cap": None,
        "daily_org_cap": None,
        "blocks_aggregate": False,
    },
    {
        "code": INTERNAL,
        "label": "Internal",
        "description": "Cell suppression at k<5. Throttled per user + org.",
        "k_floor": 5,
        "daily_user_cap": 100,
        "daily_org_cap": 5000,
        "blocks_aggregate": False,
    },
    {
        "code": PERSONAL,
        "label": "Personal",
        "description": "Cell suppression at k<10. Sub-region floor only.",
        "k_floor": 10,
        "daily_user_cap": 25,
        "daily_org_cap": 500,
        "blocks_aggregate": False,
    },
    {
        "code": SENSITIVE,
        "label": "Sensitive",
        "description": "Catalogue only. Aggregate endpoint refuses with 422.",
        "k_floor": 0,
        "daily_user_cap": 0,
        "daily_org_cap": 0,
        "blocks_aggregate": True,
    },
]


REFRESH_CADENCE_DEFAULTS: list[dict] = [
    {"code": "manual",  "label": "Manual refresh",  "interval_seconds":          0},
    {"code": "hourly",  "label": "Every hour",      "interval_seconds":       3600},
    {"code": "daily",   "label": "Daily",           "interval_seconds":      86400},
    {"code": "weekly",  "label": "Weekly",          "interval_seconds":     604800},
    {"code": "monthly", "label": "Monthly",         "interval_seconds":    2592000},
]
