# DPIA impact note — UBOS bulk and NIRA reverse-feed connectors (US-114 restore)

- **Date**: 2026-09-10
- **Stories**: US-114 (UBOS bulk connector), US-096 / US-S7-002 (NIRA vital events), US-S11-003 (credential admin pattern)
- **Modules**: DIH (ING), UPD, SEC
- **Status**: draft for DPO review

## What changed

Two source kinds that were disabled ("coming soon") in the DIH credential admin and the console *Run connector* modal are now live:

1. **UBOS bulk** — a file-drop connector reads UBOS mass-enumeration export files (`.json` / `.jsonl` / `.csv`) from a directory on the DIH host, verifies a `.sha256` sidecar before landing, and stages households through the normal DQA → IDV → DDUP → NSR Unit queue.
2. **NIRA reverse feed** — a new inbound webhook `POST /api/v1/dih/nira/vital-events/` receives NIRA births / deaths, authenticated with an HMAC-SHA256 signature over the raw body. Deaths auto-commit a `VITAL_EVENT` change request through UPD (existing S3-003 path with the 1% human-audit sample); births and unknown NINs are landed and quarantined.

## Personal data touched

| Flow | Data | Basis | Storage |
|---|---|---|---|
| UBOS file rows | Full household + member records (names, sex, DOB, NIN where present, GPS, dwelling, food security…) | DPA-UBOS-BULK (baseline row seeded; replace before the real load — DRS-O-01) | `RawLanding.payload` (immutable, JSON), `StageRecord.canonical_payload`; NIN encrypted only once promoted to `Member` |
| UBOS drop directory | The same rows, at rest as files on the DIH host | Same | Outside the database — see risks |
| NIRA events | NIN, event type, event date, registration reference; births carry surname / first name / sex / DOB | DPA-NIRA-REVERSE (baseline seeded; the MoU replaces it — NIRA-O-01) | `RawLanding.payload`; `Quarantine.payload` for unroutable events |
| NIRA secret | Shared signing secret (not personal data) | — | `NiraCredential.webhook_secret_encrypted` (Fernet today, KMS per NSR-O-04) |

## New processing and risks

- **Plaintext NIN in the raw landing.** NIRA payloads and UBOS rows are landed verbatim (AC-DIH-LANDING-IMMUTABLE), so `RawLanding.payload` holds plaintext NINs until the retention job (SAD §4.6.8) clears them. This was already true for Kobo; the NIRA feed makes it a per-event, high-frequency flow. **Mitigation**: retention job scope confirmed to cover NIRA landings; access to `RawLanding` admin is System Admin only and audited.
- **Files at rest outside the database.** The UBOS drop directory is host filesystem, not MinIO with object-level encryption. **Mitigation for the historic load**: directory owned by the app user with `0700`, populated only for the duration of the load, wiped after promotion; SFTP transport (still open in US-114) removes the manual copy step. **Open for DPO**: whether the interim file drop is acceptable for the one-off load or must wait for the SFTP + MinIO path.
- **Unauthenticated network surface.** The NIRA webhook has no session; the signature is the only gate. Rejections are audited (`dih.nira.signature_rejected`) with the caller's IP. **Mitigation**: the secret is write-only in the admin and rotated on both sides; the route should be reachable only from NIRA's address range at the gateway (Kong allowlist — runbook item).
- **Automated status change on a person.** A signed death event flips `Member.residency_status` to `deceased` without human review. This is the existing AC-UPD-NIRA-AUTO behaviour, now reachable from outside. **Mitigation**: the 1% audit sample and the GRM dispute path (US-096) are unchanged; a replay cannot double-apply (idempotency on `event_id`).
- **Quarantine as a holding pen.** Birth events sit in `Quarantine.payload` with an infant's identity until NIRA-O-01 closes. **Mitigation**: quarantine retention follows the DPA residence policy (90 days for NIRA); DPO to confirm.

## Audit

New events: `dih.nira.event_received`, `dih.nira.event_duplicate`, `dih.nira.event_quarantined`, `dih.nira.event_failed`, `dih.nira.event_refused`, `dih.nira.signature_rejected`. UBOS pulls reuse `dih.connector.triggered` / `trigger_succeeded` / `trigger_rejected` and the per-run `create connector_run` event.

## Sign-off

- DPO: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
