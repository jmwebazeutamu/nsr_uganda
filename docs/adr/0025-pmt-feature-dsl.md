# ADR-0025: PMT features as a JSON DSL on `PMTModelVersion`

- **Status**: Accepted
- **Date**: 22 May 2026 (implemented in `288d59b`, US-S22-PMT-DSL) — **written up retroactively on 8 August 2026**; see "Provenance" below
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Statistician, Engineering Lead
- **References**: SAD §4.5 (PMT), §12 O-03 (PMT weights open item); ADR-0003 (migration policy); DEP-03 / DEP-04 (TOR weights, calibrated model); `apps/pmt/feature_evaluator.py`, `apps/pmt/registry.py`, `apps/pmt/checks.py`, `apps/pmt/engine.py`, `apps/pmt/migrations/0006_seed_pmt_v1_active.py`

---

## Context

The PMT score is a weighted sum over household features. The first implementation hardcoded both the variable names and the code that computed each one, so the model and the engine were the same artefact.

That is the wrong coupling for this system. Per SAD §4.5 and the O-03 open item, the PMT model is **owned by the Statistician and UBOS, not by engineering**: v1 uses provisional TOR weights (DEP-03) and a calibrated v1 model follows later (DEP-04), with recalibration expected on each new UNHS round. Under the hardcoded design every one of those is a code change, a release, and a migration — and the audit-bearing dual-approval workflow on `PMTModelVersion` guards a row that does not actually determine the score.

The requirement is therefore that a new model version — new variables, new weights, new derivations — can be authored, dual-approved and activated **as data**, while remaining fully auditable and impossible to make silently wrong.

## Decision

### D1. Each variable carries a `feature` block describing how to compute itself.

`PMTModelVersion.variables` is a JSON document; every entry pairs a `weight` with a `feature` block. The engine no longer knows any variable by name — it evaluates whatever the active model version declares.

```json
{"name": "food_consumption_score_v1", "weight": 0.0,
 "feature": {"type": "registered_function",
             "function": "food_consumption_score_v1"}}
```

### D2. Eleven feature types, deliberately not a general expression language.

`direct`, `equality`, `inequality`, `membership`, `comparison`, `ratio`, `count_where`, `share_where`, `presence_in_collection`, `aggregate_any`, `registered_function`.

Comparison operators are limited to `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`. Path resolution walks dotted segments (`head_member.education.highest_grade`), accepting dict-key or attribute access at each step; a missing segment short-circuits to `None` and coerces to 0.

This is a closed vocabulary, not an embedded language. A model author cannot express arbitrary computation, so an approved model version cannot execute arbitrary code — which is what makes it safe to treat model authoring as a data operation rather than a code change.

### D3. `registered_function` is the escape hatch, and it costs a code review.

Features that do not fit the DSL — FIES roll-ups, FCS aggregation, percentile-based features — live as Python functions decorated with `@register("name")` in `apps/pmt/registered_features.py`, referenced from JSON by name only. There is deliberately **no JSON-only path to Python evaluation**: adding one requires a code change and review, because Python evaluation has more blast radius than a DSL expression.

### D4. A dangling function reference is a deploy blocker, not a silent zero.

The Django system check `pmt.E001` (`apps/pmt/checks.py`) walks every **ACTIVE** `PMTModelVersion` and fails `manage.py check` if a `registered_function` name is not in the registry. Without it, renaming or removing a function would silently contribute 0 for that variable — scoring drift across the whole registry with no error anywhere. Inactive drafts are skipped; a stale draft is not a deploy blocker.

The check materialises its queryset inside a `try` because `manage.py check` runs before migrations on a first-run deploy, and a lazy queryset would otherwise raise on a missing table.

### D5. The evaluator is pure; the engine builds the feature graph.

`feature_evaluator` issues no database queries. `apps.pmt.engine._household_features` pre-builds the household feature graph and the evaluator walks it. This keeps per-household scoring free of N+1 queries at 12-million-household scale and makes the evaluator directly unit-testable without fixtures.

### D6. v1 ships as a seeded ACTIVE row, not as code.

`apps/pmt/migrations/0006_seed_pmt_v1_active.py` seeds the v1 UNHS 2023/24 model as ACTIVE with its variables expressed in this DSL — the decision applied to itself.

## Consequences

**Good.** Recalibration is a dual-approved data change: author a new `PMTModelVersion`, have it approved by someone other than the author, activate it. No deploy, and the existing audit trail on the row now genuinely governs the score. The Statistician owns the model without owning the codebase.

**Good.** The closed vocabulary bounds the blast radius of a bad model version to wrong numbers — never arbitrary execution.

**Cost.** Two places must now agree: the DSL and the registry. D4 exists precisely because that seam is where silent breakage would occur.

**Cost.** Reviewing a model version means reading JSON, which is less legible than Python. Mitigated by the closed vocabulary being small enough to learn in one sitting.

**Cost.** The DSL will not express everything. That is intended — `registered_function` absorbs the rest at the price of a review.

**Testing.** Fixtures seeding `PMTModelVersion` must use `version=900+`; migration 0006 already occupies `version=1` and the field is unique.

## Alternatives considered

**Keep features hardcoded.** Rejected: makes every recalibration a release, and leaves the dual-approval workflow guarding a row that does not determine the score.

**A general expression language (e.g. embedded Python, `eval`, or a full rules engine).** Rejected: an approved model version would become executable code, so model authoring could never be delegated as a data operation — the entire point of the change.

**Store features as SQL.** Rejected: couples the model to the physical schema, defeats the pure-evaluator property of D5, and puts arbitrary SQL behind an approval workflow aimed at statisticians.

## Provenance

This ADR was written on 8 August 2026 to document a decision **already implemented and in production** since `288d59b` (22 May 2026). It was identified as missing by the 2026-08-08 delivery and code-health audit: `ADR-0025` was cited in eleven places across `apps/pmt/` — `checks.py`, `engine.py`, `feature_evaluator.py`, `registry.py`, `migrations/0006_seed_pmt_v1_active.py` and their tests — while `docs/adr/0025-*.md` did not exist.

The content above is reconstructed from those modules' own documentation, which carried the rationale in detail; nothing here is a new decision. Status is recorded as **Accepted** because the code, the system check and the seeded ACTIVE v1 model have been live since May.
