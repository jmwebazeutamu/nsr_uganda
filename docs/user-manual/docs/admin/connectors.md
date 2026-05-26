# DIH connectors

!!! info "Status"
    **Built and in use** — 8 connector classes shipped (UBOS bulk, CAPI walk-in, Web on-demand, Kobo, PDM, NUSAF, WFP-SCOPE, NIRA-Vital). Connector credential management UI is **Partial**.

Every record entering the registry passes through the **Data Integration Hub (DIH)**. This page tells you how to configure and run a connector.

## Architecture in one paragraph

A **SourceSystem** is a partner data source. A **DataProvisionAgreement (DPA)** is the inbound legal contract. A **Connector** is the Python class that pulls data. A **ConnectorRun** is one execution. Each row of data lands in **RawRecord**, then through **MappingRule** application, then through **DQA** + **DDUP**, then through the **promotion API** into `data_management.Household` and `data_management.Member`.

See [DIH module reference](../modules/dih.md) for the full data model.

## The 8 connectors

| Class | SourceSystemKind | Status | What it does |
|---|---|---|---|
| `ubos.UbosBulkConnector` | `ubos` | Built | One-off historic load from the UBOS census workbook |
| `capi_walkin` | `capi_walkin` | Built | CAPI tablet sync from offline-captured households |
| Web on-demand | `web` | Built | Web intake form posts straight to DIH |
| `kobo.KoboConnector` | `kobo` | Built | Pulls Kobo Toolbox submissions for pilot and testing |
| `pdm.PdmConnector` | `pdm` | Built | Pulls Parish Development Model beneficiaries |
| `nusaf.NusafConnector` | `nusaf` | Built | Pulls NUSAF caseload |
| `wfp_scope.WfpScopeConnector` | `wfp_scope` | Built | Pulls WFP SCOPE beneficiary registry |
| `nira_vital.NiraVitalConnector` | `nira_vital` | Built | Receives NIRA births and deaths for auto-commit (US-S3-003) |

All connectors live under `apps/ingestion_hub/connectors/`. Each has a paired `test_<name>.py` that mocks outbound `requests` calls via the `responses` library.

## Adding a new source system

Step-by-step:

1. **Sign the DPA.** Without an active DPA the connector run will fail `AC-DIH-DPA-REQUIRED`.
2. **Register the SourceSystem** in the Django admin or via `seed_dih_sources.py`. Set `kind`, `code`, `name`, `residence_days`.
3. **Set credentials.** Use the credentials admin UI at `/admin/ingestion_hub/sourcecredential/`. Secrets are stored encrypted (Fernet).
4. **Add a Connector class** if the source uses a new protocol. Subclass `connectors.base.BaseConnector`. Implement `pull()` returning an iterable of raw dicts.
5. **Add MappingRules.** One per source field to canonical model field. Visible in the admin at `/admin/ingestion_hub/mappingrule/`.
6. **Run a test pull.** `python manage.py shell -c "from apps.ingestion_hub.tasks import run_connector; run_connector('<source_code>', dry_run=True)"`.
7. **Promote to production.** Schedule the Celery task in the admin (interval or crontab).

## Connector run lifecycle

| Status | Meaning |
|---|---|
| `queued` | Scheduled by Celery but not started |
| `running` | Currently pulling |
| `mapping` | Raw → canonical via MappingRule |
| `validating` | DQA evaluation |
| `dedup` | DDUP matcher |
| `pending_review` | Awaiting steward decision (DIH review queue) |
| `promoted` | Committed to DAT |
| `quarantined` | Blocking DQA failure or rejected by steward |
| `failed` | Connector raised before promotion |

Live counts poll every 5 seconds while a run is `running` (see [ConnectorRun dashboard](../steward/dih-review-queue.md)).

## Fast-track auto-promote

CAPI walk-ins from Parish Chiefs go through the **fast-track auto-promote** path (US-S1-004, US-111). Records with zero blocking failures and zero DDUP candidates are promoted automatically, with 1% sampling for steward review. This avoids manual friction for the high-volume parish channel while preserving audit and rollback.

The 1% sample is deterministic by `submission_id` so the same record is reproducibly sampled.

## Connector credentials

The credentials admin lets you set per-source secrets without redeploying. Stored encrypted at rest with the same `NSR_DATA_KEY` Fernet key.

| Credential type | Example |
|---|---|
| API key | Kobo, PDM, NUSAF |
| OAuth client credentials | WFP-SCOPE |
| Service account JWT | NIRA-Vital |
| Basic auth | UBOS bulk (testing only) |

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `AC-DIH-DPA-REQUIRED` | No active DPA on the source | Create or renew the DPA |
| `MappingRule missing for field X` | New source field with no mapping | Add a MappingRule in the admin |
| Connector run hangs in `pending_review` | DDUP found candidates ≥ 0.80 | Resolve in the DIH review queue |
| 401 on Kobo pull | Kobo API key rotated | Update SourceCredential |

## Related

- [DIH module reference](../modules/dih.md)
- [DIH review queue (steward)](../steward/dih-review-queue.md)
- ADR-0007 — Connector plugin pattern
- `apps/ingestion_hub/connectors/`
