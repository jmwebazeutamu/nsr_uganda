# GRM — Grievance

!!! info "Status"
    **Built and in use** — L1 intake, triage and routing, GRM↔UPD auto-close tween. SLA breach dashboard live in RPT.

GRM is the citizen-facing complaints and corrections channel.

## What it does

Receives grievances from walk-in, phone, web, MDA referral, and (planned) SMS. Triages by category and severity. Routes per the matrix. Links to UPD when the resolution requires a data change. Auto-closes the grievance when the linked UPD commits.

## Where it lives

| Path | What |
|---|---|
| `apps/grievance/` | Django app |
| `/api/v1/grm/` | DRF surface |
| `/design/v0.1/screens/screens-grm.jsx` | GRM workbench |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/grm/grievances/` | GET, POST | List, create |
| `/api/v1/grm/grievances/{id}/` | GET, PATCH | Read, update |
| `/api/v1/grm/grievances/{id}/triage/` | POST | Assign to a level |
| `/api/v1/grm/grievances/{id}/escalate/` | POST | Move up a level |
| `/api/v1/grm/grievances/{id}/resolve/` | POST | Close with reason |
| `/api/v1/grm/grievances/{id}/open-change-request/` | POST | Bridge to UPD |

## Key entities

- `Grievance`
- `GrievanceStatus`
- `Triage`

## ADRs

- See ADR-0014, ADR-0015 for the programme + referral context that GRM ties into

## Stories

US-032, US-033, US-034, US-035, US-036, US-094, US-095.
