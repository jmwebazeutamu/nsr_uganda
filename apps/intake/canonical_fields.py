"""Instrument question -> canonical payload field.

Two vocabularies have always described the same concept. The instrument
names a question by where it sits on the form (`g6_wall_material`,
`b2_telephone_number`, `h8_title_deed`); the canonical payload names the
fact (`wall_material`, `contact_phone`, `land_title`). Until now nothing
wrote the correspondence down, so the household review screen carried a
private copy of it — and a private copy is how the two drift.

This is that correspondence, stated once. It seeds
`FormQuestion.canonical_field`; after seeding the database is the source
of truth and this table is only the record of how it got there.

It cannot be derived. `g4_rooms_sleeping` is `sleeping_rooms` (the words
swap), `h8_title_deed` is `land_title` (different words entirely), and
`a15_start_time` is `start`. Any prefix-stripping heuristic gets those
wrong silently, which is worse than not having them.

Keys are question names in the active v1 instrument; values are the
canonical payload leaf keys the DIH staging payloads actually carry.
"""

# --- Section A: identification ------------------------------------------
IDENTIFICATION = {
    "a7_rural_urban": "urban_rural",
    "a13_interviewer_name_code": "interviewer",
    "a14_parish_supervisor_name_code": "supervisor",
    "a15_start_time": "start",
}

# --- Section B: survey status / respondent ------------------------------
# `b2_telephone_number` is the household contact number of record per
# ADR-0033; the payload carries it as `contact_phone`.
SURVEY_STATUS = {
    "b1_respondent_name": "respondent_name",
    "b2_telephone_number": "contact_phone",
    "b3_address": "address_narrative",
    "b4_head_name": "head_name",
    "b5_interview_result": "interview_result",
    "hh_size": "reported_household_size",
    "consent": "consent",
}

# --- Section C: roster, health, education, employment -------------------
# Per-member fields. The payload carries these on the member (Kobo) or in
# a top-level bag keyed by line number (parish wizard); either way the
# leaf key is the same, which is why one mapping serves both shapes.
ROSTER = {
    "c2_relationship": "relationship_to_head",
    "c3_marital_status": "marital_status",
    "c4_sex": "sex",
    "c5_date_of_birth": "date_of_birth",
    "c6_age_years": "age_years",
    "c7_birth_certificate": "birth_certificate_status",
    "c8_nin_status": "nin_status",
    "c10_nationality": "nationality",
    "c11_residency_status": "residency_status",
}

HEALTH = {
    "d1_chronic_illness": "chronic_illness_flag",
    "d2_chronic_illness_type": "chronic_illness_types",
    "d3_seeing": "seeing",
    "d4_hearing": "hearing",
    "d5_walking": "walking",
    "d6_remembering": "memory",
    "d7_self_care": "selfcare",
    "d8_communicating": "communication",
}

EDUCATION = {
    "e1_literacy": "literacy_status",
    "e2_ever_school": "ever_attended",
    "e3_never_school_reason": "never_attended_reason",
    "e4_highest_grade": "highest_grade",
    "e5_currently_attending": "currently_attending",
    "e6_stopped_school_reason": "why_stopped",
}

EMPLOYMENT = {
    "f1_main_job": "main_activity_last_30d",
    "f2_work_frequency": "work_frequency",
    "f3_work_sector": "sector",
    "f4_work_status": "employment_status",
    "f5_not_working_reason": "not_working_reason",
    "f9_made_savings": "made_savings",
    "f10_savings_place": "savings_location",
}

# --- Section G: housing, utilities, assets, livelihood ------------------
HOUSING = {
    "g1_tenure": "tenure",
    "g2_dwelling_type": "dwelling_type",
    "g3_rooms_total": "rooms_total",
    "g4_rooms_sleeping": "sleeping_rooms",
    "g5_roof_material": "roof_material",
    "g6_wall_material": "wall_material",
    "g7_floor_material": "floor_material",
    "g8_cooking_fuel": "cooking_fuel",
    "g9_lighting_source": "lighting_energy",
    "g10_water_source": "water_source",
    "g11_toilet_type": "toilet_type",
    "g12_share_toilet": "share_toilet",
    "g13_share_toilet_households": "households_sharing_toilet",
    "g14_waste_disposal": "waste_disposal",
    "g15_assets_owned": "assets_owned",
    "g16_livelihood_source": "main_livelihood",
}

# --- Section H: agriculture ---------------------------------------------
AGRICULTURE = {
    "h1_crop_production": "crop_production",
    "h2_livestock": "livestock",
    "h3_livestock_counts": "livestock_counts",
    "h4_ag_purpose": "ag_purpose",
    "h5_crops_grown": "crops_grown",
    "h6_land_ownership": "land_ownership",
    "h7_land_hectares": "land_hectares",
    "h8_title_deed": "land_title",
}

# --- Sections K and L: shocks and coping --------------------------------
# Repeat blocks. Several questions feed one canonical column on purpose:
# the four K03 questions are the same question asked per livelihood, and
# the payload flattens them into rows of {shock_type, severity}. This is
# why canonical_field is not unique.
SHOCKS = {
    "k01_shock_affected": "shock_affected",
    "k02_livelihood_affected": "livelihood_affected",
    "k03_crops_shock_type": "shock_type",
    "k03_livestock_shock_type": "shock_type",
    "k03_labour_employment_shock_type": "shock_type",
    "k03_other_shock_type": "shock_type",
    "k04_crops_shock_severity": "severity",
    "k04_livestock_shock_severity": "severity",
    "k04_labour_employment_shock_severity": "severity",
    "k04_other_shock_severity": "severity",
}

# Every L question is one coping strategy scored on the same frequency
# scale, so they all carry the `strategy_type` column's vocabulary.
COPING_PREFIXES = ("l01", "l02")

QUESTION_TO_CANONICAL = {
    **IDENTIFICATION, **SURVEY_STATUS, **ROSTER, **HEALTH, **EDUCATION,
    **EMPLOYMENT, **HOUSING, **AGRICULTURE, **SHOCKS,
}


# --- Fields the instrument does not ask ---------------------------------
# These are emitted by the capture channel, not answered by a respondent,
# so no FormQuestion owns them and looking for one would always report a
# missing dependency. They are declared here, server-side and once, so the
# design layer still holds no field vocabulary of its own. `source` is
# carried through to the API so the screen can say where a label came
# from rather than implying the questionnaire asked it.
CAPTURE_METADATA = {
    "deviceid": "Device",
    "end": "Interview ended",
    "source_channel": "Capture channel",
    "gps_lat": "Latitude",
    "gps_lng": "Longitude",
    "gps_accuracy_m": "GPS accuracy (m)",
    "member_index": "Line number",
    "asset_counts": "Asset counts",
}
