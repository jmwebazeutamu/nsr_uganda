# ADR-0018 — Repeat-group entities as child tables (not JSONField)

**Status**: Proposed
**Date**: 2026-05-21
**Authors**: NSR Unit engineering
**Sprint**: 22 (DE build)
**Stories**: US-S22-DE-01
**Parent ADRs**: ADR-0017 (detail entities as tables)

## Context

ADR-0017 settles the question for the per-Household / per-Member
one-to-one detail entities. There's a separate question for the
**repeat groups** the questionnaire collects:

- **AssetOwnership** (G15 a–n) — up to 14 asset types per household
- **Crop** (H3, H5) — multiple crops per household
- **Livestock** (H3 a–h) — multiple livestock types
- **Shock** (K01–K04) — multiple shock events
- **CopingStrategy** (L01, L02) — multiple coping strategies, two
  categories (livelihood, food)

Each has a natural variable cardinality per household (0 to N). The
JSON answer shape is a list of objects; persisting them as the
same list-of-dicts on Household.JSONField is the obvious tempting
shortcut.

## Decision

**Child tables, one row per repeat-group entry, FK to
`Household` with `on_delete=PROTECT`.** Same audit-bearing
`_DetailBase` columns (ULID id, `sub_region_code`, soft-delete,
timestamps) and paired `_Version` snapshot tables as the
one-to-one entities per ADR-0017.

Uniqueness within the household is scoped to `is_deleted=False`
via `UniqueConstraint(... condition=Q(is_deleted=False))` so:

- A soft-deleted row releases its (household, type) slot for
  re-creation.
- Hard duplicates inside the same household can't land.

## Considered alternatives

- **JSONField list of dicts on Household.** Same problems as
  ADR-0017's rejected JSON option — not queryable, no per-event
  audit, ChoiceList integration awkward.

- **One JSONField per repeat group on Household.** Marginal
  improvement over the unified blob — still not queryable.

- **No uniqueness constraint.** Tempting because the
  questionnaire doesn't enforce uniqueness at the form layer.
  Rejected: duplicate `(household, asset_type)` rows would
  inflate counts in PMT and reporting; the constraint forces
  the questionnaire to surface "you already added radio" rather
  than letting the registry silently double-count.

## Consequences

**Gains**

- Reporting tiles (e.g. "household has radio") aggregate via
  `AssetOwnership.objects.filter(asset_type='radio').count()` —
  no JSON traversal.
- PMT engine resolves `assets.radio.count` via a dict-of-models
  the `_household_features` helper builds from a single
  IN-query (US-S22-DE-06).
- Per-event audit: a Shock row's update writes a `ShockVersion`
  with the pre-update state. The audit chain is granular enough
  to answer "what severity did this shock have on
  2026-04-01?" without parsing JSON history.

**Costs**

- 5 new repeat-group tables + their 5 `_Version` siblings = 10
  more tables on top of ADR-0017's 18 (already counted in the
  28-table total).
- Cardinality unbounded — a malicious or buggy connector could
  flood a household with thousands of Shock rows. Mitigation:
  the questionnaire has natural maxima (asset cardinality 9
  enforced at the model layer; sharing-households capped at 10).
  A per-household-per-entity row cap (e.g. 50 shocks) is OI-DE-1.

## References

- ADR-0017 (parent)
- US-S22-DE-01
- `apps/data_management/models.py` — AssetOwnership, Crop, Livestock,
  Shock, CopingStrategy
