# DIH connectors

!!! info "Status"
    **Live (credentialed, runnable)**: Kobo, UBOS bulk (file drop), NIRA reverse-feed (inbound webhook). **Canonicalise-only, no credential form yet ("coming soon")**: PDM, NUSAF, WFP SCOPE. CAPI walk-in and Web on-demand are internal channels, not connectors. Updated 2026-09-10 (US-114 restore).

Every record entering the registry passes through the **Data Integration Hub (DIH)**. This page tells you how to configure and run a connector.

## Architecture in one paragraph

A **SourceSystem** is a partner data source. A **DataProvisionAgreement (DPA)** is the inbound legal contract. A **Connector** is the Python class that pulls data. A **ConnectorRun** is one execution. Each row of data lands in **RawRecord**, then through **MappingRule** application, then through **DQA** + **DDUP**, then through the **promotion API** into `data_management.Household` and `data_management.Member`.

See [DIH module reference](../modules/dih.md) for the full data model.

## The connectors

| Module (`apps/ingestion_hub/connectors/`) | Registered code | `SourceSystemKind` | Credential row | Status | What it does |
|---|---|---|---|---|---|
| `kobo.py` | `KOBO-PILOT` | `kobo` | `KoboCredential` | Live — pull | Pulls Kobo Toolbox submissions for pilots and testing |
| `ubos.py` | `UBOS-BULK` | `ubos` | `UbosCredential` | Live — pull (file drop) | One-off historic load: reads UBOS export files from a drop directory, checksum-gated (US-114 first cut; SFTP pending) |
| `nira_vital.py` | `NIRA-REVERSE` | `nira` | `NiraCredential` | Live — inbound | Receives NIRA births / deaths on `/api/v1/dih/nira/vital-events/`; deaths auto-commit through UPD (US-096) |
| `pdm.py` | `PDM-MIS` | `partner_mis` | — | Canonicalise only | Maps PDM beneficiary payloads; no pull / credential form yet |
| `nusaf.py` | `NUSAF-MIS` | `partner_mis` | — | Canonicalise only | Maps NUSAF caseload payloads; no pull / credential form yet |
| `wfp_scope.py` | `WFP-SCOPE` | `wfp_scope` | — | Canonicalise only | Maps WFP SCOPE payloads; no pull / credential form yet |

CAPI walk-in (`capi_walkin`) and Web on-demand (`web`) are **channels**, not connector modules: they post canonical households straight to `/api/v1/dih/walk-in-submissions/`.

Each module has a paired `test_<name>.py`. The Kobo tests mock outbound `requests` via `responses`; the UBOS tests build a temporary drop directory; the NIRA webhook tests sign requests with the test secret.

### UBOS bulk — file drop

1. Save the `UBOS-BULK` source (seeded) and open it in the admin. The **UBOS bulk drop** inline asks for `drop_path` (absolute directory on the DIH host) and `require_checksum` (default on).
2. Place the export files there: `.json` (array of households), `.jsonl` (one per line) or `.csv` (dotted headers such as `geographic.district`, `members` as a JSON string). Each file needs a sibling `<file>.sha256` (`sha256sum` output is fine).
3. **Test connection** confirms the directory is readable and how many files are waiting.
4. **Run connector** in the console lists the files; only files that pass the checksum gate are selectable. Rows are landed with a `<sha256>#<row>` reference, so re-running the same file skips rows already landed, while a corrected re-export lands as new rows.
5. Rows must already be in the canonical household shape (`geographic`, `members`, …). The UBOS-native column mapping (MappingRule v1 in US-114) is still open until UBOS supplies the export dictionary. Malformed rows are quarantined, never staged half-way.

Still open from US-114: SFTP transport, the 50,000-row batch job, the two-person rule for batches over 10,000, and the per-sub-region final report.

### NIRA reverse feed — inbound webhook

1. Save the `NIRA-REVERSE` source (seeded, kind `nira`). The **NIRA webhook secret** inline takes the shared HMAC secret agreed with NIRA (write-only; stored encrypted).
2. **Test connection** checks the secret is set and probes the NIRA verification channel through the IDV provider seam. It reports `nira:mock` until `NIRA_PROVIDER=live` is wired (NIRA-O-01).
3. NIRA posts one event per request to `POST /api/v1/dih/nira/vital-events/` with `X-NIRA-Signature: sha256=<HMAC-SHA256 of the raw body>`. Deaths auto-commit a `VITAL_EVENT` change request (1% sampled for human audit); births and unknown NINs are landed and quarantined for the NSR Unit. Replays of the same `event_id` / `registration_ref` answer `duplicate`.
4. There is nothing to pull: the source shows in the console modal as "inbound feed — no manual pull".

## Adding a new source system

Step-by-step:

1. **Sign the DPA.** Without an active DPA the connector run will fail `AC-DIH-DPA-REQUIRED`.
2. **Register the SourceSystem** in the Django admin or via `seed_dih_sources.py`. Set `kind`, `code`, `name`, `residence_days`.
3. **Set credentials.** Use the credentials admin UI at `/admin/ingestion_hub/sourcecredential/`. Secrets are stored encrypted (Fernet).
4. **Add a Connector class** if the source uses a new protocol. Subclass `connectors.base.BaseConnector`. Implement `pull()` returning an iterable of raw dicts.
5. **Add MappingRules.** One per source field to canonical model field. Visible in the admin at `/admin/ingestion_hub/mappingrule/`.
6. **Run a test pull.** From the **System Admin > Connector runs** tab in the console, click **Run connector**, pick the source, tick **Dry run**, hit **Run dry-run**. The endpoint exercises credentials + form discovery without writing `RawLanding` rows. See [Run connector button](#run-connector-button) below.
7. **Promote to production.** Untick **Dry run** on the same modal for a one-shot manual pull, or schedule the Celery beat task in the admin (interval or crontab) for recurring imports.

## Run connector button {#run-connector-button}

**Path**: `/console/` → System Admin → Connector runs tab → **Run connector** (top-right of the toolbar).

**Permissions**: System Admin (`nsr_admin` group) and NSR Unit Coordinator (`nsr_unit_coordinator` group). Operators in any other group get a 403. Superusers always pass.

The modal:

- **Source system** dropdown — every registered SourceSystem appears. Kobo and UBOS bulk entries are selectable; NIRA shows as `(inbound feed — no manual pull)`; the rest carry a `(coming soon)` suffix and are disabled until their per-kind credential form lands (PDM, NUSAF, WFP SCOPE).
- **Dry run** checkbox — when ticked, the run opens as `run_type=TEST`, lists forms, iterates submissions for a count, but writes **no** `RawLanding`. Use this for first-time credentials, mapping-rule verification, or after a Kobo token rotation. When unticked, submissions are landed and immediately driven through canonicalize → DQA → IDV → DDUP, exactly as the scheduled Celery beat does.

**Backend wiring**: the button posts to `POST /api/v1/dih/source-systems/{id}/trigger-run/`. The same code path the admin action uses (`pull_kobo_submissions_action`) executes, so console and admin behaviour stay in lock-step.

**Guards** (any of these returns 400 with a `detail` toast):

- Source kind is not pull-capable (Kobo or UBOS bulk).
- UBOS: the chosen file fails the checksum gate.
- Another run is already `pending` or `running` for the source.
- No active DPA covers the source (`AC-DIH-DPA-REQUIRED`).
- No `*Credential` row exists for the source.
- `list_forms` finds zero deployed forms upstream.

**Audit**: every click emits `dih.connector.triggered`. The outcome adds `dih.connector.trigger_succeeded` (with the run note in `reason`) or `dih.connector.trigger_rejected` (with the failure reason). Both are visible in `/admin/security/auditevent/`.

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

| Credential row | Source kind | Holds |
|---|---|---|
| `KoboCredential` | `kobo` | Knox API token (encrypted), server URL |
| `UbosCredential` | `ubos` | Drop directory path, checksum policy (no secret until SFTP lands) |
| `NiraCredential` | `nira` | Webhook signing secret (encrypted, write-only) |

PDM, NUSAF and WFP SCOPE have no credential row yet — their kinds are disabled in the admin dropdown.

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `AC-DIH-DPA-REQUIRED` | No active DPA on the source | Create or renew the DPA |
| `MappingRule missing for field X` | New source field with no mapping | Add a MappingRule in the admin |
| Connector run hangs in `pending_review` | DDUP found candidates ≥ 0.80 | Resolve in the DIH review queue |
| 401 on Kobo pull | Kobo API key rotated | Update the Kobo credential |
| `checksum mismatch — refusing to land` | UBOS file changed after its `.sha256` was written | Regenerate the sidecar (`sha256sum file > file.sha256`) |
| NIRA push answers 401 | Secret mismatch between NIRA and `NiraCredential` | Rotate the secret on both sides; every rejection is audited as `dih.nira.signature_rejected` |
| NIRA push answers 503 | `NIRA-REVERSE` source, credential or DPA missing | Run `scripts/seed_dih_sources.py`, save the secret, check the DPA dates |

## Related

- [DIH module reference](../modules/dih.md)
- [DIH review queue (steward)](../steward/dih-review-queue.md)
- ADR-0007 — Connector plugin pattern
- `apps/ingestion_hub/connectors/`
