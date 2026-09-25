# REF — Referral

!!! info "Status"
    **Built and in use** — programme referral pull, creation, programme MIS notify path, PDM and NUSAF connectors.

REF pushes eligible households to programme MIS systems. The complement to inbound DIH connectors.

## What it does

Listens for PMT recompute events. Matches the household against active Programme definitions. Creates referral records. Pushes notifications to the programme MIS via per-programme connectors.


## The referral number

Every referral carries two identifiers, for different readers.

| | Example | For |
|---|---|---|
| **Reference** | `REF-2026-0001` | people — say it, write it, quote it |
| **Id** | `01M3AT4JSSXFYG02CXC8S6K20X` | the system — URLs, the audit chain, links from other modules |

A programme officer quotes it back when asking what happened to a household.

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
- Referral `status` is a plain `CharField` resolved against the
  `referral_status` ChoiceList. The `ReferralStatus` TextChoices class
  this page listed **was removed** by ADR-0015 / US-S26-003.

## ADRs

- [ADR-0014](../appendices/adrs.md) — Programme registration data model
- [ADR-0015](../appendices/adrs.md) — Consolidate referral programme into partners module

## Stories

US-037, US-038, US-039, US-040.
