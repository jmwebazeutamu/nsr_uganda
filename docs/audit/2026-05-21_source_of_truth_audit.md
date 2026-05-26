# Source-of-Truth, Cascade, Hardcoded-Values, and Duplicate Audit

Date: 2026-05-21 (Sprint 0)
Scope: `/Users/johnsonmwebaze/nsr_sris_dev` (dev codebase + `db.sqlite3`)
Run by: 4 parallel agents (source-of-truth, geo-cascade, hardcoded scan, duplicate detection)

## Headline

| Pillar | Verdict | Action |
|---|---|---|
| Single source of truth (models + queries) | PASS | None |
| Geographic cascade (tree integrity + on_delete) | PASS with one helper-method gap | Add `GeographicUnit.get_descendants()` |
| Hardcoded variables/parameters | PASS with two minor items | Move PMT `trigger_source` to ChoiceList; defer route-label i18n |
| Duplicate households in dev dataset | 0 found | No deletes. Fixture seeder has one minor inconsistency |

**No hard deletes required on this snapshot.** The dry-run delete template is preserved at the bottom of section 4 for the next run.

---

## 1. Single source of truth — PASS

Canonical models live only in `apps/data_management/models.py` (Household, Member, 14 detail entities, 14 paired Version tables). Reference data canonical models live only in `apps/reference_data/models.py` (GeographicUnit, ChoiceList, ChoiceOption).

Findings:

- No parallel/duplicate model definitions of Household, Member, or detail entities anywhere outside `data_management`. Other apps define their own domain models only (e.g. ddup.MatchPair, dqa.DqaResult, pmt.PMTResult, intake.FormVersion).
- No raw SQL outside `data_management/` and `ingestion_hub/`. Searched `cursor.execute`, `.raw(`, `RawSQL`, `connection.cursor`. Only matches were code comments.
- Direct writes to `data_management_household` / `_member` happen only in:
  - `apps/ddup/services.py:152` — `Household.objects.filter(head_member=loser).update(head_member=surviving)` (allowed: post-promotion DDUP merge)
  - `apps/pmt/services.py:89` — `Household.objects.filter(pk=...).update(current_pmt_score=..., current_vulnerability_band=...)` (allowed: PMT recompute)
  - Both modules are post-promotion. Intake, DQA, UPD, REF, GRM, API, IDV all go through serialisers and the promotion API.
- No custom Managers or QuerySets in other apps re-implement Household/Member fetch logic.
- Field duplications across entities are all intentional and documented (Member.nin_hash vs PartnerContact.nin_hash vs NiraVerificationAttempt.nin_hash; denormalised `sub_region_code` per ADR-0005; deprecated `Household.dwelling_tenure` during transition window).

No action.

## 2. Geographic cascade — PASS with one gap

`reference_data.GeographicUnit` (13,616 rows) is correctly modelled.

Tree:
- Self-FK `parent` with `on_delete=PROTECT` (correct — prevents orphaning).
- Level enum: REGION, SUB_REGION, DISTRICT, COUNTY, SUB_COUNTY, PARISH, VILLAGE.
- `UniqueConstraint(level, code, effective_from)` enforces versioning.

Row distribution (actual): 5 regions, 19 sub-regions, 147 districts, 329 counties, 2,225 sub-counties, 10,872 parishes, 19 villages. Total 13,616.

On_delete on every FK pointing to GeographicUnit:

| Model.field | on_delete |
|---|---|
| Household.region/sub_region/district/county/sub_county/parish/village | PROTECT |
| Programme.geographic_units | M2M |
| DataSharingAgreement.geographic_scope | M2M |
| GeographicUnit.parent | PROTECT |

All correct. No accidental CASCADE on a reference table.

Data integrity (live SQL check): **0 orphans, 0 cycles, no anomalies.**

UI cascades:
- Intake XLSForm export uses `choice_filter` so Kobo/Enketo enforce parent-child cascading at form runtime.
- Data-requests builder (`apps/data_requests/builder_schema.py:404`) exposes 7 flat geographic filters with no cascading dependency. Acceptable for power-user filtering, but a cascading widget would prevent invalid combinations.

**Gap to close:** there is no `GeographicUnit.get_descendant_ids()` helper or recursive CTE manager method. Callers walk `parent__parent__...` ad-hoc or hit a single level. Add a classmethod/queryset for bulk administrative operations ("all households in this sub-region").

Action: small story to add `get_descendants()` / `get_ancestors()` to GeographicUnit. ~1-day work.

## 3. Hardcoded variables and parameters — PASS with two items

Most TextChoices on Household/Member were already removed in US-S22-005c (ADR-0010 migration). Coded fields resolve through `apps/reference_data/services.py` against ChoiceList.

Items worth action:

| File:line | Literal | Class | Target | Severity |
|---|---|---|---|---|
| `apps/pmt/signals.py:27` | `triggered_by="upd_commit"` | REF-DATA | ChoiceList `pmt_trigger_source` with options `dih_promote, upd_commit, manual, backfill` | MEDIUM |
| `apps/update_workflow/routing.py:56` | Route display labels ("CDO (parish)", "M&E Officer", ...) | REF-DATA (defer) | ChoiceList once i18n lands | LOW |

Legitimate code constants (per ADR-0022 and engine policy, leave in place):

- `apps/pmt/engine.py:23` PMT band thresholds (EXTREME_POVERTY=0, POVERTY=30, VULNERABLE=60, NOT_POOR=80)
- `apps/ddup/services.py:62-78` DDUP calibration constants (AUTO_REVERSE_RATE_CEILING=0.05, THRESHOLD_NUDGE_STEP=0.05, THRESHOLD_FLOOR=0.50, THRESHOLD_CEILING=1.00, SAFE_DEFAULT_THRESHOLD=0.95)
- `apps/ddup/similarity.py:73-90` Jaro-Winkler algorithm params (prefix_scale=0.1, common_prefix=4, max_years=2)
- TextChoices for system-internal status enums (DqaResult.Severity, UpdRoutingRule.ChangeType, PMTResult.ModelStatus/Band, DdupMatchPair.PairStatus). These are not user-selectable values, so ChoiceList migration is not warranted.

Green flags (no action):

- No DB URLs, NIRA/UBOS endpoints, secrets, or hostnames hardcoded in source. All sit in `settings.py` reading from `.env`.
- NIRA client switches on `settings.NIRA_PROVIDER` (mock vs live).
- Routing matrix is in `update_workflow.UpdRoutingRule` table; the `DEFAULT_MATRIX` in code is a fallback only.
- FCS food-group weights are not yet wired (deferred per ADR-0022). Watch out when they land — they should be code constants citing the WFP source.

Action: one story to migrate PMT `trigger_source` to ChoiceList. Defer route labels to the i18n epic.

## 4. Duplicate dataset detection — 0 duplicates

Dataset on `db.sqlite3`: 13 households, 63 members.

Rule applied: NIN match on head-of-household. Head identity = `Household.head_member_id` FK (1:1 to Member). Members carry `nin_hash` (BLOB), `nin_value` encrypted, `nin_last4`, `nin_status`.

Result: **0 duplicate groups.**

Of 13 heads, 4 have a populated `nin_hash` (Mugisha James, Wasswa Lilian, Nabirye Naomi, Okello James). All 4 hashes are distinct. The remaining 9 heads have `nin_status = '08'` (no NIN) and NULL hash. NULLs do not group under SQL equality, so they are correctly excluded.

Secondary checks (report-only):

| Check | Result |
|---|---|
| Orphan Members (household_id not in Household) | 0 |
| Duplicate nin_hash within same household | 0 |
| Duplicate nin_hash anywhere across Member | 0 |
| Households with zero live Members | 0 |
| Households with multiple `relationship_to_head='01'` Members | 0 (but see note below) |

Reference-data integrity: every Household.{region, sub_region, district, county, sub_county, parish, village}_id resolves to an existing GeographicUnit row. **0 orphans.**

### Fixture seeder inconsistency (separate ticket)

No Member row in the dev fixture carries `relationship_to_head = '01'` (the questionnaire code for "Head"), even though `Household.head_member_id` is populated. The seeder sets the FK but does not flip the member's relationship code. This is a data-quality bug in the fixture, not a duplicate concern.

Action: fix the seeder (or add a `post_save` signal on Household that enforces `head_member.relationship_to_head == '01'`).

### Hard-delete template (NOT EXECUTED — no losers)

Saved at `apps/data_management/scripts/duplicate_purge_template.sql` for the next run. Order: child *Version tables → child detail tables → MemberVersion → Member → HouseholdVersion → null out head_member_id → Household. Wrapped in a single transaction.

```sql
-- Template only. Fill :loser_ids with the Household IDs returned by the
-- head-NIN duplicate query. Re-run the dry-run before executing.
-- BEGIN;
--   DELETE FROM data_management_healthversion       WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_disabilityversion   WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_educationversion    WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_employmentversion   WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_health              WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_disability          WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_education           WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_employment          WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_memberversion       WHERE member_id IN (SELECT id FROM data_management_member WHERE household_id IN (:loser_ids));
--   DELETE FROM data_management_member              WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_dwellingversion     WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_utilitiesversion    WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_livelihoodversion   WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_foodsecurityversion WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_foodconsumptionversion WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_assetownershipversion  WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_cropversion         WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_livestockversion    WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_shockversion        WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_copingstrategyversion WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_dwelling, _utilities, _livelihood, _foodsecurity, _foodconsumption,
--               _assetownership, _crop, _livestock, _shock, _copingstrategy WHERE household_id IN (:loser_ids);
--   DELETE FROM data_management_householdversion    WHERE household_id IN (:loser_ids);
--   UPDATE data_management_household SET head_member_id = NULL WHERE id IN (:loser_ids);
--   DELETE FROM data_management_household           WHERE id IN (:loser_ids);
-- COMMIT;
```

---

## Recommended follow-up stories

1. **US-REF-XXX** — Add `GeographicUnit.get_descendants(self, include_self=False)` and `get_ancestors()` classmethod with a recursive CTE on PostgreSQL (fallback to iterative on SQLite). Estimate: 1 day.
2. **US-PMT-XXX** — Migrate `PMTRun.triggered_by` and `PMTResult.triggered_by` to FK against ChoiceList `pmt_trigger_source`. Add the 4 ChoiceOption rows. Update `apps/pmt/signals.py` and `services.py`. Estimate: 1 day.
3. **US-FIX-XXX** — Fix fixture seeder so head members carry `relationship_to_head='01'`. Add a `Household.clean()` validation or a `post_save` consistency check. Estimate: 0.5 day.
4. **US-DR-XXX (defer)** — Add cascading geographic dropdowns to the data-requests builder once the schema-builder UI gets its next pass.

## Verdict

The audit-bearing modules (DAT, DAT-DQA, DAT-DDUP, UPD, DIH) hold the line on single source of truth. The codebase is reconstructable from the canonical models. The dev dataset is clean. Three small follow-up stories are queued above.

No deletes executed.
