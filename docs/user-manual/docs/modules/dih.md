# DIH — Data Integration Hub

!!! info "Status"
    **Built and in use** — SourceSystem + DPA, MappingRule, ConnectorRun + counts, pipeline orchestrator, fast-track auto-promote with 1% sampling. 8 connector classes shipped.

DIH is the front door for every record that enters the Registry. Direct writes to DAT are not allowed. The fast-track auto-promote handles parish walk-in friction without breaking the rule.

## What it does

Pulls records from partner sources via Connectors. Lands raw payloads. Applies MappingRules. Calls DQA. Calls DDUP. Routes to the steward review queue when needed. Promotes to DAT via the promotion API. Surfaces ConnectorRun status and counts.

## Where it lives

| Path | What |
|---|---|
| `apps/ingestion_hub/` | Django app |
| `apps/ingestion_hub/connectors/` | One Python class per source kind |
| `/api/v1/dih/` | DRF surface |
| `/design/v0.1/screens/screens-dih.jsx` | Review queue + ConnectorRun dashboard |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/dih/source-systems/` | GET, POST | List, create |
| `/api/v1/dih/connectors/` | GET, POST | Connector catalogue |
| `/api/v1/dih/runs/` | GET | ConnectorRun list with live counts |
| `/api/v1/dih/runs/{id}/` | GET | Run detail with log tail |
| `/api/v1/dih/staged-records/` | GET | Review queue |
| `/api/v1/dih/staged-records/{id}/promote/` | POST | Steward promotes |
| `/api/v1/dih/staged-records/{id}/reject/` | POST | Steward rejects |

## Key entities

| Entity | What |
|---|---|
| `SourceSystem` | A partner source |
| `DataProvisionAgreement` | The inbound legal contract |
| `Connector` | Bound to one SourceSystem |
| `ConnectorRun` | One execution |
| `RawRecord` | Inbound payload, pre-mapping |
| `MappingRule` | Source-field → canonical-field |
| `StagedRecord` | Mapped + validated + dedup'd, awaiting promotion or rejection |
| `SourceCredential` | Encrypted at rest via the `NSR_DATA_KEY` Fernet key |

## Connectors

| Source kind | Module | Status |
|---|---|---|
| `ubos` | `ubos.UbosBulkConnector` | Live — file-drop pull, checksum-gated (US-114 first cut) |
| `capi_walkin` | (channel — walk-in endpoint) | Built |
| `web` | (channel — walk-in endpoint) | Built |
| `kobo` | `kobo.KoboConnector` | Live — API pull |
| `nira` | `nira_vital._NiraVitalConnector` | Live — inbound webhook `/api/v1/dih/nira/vital-events/` |
| `partner_mis` (PDM, NUSAF) | `pdm.py`, `nusaf.py` | Canonicalise only — no credential form ("coming soon") |
| `wfp_scope` | `wfp_scope.py` | Canonicalise only — no credential form ("coming soon") |

## ADRs

- [ADR-0007](../appendices/adrs.md) — Connector plugin pattern

## Stories

US-105, US-106, US-107, US-108, US-109, US-110, US-111, US-112, US-113, US-114, US-115.
