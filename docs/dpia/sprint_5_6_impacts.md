# DPIA — Sprint 5 + 6 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 5 + Sprint 6
(2026-05-15).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalment**: `/docs/dpia/sprint_2_3_impacts.md`
(catalogues Sprints 2, 3, and 4).

This document satisfies **Definition of Done #6** (CLAUDE.md): every
story that touches personal data records DPIA impact. The format
matches the previous instalment.

---

## Sprint 5 stories

### US-S5-001 — UPD ChangeRequest admin workbench

- **New processing activity**: /admin/update_workflow/changerequest/
  gains an SLA-breach badge and a bulk reject action.
- **Personal-data categories**: meta-only on the admin surface — the
  workbench shows fields already visible in the REST API.
- **Lawful basis**: Public task (supervisor oversight).
- **Data minimisation**: Admin bulk action delegates to
  services.reject_change_request — same audit emission, same
  no-self-approve guard. No new fields exposed.
- **Residual risk**: None new; admin access is staff-only.

### US-S5-002 — API-DRS export-bundle rendering

- **New processing activity**: render_bundle() generates an NDJSON
  bundle containing Household rows filtered by the parent DSA's
  allowed_scopes. prepare_and_deliver() hashes + persists to the
  bundle store + locks the manifest at the DataRequest row.
- **Personal-data categories**: All Household fields the DSA grants —
  identification (id, sub_region_code), demographic (urban_rural,
  current_vulnerability_band, current_pmt_score). NIN columns excluded
  by default; surface only on Member with explicit grant (S6-002).
- **Lawful basis**: Public task + the partner's signed DSA.
- **Data minimisation**: `allowed_scopes.fields` is the single point
  of truth — a request outside scope is REJECTED at submit, never
  silently truncated. NDJSON chosen over CSV so nested types preserve
  their shape (no flattening loses partner-side semantics).
  Content-addressable bundle store ensures identical bundles dedupe
  to one byte stream.
- **Residual risk**: Bundle bytes persist beyond delivery (TTL =
  30d). If a partner endpoint is compromised, the signed manifest
  detects tampering but not re-distribution. **DPO action**: confirm
  TTL is acceptable; consider sub-day for high-risk DSAs.

### US-S5-003 — DDUP merge REVERSED state machine

- **New processing activity**: reverse_merge_decision() un-merges a
  MergeDecision within the 30-day window. Loser member is restored
  (is_deleted=False, deleted_at=None, merged_into=None), surviving's
  overrides rolled back from pre_merge_snapshot, household head
  pointers restored, pair flipped back to PENDING.
- **Personal-data categories**: All Member fields. The pre_merge_
  snapshot captures the surviving member's overridden field values
  so reverse can restore — this is a NEW persistent store of "what
  the row was before merge."
- **Lawful basis**: Public task + DPPA accountability — every
  un-merge needs a defensible reason (the service requires non-empty
  reason).
- **Data minimisation**: pre_merge_snapshot stores ONLY the
  overridden fields (not the full row). Reversal is locked to a
  30-day window per SAD §4.3.2 — beyond that, the snapshot remains
  but can no longer drive an un-merge.
- **Residual risk**: A snapshot of personal data persists for 30
  days alongside the live row. Audit chain emits action=unmerge with
  field_changes showing what was restored. **DPO action**: confirm
  the 30-day window is the right balance between operational
  flexibility and data-minimisation principle.

### US-S5-004 — DIH WFP SCOPE connector

- See combined notes with S3-005/S4-002 in the previous DPIA
  instalment. WFP SCOPE additionally drops `inactive` beneficiaries
  during canonical mapping — they never reach the registry — and
  preserves local-language names in `_source_keys._local_name` for
  audit lineage (not in the Household/Member columns).
- **Lawful basis**: Public task + the (placeholder) signed DPA with
  WFP Uganda.
- **Residual risk**: The placeholder DPA-WFP-SCOPE-1 must be
  replaced with a signed agreement before the connector is enabled
  in prod. **DPO action**: same as PDM/NUSAF — validate signed DPA
  before is_active=True.

### US-S5-005 — IDV NIRA queue-and-retry

- **New processing activity**: NiraVerificationAttempt table
  persists every queued NIRA verification request. drain_queue()
  retries on exponential backoff (60s, 5min, 1h, 24h, max 5
  attempts).
- **Personal-data categories**: NIN-derived — only the SHA-256 hash
  is persisted (nin_hash). The raw NIN is supplied to the queue
  function at call time, hashed before persistence, and never
  written to any column. last_error captures the NIRA error message
  but a tracking test verifies the raw NIN never lands there.
- **Lawful basis**: Public task. The NIRA verification step itself
  is consent-based (Section 8 DPPA 2019) — the head of household
  consented at enumeration; the queue is just a retry mechanism for
  the same call.
- **Data minimisation**: nin_hash only; result_payload (demographics
  from a successful match) lands on success but contains ONLY what
  NIRA returns. Member.nin_value (encrypted at rest) is the
  resolver's source for retry, accessed through the
  EncryptedBinaryField decryption seam.
- **Residual risk**: Resolver path decrypts Member.nin_value to pass
  to NIRA on retry. Access to the resolver is via management command
  or Celery task only (no API surface). When a member is merged
  + soft-deleted after the original queue, the resolver returns None
  and the attempt is marked FAILED so it doesn't cycle forever.

### US-S5-006 — API-DRS expiry sweep

- **New processing activity**: expire_data_requests management
  command (later turned into a Celery task in S6-004) flips
  DELIVERED DataRequests past expires_at to EXPIRED.
- **Personal-data categories**: meta-only — sweeping the status
  column on the DataRequest row, not the bundle bytes.
- **Lawful basis**: Public task + DPPA storage limitation principle.
- **Data minimisation**: The bundle bytes themselves are not deleted
  by this sweep — only the request is marked EXPIRED. **DPO action**:
  define whether expired bundles should be purged from the store
  too; SAD §8.5 doesn't yet specify.
- **Residual risk**: An EXPIRED row still carries the manifest_sha256
  pointing to the bundle store; if a partner re-presents an old
  manifest URL after expiry, the bundle still resolves. **DPO
  action**: define the bundle purge policy.

---

## Sprint 6 stories

### US-S6-001 — DDUP reverse-merge admin + API surface

- **New processing activity**: REST and admin UI exposed for the
  reverse_merge_decision() service that S5-003 shipped.
- **Personal-data categories**: meta-only on the new surface —
  exactly the data S5-003 covered.
- **Lawful basis**: Public task.
- **Residual risk**: None new; the underlying processing was
  already documented and gated.

### US-S6-002 — DRS bundle embeds household members

- **New processing activity**: render_bundle() now embeds a
  `members` array per household row when the DSA either grants
  `member.*` explicitly or is unrestricted.
- **Personal-data categories**: All Member fields the DSA grants:
  identification (id, line_number, surname, first_name, other_name),
  demographic (sex, date_of_birth, age_years), contact (telephone_1,
  telephone_2), family (relationship_to_head), and the NIN trio
  pieces (nin_hash, nin_last4). The raw NIN value is never in the
  bundle.
- **Lawful basis**: Public task + the partner's DSA `member.*`
  grant.
- **Data minimisation**: Per-member field filtering is the same
  strict whitelist as household.* — a member.nin_hash request
  outside the DSA's `fields` list fails at submit. Soft-deleted
  members (post-merge losers, post-vital-event removals) are
  filtered out of every bundle. nin_hash exposed as 64-char hex
  (JSON-safe); the raw bytes never serialise.
- **Residual risk**: A DSA that grants `member.nin_hash` exposes a
  joinable identifier — even though it's a one-way hash, a partner
  with the same hash function (or a list of known NINs) could match
  rows. **DPO action**: review every DSA that whitelists
  member.nin_hash before activation.

### US-S6-003 — DRS bundle MinIO seam

- **New processing activity**: Bundle persistence layer abstracted
  behind a BundleStorage Protocol. Today the in-process dict
  backend stores bundle bytes in process memory; MinIO backend
  placeholder lands when DRS-O-02 closes.
- **Personal-data categories**: Same bundle bytes — the seam
  doesn't change what is stored, just where.
- **Lawful basis**: Public task.
- **Data minimisation**: Content-addressable storage — identical
  bundle bytes hash to the same key, so re-puts are deduped. No new
  data category surfaces.
- **Residual risk**: MinIO at NITA-U is the eventual store; bucket
  ACLs, encryption-at-rest, and signed-URL TTL need DPO sign-off
  before DRS-O-02 closes. **DPO action**: review MinIO bucket policy
  draft when wiring lands.

### US-S6-004 — Celery beat wiring

- **New processing activity**: Beat schedule replaces the two cron-
  driven management commands from S5-005/S5-006. Same sweeps, same
  audit emission — only the scheduler changes.
- **Personal-data categories**: None new (sweep targets were
  already documented under their source stories).
- **Lawful basis**: Public task.
- **Data minimisation**: The Celery result backend, if a persistent
  one is configured, will retain task return values (counts dicts).
  Counts dicts do NOT contain personal data — only aggregate
  numbers ({succeeded: 1, requeued: 0, ...}).
- **Residual risk**: When CELERY_BROKER_URL points at a Redis
  instance shared with other apps, task payloads transit through it.
  Both task functions take ONLY actor strings as arguments (no
  personal data in the payload).

### US-S6-005 — RPT promotion-latency dashboard

- **New processing activity**: New aggregate read endpoint at
  /api/v1/rpt/dashboards/promotion-latency-by-connector/.
- **Personal-data categories**: None — the aggregate reports counts
  per (connector, latency bucket). No row-level data leaves the
  aggregation.
- **Lawful basis**: Public task (ops oversight).
- **Data minimisation**: Same scope-before-aggregate pattern as the
  six existing RPT dashboards. Pre-promotion stages are invisible to
  sub-region operators by definition (no household_id yet to scope
  through). Counts on individual buckets could still be small in a
  small connector run.
- **Residual risk**: Same small-cell concern as the existing RPT
  dashboards — covered by the open DPO action on small-cell
  suppression thresholds.

### US-S6-006 — DPIA Sprint 4+5 follow-up

- This document. No processing changes; documentation of prior
  stories.

---

## DPO action summary (delta from sprint_2_3_impacts.md)

| Action | Owner | Tied to |
|---|---|---|
| Confirm 30-day un-merge window is acceptable | DPO | US-S5-003 |
| Define DRS bundle TTL — confirm 30d default or set per-DSA | DPO | US-S5-002 |
| Define expired-bundle purge policy (drop bytes from store?) | DPO | US-S5-006 |
| Review DSAs that whitelist `member.nin_hash` before activation | DPO | US-S6-002 |
| Review MinIO bucket policy draft when DRS-O-02 lands | DPO | US-S6-003 |

Plus the eight actions still outstanding from
sprint_2_3_impacts.md.

---

## Next review

Sprint 7 close — the next batch of stories will likely touch the
first wiring of the React console (UI Design Brief §4), additional
DIH connectors (NIRA reverse-feed for vital events), and the
beginnings of the Keycloak realm wiring (US-S2-002 unblock). Each of
those will add to the action list above.
