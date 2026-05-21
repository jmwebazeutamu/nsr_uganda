# ADR-0020 — FIES and FCS computed-column placement

**Status**: Proposed
**Date**: 2026-05-21
**Authors**: NSR Unit engineering
**Sprint**: 22 (DE build)
**Stories**: US-S22-DE-01
**Parent ADRs**: ADR-0017 (detail entities as tables)

## Context

Two of the detail entities carry standardised aggregate scores:

- **`FoodSecurity.fies_raw_score`** — the FAO Food Insecurity
  Experience Scale (FIES) raw count, 0–8, summed from the eight
  yes/no questions I1–I8.
- **`FoodConsumption.fcs_score`** — the WFP Food Consumption
  Score, 0–112, computed as `Σ days_last_7[group] × weight[group]`
  over nine food groups with WFP-published weights.
- (A third — **`Disability.wg_disability_flag`** — is a derived
  boolean, not a numeric aggregate, but the same decision applies.)

The PMT engine references these as variables —
`household.food_security.fies_raw_score` and
`household.food_consumption.fcs_score` — every time it scores a
household. They also feed dashboard tiles (US-S22-DE-10 FCS
distribution).

The question: **where do we compute these?**

## Decision

**Compute on save inside the model's `save()` override** and
persist on the column. Reads are then one SQL hop —
`SELECT fies_raw_score FROM food_security WHERE household_id = ?` —
not a Python recomputation per scoring run.

The same approach applies to `Disability.wg_disability_flag`:
`save()` walks the six Washington Group columns and sets the
flag when any reports "03" / "04".

## Considered alternatives

- **Compute in Python at read time (e.g. as a `@property`).**
  Rejected — the PMT engine reads these on every scoring; for a
  12 M-row registry a recompute is a wasted ~10 ms per row,
  multiplied by N rows on bulk re-scoring.

- **Database trigger / `GENERATED COLUMN`.** Cleaner from a
  database-purity standpoint and prevents application-layer
  drift. Rejected for v1 because:
  - SQLite (the dev / CI backend) supports `GENERATED COLUMN`
    only partially; the Postgres+PostGIS production backend does.
    Per CLAUDE.md the audit-chain trigger is already
    Postgres-only and "degrades to no-op on sqlite"; another
    backend-divergent feature compounds that gap.
  - The WFP food-group weights and FIES affirmative-code
    convention may evolve (FAO publishes revisions); keeping the
    computation in Python lets the rule travel with the model
    file, not a migration.

- **Compute in a pre_save signal handler.** Functionally equivalent
  to the `save()` override but splits the logic across two files
  (model file + signals module). Rejected for module locality.

## Consequences

**Gains**

- PMT engine reads + dashboard reads are O(1) per row — no
  Python recompute, no SQL trigger.
- Single source of truth for the formula — `FoodSecurity.save()`,
  `FoodConsumption.save()`, `Disability.save()`. A revision
  updates one place.
- The score IS recomputed on every save, so an in-place column
  update via the ORM keeps the derived value in lockstep.

**Costs**

- `bulk_update(...)` and `Model.objects.update(...)` bypass
  `save()` — they won't recompute. The team must use
  per-row `.save()` for any code path that mutates a FIES /
  FCS column. Linted by an integration test (US-S22-DE-03's
  `test_fies_recomputed_on_resave`); a future linter rule may
  flag direct .update() on these tables.

- The score is read-only from the API surface
  (`SerializerMethodField` exposes the persisted column;
  clients can't write to it). The serialiser test in
  US-S22-DE-08 confirms `fies_raw_score` and `fcs_score` are
  read-only.

## References

- FAO Food Insecurity Experience Scale (FIES) — Voices of the
  Hungry programme
- WFP Food Consumption Score (FCS) Indicators (2008)
- Washington Group Short Set on Functioning (UN Statistics
  Division, 2010)
- ADR-0017 (detail entities as tables)
- `apps/data_management/models.py` — `FoodSecurity`,
  `FoodConsumption`, `Disability` save() overrides
