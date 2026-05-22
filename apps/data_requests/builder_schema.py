"""DRS builder-schema generation.

Returns the full catalogue of fields, filter operators, and delivery
methods the DRS query builder needs to render — same structure for
every role, with `disabled` + `disabled_reason` flagged per-field
based on the user's active DSA (for partner roles) or never (for
operator roles).

This module is the source of truth the React DRS wizard reads from
(/api/v1/drs/builder-schema/). Both the operator-side DRSScreen and
the partner-side PartnerDRSScreen consume the same response —
client-side rendering of the disabled state is uniform; only the
flag values differ by role.

Contract guarantee (enforced by contract test): the top-level shape
{fields, filter_operators, delivery_methods} is invariant across
all roles. A new role that needs fewer fields gets `disabled: true`
entries, never an entirely missing key.
"""

from __future__ import annotations

from typing import Any

from apps.partners.models import DataSharingAgreement

# All registry fields the DRS surface can use as query parameters
# AND as output selections. Each entry's `type` drives which
# operators apply on the wizard's query builder (`text`/`enum`/
# `enum-multi`/`number`/`date`/`bool`). `options` is included for
# enum fields whose value set is known statically; for enums
# whose values come from external reference data (sub-region,
# programme), the wizard fetches them at runtime via the
# `filter_fields` value_source URLs.
#
# Covers Household + Member level columns exposed by
# apps/data_management/models.py. Reflects real model columns —
# adding a field here requires the model column to actually exist
# on the persisted row.
FIELD_CATALOGUE: list[dict[str, Any]] = [
    # ---- Household: identifiers + geography ------------------------------
    {"group": "Identifiers", "key": "household.id",
     "label": "Registry ID",       "sensitivity": "Public",   "type": "text"},
    {"group": "Identifiers", "key": "household.household_number",
     "label": "Household number",  "sensitivity": "Public",   "type": "text"},
    {"group": "Identifiers", "key": "household.enumeration_area",
     "label": "Enumeration area",  "sensitivity": "Public",   "type": "text"},
    {"group": "Geography",   "key": "household.region_code",
     "label": "Region",            "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=region"},
    {"group": "Geography",   "key": "household.sub_region_code",
     "label": "Sub-region",        "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=sub_region"},
    {"group": "Geography",   "key": "household.district_code",
     "label": "District",          "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=district"},
    {"group": "Geography",   "key": "household.county_code",
     "label": "County",            "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=county"},
    {"group": "Geography",   "key": "household.sub_county_code",
     "label": "Sub-county",        "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=sub_county"},
    {"group": "Geography",   "key": "household.parish_code",
     "label": "Parish",            "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=parish"},
    {"group": "Geography",   "key": "household.village_code",
     "label": "Village",           "sensitivity": "Public",   "type": "enum",
     "options_source": "geographic-units?level=village"},
    {"group": "Geography",   "key": "household.urban_rural",
     "label": "Urban / rural",     "sensitivity": "Public",   "type": "enum",
     "options": [{"value": "1", "label": "Urban"}, {"value": "2", "label": "Rural"}]},
    {"group": "Geography",   "key": "household.gps_lat",
     "label": "GPS latitude",      "sensitivity": "Sensitive", "type": "number"},
    {"group": "Geography",   "key": "household.gps_lng",
     "label": "GPS longitude",     "sensitivity": "Sensitive", "type": "number"},
    {"group": "Geography",   "key": "household.gps_accuracy_m",
     "label": "GPS accuracy (m)",  "sensitivity": "Sensitive", "type": "number"},

    # ---- Household: dwelling + status ------------------------------------
    {"group": "Dwelling",    "key": "household.dwelling_tenure",
     "label": "Dwelling tenure",   "sensitivity": "Internal", "type": "text"},
    {"group": "Dwelling",    "key": "household.residence_status",
     "label": "Residence status",  "sensitivity": "Internal", "type": "text"},

    # ---- Household: PMT / vulnerability ----------------------------------
    {"group": "PMT",         "key": "household.current_pmt_score",
     "label": "PMT score",         "sensitivity": "Internal", "type": "number"},
    {"group": "PMT",         "key": "household.current_vulnerability_band",
     "label": "Vulnerability band","sensitivity": "Internal", "type": "enum",
     "options": [
         {"value": "extremely_vulnerable", "label": "Extremely vulnerable"},
         {"value": "vulnerable",           "label": "Vulnerable"},
         {"value": "resilient",            "label": "Resilient"},
     ]},

    # ---- Household: lifecycle --------------------------------------------
    {"group": "Lifecycle",   "key": "household.current_consent_state",
     "label": "Consent state",     "sensitivity": "Internal", "type": "text"},
    {"group": "Lifecycle",   "key": "household.current_intake_source",
     "label": "Intake source",     "sensitivity": "Internal", "type": "text"},
    {"group": "Lifecycle",   "key": "household.is_deleted",
     "label": "Soft-deleted",      "sensitivity": "Internal", "type": "bool"},
    {"group": "Lifecycle",   "key": "household.created_at",
     "label": "Created at",        "sensitivity": "Public",   "type": "date"},
    {"group": "Lifecycle",   "key": "household.updated_at",
     "label": "Last updated",      "sensitivity": "Public",   "type": "date"},

    # ---- Household: programme enrolment (derived via Referral/Enrolment) --
    {"group": "Programmes",  "key": "household.programme_codes",
     "label": "Programme enrolment",
     "sensitivity": "Internal", "type": "enum-multi",
     "options_source": "programmes"},

    # ---- Member: identifiers ---------------------------------------------
    {"group": "Members",     "key": "member.id",
     "label": "Member ID",         "sensitivity": "Public",   "type": "text"},
    {"group": "Members",     "key": "member.line_number",
     "label": "Line number",       "sensitivity": "Public",   "type": "number"},
    {"group": "Members",     "key": "member.surname",
     "label": "Surname",           "sensitivity": "Personal", "type": "text"},
    {"group": "Members",     "key": "member.first_name",
     "label": "First name",        "sensitivity": "Personal", "type": "text"},
    {"group": "Members",     "key": "member.other_name",
     "label": "Other name",        "sensitivity": "Personal", "type": "text"},

    # ---- Member: demographic + status ------------------------------------
    # BUG-S27-022 — every coded Member field below mirrors
    # apps/data_management/choice_field_map.py:MEMBER_FIELDS. The
    # `options_source` slug maps to a seeded ChoiceList — the wizard's
    # /choice-list-bundle/ batch fetch resolves them all in one
    # round-trip (BUG-S27-020). They used to ship as type:text with no
    # options, so Step 2 of the DRS wizard rendered free-text inputs
    # for fields that are actually closed-vocabulary codes.
    {"group": "Members",     "key": "member.relationship_to_head",
     "label": "Relationship to head", "sensitivity": "Public", "type": "enum",
     "options_source": "choice_list?name=relationship"},
    # `member.sex` keeps inline F/M options pending verification of the
    # in-DB code space (memory hint: "1"/"2" not "F"/"M" — needs check
    # before flipping, lest existing DRS queries break).
    {"group": "Members",     "key": "member.sex",
     "label": "Sex",               "sensitivity": "Public",   "type": "enum",
     "options": [{"value": "F", "label": "Female"}, {"value": "M", "label": "Male"}]},
    {"group": "Members",     "key": "member.date_of_birth",
     "label": "Date of birth",     "sensitivity": "Personal", "type": "date"},
    {"group": "Members",     "key": "member.age_years",
     "label": "Age (years)",       "sensitivity": "Personal", "type": "number"},
    {"group": "Members",     "key": "member.marital_status",
     "label": "Marital status",    "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=marital_status"},
    {"group": "Members",     "key": "member.nationality",
     "label": "Nationality",       "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=nationality"},
    {"group": "Members",     "key": "member.residency_status",
     "label": "Residency status",  "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=residency_status"},
    {"group": "Members",     "key": "member.birth_certificate_status",
     "label": "Birth certificate", "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=birth_certificate"},

    # ---- Member: NIN (sensitive) -----------------------------------------
    {"group": "Members",     "key": "member.nin_status",
     "label": "NIN status",        "sensitivity": "Sensitive","type": "enum",
     "options_source": "choice_list?name=nin_status"},
    {"group": "Members",     "key": "member.nin_hash",
     "label": "NIN hash",          "sensitivity": "Sensitive","type": "text"},
    {"group": "Members",     "key": "member.nin_last4",
     "label": "NIN last 4",        "sensitivity": "Sensitive","type": "text"},

    # ---- Member: contact + flags -----------------------------------------
    {"group": "Members",     "key": "member.telephone_1",
     "label": "Telephone 1",       "sensitivity": "Personal", "type": "text"},
    {"group": "Members",     "key": "member.telephone_2",
     "label": "Telephone 2",       "sensitivity": "Personal", "type": "text"},
    {"group": "Members",     "key": "member.telephone_in_name_flag",
     "label": "Phone in own name", "sensitivity": "Personal", "type": "bool"},
    {"group": "Members",     "key": "member.mobile_money_flag",
     "label": "Mobile money",      "sensitivity": "Personal", "type": "bool"},
    {"group": "Members",     "key": "member.mother_alive_flag",
     "label": "Mother alive",      "sensitivity": "Personal", "type": "bool"},
    {"group": "Members",     "key": "member.father_alive_flag",
     "label": "Father alive",      "sensitivity": "Personal", "type": "bool"},

    # ---- US-S22-DE-09: Dwelling (G1–G7) ---------------------------------
    {"group": "Dwelling",    "key": "household.dwelling.tenure",
     "label": "Dwelling tenure",   "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=dwelling_tenure"},
    {"group": "Dwelling",    "key": "household.dwelling.dwelling_type",
     "label": "Dwelling type",     "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=dwelling_type"},
    {"group": "Dwelling",    "key": "household.dwelling.total_rooms",
     "label": "Total rooms",       "sensitivity": "Public",   "type": "number"},
    {"group": "Dwelling",    "key": "household.dwelling.sleeping_rooms",
     "label": "Sleeping rooms",    "sensitivity": "Public",   "type": "number"},
    {"group": "Dwelling",    "key": "household.dwelling.roof_material",
     "label": "Roof material",     "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=roof_material"},
    {"group": "Dwelling",    "key": "household.dwelling.wall_material",
     "label": "Wall material",     "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=wall_material"},
    {"group": "Dwelling",    "key": "household.dwelling.floor_material",
     "label": "Floor material",    "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=floor_material"},

    # ---- US-S22-DE-09: Utilities (G8–G14) -------------------------------
    {"group": "Utilities",   "key": "household.utilities.cooking_fuel",
     "label": "Cooking fuel",      "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=cooking_fuel"},
    {"group": "Utilities",   "key": "household.utilities.lighting_energy",
     "label": "Lighting energy",   "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=lighting_energy"},
    {"group": "Utilities",   "key": "household.utilities.drinking_water_source",
     "label": "Drinking water",    "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=drinking_water_source"},
    {"group": "Utilities",   "key": "household.utilities.toilet_facility",
     "label": "Toilet facility",   "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=toilet_facility"},
    {"group": "Utilities",   "key": "household.utilities.toilet_shared",
     "label": "Toilet shared",     "sensitivity": "Public",   "type": "bool"},
    {"group": "Utilities",   "key": "household.utilities.households_sharing_toilet",
     "label": "Households sharing toilet", "sensitivity": "Public", "type": "number"},
    {"group": "Utilities",   "key": "household.utilities.waste_disposal",
     "label": "Waste disposal",    "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=waste_disposal"},

    # ---- US-S22-DE-09: Livelihood (G16, H1–H8) --------------------------
    {"group": "Livelihood",  "key": "household.livelihood.main_livelihood",
     "label": "Main livelihood",   "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=main_livelihood"},
    {"group": "Livelihood",  "key": "household.livelihood.agricultural_purpose",
     "label": "Agricultural purpose", "sensitivity": "Public", "type": "enum",
     "options_source": "choice_list?name=agricultural_purpose"},
    {"group": "Livelihood",  "key": "household.livelihood.land_ownership",
     "label": "Land ownership",    "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=land_ownership"},
    {"group": "Livelihood",  "key": "household.livelihood.land_hectares",
     "label": "Land hectares",     "sensitivity": "Public",   "type": "number"},
    {"group": "Livelihood",  "key": "household.livelihood.land_title",
     "label": "Land title",        "sensitivity": "Public",   "type": "enum",
     "options_source": "choice_list?name=land_title"},

    # ---- US-S22-DE-09: FoodSecurity (I1–I8 + computed score) -----------
    {"group": "Food security", "key": "household.food_security.fies_raw_score",
     "label": "FIES raw score",    "sensitivity": "Internal", "type": "number"},
    {"group": "Food security", "key": "household.food_security.worried_food",
     "label": "Worried about food","sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Food security", "key": "household.food_security.skipped_meal",
     "label": "Skipped a meal",    "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Food security", "key": "household.food_security.ran_out_food",
     "label": "Ran out of food",   "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Food security", "key": "household.food_security.hungry_no_eat",
     "label": "Hungry, did not eat", "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Food security", "key": "household.food_security.whole_day_no_eat",
     "label": "Whole day without eating", "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},

    # ---- US-S22-DE-09: FoodConsumption (I9–I17 + WFP-weighted) ---------
    {"group": "Food consumption", "key": "household.food_consumption.fcs_score",
     "label": "Food consumption score (FCS)", "sensitivity": "Internal", "type": "number"},
    {"group": "Food consumption", "key": "household.food_consumption.staples_days",
     "label": "Staples — days last 7", "sensitivity": "Internal", "type": "number"},
    {"group": "Food consumption", "key": "household.food_consumption.pulses_days",
     "label": "Pulses — days last 7",  "sensitivity": "Internal", "type": "number"},
    {"group": "Food consumption", "key": "household.food_consumption.dairy_days",
     "label": "Dairy — days last 7",   "sensitivity": "Internal", "type": "number"},
    {"group": "Food consumption", "key": "household.food_consumption.meat_days",
     "label": "Meat — days last 7",    "sensitivity": "Internal", "type": "number"},
    {"group": "Food consumption", "key": "household.food_consumption.vegetables_days",
     "label": "Vegetables — days last 7", "sensitivity": "Internal", "type": "number"},

    # ---- US-S22-DE-09: Health (D1–D2) — chronic_illness_types is DPPA --
    # special category data (HIV / TB codes possible) and requires a
    # DSA clause explicitly granting it.
    {"group": "Health",      "key": "member.health.chronic_illness_flag",
     "label": "Chronic illness",   "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Health",      "key": "member.health.chronic_illness_types",
     "label": "Chronic illness types (HIV/TB possible)",
     "sensitivity": "Sensitive",   "type": "enum-multi",
     "options_source": "choice_list?name=chronic_illness_type",
     "requires_special_scope": True},

    # ---- US-S22-DE-09: Disability (Washington Group D3–D8) -------------
    {"group": "Disability",  "key": "member.disability.seeing",
     "label": "WG — seeing",       "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=wg_difficulty_level"},
    {"group": "Disability",  "key": "member.disability.hearing",
     "label": "WG — hearing",      "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=wg_difficulty_level"},
    {"group": "Disability",  "key": "member.disability.walking",
     "label": "WG — walking",      "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=wg_difficulty_level"},
    {"group": "Disability",  "key": "member.disability.memory",
     "label": "WG — memory",       "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=wg_difficulty_level"},
    {"group": "Disability",  "key": "member.disability.selfcare",
     "label": "WG — self-care",    "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=wg_difficulty_level"},
    {"group": "Disability",  "key": "member.disability.communication",
     "label": "WG — communication","sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=wg_difficulty_level"},
    {"group": "Disability",  "key": "member.disability.wg_disability_flag",
     "label": "WG disability (any)","sensitivity": "Personal", "type": "bool"},

    # ---- US-S22-DE-09: Education (E1–E6) -------------------------------
    {"group": "Education",   "key": "member.education.literacy_status",
     "label": "Literacy status",   "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=literacy_status"},
    {"group": "Education",   "key": "member.education.ever_attended",
     "label": "Ever attended",     "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Education",   "key": "member.education.highest_grade",
     "label": "Highest grade",     "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=highest_grade"},
    {"group": "Education",   "key": "member.education.currently_attending",
     "label": "Currently attending", "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Education",   "key": "member.education.why_stopped",
     "label": "Why stopped",       "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=why_stopped_school"},

    # ---- US-S22-DE-09: Employment (F1–F10) -----------------------------
    {"group": "Employment",  "key": "member.employment.main_activity_last_30d",
     "label": "Main activity (30d)", "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=employment_main_activity"},
    {"group": "Employment",  "key": "member.employment.sector",
     "label": "Sector",            "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=employment_sector"},
    {"group": "Employment",  "key": "member.employment.employment_status",
     "label": "Employment status", "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=employment_status"},
    {"group": "Employment",  "key": "member.employment.is_govt_programme_beneficiary",
     "label": "Gov programme beneficiary", "sensitivity": "Internal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},
    {"group": "Employment",  "key": "member.employment.made_savings",
     "label": "Made savings",      "sensitivity": "Personal", "type": "enum",
     "options_source": "choice_list?name=yes_no"},

    # ---- US-S22-DE-09: NIN-derived columns flagged for special scope ---
    # nin_hash/nin_last4 are already in the catalogue above with
    # sensitivity=Sensitive; here we flag them as requires_special_scope
    # so the DRS wizard prevents accidental selection without an explicit
    # DSA clause (DPPA 2019 + ADR-0021).
]


# US-S22-DE-09: NIN-derived columns and any HIV-relevant column require
# the DSA to explicitly grant access. The flag is read by the wizard
# to surface a "needs scope expansion" badge — server still enforces
# scope via the existing field_scope check at submit time.
_REQUIRES_SPECIAL_SCOPE = {
    "member.nin_hash",
    "member.nin_last4",
    "member.health.chronic_illness_types",
}


for _entry in FIELD_CATALOGUE:
    if _entry["key"] in _REQUIRES_SPECIAL_SCOPE:
        _entry.setdefault("requires_special_scope", True)

# Filter operators a partner / operator can use to constrain rows.
# Same for every role; the values they can compare against depend
# on the field type and the DSA's per-field sensitivity.
FILTER_OPERATORS: list[dict[str, str]] = [
    {"op": "eq",          "label": "is",                "applies_to": "any"},
    {"op": "neq",         "label": "is not",            "applies_to": "any"},
    {"op": "in",          "label": "is one of",         "applies_to": "any"},
    {"op": "not_in",      "label": "is not one of",     "applies_to": "any"},
    {"op": "between",     "label": "between",           "applies_to": "numeric_or_date"},
    {"op": "starts_with", "label": "starts with",       "applies_to": "string"},
    {"op": "is_null",     "label": "is missing",        "applies_to": "any"},
]

# Filter predicates the backend's validate_against_dsa actually
# recognises. The frontend query builder renders rows over this
# catalogue — `payload_key` is where the row's values land in
# request_payload, `value_source` is the URL the UI fetches to
# populate the value picker. When the backend learns a new
# predicate, add an entry here and the UI follows automatically
# (US-S27-012).
def _geo_filter_field(level: str, label: str) -> dict[str, Any]:
    return {
        "key": f"household.{level}_code",
        "label": label,
        "operators": ["in"],
        "value_source": (
            "/api/v1/reference-data/geographic-units/"
            f"?level={level}&status=active&page_size=500"
        ),
        "value_type": "multi_code",
        "payload_key": f"{level}_codes",
        "value_code_field": "code",
        "value_label_field": "name",
    }


# US-S27-016: every UBOS level (region → village) is a filter
# predicate. validate_against_dsa walks each one against the
# DSA's geographic_scope at the same level.
FILTER_FIELDS: list[dict[str, Any]] = [
    _geo_filter_field("region",     "Region"),
    _geo_filter_field("sub_region", "Sub-region"),
    _geo_filter_field("district",   "District"),
    _geo_filter_field("county",     "County"),
    _geo_filter_field("sub_county", "Sub-county"),
    _geo_filter_field("parish",     "Parish"),
    _geo_filter_field("village",    "Village"),
    {
        "key": "programme",
        "label": "Programme",
        "operators": ["in"],
        "value_source": "/api/v1/programmes/?status=active&page_size=200",
        "value_type": "multi_code",
        "payload_key": "programme_codes",
        "value_code_field": "code",
        "value_label_field": "name",
    },
]

# Delivery channels — partner-facing differ from operator-facing.
DELIVERY_METHODS: list[dict[str, Any]] = [
    {"id": "portal_download",
     "label": "Download from this portal (NDJSON, signed manifest)",
     "available_to": ["partner-analyst", "partner-dpo", "nsr-unit", "cdo"]},
    {"id": "sftp_push",
     "label": "SFTP push to your endpoint",
     "available_to": ["partner-analyst", "nsr-unit"]},
    {"id": "webhook",
     "label": "HTTPS webhook (HMAC-signed payload)",
     "available_to": ["partner-analyst", "nsr-unit"]},
]


def _active_partner_dsa(user) -> DataSharingAgreement | None:
    """Resolve the partner user's currently active DSA. Returns None
    when the user has no PARTNER scope (operator roles), or no active
    DSA under their partner code. The 'first active' is acceptable
    in MVP — partners with multiple active DSAs see fields the most
    permissive grants; tightening to per-DSA-selection lands later.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    from apps.security.models import OperatorScope, ScopeLevel
    partner_codes = list(
        OperatorScope.objects.filter(
            user=user, active=True, scope_level=ScopeLevel.PARTNER,
        ).exclude(scope_code="").values_list("scope_code", flat=True),
    )
    if not partner_codes:
        return None
    return (
        DataSharingAgreement.objects.filter(
            partner__code__in=partner_codes, status="active",
        ).order_by("-effective_from").first()
    )


def _available_dsas_for_user(user) -> list[DataSharingAgreement]:
    """Return active DSAs the user can file requests under, ordered by
    reference. The wizard uses this to render a "Filing on behalf of"
    picker on Step 1 — required for operator roles, redundant (but
    consistent) for partner roles.

    Partner-affiliated users: only DSAs whose partner matches their
    PARTNER scope. Operator / NSR Unit (no partner scope): every
    active DSA — they submit on behalf of any partner. The previous
    schema response had no way to express this, so the operator
    submit path silently dead-ended whenever schema.dsa_id was empty.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    qs = DataSharingAgreement.objects.filter(status="active").select_related("partner")
    from apps.security.models import OperatorScope, ScopeLevel
    partner_codes = list(
        OperatorScope.objects.filter(
            user=user, active=True, scope_level=ScopeLevel.PARTNER,
        ).exclude(scope_code="").values_list("scope_code", flat=True),
    )
    if partner_codes:
        qs = qs.filter(partner__code__in=partner_codes)
    return list(qs.order_by("reference"))


def build_schema(user) -> dict[str, Any]:
    """Generate the builder schema for `user`. Same top-level shape
    for every role; partner roles get DSA-restricted fields flagged
    with disabled=True + a human-readable reason.

    Operators (NSR Unit, CDO, etc.) are NOT subjected to DSA
    field-level limits at this layer — their access is controlled
    by ABAC on the underlying viewsets and the audit chain. The
    builder schema gives them the full field catalogue.
    """
    dsa = _active_partner_dsa(user)
    is_partner = dsa is not None
    # ADR-0013: read allowed field groups from the canonical field_scope.
    # Legacy 'household.x' style fields are matched by group prefix.
    if is_partner:
        groups = {k for k, v in (dsa.field_scope or {}).items() if v}
        allowed_fields = set()
        for cat in FIELD_CATALOGUE:
            group_root = cat["key"].partition(".")[0]
            if group_root in groups or cat["group"] in groups:
                allowed_fields.add(cat["key"])
    else:
        allowed_fields = None

    fields = []
    for entry in FIELD_CATALOGUE:
        # Copy so we don't mutate the module-level catalogue.
        item = dict(entry)
        if is_partner and allowed_fields is not None and entry["key"] not in allowed_fields:
            item["disabled"] = True
            item["disabled_reason"] = (
                f"Outside DSA {dsa.reference} clause 4.2.b — "
                "request expansion via your data steward."
            )
        else:
            item["disabled"] = False
            item["disabled_reason"] = ""
        fields.append(item)

    role = "partner" if is_partner else "operator"
    delivery_methods = [
        m for m in DELIVERY_METHODS
        if (role == "partner" and "partner-analyst" in m["available_to"])
            or (role == "operator" and "nsr-unit" in m["available_to"])
    ]

    available_dsas = [
        {
            "id": str(d.id),
            "reference": d.reference,
            "partner_code": d.partner.code,
            "partner_name": d.partner.name,
            # Dates + budget travel on the picker payload so the
            # wizard's right-rail ACTIVE DSA card renders the real
            # values the operator just bound to (rather than the
            # earlier hardcoded OPM placeholder).
            "effective_from": d.effective_from.isoformat() if d.effective_from else None,
            "effective_to":   d.effective_to.isoformat()   if d.effective_to   else None,
            "monthly_row_budget": d.monthly_row_budget,
            "status": d.status,
            "version": d.version,
        }
        for d in _available_dsas_for_user(user)
    ]
    return {
        "role": role,
        "dsa_id": str(dsa.id) if dsa else "",
        "dsa_reference": dsa.reference if dsa else "",
        "available_dsas": available_dsas,
        "fields": fields,
        "filter_operators": list(FILTER_OPERATORS),
        "filter_fields": [dict(f) for f in FILTER_FIELDS],
        "delivery_methods": delivery_methods,
    }
