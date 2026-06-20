# DAT-DQA — Data Quality

!!! info "Status"
    **Built and in use** — rule CRUD, real registry-sweep Run-preview, four-severity vocabulary, full Clone/Submit/Approve/Reject/Retire lifecycle, evaluation on ingest + UPD commit, violations dashboard, intra-household rule pack live (US-076 through US-079, US-082, US-S11-044).

DQA is the rule engine that decides whether a record can promote into DAT, gets flagged for reviewer attention, or is silently logged. Shared service called from DIH (on ingest + promote) and from UPD (on change-request commit).

## What it does

Maintains a versioned, dual-approved catalogue of rules. Evaluates them against staged records and committed UPD changes. Aborts promotion on `block` / `reject_with_override` (DIH promote). Emits `dqa.household.flag` audit events for `flag` severity so the UPD reactor opens a review case. Surfaces a violations dashboard with daily triage.

## Where it lives

| Path | What |
|---|---|
| `apps/dqa/` | Django app |
| `apps/dqa/engine.py` | Legacy entity-filtered evaluator |
| `apps/dqa/household_evaluator.py` | US-S11-044 intra-household evaluator |
| `apps/dqa/pipeline.py` | `run_household_gate()` — per-stage abort policy |
| `apps/dqa/signals.py` | UPD post-commit re-eval |
| `/api/v1/dqa/` | DRF surface (lower-level) |
| `/api/v1/admin/workflow/dqa/` | Admin-console workflow surface |
| `/design/v0.1/screens/screens-admin-workflow-dqa.jsx` | Rule Editor |

## Endpoints (admin-console)

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/admin/workflow/dqa/rules/` | GET | List rules with severity + recent previews |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/` | GET, PATCH | Detail; PATCH severity/expression on DRAFT only (409 otherwise) |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/clone/` | POST | Clone latest non-retired → new DRAFT (v+1) |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/preview/` | POST | Real registry sweep, persists `DqaRulePreviewRun` |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/v{version}/submit/` | POST | DRAFT → PENDING_APPROVAL |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/v{version}/sign/` | POST | PENDING → ACTIVE (note required) |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/v{version}/reject/` | POST | PENDING → REJECTED (reason required) |
| `/api/v1/admin/workflow/dqa/rules/{rule_id}/v{version}/retire/` | POST | ACTIVE → RETIRED |

## Severity vocabulary

Four severities; legacy aliases parsed for back-compat:

| Severity | Behaviour | Legacy alias |
|---|---|---|
| `block` | Abort promotion at `dih_promote` | `blocking` |
| `reject_with_override` | Abort unless an override reason is supplied (audited) | — |
| `flag` | Emit `dqa.household.flag`; UPD reactor opens a review case | `warning` |
| `info` | Logged only | `info` |

Every consumer of severity reads through `apps.dqa.models.severity_bucket()` so both vocabularies route to the same {block, flag, info} bucket.

## Key entities

- `DqaRule` — versioned, dual-approved.
- `DqaResult` — one row per failing evaluation; linked to staged or committed record.
- `DqaRulePreviewRun` — audit trail of Run-preview sweeps. Counts + up to 10 failing IDs; never persists field values.
- `DqaEvaluation` (intra-household path) — one row per household × stage × evaluation.

## Seeded rule pack

### Legacy entity-filtered (active)

| Rule | Severity | Scope |
|---|---|---|
| `AC-MANDATORY-MEMBER-NAME` | block | member |
| `AC-NIN-FORMAT` | block | member |
| `AC-GPS-ACCURACY` | block | household |
| `AC-MEMBER-AGE-MAX` | flag | member |

Seeded by `scripts/seed_dqa_rules.py`.

### Intra-household (US-S11-044, seeded DRAFT)

`AC-HOH-EXISTS`, `AC-HOH-AGE`, `AC-HOH-AGE-CHILD-LED`, `AC-SPOUSE-PAIR`, `AC-PARENT-AGE`, `AC-MEMBER-COUNT-MATCH`, `AC-DUPLICATE-MEMBER`, `AC-DISABILITY-CONSISTENCY`, `AC-ORPHAN-FLAG`.

Seeded DRAFT by `scripts/seed_dqa_intra_household_rules.py`. Walk each through the dual-approval flow to activate.

## Where rules fire

| Stage | Engine | Aborts? |
|---|---|---|
| `dih_ingest` | both | never — `DqaResult` + `dqa.household.flag` for FLAGs |
| `dih_promote` | intra-household | yes — `block`/`reject_with_override` |
| `registry_post_promote` | both | never — `DqaResult` + `dqa.household.flag` since 2026-05-30 |

## ADRs

- [ADR-0009-dqa](../appendices/adrs.md) — DQA Rule Editor UI

## Stories

US-076, US-077, US-078, US-079, US-080, US-081, US-082, US-S11-044 (intra-household), US-119 (rule pack rebuild on questionnaire activation).
