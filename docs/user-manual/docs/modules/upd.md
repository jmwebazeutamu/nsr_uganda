# UPD — Update Workflow

!!! info "Status"
    **Built and in use.** ChangeRequest lifecycle, an operations-editable routing table, the GRM bridge, the SLA breach dashboard and NIRA auto-commit are all live. Separation of duties (US-091) is enforced — see [Who may review](#who-may-review). Revised 25 September 2026.

UPD routes every change to a household through review and commit. Inputs come from GRM, walk-in update requests, NIRA vital events, and partner corrections.

## What it does

Receives a `ChangeRequest`. Routes it using the `UpdRoutingRule` table. Stages the proposed change as a field-level diff on the request itself. Re-runs DQA against the proposed state. Routes to an approver. Commits in a single transaction with a new HouseholdVersion + MemberVersion row.


## The change request number

Every change request carries two identifiers, for different readers.

| | Example | For |
|---|---|---|
| **Reference** | `UPD-2026-0001` | people — say it, write it, quote it |
| **Id** | `01M3AT4JSSXFYG02CXC8S6K20X` | the system — URLs, the audit chain, links from other modules |

A Parish Chief quotes it to the citizen whose record is changing.

The year, then the record's number within that year, restarting each
January. Four digits is a minimum, not a limit.

**Type it however it reaches you.** `?q=` on the list endpoint accepts
it lower-case, without the prefix, without the dashes, with spaces, and
with a letter **O** typed for zero or **I**/**l** for one.

!!! warning "A number can be guessed — that is why scope matters"
    The number after yours is somebody's record. Guessing it opens
    nothing: every list and detail route applies your scope first, so a
    reference you were not given behaves exactly like one that does not
    exist. What a sequence does disclose is **how many** records exist.
    [ADR-0039](../appendices/adrs.md) records that trade.

!!! note "The number never changes"
    Assigned once when the record is created. Nothing afterwards
    touches it, because a number quoted to somebody has to keep meaning
    the same record.


## Where it lives

| Path | What |
|---|---|
| `apps/update_workflow/` | Django app |
| `/api/v1/upd/` | DRF surface |
| `/design/v0.1/screens/screens-upd.jsx` | UPD reviewer |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/upd/change-requests/` | GET, POST | List (`?q=` change-request number; `?status=` accepts a comma-separated list; `?entity_id=` to scope to one record), create |
| `/api/v1/upd/change-requests/{id}/` | GET, PATCH | Read, edit (draft only) |
| `/api/v1/upd/change-requests/{id}/submit/` | POST | Submit for review |
| `/api/v1/upd/change-requests/{id}/approve/` | POST | Approve (no self-approval) |
| `/api/v1/upd/change-requests/{id}/reject/` | POST | Reject with reason |
| ~~`/api/v1/upd/change-requests/{id}/commit/`~~ | — | **Not exposed.** The commit runs in-process when a request is approved; there is no HTTP route for it. Documented here since 2026 and never built. |
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

| Entity | What |
|---|---|
| `ChangeRequest` | the request — `id` is the ULID key, `reference` the number people quote, `changes` the field-level diff as JSON |
| `UpdRoutingRule` | one active row per (change type, PMT-relevant) giving the required role and the SLA window |

!!! warning "Two entities this page used to list do not exist"
    `ChangeRequestDiff` and `RoutingDecision` were never built. The diff
    is the `changes` JSON column on `ChangeRequest`; the routing
    decision is `required_role` and `sla_deadline`, stamped onto the
    request at capture. Corrected 25 September 2026.

## Routing

`UpdRoutingRule` holds one active row per (change type, PMT-relevant)
pair, giving the role that must review it and how long they have.
Operations can retune it without a software release.

**There is no code fallback.** A combination with no active row raises
rather than guessing. That is deliberate — a fallback means a code
release can change routing policy, and it means a half-configured table
looks fine while a constant quietly answers for it.

!!! danger "This bit us on 25 September 2026"
    The fallback was removed while nine of the twenty-two combinations
    had no row — `address_move`, `roster_change`, `asset_change`,
    `verification` and PMT-relevant `life_event` had been living off
    the constant since they were added. Production held 13 of 22.
    Caught by querying the live table before deploying; migrations
    `0006` and `0007` seeded the rest.

    If you add a `ChangeType`, **seed its two rows in the same
    migration**. The completeness test in
    `apps/update_workflow/tests.py` will fail if you do not.

## Who may review

Separation of duties is enforced in `apps/update_workflow/authorization.py`
and answered as a **permission** question:

| | |
|---|---|
| A requester reviewing their own request | **403**, `AC-UPD-NO-SELF-APPROVE` |
| A reviewer without the required role | **403** |
| A request in the wrong state for the action | **400** — that is a precondition, not a permission |

Naming somebody else in the request body does not help: the actor is
taken from the authenticated session, never from the payload.

## Auto-commit cases

| Source | Trigger |
|---|---|
| NIRA vital event | Birth or death from `nira_vital` connector |
| GRM resolution | Reviewer marks the linked grievance resolved with a data-correction action |

## ADRs

- [ADR-0014](../appendices/adrs.md) — Programme registration data model

## Stories

US-027, US-028, US-029, US-030, US-031, US-088, US-089, US-090, US-091, US-092, US-093, US-094, US-095, US-096.
