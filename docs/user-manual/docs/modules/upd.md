# UPD — Update Workflow

!!! info "Status"
    **Partial** — ChangeRequest scaffold + routing matrix in REF-DATA + GRM tween + SLA breach dashboard + NIRA auto-commit live. Reviewer screen wiring deferred to S5; no-self-approve enforcement (US-091) pending.

UPD routes every change to a household through review and commit. Inputs come from GRM, walk-in update requests, NIRA vital events, and partner corrections.

## What it does

Receives a `ChangeRequest`. Routes via the matrix (REF-DATA). Stages the proposed change as a diff. Re-runs DQA against the proposed state. Routes to one or more approvers. Commits in a single transaction with a new HouseholdVersion + MemberVersion row.

## Where it lives

| Path | What |
|---|---|
| `apps/update_workflow/` | Django app |
| `/api/v1/upd/` | DRF surface |
| `/design/v0.1/screens/screens-upd.jsx` | UPD reviewer |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/upd/change-requests/` | GET, POST | List, create |
| `/api/v1/upd/change-requests/{id}/` | GET, PATCH | Read, edit (draft only) |
| `/api/v1/upd/change-requests/{id}/submit/` | POST | Submit for review |
| `/api/v1/upd/change-requests/{id}/approve/` | POST | Approve (no self-approval) |
| `/api/v1/upd/change-requests/{id}/reject/` | POST | Reject with reason |
| `/api/v1/upd/change-requests/{id}/commit/` | POST | Commit approved change |

## Key entities

- `ChangeRequest`
- `ChangeRequestDiff` — per-field diff
- `RoutingDecision` — the matrix's decision and rationale

## Auto-commit cases

| Source | Trigger |
|---|---|
| NIRA vital event | Birth or death from `nira_vital` connector |
| GRM resolution | Reviewer marks the linked grievance resolved with a data-correction action |

## ADRs

- [ADR-0014](../appendices/adrs.md) — Programme registration data model

## Stories

US-027, US-028, US-029, US-030, US-031, US-088, US-089, US-090, US-091, US-092, US-093, US-094, US-095, US-096.
