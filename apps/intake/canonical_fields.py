"""Payload field -> instrument question.

Three vocabularies describe the same facts and none of them agree:

  the instrument   g4_rooms_sleeping   d7_self_care   f1_main_job
  Kobo payloads    rooms_sleeping      self_care      main_job
  wizard payloads  sleeping_rooms      selfcare       main_activity_last_30d

The instrument codes a question by its place on the form. The Kobo
connector mostly strips that prefix. The parish wizard was written
separately and named the same fields differently again. Nothing has ever
recorded the correspondence, so the review screen carried a private copy
of it — and a private copy covered only the wizard's names, which is why
every Kobo-shaped record showed `rooms_sleeping` as "Rooms sleeping" with
its codes undecoded.

This is the correspondence, stated once, as question -> the payload keys
that feed it. It seeds FormQuestion.canonical_field (the first alias) and
FormQuestion.payload_aliases (all of them). After seeding the database is
the source of truth; this table is the record of how it got there.

It cannot be derived. Prefix-stripping resolves 57 of 185 questions and
silently mismaps the rest. Every entry below was read off real staged
payloads of both shapes, not inferred.
"""

# --- Sections A and B: identification, geography, respondent ------------
IDENTIFICATION = {
    "a0_region": ["region"],
    "a1_subregion": ["sub_region", "subregion"],
    "a2_district_city": ["district"],
    "a3_county_municipality": ["county"],
    "a4_subcounty_division_tc": ["sub_county", "subcounty"],
    "a5_parish_ward": ["parish"],
    "a6_lc1_village_cell": ["village"],
    "a7_rural_urban": ["urban_rural"],
    "a13_interviewer_name_code": ["interviewer"],
    "a14_parish_supervisor_name_code": ["supervisor"],
    "a15_start_time": ["start"],
}

# `b2_telephone_number` is the household contact number of record per
# ADR-0033. Kobo carries it as respondent_phone; the wizard as
# contact_phone.
SURVEY_STATUS = {
    "b1_respondent_name": ["respondent_name"],
    "b2_telephone_number": ["contact_phone", "respondent_phone"],
    "b3_address": ["address_narrative"],
    "b4_head_name": ["head_name"],
    "b5_interview_result": ["interview_result"],
    "hh_size": ["reported_household_size", "hh_size"],
    "consent": ["consent"],
}

# --- Section C: roster ---------------------------------------------------
ROSTER = {
    "c2_relationship": ["relationship_to_head"],
    "c3_marital_status": ["marital_status"],
    "c4_sex": ["sex"],
    "c5_date_of_birth": ["date_of_birth"],
    "c6_age_years": ["age_years"],
    "c7_birth_certificate": ["birth_certificate_status"],
    "c8_nin_status": ["nin_status"],
    "c9_nin": ["nin"],
    "c10_nationality": ["nationality"],
    "c11_residency_status": ["residency_status"],
    "c12_mother_alive": ["mother_alive_flag"],
    "c13_father_alive": ["father_alive_flag"],
    "c14_father_line": ["father_line_number"],
    "c15_mother_line": ["mother_line_number"],
    "c18_telephone_1": ["telephone_1"],
    "c19_telephone_2": ["telephone_2"],
}

# --- Section D: health and disability ------------------------------------
HEALTH = {
    "d1_chronic_illness": ["chronic_illness_flag", "chronic_illness"],
    "d2_chronic_illness_type": ["chronic_illness_types"],
    "d3_seeing": ["seeing"],
    "d4_hearing": ["hearing"],
    "d5_walking": ["walking"],
    "d6_remembering": ["memory", "remembering"],
    "d7_self_care": ["selfcare", "self_care"],
    "d8_communicating": ["communication", "communicating"],
}

# --- Section E: education ------------------------------------------------
EDUCATION = {
    "e1_literacy": ["literacy_status", "literacy"],
    "e2_ever_school": ["ever_attended", "ever_school"],
    "e3_never_school_reason": ["never_attended_reason", "never_school_reason"],
    "e4_highest_grade": ["highest_grade"],
    "e5_currently_attending": ["currently_attending"],
    "e6_stopped_school_reason": ["why_stopped", "stopped_school_reason"],
}

# --- Section F: employment -----------------------------------------------
EMPLOYMENT = {
    "f1_main_job": ["main_activity_last_30d", "main_job"],
    "f2_work_frequency": ["work_frequency"],
    "f3_work_sector": ["sector", "work_sector"],
    "f4_work_status": ["employment_status", "work_status"],
    "f5_not_working_reason": ["not_working_reason"],
    "f6_gov_program_beneficiary": ["gov_program_beneficiary"],
    "f7_programmes": ["programmes"],
    "f8_currently_benefiting": ["currently_benefiting"],
    "f9_made_savings": ["made_savings"],
    "f10_savings_place": ["savings_location", "savings_place"],
}

# --- Section G: housing, utilities, assets, livelihood -------------------
HOUSING = {
    "g1_tenure": ["tenure"],
    "g2_dwelling_type": ["dwelling_type"],
    "g3_rooms_total": ["total_rooms", "rooms_total"],
    "g4_rooms_sleeping": ["sleeping_rooms", "rooms_sleeping"],
    "g5_roof_material": ["roof_material"],
    "g6_wall_material": ["wall_material"],
    "g7_floor_material": ["floor_material"],
    "g8_cooking_fuel": ["cooking_fuel"],
    "g9_lighting_source": ["lighting_energy", "lighting_source"],
    "g10_water_source": ["drinking_water_source", "water_source"],
    "g11_toilet_type": ["toilet_facility", "toilet_type"],
    "g12_share_toilet": ["toilet_shared", "share_toilet"],
    "g13_share_toilet_households": ["households_sharing_toilet", "share_toilet_households"],
    "g14_waste_disposal": ["waste_disposal"],
    "g15_assets_owned": ["assets_owned"],
    "g16_livelihood_source": ["main_livelihood", "livelihood_source"],
    # housing.asset_counts.<item> — one question per counted asset.
    "g15_count_radio": ["radio"],
    "g15_count_tv": ["tv"],
    "g15_count_phone": ["phone"],
    "g15_count_bicycle": ["bicycle"],
    "g15_count_motorcycle": ["motorcycle"],
    "g15_count_car": ["car"],
    "g15_count_bed": ["bed"],
    "g15_count_mattress": ["mattress"],
    "g15_count_solar": ["solar"],
    "g15_count_livestock": ["livestock_count"],
}

# --- Section H: agriculture ---------------------------------------------
AGRICULTURE = {
    "h1_crop_production": ["crop_production"],
    "h2_livestock": ["livestock"],
    "h3_livestock_counts": ["livestock_counts"],
    "h4_ag_purpose": ["agricultural_purpose", "ag_purpose"],
    "h5_crops_grown": ["crops_grown"],
    "h6_land_ownership": ["land_ownership"],
    "h7_land_hectares": ["land_hectares"],
    "h8_title_deed": ["land_title"],
}

# --- Section I: food security -------------------------------------------
# The eight FIES items. Kobo keys them i1_fies..i8_fies; the wizard names
# each one after what it asks.
FIES = {
    "i1_fies": ["i1_fies", "worried_food"],
    "i2_fies": ["i2_fies", "unhealthy_food"],
    "i3_fies": ["i3_fies", "limited_variety"],
    "i4_fies": ["i4_fies", "skipped_meal"],
    "i5_fies": ["i5_fies", "ate_less"],
    "i6_fies": ["i6_fies", "ran_out_food"],
    "i7_fies": ["i7_fies", "hungry_no_eat"],
    "i8_fies": ["i8_fies", "whole_day_no_eat"],
}

# Food groups. Kobo nests them — food_security.food_groups.staples.days —
# so the leaf key alone ("days") is ambiguous across nine groups and the
# parent segment is needed to resolve it. The alias below is the joined
# form, and resolveField tries "<parent>_<key>" for exactly this reason.
# The wizard flattens the same facts to staples_days, so one alias serves
# both shapes.
FOOD_GROUPS = {
    "i9_staples_days": ["staples_days"],
    "i9_staples_yesterday": ["staples_yesterday"],
    "i9_staples_source_primary": ["staples_source_primary", "staples_source"],
    "i9_staples_source_secondary": ["staples_source_secondary"],
    "i10_pulses_nuts_days": ["pulses_nuts_days", "pulses_days"],
    "i10_pulses_nuts_yesterday": ["pulses_nuts_yesterday"],
    "i10_pulses_nuts_source_primary": ["pulses_nuts_source_primary"],
    "i10_pulses_nuts_source_secondary": ["pulses_nuts_source_secondary"],
    "i11_milk_dairy_days": ["milk_dairy_days", "dairy_days"],
    "i11_milk_dairy_yesterday": ["milk_dairy_yesterday"],
    "i11_milk_dairy_source_primary": ["milk_dairy_source_primary"],
    "i11_milk_dairy_source_secondary": ["milk_dairy_source_secondary"],
    "i12_meat_fish_eggs_days": ["meat_fish_eggs_days", "meat_days"],
    "i12_meat_fish_eggs_yesterday": ["meat_fish_eggs_yesterday"],
    "i12_meat_fish_eggs_source_primary": ["meat_fish_eggs_source_primary"],
    "i12_meat_fish_eggs_source_secondary": ["meat_fish_eggs_source_secondary"],
    "i13_vegetables_days": ["vegetables_days"],
    "i13_vegetables_yesterday": ["vegetables_yesterday"],
    "i13_vegetables_source_primary": ["vegetables_source_primary"],
    "i13_vegetables_source_secondary": ["vegetables_source_secondary"],
    "i14_fruits_days": ["fruits_days"],
    "i14_fruits_yesterday": ["fruits_yesterday"],
    "i14_fruits_source_primary": ["fruits_source_primary"],
    "i14_fruits_source_secondary": ["fruits_source_secondary"],
    "i15_oils_fats_days": ["oils_fats_days", "oils_days"],
    "i15_oils_fats_yesterday": ["oils_fats_yesterday"],
    "i15_oils_fats_source_primary": ["oils_fats_source_primary"],
    "i15_oils_fats_source_secondary": ["oils_fats_source_secondary"],
    "i16_sugar_sweets_days": ["sugar_sweets_days", "sugar_days"],
    "i16_sugar_sweets_yesterday": ["sugar_sweets_yesterday"],
    "i16_sugar_sweets_source_primary": ["sugar_sweets_source_primary"],
    "i16_sugar_sweets_source_secondary": ["sugar_sweets_source_secondary"],
    "i17_condiments_days": ["condiments_days"],
    "i17_condiments_yesterday": ["condiments_yesterday"],
    "i17_condiments_source_primary": ["condiments_source_primary"],
    "i17_condiments_source_secondary": ["condiments_source_secondary"],
}

# --- Sections K and L: shocks and coping --------------------------------
# Repeat blocks. Several questions feed one column on purpose: the four
# K03 questions are the same question asked per livelihood, and the
# payload flattens them into rows of {shock_type, severity}. This is why
# canonical_field is not unique.
SHOCKS = {
    "k01_shock_affected": ["shock_affected"],
    "k02_livelihood_affected": ["livelihood_affected"],
}

# Section K asks the shock questions once per livelihood: K03 is "main
# shock affecting crops / livestock / labour / other" and K04 is the
# severity of that shock. The question name carries the livelihood, and
# the `shock_livelihood` ChoiceList codes it.
#
# That correspondence is not derivable from either side — "labour_
# employment" in the question name is "03 Labour/employment" in the code
# frame — so it is declared here, once, next to the rest of the
# instrument mapping. A contract test checks these codes still match the
# active shock_livelihood list, so a code-frame change fails a test
# rather than silently mismapping every shock in the country.
#
# (livelihood code, the infix in the K03/K04 question names)
SHOCK_LIVELIHOODS = (
    ("01", "crops"),
    ("02", "livestock"),
    ("03", "labour_employment"),
    ("04", "other"),
)
SHOCK_LIVELIHOOD_LIST = "shock_livelihood"

# Every L question is one coping strategy on the same frequency scale.
# Kobo keys each by question name; the wizard emits rows of
# {strategy_type, frequency}.
COPING_PREFIXES = ("l01", "l02")

QUESTION_ALIASES: dict[str, list[str]] = {
    **IDENTIFICATION, **SURVEY_STATUS, **ROSTER, **HEALTH, **EDUCATION,
    **EMPLOYMENT, **HOUSING, **AGRICULTURE, **FIES, **FOOD_GROUPS, **SHOCKS,
}

# The primary canonical name for each question: the first alias listed.
QUESTION_TO_CANONICAL = {q: a[0] for q, a in QUESTION_ALIASES.items()}


# --- Repeat-block columns ------------------------------------------------
# A repeat block flattens many questions into a few columns. The payload
# carries the COLUMN name — shock_type, severity, strategy_type — and the
# question identity moves into the row.
#
# These cannot be aliases of a question, because every question in the
# block would claim them and the first one would win: the shock_type
# column then reads "Main shock affecting crops" on the livestock row,
# and strategy_type reads "Engage in casual labor" for all eighteen
# coping strategies. A column that names one of the things it holds is
# worse than one that names none.
#
# So each column is declared once, with the name of the column and the
# list its values decode through.
REPEAT_COLUMNS = {
    "shock_type": ("Shock type", "shock_type"),
    "severity": ("Severity of loss", "severity"),
    "category": ("Livelihood affected", "shock_livelihood"),
    "strategy_type": ("Coping strategy", None),
    "frequency": ("How often", "coping_frequency"),
    "asset_type": ("Asset", "asset_type"),
    "livelihoods_affected": ("Livelihoods affected", "shock_livelihood"),
    "crop_name": ("Crop", None),
    "livestock_type": ("Livestock", None),
    "count": ("Number", None),
    "rank_order": ("Rank", None),
    "event_date": ("Event date", None),
}


# --- Fields the instrument does not ask ---------------------------------
# Emitted by the connector or the capture channel, not answered by a
# respondent, so no FormQuestion owns them and hunting for one would
# always report a missing dependency. Declared here, server-side and once,
# so the design layer still holds no field vocabulary of its own. `source`
# is carried to the API so the screen can say a field was not asked rather
# than implying the questionnaire asked it.
DERIVED_FIELDS = {
    # Name parts the connector splits out of C1 Full Name.
    "first_name": "First name",
    "surname": "Surname",
    "other_name": "Other name",
    # Head designation, derived from C2 relationship.
    "is_head": "Is head of household",
    "line_number": "Line number",
    "member_index": "Line number",
    # Identity, held as a hash plus last four digits (never in full).
    "nin_last4": "NIN (last 4 digits)",
    # Capture channel metadata.
    "deviceid": "Device",
    "end": "Interview ended",
    "start_time": "Interview started",
    "source_channel": "Capture channel",
    "gps_lat": "Latitude",
    "gps_lng": "Longitude",
    "gps_accuracy_m": "GPS accuracy (m)",
    # Repeat-row bookkeeping.
    "asset_counts": "Asset counts",
}
