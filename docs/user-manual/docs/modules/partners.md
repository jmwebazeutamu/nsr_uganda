# Partners and DSA

!!! info "Status"
    **Built and in use** — Partner + DSA models, scope, scope edit, renewal, DocuSign signature seam (default off), programme lifecycle, dashboards.

Partners and DSA are the outbound counterpart to the inbound DIH SourceSystem + DPA. One canonical Partner model serves both DRS consumers and Programme MIS systems ([ADR-0013](../appendices/adrs.md), [ADR-0015](../appendices/adrs.md)).

## What it does

Maintains the Partner catalogue. Maintains DSAs per partner with full scope (fields, geographies, programmes, sensitivity, expiry). Routes DSA signature through DocuSign (or the in-memory stub by default). Maintains Programme definitions and lifecycle ([ADR-0014](../appendices/adrs.md)). Surfaces partner dashboards.

## Where it lives

| Path | What |
|---|---|
| `apps/partners/` | Django app |
| `apps/partners/services/scope.py`, `signature.py`, `programme_lifecycle.py`, `activity.py` | Service layer |
| `apps/partners/integrations/docusign.py` | DocuSign client (gated by flag) |
| `/api/v1/partners/` | DRF surface |
| `/design/v0.1/screens/screens-partners.jsx`, `screens-partner-detail.jsx`, `screens-dsas.jsx`, `screens-programmes.jsx`, `screens-programme-detail.jsx`, `screens-programme-new.jsx` | Admin Console UIs |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/partners/` | GET, POST | Partner catalogue |
| `/api/v1/partners/{id}/` | GET, PATCH | Detail |
| `/api/v1/partners/dsas/` | GET, POST | DSA list and create |
| `/api/v1/partners/dsas/{id}/` | GET, PATCH | DSA detail |
| `/api/v1/partners/dsas/{id}/scope-edit/` | POST | Edit scope (narrow immediate, widen needs countersign) |
| `/api/v1/partners/dsas/{id}/renew/` | POST | Renewal flow |
| `/api/v1/partners/dsas/{id}/signature/` | POST | Trigger signature |
| `/api/v1/partners/dashboards/` | GET | Aggregates |
| `/api/v1/partners/programmes/` | GET, POST | Programme catalogue |

## Key entities

- `Partner`
- `DataSharingAgreement` (DSA)
- `Programme`
- `ProgrammeLifecycleEvent`

## Feature flags

| Flag | Default |
|---|---|
| `PARTNERS_MODULE_ENABLED` | True |
| `PARTNERS_DOCUSIGN_ENABLED` | False (in-memory stub default) |

## ADRs

- [ADR-0011](../appendices/adrs.md) — Partners module
- [ADR-0012](../appendices/adrs.md) — DSA signature workflow
- [ADR-0013](../appendices/adrs.md) — Canonical Partner and DSA models
- [ADR-0014](../appendices/adrs.md) — Programme registration data model
- [ADR-0015](../appendices/adrs.md) — Consolidate referral programme
- [ADR-0016](../appendices/adrs.md) — DSA scope edit and renewal

## Stories

US-S23-008, US-S2-009, US-S3-005, US-S4-002 plus the partners-module epic.
