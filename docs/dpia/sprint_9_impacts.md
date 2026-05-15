# DPIA — Sprint 9 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 9 (2026-05-15).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)
- `/docs/dpia/sprint_8_impacts.md` (Sprint 8)

This document satisfies **Definition of Done #6** (CLAUDE.md): every
story that touches personal data records DPIA impact. Same shape as
the previous instalments.

---

## Sprint 9 stories

### US-S9-001 — DDUP MatchPair admin per_field_scores display

- **New processing activity**: Browser-side rendering of the
  `per_field_scores` JSON column from MatchPair as a coloured
  table in /admin/ddup/matchpair/. Same data, friendlier form.
- **Personal-data categories**: meta-only on the admin row — the
  scores are decimals derived from Jaro-Winkler comparisons over
  name fields; the original field VALUES are NOT in
  per_field_scores (only their pairwise similarity).
- **Lawful basis**: Public task (reviewer adjudication of dedup).
- **Data minimisation**: The scores reveal that two members had
  e.g., 0.95 surname similarity but NOT the surname strings.
  An attacker with read-access to the table can't reconstruct
  names from the decimals.
- **Residual risk**: A reviewer staring at a 1.0 / 1.0 / 1.0 row
  effectively knows two records share surname, first name, and
  DOB; this is the operational point of the dedup workbench.
  Reviewer access is staff-only and audit-logged.

### US-S9-002 — RPT grievances-by-category dashboard

- **New processing activity**: New aggregate endpoint at
  /api/v1/rpt/dashboards/grievances-by-category/. Counts of
  non-closed grievances grouped by Category enum.
- **Personal-data categories**: None — aggregate counts.
- **Lawful basis**: Public task (ops oversight).
- **Data minimisation**: Same scope-before-aggregate pattern as
  the 9 other RPT dashboards. RESOLVED + CLOSED rows excluded.
  Orphan grievances (no household_id) are invisible to sub-
  region operators.
- **Residual risk**: A small sub-region with a single
  OPERATOR_CONDUCT grievance is identifiable in the count. The
  small-cell-suppression DPO action from S4-004 covers this.

### US-S9-003 — API throttling on DRS download

- **New processing activity**: Rate-limiting on the bundle-
  download endpoint. 10 requests per minute per authenticated
  user (env-tunable via DRS_DOWNLOAD_THROTTLE_RATE). No new
  personal data processing; existing flows are gated.
- **Personal-data categories**: None new.
- **Lawful basis**: Public task + system-availability principle
  (DPPA §29: prevent harm to the data subject by preventing
  bulk-extract abuse).
- **Data minimisation**: Throttle state lives in Django's cache
  backend keyed by `throttle_drs-download_{user_id}`. Cache
  entries TTL out automatically (no PII in keys; just numeric
  user IDs).
- **Residual risk**: Throttle bypass via multiple partner
  service accounts. Out of scope today (one partner =
  one DSA + one bot account); ADR-0006's Keycloak realm
  design handles the multi-account case via realm-level
  client management.

### US-S9-004 — GRM → UPD cross-screen handoff

- **New processing activity**: UI-only. The React app shell
  passes a `changeRequestId` payload from the GRM screen to
  the UPD screen on navigation. No server change.
- **Personal-data categories**: meta-only (one ULID in transit
  inside the browser).
- **Lawful basis**: Public task.
- **Data minimisation**: The payload is the ChangeRequest ID
  only; the receiving screen fetches the full ChangeRequest
  data through the existing audit-emitted API. The handoff
  doesn't duplicate any personal data into the URL or browser
  history.
- **Residual risk**: None new.

### US-S9-005 — DRS partner portal screen (second React screen)

- **New processing activity**: Browser-side display of partner-
  scoped DataRequest data. Consumes /api/v1/drs/requests/mine/
  (S7-004) and /download/ (S8-003) — both audit-emitted.
- **Personal-data categories**: meta-only on the row level
  (request id, DSA reference, status, timestamps, manifest
  SHA, row count). The actual bundle bytes are served by the
  download endpoint, which has its own DPIA notes (S8-003).
- **Lawful basis**: Public task + the partner's DSA.
- **Data minimisation**: Slim MyDataRequestSerializer
  excludes admin/internal fields (decision_reason, requester
  identity of other users, request_payload). PartnerScope ABAC
  from S4-001 still gates the read.
- **Residual risk**: A partner browser left open at a shared
  workstation exposes the queue to whoever sits down next.
  Session-idle behaviour gated on US-S2-002 (Keycloak realm
  per ADR-0006); the DPO action from S8-006 covers it.

### US-S9-006 — DPIA Sprint 8 impacts

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm dedup workbench per-field-score disclosure is acceptable | DPO | US-S9-001 |
| Define small-cell threshold for grievance-by-category counts (extends S4-004 action) | DPO | US-S9-002 |
| Confirm 10/min download throttle is acceptable for MVP partners | DPO | US-S9-003 |

Plus the 21 actions still outstanding from prior instalments.

---

## Next review

Sprint 10 close. The Sprint 10 backlog touched the DDUP feedback
counters (reverse-rate signal — pure aggregation over existing
data), partner DRS request-builder UI (first partner-side write
surface), and UPD bulk-action endpoints (which need their own
DPIA notes for the bulk approval-loop attack surface).
