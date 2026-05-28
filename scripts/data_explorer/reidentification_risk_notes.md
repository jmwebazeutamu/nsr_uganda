# Re-identification risk notes — DATA-EXP catalogue variables

Companion to `catalogue_seed.yaml`. One paragraph per Personal-class and Internal-class variable, articulating the attacker model the variable enables and why the locked k-floor + the geographic floor mitigates it. This document is what the Data Protection Officer reviews at variable-activation time per ADR-0023 §D5.

References:
- ADR-0023 §D3 — k_floor: Public=0, Internal=5, Personal=10, Sensitive=blocked.
- ADR-0023 §D4 — Geographic floor: sub_county for Public/Internal; sub_region for Personal; parish/village forbidden on discovery.
- ADR-0023 Appendix A — Cell-reconstruction risk-probe.
- DPPA 2019 — Data Protection and Privacy Act, Uganda. "Special category data" includes data on health, ethnicity, religion, sexual orientation, biometrics.

Sensitive-class variables (`member.nin_value`, `member.nin_hash`, `member.date_of_birth`, `health.chronic_illness_types`) are listed at the end with the rationale for why they are NEVER projectable on the discovery surface, not even at sub-region.

---

## Personal-class variables (k_floor = 10, geographic floor = sub_region)

### `member.sex` (questionnaire C.4)

Sex alone is non-identifying at registry scale (12M households, ~50/50 split nationally). The re-identification risk is in combination: combined with a small sub-region count and one other demographic axis (age band, marital status, relationship to head), a single-sex cell becomes a 2D differencing target. The k=10 floor at sub-region means an attacker cannot resolve a sub-region cell below 10 households for any (sex, axis) pairing. Without the floor, e.g. a Karamoja x male x 75+ x widowed cell could plausibly be a single individual.

### `member.age_band` and `member.age_years` (questionnaire C.7)

Age in years is highly identifying when combined with a small geography and sex (the classic 87% of Americans uniquely identifiable by ZIP+DOB+sex — Sweeney 2002). Age_years is therefore restricted to sub_region and aggregated as bands only on the discovery path; raw age_years remains catalogued but not projectable on the catalogue surface (record-level access via DRS with a DPO-approved purpose). Bands of 5+ years (with the youngest bucket 0-4 unbanded) plus the k=10 floor and the sub_region floor combine to prevent any (age_band, sex, sub_region) cell from collapsing to a single individual.

### `member.date_of_birth` — see Sensitive section.

### `member.relationship_to_head` (questionnaire C.3)

Relationship to head, in combination with age and sex, is the textbook "household structure" identifier. A 17-year-old female niece in a small sub-county Karamoja household is identifying if the operator already knows the household; the registry must therefore not surface (relationship, age_band, sex) cells below k=10 at sub_region. Combined with the geographic floor this prevents an attacker from finding the unique structural fingerprint of a household via the discovery surface.

### `member.marital_status` (questionnaire C.5)

Marital status is sparsely distributed for rare categories — Hindu marriage (code 14), Civil marriage (code 13) — and in many sub-regions a single (sub_region, marital_status=14) cell may be 1-3 individuals. The k=10 floor at sub_region forces these rare cells to suppress; partial-suppression on a (sub_region, marital_status) projection is the expected output for Bukedi/Karamoja (see Q19 in `aggregate_query_corpus.yaml`). Combined with sex + age band, a rare marital status becomes structurally identifying without the floor.

### `member.nationality` (questionnaire C.10)

Most household members are Ugandan (code 1); minority nationalities (Eritrean, Ethiopian, Somali, DRC, Burundian) are rare in some sub-regions and concentrated in others (West Nile and Kampala carry most refugee population). A (sub_region, nationality=10 Eritrean) cell in a non-West-Nile sub-region may be near-singleton. The k=10 floor at sub_region forces suppression on those cells.

### `member.residency_status` (questionnaire C.11)

IDP, refugee, returnee and repatriated statuses are concentrated geographically (West Nile + Karamoja). A (sub_region=BUGANDA, residency_status=refugee) cell may be very small and combinable with sex + age to identify a specific protection beneficiary. The k=10 floor prevents this; the sub_region floor prevents anyone from narrowing it further on the discovery surface.

### `member.birth_certificate_status` (questionnaire C.8)

Combined with age and a small geography, lacking a birth certificate (code 5) under-5 is a child-protection signal and could be combinable with referral records (NUSAF child grants) to single out specific children. The k=10 floor + sub_region floor combine to suppress (sub_region, age_band=0-4, birth_certificate_status=5) cells where count < 10.

### `member.nin_status` (questionnaire C.9)

`nin_status` carries the answer to "has a NIN card / lost it / not issued / no". Combined with age band and sex it is mostly non-identifying for the populous "has-a-card" category but becomes identifying in sparse cells: e.g. a (sub_county, age_band=18-29, nin_status=lost) cell may be a single individual seeking NIN reissue. nin_status is therefore Personal-class and aggregated at sub_region with k=10.

### `member.nin_verified_flag` (derived)

Derived from `nin_status='1' AND nin_hash IS NOT NULL`. Slightly more identifying than `nin_status` alone because the hash presence reveals whether NIRA verification has been attempted and succeeded; combined with sub_region + sex + age_band it could correlate with the NSR's identity-verification workflow. Same controls as `nin_status` — Personal-class, sub_region floor, k=10.

### `member.telephone_present_flag` (questionnaire C.17-C.20)

Whether a member has any telephone is mostly non-identifying (~80% of adults). Becomes identifying in combination with age_band + sub_county for under-15 or 75+ members where phone ownership is rare. The k=10 floor at sub_region prevents (sub_region, age_band=0-4, telephone_present_flag=true) cells from collapsing below 10.

### `member.mobile_money_flag` (questionnaire C.21)

Similar to `telephone_present_flag` but additionally a beneficiary-eligibility signal (mobile-money is the payment rail for cash-transfer programmes). Personal-class, sub_region floor, k=10. The combination (mobile_money_flag, sub_region, head_sex) is heavily filtered by the NUSAF + SEGOP programmes, which makes the cell shape predictable but still non-singleton at k=10.

### `member.orphan_flag` (questionnaire C.12-C.13)

Child-protection sensitive. An orphan flag combined with sub_region + age_band identifies a small protection cohort; the k=10 floor forces suppression where the cohort is small. The sub_region floor (rather than sub_county) is critical here: a (sub_county, age_band=10-14, orphan_flag=true) cell would frequently be 1-5 children, which the k=5 Internal floor at sub_county would still surface — therefore this variable is Personal at sub_region, not Internal at sub_county.

### `member.mother_alive_flag` and `member.father_alive_flag` (questionnaire C.12-C.13)

Same controls as `orphan_flag`. The discovery surface aggregates these at sub_region with k=10. Combined, (mother_alive=false, father_alive=false, age_band=<18) is the derivation source of `orphan_flag`; an attacker who computes the AND on raw cells could recover the orphan count, which is why both inputs are Personal-class at the same floor — there is no leakage path that the derived flag closes.

### `health.chronic_illness_flag` (questionnaire D.1)

Binary yes/no. Combined with a small geography and age, chronic-illness prevalence can imply household composition (e.g. an HIV+ caregiver in a small sub-county). At sub_region with k=10 the cell is statistically too large to single out an individual. The specific illness type is Sensitive (see below) and never surfaced.

### `disability.wg_disability_flag` and the six WG dimensions (questionnaire D.3-D.8)

Disability status combined with age + sex + sub_region is identifying when the disability is rare (severe walking difficulty at age 0-4 in a single sub-region). The k=10 floor at sub_region combined with the sub_region geographic floor mitigates this; the operational referral pipeline that uses these flags reads from DAT directly (not via DATA-EXP) and is bound by DSA scope.

### `education.literacy_status`, `education.highest_grade`, `education.ever_attended`, `education.currently_attending`, `education.never_attended_reason`, `education.why_stopped` (questionnaire E.1-E.6)

Education profile is identifying when combined with age and a small geography — e.g. a 15-year-old female who has never attended school in a sub-county where universal primary education is near-100% is potentially a single individual. The k=10 floor at sub_region forces suppression on rare cells. Why-attended-reason and why-stopped-reason are particularly sensitive because they reveal protection-relevant reasons (pregnancy, marriage, disability) — these are aggregated at sub_region with k=10.

### `employment.main_activity_last_30d`, `employment.work_frequency`, `employment.sector`, `employment.employment_status`, `employment.not_working_reason` (questionnaire F.1-F.5)

Employment profile combined with age and sub_region can identify individuals in rare-sector roles (e.g. an extraterritorial-organisation employee in a non-Kampala sub-region). The k=10 floor at sub_region and the ISIC-aligned sector categorisation (which collapses fine-grained jobs) mitigate this.

### `employment.is_govt_programme_beneficiary`, `employment.currently_benefiting`, `employment.made_savings`, `employment.savings_location` (questionnaire F.6-F.10)

Government-programme history is operationally sensitive — it can imply household income level and prior assistance. Combined with sub_region + age it could single out beneficiaries of small programmes (e.g. an Emyooga grantee in a non-host district). Personal at sub_region with k=10. Note that the operational programme-enrolment view goes through `referral.status` / `programme_enrolment.status` (both Internal at sub_county), not through these member-level fields — DATA-EXP catalogues both because the questionnaire asks both, and the DPO will decide at activation whether the member-level F.6-F.10 path stays open at all.

### `pmt.score` (raw score)

Raw PMT score combined with sub_county is highly identifying — small sub-counties yield discrete score distributions where a single household has a unique numeric value. The k=10 floor at sub_region forces suppression and the discovery aggregates use `pmt.band` (Internal at sub_county) for granular geographic breakdowns.

---

## Internal-class variables (k_floor = 5, geographic floor = sub_county)

### `household.reported_household_size` (questionnaire B)

Household size combined with sub_county and head sex is the textbook compositional fingerprint (Sweeney's quasi-identifier). At k=5 at sub_county a (sub_county, reported_household_size=N, head_sex=F) cell forces ≥5 households per combination. The combination is mitigated further by the fact that DATA-EXP aggregates household-size as a *count* of households-at-that-size, not as a projection on individual households.

### `household.member_count_actual` (derived)

Same controls as `reported_household_size`. Note that DATA-EXP intentionally surfaces both — DPO + M&E can spot AC-MEMBER-COUNT-MATCH drift across geography by comparing the two coverage rates.

### `household.head_sex`, `household.head_age_band` (derived from Member where head_member)

These are household-level *attributes* of the head — they roll up Member.sex / Member.age_band to the household grain. At sub_county with k=5 the (head_sex, head_age_band, sub_county) cell forces ≥5 households per cell. Combined with dwelling characteristics (tenure, roof material) they become identifying very quickly without the floor; the floor is therefore load-bearing for the four core compositional quasi-identifiers.

### `household.residence_status` (questionnaire C.11)

Resident vs displaced vs refugee vs returnee. At sub_county a (sub_county, residence_status=refugee) cell can be very small outside West Nile / Kampala; k=5 prevents singleton cells. The risk is the same as `member.residency_status` but at the household grain — the DPO may decide to elevate this to Personal at sub_region during activation; the default is Internal to enable operational protection-targeting dashboards.

### `household.current_consent_state`

Consent state combined with sub_county reveals where consent withdrawal is concentrated — a protection signal. At k=5 a (sub_county, current_consent_state=withdrawn) cell forces ≥5 households. The DPO is the primary consumer of this metric; the variable is catalogued so the DPO can monitor consent-withdrawal rates by geography.

### `household.current_intake_source`

CAPI vs walk-in vs Kobo vs partner intake. Combined with sub_county and dwelling characteristics it can reveal CAPI-team coverage gaps but is otherwise non-identifying.

### `household.gps_present_flag`, `household.gps_accuracy_m`

GPS presence + accuracy at sub_county is operational (field-ops coverage). The raw lat/lng pair is Sensitive (below); only the presence flag and the metres-of-accuracy float are Internal.

### `household.enumeration_area`

UBOS EA code; ~30-80 households per EA. At k=5 at sub_county the EA dimension is permissible because the floor prevents EA-level cell singletons. Combined with dwelling type or roof material it could become identifying in a small EA — the DPO should re-evaluate at activation whether EA stays as a projection on the discovery surface or moves to DRS-only.

### `dwelling.tenure`, `dwelling.dwelling_type`, `dwelling.roof_material`, `dwelling.wall_material`, `dwelling.floor_material` (questionnaire G.1-G.7)

Dwelling materials are heavily distributed across sub-counties; rare materials (tile, asbestos, concrete in rural sub-counties) produce small cells where k=5 forces suppression — see Q17 in the corpus. Combined with tenure + dwelling_type the (tenure, dwelling_type, roof, wall, floor) quintuple becomes near-unique for unusual buildings; the floor + the k=5 threshold combined with the suppressor's "all-fields-contributing-to-the-count" rule force the strictest class to apply.

### `dwelling.total_rooms`, `dwelling.sleeping_rooms`

Room counts combined with household-size produce the crowding index. At k=5 at sub_county the (rooms, sleeping_rooms, sub_county) cell forces ≥5 households per (rooms, sleeping_rooms) pair.

### `utilities.cooking_fuel`, `utilities.lighting_energy`, `utilities.drinking_water_source`, `utilities.toilet_facility`, `utilities.waste_disposal` (questionnaire G.8-G.14)

Service-access variables are correlated with poverty band; combined with dwelling characteristics they form the modernisation index used by donors. At k=5 at sub_county rare service profiles (e.g. flush toilet + electricity grid in a Karamoja sub-county) are suppressed.

### `utilities.toilet_shared`, `utilities.households_sharing_toilet` (questionnaire G.12-G.13)

`households_sharing_toilet` is capped at 10 by the model; the metric is well-distributed and not identifying at k=5 at sub_county.

### `livelihood.*` (questionnaire G.16, H)

Land ownership + hectares + main livelihood combined with sub_county is the rural-economy fingerprint. Large hectares are rare in most sub-counties; the k=5 floor and the natural land-size band buckets (the matview aggregates land_hectares into bands ≤1, 1-2, 2-5, 5-10, >10 ha) combine to suppress singleton cells.

### `food_security.*` (questionnaire I.1-I.8)

FIES items are coded yes/no and produce a 0-8 score. Combined with sub_county a (sub_county, fies_raw_score=8) cell can be very small in islands or low-vulnerability districts — Q18 in the corpus is the partial-suppression case for this. The k=5 floor at sub_county suppresses these correctly.

### `food_consumption.*` (questionnaire I.9-I.17)

FCS days per food group are 0-7 each; the weighted score is 0-112 and bands into poor/borderline/acceptable. Combined with sub_county the (sub_county, fcs_band=poor) cell is operationally important but k=5 prevents singletons.

### `asset_ownership.asset_type`, `asset_ownership.count`, `asset_ownership.motor_vehicle_flag`, `asset_ownership.communication_asset_flag` (questionnaire G.15)

Asset ownership combined with dwelling type and sub_county can identify households (a household owning a minibus + a fixed phone + a generator in a small rural sub-county is likely structurally unique). The k=5 floor at sub_county suppresses these correctly. The derived flags `motor_vehicle_flag` and `communication_asset_flag` are coarser, more aggregatable signals and are the recommended discovery-surface projections.

### `shock.shock_type`, `shock.severity`, `shock.event_year`, `shock.crops_severity_score`, `shock.livestock_severity_score`

Shocks are Public-class (k=0) — they are about events affecting households, not about identifying individuals. However the per-household-recovery-status (`shock.recovery_status`) derived flag is Internal at sub_county because it combines shock data with current FIES/FCS state, which is identifying in combination.

### `coping_strategy.*` (questionnaire L.1, L.2)

Coping strategies (begging, selling assets, relocating family, restricting children's meals) are protection-sensitive. The k=5 floor at sub_county forces suppression on rare strategies like `relocate_family` or `begging`. Combined with shock + livelihood this is the operational vulnerability fingerprint; the DPO may move some of these to Personal at activation.

### `pmt.band`, `pmt.vulnerability_tier`, `pmt.computed_at_date`

PMT band is the discoverable proxy for PMT score; at sub_county with k=5 the band distribution by sub_county is the canonical M&E coverage metric. `pmt.score` (raw) is Personal at sub_region (above) because the raw numeric is identifying in small cells.

### `referral.programme_code`, `referral.status`, `referral.eligibility_rule_version`

Referral-level data at sub_county. Programme code is Public; status is Internal because the combination (programme_code, status=rejected, sub_county) reveals partner-side rejection patterns and could expose beneficiary cohorts. k=5 at sub_county forces ≥5 households per (programme, status) pair.

### `programme_enrolment.status`, `programme_enrolment.exit_reason`, `programme_enrolment.effective_year`

Same controls as referral. `exit_reason` is free-text but coverage-aggregated into a banded count (graduated / non-compliance / death / relocation / other) at the matview level; the raw free-text never reaches the discovery surface.

---

## Sensitive-class variables — NEVER projectable

These variables appear in the catalogue (operators can see the dictionary entry, definition, source path, and value domain) but every aggregate involving them is refused at validation with HTTP 422.

### `member.nin_value` (encrypted, AES-256, ADR-0002)

The raw NIN string. Even a count of NIN-presence by sub-region would leak NIRA-verification coverage in a way that combines with the timing pattern of the NIRA sandbox to attribute specific verifications to specific households. Record-level access requires a DSA, a DPO-approved DRS request, and the cryptographic-bundle delivery path. The catalogue keeps the dictionary entry so operators understand what NSR holds; the value never leaves DAT on the discovery path.

### `member.nin_hash` (SHA-256 of NIN, ADR-0002)

Same controls as `nin_value`. The hash is the join key into NIRA + other partner registries. Surfacing presence/absence aggregates by geography would enable cross-registry identity matching without DPO consent. Refused at validation.

### `member.date_of_birth` (questionnaire C.6)

Full DOB combined with sub-region + sex is in the canonical Sweeney quasi-identifier set; the registry's risk threshold (Appendix A: posterior < 90% over ≥3 integer counts) cannot be met for DOB at any geographic level given 12M households spread across 9 sub-regions. The discovery surface uses `member.age_band` (Personal at sub_region, k=10) instead.

### `health.chronic_illness_types_encrypted` (questionnaire D.2)

DPPA 2019 special-category data: the list may include HIV/AIDS, TB, Hepatitis codes. Surfacing even an aggregate "count by sub_region of TB-positive members" would leak national prevalence data that the Ministry of Health is the primary publisher of and that NSR is forbidden by ADR-0019 from publishing independently. Refused at validation; the binary `health.chronic_illness_flag` (Personal at sub_region, k=10) is the discovery-surface alternative.

### `household.gps_lat`, `household.gps_lng` (questionnaire A.11, A.12)

GPS points are PostGIS geometry; even snapped to a 100m grid they single out individual households in rural sub-counties. Refused on the discovery path; the `household.gps_present_flag` and `household.gps_accuracy_m` (both Internal at sub_county) are the discovery surfaces.

### `geography.parish_code`, `geography.village_code`

Not technically PII but they cross the geographic floor (ADR-0023 §D4). The catalogue lists them so operators see the dictionary entry; the query builder disables them in the picker; the aggregate endpoint refuses them with `geographic_floor_violation` and offers the DRS handoff URL.

---

End of `reidentification_risk_notes.md`. The DPO countersigns this file at variable-activation time per ADR-0023 §D5 ("Activation requires dual approval... DPO mandatory on every PrivacyClass override").
