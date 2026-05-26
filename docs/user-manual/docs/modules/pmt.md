# PMT — Proxy Means Test

!!! info "Status"
    **Built and in use** — engine, feature evaluator, sign-off workflow, band threshold, v1 active seed, recompute on commit. Calibrated weights pending DEP-03 / DEP-04.

PMT scores every household for eligibility. Runs **only in the registry**, never in DIH. Triggers immediately after promotion or a committed UPD.

## What it does

Reads the household and its detail entities. Evaluates the registered feature set. Computes a continuous score, then maps the score to a band. Writes the band to the Household and queues notifications to downstream consumers (REF, RPT).

## Where it lives

| Path | What |
|---|---|
| `apps/pmt/` | Django app |
| `/api/v1/pmt/` | DRF surface |
| `/design/v0.1/screens/screens-pmt-dashboard.jsx`, `screens-pmt-configuration.jsx` | PMT dashboards and config |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/pmt/scores/{household_id}/` | GET | Latest score and band |
| `/api/v1/pmt/configurations/` | GET, POST | PMT model versions |
| `/api/v1/pmt/configurations/{id}/sign-off/` | POST | DPO sign-off for a model |

## Key entities

- `PmtScore` — historical chain of scores per household
- `PmtConfiguration` — versioned model weights and thresholds
- Feature registry under `apps/pmt/registered_features.py`

## Trigger surface

| Trigger | Source |
|---|---|
| Promotion | DIH commits a new Household |
| Change | UPD commits a ChangeRequest |
| Vital event | NIRA delivers a member change |
| Periodic recompute | Celery beat (per SLA in SAD §6) |

## ADRs

- [ADR-0020](../appendices/adrs.md) — FIES / FCS computed columns (feeds PMT features)

## Stories

US-022, US-023, US-024, US-025, US-026.
