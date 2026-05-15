# DPIA — Sprint 10+11 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 10 + Sprint 11.
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)
- `/docs/dpia/sprint_8_impacts.md` (Sprint 8)
- `/docs/dpia/sprint_9_impacts.md` (Sprint 9)

This document satisfies **Definition of Done #6** (CLAUDE.md): every
story that touches personal data records DPIA impact.

---

## Sprint 10 stories

### US-S10-001 — Tweaks panel reopen pill

- **New processing activity**: UI-only behaviour change.
- **Personal-data categories**: None.
- **Lawful basis**: Public task.
- **Residual risk**: None new.

### US-S10-002 — DDUP reverse-merge feedback counters

- **New processing activity**: Computed properties on
  `DdupModelVersion` joining MergeDecision rows to surface auto-
  vs manual-merge counts and the auto-reverse rate. No new
  columns; no new data captured.
- **Personal-data categories**: None — purely aggregate counts.
- **Lawful basis**: Public task.
- **Data minimisation**: Counts live behind read-only Django-admin
  fields; no broader REST surface.
- **Residual risk**: Operators with admin access can infer
  "model v2.4 reversed 5 of 17 auto-merges" — useful for
  calibration, never identifying any data subject.

### US-S10-003 — Partner DRS request-builder (third React screen)

- **New processing activity**: Browser-side request composition.
  Calls `/api/v1/drs/requests/builder-schema/` for the
  field-checklist and `/api/v1/drs/requests/` to POST the
  composed payload.
- **Personal-data categories**: meta-only inside the browser
  (fields the partner CAN request — not the rows themselves).
- **Lawful basis**: Public task + DSA scope (`allowed_scopes`).
- **Data minimisation**: Disabled fields render greyed out
  rather than being filtered out — partners see exactly which
  fields lie outside their DSA. The composed payload references
  fields, not actual data.
- **Residual risk**: A partner sees the LIST of unavailable
  fields. Acceptable: knowing a field EXISTS in the registry is
  not the same as accessing it.

### US-S10-004 — UPD bulk-action endpoints

- **New processing activity**: Three new endpoints (`bulk-approve`,
  `bulk-reject`, `bulk-escalate`) at `/api/v1/upd/change-requests/`.
  Each takes a list of ChangeRequest IDs (max 200) and runs the
  per-row service once per id. Each acted row emits its own
  AuditEvent — same shape as the single-row endpoints.
- **Personal-data categories**: Indirectly all of them — the
  ChangeRequests being bulk-acted on contain household + member
  diffs. The new surface is the BATCH abstraction, not new data.
- **Lawful basis**: Public task.
- **Data minimisation**: Per-row guards (AC-UPD-NO-SELF-APPROVE,
  state precondition) skip non-eligible rows rather than aborting
  the batch — skipped rows surface via `{acted, skipped: [{id,
  reason}], not_found}` so the caller can act differently. The
  cap (200) prevents an over-broad operator action.
- **Residual risk**: An operator who can call bulk-approve can,
  in 200-row chunks, walk through their entire scope's pending
  queue. ABAC scope still applies (rows out of scope filter to
  `not_found`); the audit chain captures every action. **New DPO
  action**: define an operations alert for a single operator
  bulk-approving > N rows in K minutes (anomaly signal for
  insider abuse).

### US-S10-005 — DIH ConnectorRun admin enhancements

- **New processing activity**: Admin UI rendering only — a
  status badge, a STUCK overlay, and a bulk "mark stuck FAILED"
  action that flips status without touching record counts.
- **Personal-data categories**: None — ConnectorRun is meta data
  about runs.
- **Residual risk**: None new.

### US-S10-006 — DPIA Sprint 9 follow-up

- Documentation only.

---

## Sprint 11 stories

### US-S11-001 — React admin screen

- **New processing activity**: Read-only summary of installed
  modules + connector kinds, role-gated to `nsr_unit_admin`.
- **Personal-data categories**: None — pure metadata.
- **Lawful basis**: Public task.
- **Residual risk**: None new.

### BUG-S11-002a/b — DRS builder-schema + unify operator/partner

- **New processing activity**: A `builder-schema` GET endpoint
  that returns the catalogue of requestable fields with
  role-aware `disabled` flags; the partner UI now uses the same
  React component the operator uses with `role="partner"`.
- **Personal-data categories**: meta-only.
- **Lawful basis**: Public task + DSA.
- **Data minimisation**: The endpoint reveals which fields EXIST
  but `disabled` accurately reflects the partner's
  `allowed_scopes`; partners can't compose a request for a
  disabled field. The unified UI removes the prior MVP gap where
  partners had a reduced builder.
- **Residual risk**: None new — same as US-S10-003.

### US-S11-003 — Kobo connector + credential admin + ADR-0007

- **New processing activity**: Outbound HTTP to a partner Kobo
  Toolbox instance (default: kobo.humanitarianresponse.info).
  Pulls submissions on demand into RawLanding. Stores upstream
  credentials encrypted at rest. Adds a `test_connection` admin
  action that probes the upstream and writes a
  `ConnectorRun(run_type=TEST)` row + a `test_connection`
  AuditEvent on every attempt.
- **Personal-data categories**:
  - **Upstream payload**: Household and Member personal data from
    the Kobo form. Same categories as native NSR intake.
  - **Operator credentials**: A Kobo Knox token (encrypted) +
    `acquired_by_username` (plaintext, for audit lineage).
    Plaintext password lives only in the request handler's stack
    frame during the token exchange — never persisted.
- **Lawful basis**: Public task + the relevant DPA covering the
  Kobo source (AC-DIH-DPA-REQUIRED already enforced).
- **Data minimisation**:
  - The token is held in an `EncryptedBinaryField` (Fernet today;
    KMS-envelope-encryption per US-S2-004 / NSR-O-04 when KMS is
    provisioned). The same field type used for `Member.nin_value`.
  - The "Test connection" probe is a `GET /api/v2/assets.json?
    limit=1` — read-only and idempotent; doesn't pull any
    submission rows. Per the ADR.
  - DDUP / DQA + DIH promotion gates still run on every pulled
    record (per the framework, no Kobo-specific bypass).
- **Residual risk**:
  - **Memory disclosure of plaintext password.** Between the
    Django form `clean()` and `acquire_token()`, the password
    sits in the Python heap. Mitigations: `PasswordInput(
    render_value=False)` prevents echo-back to the browser;
    nothing logs `cleaned_data`. Residual risk: a heap dump of
    the running process. Accepted as residual until the KMS
    rollout (NSR-O-04) provides a hardware-isolated credential
    flow. **New DPO action**: confirm the residual is acceptable
    for pilot scope.
  - **Token revocation on upstream.** Deleting a KoboCredential
    row does NOT revoke the token at Kobo's end. ADR-0007
    flagged this as open question DIH-O-CONN-02 — needs a
    `DELETE /api/v2/users/{user}/api_token/` call before the
    local row is dropped. **New DPO action**: track to ADR
    closure.
  - **Who can mint credentials.** Today any Django staff user.
    Should be a SEC role `dih_credential_admin` per ADR-0007
    DIH-O-CONN-03 — closes with US-S2-002.

### US-S11-004 — UPD bulk-action UI surface

- **New processing activity**: React UI that consumes the
  S10-004 bulk endpoints. No server change.
- **Personal-data categories**: Indirect — same as S10-004.
- **Data minimisation**: The UI surfaces the per-row guards
  visually (rows where the operator is the submitter get marked
  with a shield icon), so an operator doesn't even attempt a
  guard-skipped bulk action.
- **Residual risk**: The same insider-abuse anomaly signal from
  S10-004 covers this surface.

### US-S11-005 — DDUP threshold tuning admin

- **New processing activity**: `clone_with_threshold_delta`
  service + three Django-admin actions on DdupModelVersion that
  mint a new DRAFT version with a calibrated
  `auto_merge_threshold`. Each calibration emits a `calibrate`
  AuditEvent recording before/after threshold.
- **Personal-data categories**: None — pure config.
- **Lawful basis**: Public task.
- **Data minimisation**: The clone-into-DRAFT flow preserves
  AC-DDUP-MODEL-VERSION dual approval; nothing reaches Member
  rows without a second human approval.
- **Residual risk**: A reduced threshold (more auto-merges)
  raises the false-merge rate, which IS a personal-data event.
  The "TUNE UP" admin badge (S11-005) keeps the calibration
  cycle visible; the auto-reverse rate is the feedback signal.
  **New DPO action**: confirm the 5% policy ceiling
  (AUTO_REVERSE_RATE_CEILING) is acceptable.

### US-S11-006 — DRS bundle integrity verification helper

- **New processing activity**: Browser-side SHA-256 over a
  downloaded bundle file. The Web Crypto API hashes locally; the
  hex digest is compared to the manifest hash returned by the
  API.
- **Personal-data categories**: The file the partner picks IS the
  delivered bundle — Household + Member rows under the active
  DSA. The verification helper processes those rows in the
  partner's browser memory only; nothing is sent anywhere.
- **Lawful basis**: Public task + the partner's DSA (which
  already authorised the download).
- **Data minimisation**: The helper reads the bundle as an
  ArrayBuffer for the SHA-256 input and immediately drops it
  after the digest. No row-level inspection; no other use of
  the bytes.
- **Residual risk**: A malicious browser extension intercepting
  the FileReader buffer. Out of scope for the registry; partner
  operating-environment control. The mismatch callout
  instructs the operator to "report to DPO at once," which is the
  insider-abuse signal the DPO needs.

### US-S11-007 — RPT comparative dashboards

- **New processing activity**: Single new APIView
  `ComparativeMetric` that returns the current-window count + the
  previous-window count for one of four metrics, scoped through
  the same ABAC counters the row-level dashboards use.
- **Personal-data categories**: None — aggregate counts.
- **Lawful basis**: Public task.
- **Data minimisation**: Same scope-before-aggregate pattern.
  Empty-baseline windows surface `delta_pct: null` so no 0/0
  signal leaks.
- **Residual risk**: A sub-region operator who notices a sharp
  WoW drop in `households_created` for their scope learns
  something they could already learn from the existing trend
  dashboards. Acceptable.

### US-S11-008 — DPIA Sprint 10+11 follow-up

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Define ops alert for single operator bulk-approving > N rows in K min | DPO + Ops | US-S10-004 |
| Confirm plaintext-password residual risk in KoboCredentialForm is acceptable for pilot scope | DPO | US-S11-003 |
| Track DIH-O-CONN-02 (Kobo token upstream revocation) to ADR-0007 closure | DPO | US-S11-003 |
| Confirm 5% AUTO_REVERSE_RATE_CEILING is acceptable | DPO | US-S11-005 |

Plus the 24 actions still outstanding from prior instalments.

---

## Next review

Sprint 12 close. Sprint 12 is expected to focus on the deferred
external-dependency stories (Keycloak realm provisioning,
KMS rollout, NIRA + UBOS live connectors) plus the operations
runbook for the credentialing flow shipped this sprint.
