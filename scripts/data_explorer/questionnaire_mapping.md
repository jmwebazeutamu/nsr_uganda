# Questionnaire → catalogue mapping

Proof-of-trace. Every variable in `catalogue_seed.yaml` that has a `source_questionnaire_path` populated traces back to questionnaire v2 (`/docs/06_questionnaire.docx`, March 2026). Variables that are `derived_from` a computation rather than a direct question (e.g. `pmt.band`, `household.member_count_actual`, derived flags) carry no questionnaire path and are excluded from the table below.

| Variable code | Questionnaire section | Original question text (verbatim, English) |
|---|---|---|
| `geography.sub_region_code` | A.1 | SUB REGION |
| `geography.district_code` | A.2 | DISTRICT/CITY |
| `geography.county_code` | A.3 | COUNTY/MUNICIPALITY |
| `geography.sub_county_code` | A.4 | SUBCOUNTY/DIVISION/TOWN COUNCIL |
| `geography.parish_code` | A.5 | Parish/Ward |
| `geography.village_code` | A.6 | LC1/Village/Cell |
| `household.sub_region_code` | A.1 | SUB REGION |
| `household.district_code` | A.2 | DISTRICT/CITY |
| `household.sub_county_code` | A.4 | SUBCOUNTY/DIVISION/TOWN COUNCIL |
| `household.urban_rural` | A.7 | Rural/Urban (Urban = 1; Rural = 2) |
| `household.enumeration_area` | A.8 | Enumeration Area |
| `household.reported_household_size` | B | SURVEY STATUS — operator-reported household size at intake |
| `household.head_sex` | C.4 | Is (NAME) male or female? |
| `household.head_age_band` | C.7 | What is (NAME'S) age in completed years? |
| `household.residence_status` | C.11 | Residency Status (Resident / Displaced (IDP) / Asylum Seeker / Refugee / Returnee / Repatriated) |
| `household.current_consent_state` | Consent statement | Do you agree to participate in the interview and consent for the use of the data collected by partners engaged in social protection programs? |
| `household.current_intake_source` | B | Result of the household interview / channel through which the household entered NSR |
| `household.gps_present_flag` | A.11-A.12 | CAPI GPS Coordinates - Latitude / Longitude |
| `household.gps_accuracy_m` | A.11-A.12 | CAPI GPS Coordinates - Latitude / Longitude (accuracy fix value) |
| `member.sex` | C.4 | Is (NAME) male or female? (1=Male, 2=Female) |
| `member.age_band` | C.7 | What is (NAME'S) age in completed years? |
| `member.age_years` | C.7 | What is (NAME'S) age in completed years? IF Age is 95 OR MORE RECORD 95 |
| `member.date_of_birth` | C.6 | What is (NAME'S) exact date of birth? |
| `member.relationship_to_head` | C.3 | Relationship to Head (01.Head ... 15.Not related) |
| `member.marital_status` | C.5 | Marital status (only members aged 12 and above) |
| `member.nationality` | C.10 | Nationality (1=Ugandan ... 11=Other) |
| `member.residency_status` | C.11 | Residency Status |
| `member.birth_certificate_status` | C.8 | Does (NAME) have a Birth Certificate? |
| `member.nin_status` | C.9 | Does (NAME) have a National Identification Number (NIN)? (1=Yes has card ... 8=Don't know) |
| `member.nin_value` | C.9 | If Yes, Enter your NIN |
| `member.nin_hash` | C.9 | Derived join hash of NIN (ADR-0002) |
| `member.telephone_present_flag` | C.17-C.20 | Does [Name] have A telephone Number? / Telephone 1 / Telephone 2 |
| `member.mobile_money_flag` | C.21 | Are these Numbers registered in your Names and Mobile Money Activated? |
| `member.orphan_flag` | C.12-C.13 | Is [NAME'S] biological mother alive? / Is [NAME]'s biological father alive? |
| `member.mother_alive_flag` | C.12 | Is [NAME'S] biological mother alive? |
| `member.father_alive_flag` | C.13 | Is [NAME]'s biological father alive? |
| `dwelling.tenure` | G.1 | TENURE OF DWELLING UNIT? (11=Owner occupied ... 17=Rented private) |
| `dwelling.dwelling_type` | G.2 | WHAT IS THE TYPE OF DWELLING UNIT? (11=Detached/Bangalow ... 22=Flat/Multi-storey) |
| `dwelling.total_rooms` | G.3 | HOW MANY ROOMS DOES THIS DWELLING HAVE? |
| `dwelling.sleeping_rooms` | G.4 | HOW MANY ROOMS ARE USED FOR SLEEPING |
| `dwelling.roof_material` | G.5 | TYPE OF MATERIAL MAINLY USED FOR THE CONSTRUCTION OF THE ROOF |
| `dwelling.wall_material` | G.6 | TYPE OF MATERIAL MAINLY USED FOR THE CONSTRUCTION OF THE WALL |
| `dwelling.floor_material` | G.7 | TYPE OF MATERIAL MAINLY USED FOR THE FLOOR |
| `utilities.cooking_fuel` | G.8 | What does this household use mainly for cooking most of the time...? |
| `utilities.lighting_energy` | G.9 | What does this household mainly use most of the time as energy for lighting...? |
| `utilities.drinking_water_source` | G.10 | What is the household's MAIN source of water for DRINKING? |
| `utilities.toilet_facility` | G.11 | What type of toilet facility does this household MAINLY use? |
| `utilities.toilet_shared` | G.12 | Does the household share this toilet facility with other households? |
| `utilities.households_sharing_toilet` | G.13 | With how many households does this household share a toilet facility? (cap 10) |
| `utilities.waste_disposal` | G.14 | What is the most commonly used method of solid waste disposal/rubbish from this household? |
| `asset_ownership.asset_type` | G.15 | Does any member in this household own…(ASSETS)? Record the number owned by entire household |
| `asset_ownership.count` | G.15 | Record the number owned by entire household, and if 9 or more record 9 |
| `livelihood.main_livelihood` | G.16 | What was the main source of the household's livelihood in the last 12 months? |
| `livelihood.crop_production_zone` | H.1 | Did this household undertake crop production in the last 12 months? (1=Yes within EA ... 5=No) |
| `livelihood.livestock_zone` | H.2 | Did this household rear/keep livestock/poultry/bees in the last 12 months? |
| `livelihood.agricultural_purpose` | H.4 | What is the main purpose of [agricultural] production? (1=Mainly for sale ... 6=Others) |
| `livelihood.land_ownership` | H.6 | Does Household or any member of household own any agricultural or non-agricultural land...? |
| `livelihood.land_hectares` | H.7 | Specify how many hectares of each type of land |
| `livelihood.land_title` | H.8 | Does [NAME] have title deed, certificate of ownership, certificate of hereditary acquisition, lease or rental...? |
| `food_security.fies_raw_score` | I.1-I.8 | FIES eight-item raw score (sum of yes-coded responses) |
| `food_security.worried_food` | I.1 | In the LAST 12 MONTHS did any member in this household get WORRIED for not having food to eat because of a lack of money or other resources? |
| `food_security.skipped_meal` | I.4 | In the last 12 months has any member in this household EVER HAD TO SKIP A MEAL because there was not enough money or other resources to get food? |
| `food_security.whole_day_no_eat` | I.8 | Has this household ever GONE WITHOUT EATING FOR A WHOLE DAY because of a lack of money or other resources in the last 12 months? |
| `food_consumption.fcs_score` | I.9-I.17 | WFP Food Consumption Score — weighted sum of days-eaten across 9 food groups |
| `food_consumption.fcs_band` | I.9-I.17 | Derived FCS band (poor ≤21 / borderline 22-35 / acceptable >35) |
| `food_consumption.staples_days` | I.9 | Staples: cereals, grains, roots and tubers (rice, pasta, bread, sorghum, millet, maize, potato, cassava, sweet potato) — days eaten in last 7 |
| `food_consumption.meat_days` | I.12 | Meat, fish and eggs: all flesh meat, fish and shellfish, and eggs — days eaten in last 7 |
| `food_consumption.dairy_days` | I.11 | Milk and dairy products: fresh milk, sour milk, yoghurt, cheese — days consumed in last 7 |
| `health.chronic_illness_flag` | D.1 | Does [NAME] suffer from any chronic illness? (Yes / No / Don't know) |
| `health.chronic_illness_types` | D.2 | From what type of chronic illness does [NAME] suffer from? (TB / Respiratory / Schistosomiasis / HIV/Aids / Diabetes / Hypertension / Cancer / Hepatitis) |
| `disability.wg_disability_flag` | D.3-D.8 | Derived: any WG dimension is 03 (a lot of difficulty) or 04 (cannot do at all) |
| `disability.seeing` | D.3 | Does [NAME] have difficulty seeing, even if wearing glasses? |
| `disability.hearing` | D.4 | Does [NAME] have any difficulty hearing, even if using a hearing aid? |
| `disability.walking` | D.5 | Does [NAME] have any difficulty walking or climbing steps? |
| `disability.memory` | D.6 | Does [NAME] have difficulty remembering or concentrating? |
| `disability.selfcare` | D.7 | Does [NAME] have difficulty with self-care such as washing all over or dressing? |
| `disability.communication` | D.8 | Using your usual language, does [NAME] have difficulty communicating, for example understanding or being understood? |
| `education.literacy_status` | E.1 | Can [NAME] read and/or write in any language? (For Household members 15 years and above) |
| `education.ever_attended` | E.2 | Has [NAME] ever attended formal school or any early childhood education programme? |
| `education.never_attended_reason` | E.3 | Why has (NAME) never attended school? |
| `education.highest_grade` | E.4 | What is the highest grade/class of formal education or early childhood education programme that [NAME] completed? |
| `education.currently_attending` | E.5 | Is (NAME) currently attending school? (For Household Members 3-24 years old) |
| `education.why_stopped` | E.6 | Why has (NAME) stopped going to school? |
| `employment.main_activity_last_30d` | F.1 | What has been [NAME]'s MAIN job/activity in the last 30 days? |
| `employment.work_frequency` | F.2 | If [NAME] has been working, how frequently? |
| `employment.sector` | F.3 | If [NAME] has been working, in which (main) sector? |
| `employment.employment_status` | F.4 | If [NAME] has been working, which is his/her status? |
| `employment.not_working_reason` | F.5 | If [NAME] has not been working, what is the main reason? |
| `employment.is_govt_programme_beneficiary` | F.6 | Has [NAME] ever been a beneficiary of a Government Programme? |
| `employment.currently_benefiting` | F.8 | Is [Name] currently benefiting from the programme? |
| `employment.made_savings` | F.9 | Did [Name] Make any Savings? |
| `employment.savings_location` | F.10 | If yes, where do [name] save your money? |
| `shock.shock_type` | K.3 | What is the main type of shock which affected the household activities? |
| `shock.severity` | K.4 | How do you judge the severity of the losses caused by the shock? (Very severe / Severe / Mild / moderate) |
| `shock.event_year` | K.1 | In the last 12 months, have the household's livelihood activities been affected by any major negative event? (derived: event year from event_date) |
| `shock.crops_severity_score` | K.4.a | Crops — severity 1-10 score |
| `shock.livestock_severity_score` | K.4.b | Livestock — severity 1-10 score |
| `coping_strategy.strategy_type` | L.1, L.2 | In the last 12 months, did the household resort to any of these livelihood (L.1) or food (L.2) coping strategies? |
| `coping_strategy.frequency` | L.1, L.2 | (Yes frequently / only-during-dry-period / occasionally / never) |
| `coping_strategy.category` | L.1, L.2 | L01 (livelihood coping) vs L02 (food coping) |
| `referral.programme_code` | F.7 | Which programmes did [Name] benefit from? (PDM / OWC / YLP / UWEP / NUSAF / NAADS / Emyooga / SEGOP / PWD Grant / ...) |

Variables not traced back to a questionnaire question (system-derived, computed, or sourced from operational tables not from the field instrument):

- `household.member_count_actual` — derived from Member roster length
- `household.has_disability_member_flag`, `household.has_chronic_illness_member_flag`, `household.has_elderly_member_flag`, `household.has_under5_member_flag`, `household.female_headed_flag`, `household.child_headed_flag`, `household.elderly_headed_flag`, `household.crowding_index`, `household.shock_in_last_12m_flag` — derived from underlying member / dwelling / shock data
- `member.nin_verified_flag` — derived from `nin_status` AND `nin_hash IS NOT NULL`
- `shock.recovery_status` — derived from severity × FIES change over 12 months
- `pmt.band`, `pmt.score`, `pmt.vulnerability_tier`, `pmt.computed_at_date`, `pmt.model_version` — computed by the PMT engine, no questionnaire question
- `referral.status`, `referral.eligibility_rule_version`, `programme_enrolment.status`, `programme_enrolment.exit_reason`, `programme_enrolment.effective_year` — operational referral / enrolment lifecycle, no questionnaire question
- `asset_ownership.motor_vehicle_flag`, `asset_ownership.communication_asset_flag` — derived from per-asset-type counts in G.15

End of `questionnaire_mapping.md`.
