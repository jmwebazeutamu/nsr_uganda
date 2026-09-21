# ADR-0032: One code frame per choice list (UBOS 2024), and how the legacy one is retired

- **Status**: Accepted
- **Date**: 20 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, UBOS liaison, Engineering Lead
- **References**: ADR-0010 (choice lists and coded fields); ADR-0003 (forward-only migrations); SAD §5; `apps/reference_data/legacy_code_frames.py`, `apps/reference_data/migrations/0019_retire_legacy_code_frames.py`, `apps/reference_data/seeds/choice_lists_v1.json`

---

## Context

Six housing lists and two employment lists each carried **two code frames at
once**: a legacy single-digit frame (1–8) and the UBOS 2024 frame (00–24,
96, 98). Both were `active`, so the capture wizard rendered them merged into
one dropdown:

| List | Duplicate the enumerator saw |
|---|---|
| Dwelling type | "Detached" (1) and "Detached house (Bungalow)" (11); "Hut" (5) and "Hut" (17) |
| Roof material | "Iron sheets" twice (1, 11); "Tiles" twice (2, 12); "Concrete" (3) and "Concrete" (14) |
| Wall material | "Wood" twice (3, 16); "Iron sheets" twice (4, 19) |
| Floor material | "Tiles" twice (2, 17); "Wood" twice (4, 16) |
| Cooking fuel | "Other" twice (8, 96) |
| Waste disposal | "Burned" (2) / "Burn solid waste" (12); "Buried" (3) / "Rubbish pit (burn/bury)" (13) |
| Work frequency | "Full-time" (1) / "Full time - permanent work" (01) |
| Reason not working | "Studying" (1) / "Student" (03); "Other" twice (98, 96) |

Two enumerators coding the same hut produce different values, and nothing
downstream can tell whether a difference between two households is real or
is two people picking different rows from the same list. These fields feed
the Proxy Means Test.

Only the UBOS 2024 frame is seeded
(`apps/reference_data/seeds/choice_lists_v1.json`). The single-digit rows
exist in the database alone, left over from an earlier seed, so this is data
debt with no code to delete.

On the dev database the merged frames had already produced real mixed data:
**562 `Employment` rows** on legacy codes beside 641 on UBOS codes, in the
same two columns.

## Decision

**UBOS 2024 is the surviving frame.** It is the national statistical
standard, it is what the seed ships, it is more granular, and UBOS is the
authority for this vocabulary.

### Legacy options are deprecated, never deleted

`ChoiceOption.Status.DEPRECATED` already means exactly this: readable for
historical records, not selectable on a new intake. The choice-list bundle
endpoint already filters to `ACTIVE`, so deprecating removed the duplicates
from every dropdown with no UI change at all. Deleting them would make every
record still carrying one unreadable, which ADR-0010 forbids.

### Stored values are rewritten only where the meaning is identical

The mapping lives in `apps/reference_data/legacy_code_frames.py`, split in
two, and the split is the substance of this ADR.

**`EXACT`** — the legacy label and the UBOS label denote the same thing, so
rewriting changes no meaning. Migration 0019 rewrites these across every
model field in `CODED_FIELDS`, **including the `*Version` history tables**: a
household's history has to read the same way as its current row.

**`AMBIGUOUS`** — no single UBOS counterpart. **Not rewritten.** The option
is deprecated so nobody can pick it again, the stored value is left alone,
and the deprecated option row keeps the original label resolvable.

Guessing here would put an answer nobody gave into a household's record, and
from there into its PMT score and its eligibility for a cash transfer. A
value that is honestly "coded under a retired frame" is recoverable. A value
that has been silently reinterpreted is not.

Three shapes of ambiguity, all treated the same way:

- **UBOS splits the legacy category.** `wall_material` 1 "Brick (burnt /
  unburnt)" maps to 13, 14 *or* 15; the legacy code does not say which.
  `not_working_reason` 3 "Illness / disability" maps to 04 *or* 05.
  `work_frequency` 4 "Seasonal" maps to 03 *or* 04.
- **UBOS has no equivalent.** `dwelling_type` 6 "Tent". `roof_material` 5
  "Mud / dung". `waste_disposal` 4 "Composted". `not_working_reason` 2
  "Household duties".
- **They are not the same variable.** `cooking_fuel` is the important one:
  the legacy list codes the **fuel** (firewood, charcoal, paraffin); UBOS
  2024 codes the **stove** (three-stone open fire, LPG stove, electric
  stove). Mapping "Firewood" onto "Three stone stove/open fire" would assert
  a stove type nobody was ever asked about. Almost the whole list is
  therefore `AMBIGUOUS`, and that is not an oversight.

### What remains is a named backlog, not a silence

`python manage.py report_legacy_choice_codes` prints every row still on an
unmapped legacy code, with the reason it was not mapped, and `--format csv`
produces the sign-off pack. On the dev database it currently prints:

```
48 row(s) across 1 (field, code) pair(s) are still on a legacy code with
no UBOS 2024 equivalent.
     48  Employment.not_working_reason = '2' (Household duties)
         Household duties — no UBOS 2024 equivalent. Mapping it to 06
         'Not looking for a job' asserts a labour-market status the
         respondent was never asked about.
```

Once MGLSD/UBOS decide a pair, it moves from `AMBIGUOUS` to `EXACT` and a
follow-up data migration applies it. The command also flags any row found on
an `EXACT` legacy code, which would mean the migration has not run or
something wrote a legacy code after it did.

## Migration plan for existing records

1. **`0019_retire_legacy_code_frames`** (shipped, forward-only per ADR-0003):
   - rewrites `EXACT` pairs across all 16 entries in `CODED_FIELDS`;
   - deprecates every legacy option on every version of each list;
   - asserts, in a second `RunPython` step, that no row survives on an
     `EXACT` legacy code — the migration fails loudly rather than reporting
     a clean run over rows it missed.
   - Idempotent. The reverse is a no-op: re-activating a frame that produced
     uncodeable duplicates is not a state worth being able to return to.
2. **Before running it in production**: take the standard pre-migration dump
   (`~/nsr_migration_backup/`), and capture the *current* distribution with
   `report_legacy_choice_codes --format csv` so the before/after is on
   record.
3. **After running it**: re-run the report. The only rows it may name are
   `AMBIGUOUS` ones. Anything else is a defect in the mapping.
4. **The remainder** goes to MGLSD/UBOS as the sign-off pack. Each decided
   pair is a one-line addition to `EXACT` plus a follow-up migration that
   reuses the same `_retire_legacy_frames` shape.
5. **Detail tables are currently empty on dev** (`Dwelling`, `Utilities` and
   their version tables have 0 rows), so step 1 is effectively
   employment-only there. Production is expected to carry housing rows too;
   the mapping covers them and the report will size them.

No `AuditEvent` rows are emitted — a migration-time reference-data fix has no
actor, matching `0015_retire_duplicate_sub_regions` and
`0018_retire_duplicate_northern_region`. Operator-driven reference-data edits
still go through `apps.reference_data.lifecycle`, which does emit audit
events.

## Consequences

- Every housing and employment dropdown now offers one unambiguous option
  per concept. `TestOneCodeFrame` asserts that no two selectable options in
  an affected list share a label, against the bundle the wizard actually
  fetches.
- Analysis spanning the cutover must treat `AMBIGUOUS`-coded rows as a
  distinct category until the sign-off lands. They are a *named* category,
  which is the improvement.
- Adding a code to `EXACT` without a UBOS decision is the failure mode this
  ADR exists to prevent. `test_every_exact_target_is_a_real_ubos_code` and
  `test_every_ambiguous_code_says_why` are the guard rails.
- `CODED_FIELDS` must gain an entry whenever a new model column stores one
  of these lists. `test_version_tables_are_covered` catches the common
  omission — remapping a base model and forgetting its `*Version`.

## Alternatives considered

**Delete the legacy options.** Simplest dropdown, but every record still
carrying a legacy code becomes uninterpretable, which ADR-0010 forbids and
which the audit trail depends on.

**Keep both frames and disambiguate the labels** ("Detached (legacy)").
Keeps two frames alive forever, doubles every list, and leaves the
enumerator making a data-governance decision at the point of interview.

**Map everything, using nearest-neighbour for the ambiguous cases.** Gives a
single clean frame today at the cost of an unknown number of fabricated
answers feeding PMT scores. Rejected: a wrong PMT band is a household not
receiving a transfer.
