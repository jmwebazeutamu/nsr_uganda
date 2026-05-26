# INT — Intake

!!! info "Status"
    **Scaffolded** — Submission model + intake form scaffold (US-001, US-005, US-008). CAPI offline path and full intake flows Planned for S8+ alongside questionnaire authoring (US-116 to US-120).

INT is the entry surface for any household submission. Walk-in, web, CAPI tablet, bulk import.

## What it does

Receives a submission from any channel. Creates a `Submission` row with channel metadata. Hands the payload to DIH for validation and promotion. Returns the provisional Registry ID.

## Where it lives

| Path | What |
|---|---|
| `apps/intake/` | Django app |
| `/api/v1/intake/` | DRF surface |
| `/design/v0.1/screens/screens-capture.jsx` | Capture screen |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/intake/submissions/` | POST | Submit a household payload |
| `/api/v1/intake/submissions/{id}/` | GET | Read a submission status |

## Key entities

- `Submission` — one row per inbound payload, with channel, operator, timestamp, raw payload reference, status.

## Status detail

| What | State |
|---|---|
| Submission entity scaffolded | Built (US-001) |
| Walk-in form (desktop) | Built (US-088) |
| CAPI offline | Scaffolded |
| Web on-demand form | Built |
| Bulk import | Built via DIH |
| Questionnaire authoring (US-116 to US-120) | Planned |

## ADRs

- [ADR-0004](../appendices/adrs.md) — CAPI form runtime
- [ADR-0018](../appendices/adrs.md) — Repeat groups as child tables

## Stories

US-001, US-002, US-003, US-004, US-005, US-006, US-007, US-008, US-009, US-010, US-088, US-112, US-117, US-118.
