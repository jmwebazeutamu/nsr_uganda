# ADR-0010: Coded fields are resolved via ChoiceList, not TextChoices

- **Status**: Proposed
- **Date**: 19 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Engineering Lead, Data Protection Officer
- **References**: SAD v0.6 §4.2 (DQA), §5.1 (Member/Household entities), §5.3 (versioning); ADR-0002 (ULIDs); ADR-0003 (migration policy); US-S22-005 (story).

---

## Context

The questionnaire (`/docs/06_questionnaire.docx` v2) carries dozens of coded fields: tenure, roof material, wall material, floor material, cooking fuel, lighting source, water source, toilet type, waste disposal, livelihood source, relationship, marital status, sex, nin status, education level, asset type, and roughly thirty others. Every value in the captured payload is a numeric or short string code from a closed list.

Three of these were modelled in Django as `TextChoices` on `apps/data_management/models.py`:

- `Member.sex` (`Sex.MALE = "M"`, `Sex.FEMALE = "F"`).
- `Member.nin_status` (`NinStatus.HAS_CARD = "has_card"`, etc.).
- `Household.urban_rural` (`UrbanRural.URBAN = "urban"`, etc.).

The rest of the questionnaire's codes are not modelled as columns at all. They live inside the JSON `canonical_payload` of the upstream `StageRecord` (DIH), which `HouseholdSerializer.get_source_payload()` exposes through the household-detail API. The React detail view reads keys off that JSON and renders the raw codes — `Tenure 13`, `Roof 14`, `Walls 11` — because there is no resolver in the read path.

Meanwhile, `apps/reference_data/` already carries `ChoiceList` (with `status`, `version`, `effective_from`, `effective_to`, dual-approval workflow) and `ChoiceOption` (with `code`, `label`, `language`). The seed `apps/reference_data/seeds/choice_lists_v1.json` defines 46 active lists / 370 options including all the names the questionnaire uses.

This duplicates the source of truth in three ways:

1. `TextChoices` in Python code overlaps `ChoiceList` rows in the database for `sex`, `nin_status`, `urban_rural`. Adding an option to either side does not flow to the other; the seed has codes (1, 2) for `sex` while the model carries letters (M, F).
2. The questionnaire's option lists are duplicated in `k-forms/build_nsr_xlsform.py` and elsewhere because there is no canonical endpoint the form runtime can fetch.
3. The detail view shows raw codes because the read path never resolves them.

## Decision

Codes are persisted; labels are resolved at read time, always against `ChoiceList`/`ChoiceOption`, versioned by the as-of date of the underlying record. Concretely:

1. **No `TextChoices` on coded fields.** `Member.sex`, `Member.nin_status`, `Household.urban_rural`, and any future coded field on `Household`, `Member`, or any intake-payload column are plain `CharField(max_length=32)` storing the raw `ChoiceOption.code`. The closed-list invariant is enforced by the resolver (warning on unmapped code), not by a Python enum.
2. **The audit blob is preserved bit-for-bit.** `Household.source_payload` (sourced from `StageRecord.canonical_payload`) is never mutated. Labels for the questionnaire payload are computed lazily into a parallel `source_payload_labels` tree at serialisation time. Two trees, never merged. The audit hash of the source payload continues to match what DIH ingested.
3. **Versioned reads via `as_of`.** Every label resolution is anchored to an `as_of` date — for a `Household`, the date of the originating `StageRecord` (intake date), falling back to `Household.created_at`. The resolver picks the `ChoiceList` row where `status=ACTIVE`, `effective_from <= as_of`, and (`effective_to IS NULL` OR `effective_to > as_of`). A household captured before a new version of `tenure` becomes effective continues to show the labels active when it was captured.
4. **One field map.** `apps/data_management/choice_field_map.py` is the only place in app code that names a `ChoiceList`. Every coded column on `Household`/`Member` and every coded key inside `source_payload` is declared there with its `list_name` and its kind (`"single"` or `"multi"`). Adding a new coded field is a one-line edit; the resolver, serializer label fields, and detail-view rendering follow automatically.
5. **`get_<field>_label()` is attached automatically.** An `AppConfig.ready()` hook reads the field map and attaches `get_<field>_label()` (and for multi-select fields, `get_<field>_labels()`) onto `Household` and `Member`. No hand-written boilerplate per field.
6. **Bundle endpoint for the questionnaire runtime.** `GET /api/v1/reference-data/choice-lists/?as_of=YYYY-MM-DD&lang=en` returns the active bundle as `{list_name, version, options[]}`. The response carries an `ETag` (sha256 of the bundle bytes); clients that send `If-None-Match` get `304 Not Modified` when nothing has changed. CAPI fetches this on every sync; the web intake form fetches on load. The form runtime never holds a hardcoded option list.
7. **Approval gate is unchanged.** Editing a `ChoiceList` still goes through the existing dual-approval workflow (`status=DRAFT → SUBMITTED → ACTIVE`). The cache invalidates on `ChoiceList.save()` via a `post_save` signal; the bundle ETag changes on the next request; CAPI picks it up on next sync; the detail view picks it up on next read. No code deploy is required to add or deprecate an option.
8. **Bilingual support.** The resolver accepts `language=` (default `en`) and falls back to `en` when a row for the requested language is missing. UI chrome strings continue to go through Django's translation framework.

## Consequences

### Positive

- One source of truth. The Reference Data Admin and Data Steward role can curate the closed lists without a code change, and the registry, DIH staging, the questionnaire runtime, and operator-facing detail views all read the same data.
- Historical correctness. A 2025 household keeps its 2025 labels even after `tenure` v2 supersedes v1 in 2026. Audit reviewers see the questionnaire as it was answered.
- No hidden duplication. The compiler will not let you add a new `TextChoices` for a coded field — the migration policy below makes that explicit. Reviewers can spot the anti-pattern by greppling for `TextChoices` in `apps/data_management/`.
- Smaller surface for the operator UX work in US-S12. The console's UPD modal already reads coded fields by name; once labels ship in the API, the modal swaps display verbatim without inventing its own lookups.

### Negative

- Migration churn. Replacing `TextChoices` with `CharField` and rewriting the stored values is a forward-only migration (per ADR-0003 once we are past Sprint 5) and touches the audit-bearing path. The reverse plan goes in the release ticket.
- Caller updates. Code that compares `member.sex == "F"` or `nin_status == NinStatus.HAS_CARD` has to be rewritten to compare against the new code (`"2"`, `"1"`). The migration's tests catch this; reviewers also re-grep the codebase.
- Resolver hot path. The detail view now does one extra lookup per coded field on read. We mitigate with `lru_cache` keyed by `(list_name, as_of_date, language)`, invalidated on `ChoiceList.save()`. For the bundle endpoint, the ETag short-circuits unchanged-payload responses to `304`.
- The audit blob is no longer the only place the labels live for old data. The parallel `source_payload_labels` is recomputed on every read; if the lists are edited retroactively (history rewrite), the labels shift. The dual-approval gate makes that an intentional, audited act, not an accident.

### Neutral

- `Household.urban_rural` becomes a 32-char CharField but the seed `rural_urban` list currently has only two options. If the operating manual extends the list, no migration is needed — a new `ChoiceOption` lands through the approval gate. The current third `TextChoices` value (`peri_urban`) is unused in the database; if it becomes needed, the steward adds it to the list.
- `sex` codes shift from M/F to 1/2 in the column. Downstream consumers (e.g., the PMT model in `apps/pmt/`) must read `sex` as `"1"`/`"2"` and either resolve to `Male`/`Female` via the resolver or test by code. The migration test enumerates all consumers; none can stay on the letter form.

## Out of scope

- The CAPI Android client. This ADR specifies the bundle endpoint's contract; the Android consumer is built in US-081 once ADR-0004 (form runtime) is decided.
- The XLSForm build pipeline (`k-forms/build_nsr_xlsform.py`). Today the pipeline lives outside the repo by design. A follow-up story replaces its hardcoded option tables with a fetch against the bundle endpoint.

## Migration policy

Per ADR-0003, migrations after Sprint 5 are forward-only with a reverse plan attached to the release ticket. The migration for this ADR ships in US-S22-005c with:

- Schema change: drop `choices=` on `Member.sex`, `Member.nin_status`, `Household.urban_rural`.
- Data step: map every existing value to the matching `ChoiceOption.code` against the active version of each list. The data step asserts that every distinct value in the table has a mapping; if any value is unmapped, the migration aborts with the list of orphans.
- Reverse plan (release ticket): if the migration must be rolled back, the inverse map is `{ "1": "M", "2": "F" }` for sex, `{ "1": "has_card", "2": "lost", "3": "not_issued", "4": "no", "8": "unknown" }` for nin_status, `{ "1": "urban", "2": "rural" }` for urban_rural. The reverse data migration script is checked into `/scripts/reverse/us_s22_005c.py` and the `TextChoices` classes are restored from git.

## Open items

- **OI-S22-1.** Bilingual label authoring. The Reference Data admin currently surfaces only the `en` row; the dual-approval workflow does not yet have a "translate" step for adding `lg` (or other) rows. Owner: NSR Unit Coordinator + Engineering Lead. Defer until first non-English deployment is scheduled.
- **OI-S22-2.** Effective-date editor UX. The admin form for `ChoiceList` lets an editor set `effective_from` / `effective_to` directly, but does not warn on overlapping windows. Owner: Engineering Lead. Land before the first retroactive list edit.

---

Signed off by:

- NSR Unit Coordinator: ____________________ Date: __________
- Data Protection Officer: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________

End of ADR-0010.
