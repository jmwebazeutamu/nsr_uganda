# DAT-DQA — Data Quality

!!! info "Status"
    **Built and in use** — rule CRUD, preview, dual approval, evaluation on ingest, violations dashboard (US-076 through US-079, US-082).

DQA is the rule engine that decides whether a record can promote into DAT. Shared service called from both DIH (on ingest) and UPD (on change).

## What it does

Maintains a versioned, dual-approved catalogue of rules. Evaluates rules against staged records. Quarantines on blocking failure. Attaches warnings for steward visibility. Surfaces a violations dashboard with daily triage.

## Where it lives

| Path | What |
|---|---|
| `apps/dqa/` | Django app |
| `/api/v1/dqa/` | DRF surface |
| `/design/v0.1/screens/screens-admin-workflow-dqa.jsx` | Rule Editor |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/dqa/rules/` | GET, POST | List, create draft |
| `/api/v1/dqa/rules/{id}/submit-for-approval/` | POST | Move to `pending_approval` |
| `/api/v1/dqa/rules/{id}/approve/` | POST | Approve (rejects same-author) |
| `/api/v1/dqa/rules/{id}/reject/` | POST | Reject with reason |
| `/api/v1/dqa/rules/{id}/preview/` | POST | Dry-run against sample |
| `/api/v1/dqa/violations/` | GET | Daily triage queue |

## Key entities

- `DqaRule` — versioned, dual-approved.
- `DqaResult` — one row per rule evaluation; linked to staged record and to violations.

## The 3 seeded Sprint 0 rules

| Rule | Severity |
|---|---|
| `AC-MANDATORY-MEMBER-NAME` | blocking |
| `AC-NIN-FORMAT` | blocking |
| `AC-GPS-ACCURACY` | blocking |

Seeded by `scripts/seed_dqa_rules.py`.

## ADRs

- [ADR-0009-dqa](../appendices/adrs.md) — DQA Rule Editor UI

## Stories

US-076, US-077, US-078, US-079, US-080, US-081, US-082, US-119 (rule pack rebuild on questionnaire activation).
