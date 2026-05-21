# ADR-0017 — Detail entities as separate tables (not JSONField on Household)

**Status**: Proposed
**Date**: 2026-05-21
**Authors**: NSR Unit engineering
**Sprint**: 22 (DE build)
**Stories**: US-S22-DE-01 (this ADR), US-S22-DE-02 … US-S22-DE-14
**Parent ADRs**: ADR-0001 (architecture style), ADR-0005 (sub-region
partitioning), ADR-0010 (coded fields via ChoiceList)

## Context

The household questionnaire (`/docs/06_questionnaire.docx`) collects
~120 typed answers per household across sections C16–L02 — dwelling
materials, water/sanitation, agricultural land, member-level health,
disability (Washington Group Short Set), education, employment, food
security (FIES), food consumption (FCS), shocks, coping strategies.

Pre-US-S22-DE these answers landed in `RawLanding.payload` and
`StageRecord.canonical_payload` (both JSONField blobs) and were
silently dropped by `promote_stage_record` — only ~20 typed
columns on Household + Member survived promotion. Consequences:

1. **PMT engine is starved.** The Sprint 1 placeholder formula
   weights 3–5 predictors; country comparators (Philippines
   Listahanan = 46, Indonesia UDB ≈ 30+) sit well above that.
2. **DRS queries can't restrict on the detail tail.** Partners
   building DSAs against the registry can't scope a request to
   "households with FIES affirmative count ≥ 5" — that field
   doesn't exist as a queryable column.
3. **No per-detail audit.** A change to a member's chronic
   illness status writes only the parent Member._Version row;
   no granular trail.
4. **Reporting is impossible.** Disability prevalence,
   Food Consumption Score distribution, etc. are aggregates the
   GoU stakeholders need monthly; computing them from a JSON blob
   per household is O(N) per dashboard read.

The question this ADR settles: **how do we persist the
socioeconomic detail tail in the registry?**

## Decision

**Separate, typed tables — one per logical entity — joined to
`Household` (or `Member`) by FK. Each entity carries its own
`_Version` snapshot table per SAD §5.3, the standard `_DetailBase`
audit-bearing columns, and `sub_region_code` denormalisation for
partition routing per ADR-0005.**

The five per-Household one-to-one entities (Dwelling, Utilities,
Livelihood, FoodSecurity, FoodConsumption) and four per-Member
one-to-one entities (Health, Disability, Education, Employment)
use `OneToOneField(parent, on_delete=PROTECT)` with reverse
accessors that the PMT engine + serialisers traverse via dotted
paths.

## Considered alternatives

- **One JSONField per entity on Household.** Keeps the schema
  small. Rejected: not queryable from DRS / reporting / PMT
  without parsing on every read; per-field audit + versioning
  becomes bespoke; ChoiceList integration would need per-key
  custom serialisation.

- **Hybrid: typed columns for PMT predictors, JSONField for
  everything else.** Tempting for a six-month iteration. Rejected
  because the boundary is unstable — every reporting addition
  would move fields from JSON to columns, requiring data
  migrations anyway.

- **Add columns directly to Household / Member.** Both tables
  are already at ~30 columns; adding 120 more would make
  partial reads expensive and the model file unmaintainable.

## Consequences

**Gains**

- Every detail column is indexable, queryable from DRS, walkable
  by the PMT engine via dotted paths.
- Per-entity `_Version` table gives granular audit + change-history
  that the operator's Update Workflow can reason about.
- Reporting tiles aggregate via standard ORM (`Count`,
  `aggregate`) without JSON parsing.
- ChoiceList resolution via ADR-0010 works uniformly — every
  coded column gets its `<col>_label` companion on the serialiser.

**Costs**

- 14 new model tables + 14 `_Version` mirrors = 28 tables. The
  Household + Member detail surface is now ~10× larger than the
  Sprint 0 schema.
- Promotion-time fanout (`apps.ingestion_hub.services._create_*`)
  now does N writes per household — measurable but bounded.
  Per US-S22-DE-04 testing, an average household promotion
  remains well inside the AC-DIH-PROMOTE-ATOMIC budget.
- PMT engine has to be N+1-free; achieved via the
  `select_related`/`prefetch_related` chain in
  `apps.pmt.services.recompute_for_household` (US-S22-DE-06).

## References

- SAD §5 (Entity model), §5.3 (Versioning)
- ADR-0001, ADR-0005, ADR-0010
- US-S22-DE-01 (this slice's first commit)
- Build prompt: `docs/build_prompts/US-S22-detail-entities_implementation_prompt.md`
