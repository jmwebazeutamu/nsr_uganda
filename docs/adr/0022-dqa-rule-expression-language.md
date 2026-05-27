# ADR-0022 — DQA rule expression language

- **Status**: Accepted
- **Date**: 2026-05-27
- **Story**: US-S11-044 (intra-household DQA rule slice)
- **Supersedes**: —
- **Superseded by**: —

## Context

SAD §4.2 mandates that DAT-DQA rules are operations-editable: the
Rule Editor admin view captures parameters, severity, message
template, watched fields, and test fixtures, and a dual-approval
workflow gates activation. SAD §12 lists the rule-expression-language
choice (DSL vs Python callable vs SQL) as an open item.

Sprint 0 shipped a JSON DSL in `apps/dqa/engine.py` for the
record-scope rules (AC-MANDATORY, AC-NIN-FORMAT, AC-GPS-ACCURACY).
The intra-household slice extends DAT-DQA to household-scope and
must commit to a single expression language across record and
household scopes — otherwise the Rule Editor becomes mode-dependent
and the dual-approval review surface forks per scope.

## Decision

We commit to the **existing JSON DSL** as the canonical expression
language for every DQA rule scope:

- FIELD
- RECORD
- HOUSEHOLD (new in US-S11-044)
- CROSS_HOUSEHOLD (later)

The `expression_type` enum is added to `DqaRule` so the model can
accept Python callables or SQL in the future without another
migration, but DSL is the only honoured option in the v1 evaluator.
Rules with `expression_type != "dsl"` are persisted but raise at
evaluation time until a future ADR opens those code paths.

### Why DSL over the alternatives

| Option | Verdict | Reason |
|---|---|---|
| **JSON DSL** (chosen) | ✓ | Operations-editable from the Rule Editor without a deploy. Sandboxed evaluator — no `eval()`, no SQL injection surface. Reviewable in the dual-approval workflow because every rule expression is a deterministic tree. Already in production for record-scope rules. |
| Python callable | ✗ | Operationally toxic: rule authors edit Python in the Rule Editor → arbitrary code in the evaluator process → security review on every rule. Defeats the audit-bearing point of DQA. |
| Raw SQL | ✗ | Half-way solution: still requires the same review burden as Python. Can't run against in-memory canonical payloads at the DIH-ingest stage (no row in the DB yet). Couples rule semantics to schema specifics, so an ERD change breaks rules. |

### DSL surface

The household-scope DSL extends the existing record-scope DSL with
two new top-level operators and one collection helper:

- `for_each_member` — iterates over `payload.members`, evaluating
  the inner expression per member and aggregating offending member
  ids. Enables AC-PARENT-AGE, AC-DISABILITY-CONSISTENCY,
  AC-ORPHAN-FLAG.
- `count_where` — counts members matching a predicate. Enables
  AC-HOH-EXISTS (count of `relationship_to_head == "01"`).
- `lookup_member` — resolves a member by line_number or id from
  another member's payload (e.g. follows the spouse pointer for
  AC-SPOUSE-PAIR).

Every threshold is read from `DqaRule.parameters`. The evaluator
refuses to run a rule whose expression references a parameter that
isn't declared on the rule row — this fails fast in the Rule
Editor's test-fixtures runner so authors catch their typos before
submit.

### Storage shape

```jsonc
{
  "rule_id": "AC-HOH-AGE",
  "version": 1,
  "category": "INTRA_HOUSEHOLD",
  "scope": "HOUSEHOLD",
  "expression_type": "dsl",
  "expression": {
    "op": "count_where",
    "collection": "members",
    "predicate": { "and": [
      { "eq": ["$.relationship_to_head", "01"] },
      { "lt": ["$.age_years", "$parameters.min_head_age"] }
    ]},
    "fail_when": { "gt": 0 }
  },
  "parameters": { "min_head_age": 12, "warn_below": 18 },
  "applies_to": {
    "fields": ["members.*.relationship_to_head", "members.*.age_years"]
  },
  "severity": "block",
  "stages": ["dih_ingest", "dih_promote", "registry_post_promote"],
  "message_template_i18n_key": "dqa.ac_hoh_age.message",
  "message_template_en":
    "Head of household must be {min_head_age}+; got {age_years}."
}
```

## Consequences

### Positive
- Single expression language across all rule scopes — Rule Editor
  has one editing surface.
- DSL is data, not code: rules are diffable, version-controllable,
  and auditable.
- The sandboxed evaluator is the only execution surface, so the
  Python process running DQA never executes operator-supplied code.
- Existing record-scope rules don't need changes.

### Negative
- The DSL needs extending for every new operator a rule author
  wants. Mitigated by `expression_type` field — future Python /
  SQL escape hatches are schema-ready.
- Rule authors learn a DSL rather than the language they already
  know. The Rule Editor's parameter form + test-fixture runner
  carry most of the load.

### Operational
- Apps reading rules must read `expression_type` and dispatch.
  Today: only DSL is honoured; future ADRs open other paths.
- The Rule Editor surfaces `expression_type` as a dropdown but
  every option except DSL is disabled until a follow-up story
  enables it.

## Compliance

- **SAD §4.2** — DAT-DQA shared service, used by DIH + registry.
- **SAD §12** — closes the rule-language open item.
- **DPPA 2019** — rule evaluator never persists rule input payloads;
  only ids of offending members are persisted on `DqaEvaluation`.
  See the DPIA addendum in `docs/dpia/sprint_*_impacts.md` for the
  P9 commit of US-S11-044.
