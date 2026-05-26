# REF — Referral

!!! info "Status"
    **Built and in use** — programme referral pull, creation, programme MIS notify path, PDM and NUSAF connectors.

REF pushes eligible households to programme MIS systems. The complement to inbound DIH connectors.

## What it does

Listens for PMT recompute events. Matches the household against active Programme definitions. Creates referral records. Pushes notifications to the programme MIS via per-programme connectors.

## Where it lives

| Path | What |
|---|---|
| `apps/referral/` | Django app |
| `apps/partners/services/programme_lifecycle.py` | Programme model + lifecycle (consolidated per ADR-0015) |
| `/api/v1/ref/` | DRF surface |
| `/design/v0.1/screens/screens-programmes.jsx`, `screens-programme-detail.jsx`, `screens-programme-new.jsx` | Programme admin |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/ref/referrals/` | GET | Referrals list |
| `/api/v1/ref/referrals/{id}/` | GET | Detail |
| `/api/v1/partners/programmes/` | GET, POST | Programme catalogue |

## Key entities

- `Programme` (defined in `apps/partners`, consolidated per ADR-0015)
- `Referral`
- `ReferralStatus`

## ADRs

- [ADR-0014](../appendices/adrs.md) — Programme registration data model
- [ADR-0015](../appendices/adrs.md) — Consolidate referral programme into partners module

## Stories

US-037, US-038, US-039, US-040.
