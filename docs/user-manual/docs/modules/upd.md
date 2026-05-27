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
| `/api/v1/upd/change-requests/` | GET, POST | List (filter `?status=`, comma-separated for multi-state; `?entity_id=` to scope to one record), create |
| `/api/v1/upd/change-requests/{id}/` | GET, PATCH | Read, edit (draft only) |
| `/api/v1/upd/change-requests/{id}/submit/` | POST | Submit for review |
| `/api/v1/upd/change-requests/{id}/approve/` | POST | Approve (no self-approval) |
| `/api/v1/upd/change-requests/{id}/reject/` | POST | Reject with reason |
| `/api/v1/upd/change-requests/{id}/commit/` | POST | Commit approved change |
| `/api/v1/upd/change-requests/{id}/hold/` | POST | Hold for more info |
| `/api/v1/upd/change-requests/{id}/release/` | POST | Release from hold back to pending |
| `/api/v1/upd/change-requests/bundle/` | POST | Multi-row Open-CR submission from the wizard modal |
| `/api/v1/upd/field-catalog/` | GET | Backend-owned field catalog with select options resolved against the active ChoiceList version (ADR-0010). `?lang=` for label language; ETag-cached. |
| `/api/v1/upd/current-values/` | GET | Current persisted values for an entity, projected for the Open-CR wizard's Before/After diff. |

## Open-CR wizard (US-S28)

The Open-CR modal (`design/v0.1/components/change-request-modal.jsx`) is a 4-step wizard: **Target → Fields → Evidence → Review**. It no longer carries its own field catalog — sections, fields, types, constraints, and select options all come from `/api/v1/upd/field-catalog/` on mount. The hardcoded JSX `CATEGORIES` is retained as a fallback for design-preview / unauthenticated sessions only.

Wizard validation gates (since v0.3):

- Step 1 (Target) — when entity=member, a member must be picked.
- Step 2 (Fields) — at least one row with a non-blank value, **and at least one row's new value must differ from the current value** (no-op detection — submitting a CR that changes nothing is now impossible).
- Step 3 (Evidence) — note ≥ 6 chars. (Earlier this gate sat on the Submit button at step 4, which surprised operators who only saw the disabled state at the end.)
- Step 4 (Review) — same as step 3.

PMT relevance is auto-derived from the picked rows but the **Mark PMT-relevant** checkbox is now bidirectional — operator can override either way, including unticking when a PMT-relevant field is added. An override chip surfaces in the help text when the operator's choice differs from the derived value.

Input controls match the field type — text input, number input with `min`/`max`/`step` from the catalog, date picker bounded by the catalog (e.g. `member_dob` resolves `max_today: true` to today's ISO date so birthdays can't be in the future), and `select` populated from the active ChoiceList. Submit error banners are dismissible with inline **Retry**.

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
