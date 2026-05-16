# DPIA — Sprint 12 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-16.
**Covers**: All stories merged to `main` during Sprint 12.
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)
- `/docs/dpia/sprint_8_impacts.md` (Sprint 8)
- `/docs/dpia/sprint_9_impacts.md` (Sprint 9)
- `/docs/dpia/sprint_10_11_impacts.md` (Sprints 10 + 11)

---

## Sprint 12 stories

### US-S12-001 — Home-screen KPIs from live counts

- **New processing activity**: One-shot aggregator at
  `/api/v1/rpt/dashboards/operator-kpis/` returning eleven count
  metrics (households_total, stages_pending_promotion + variants,
  change_requests_pending, grievances_open + L2, data_requests_*).
  Called by the React home dashboard on mount, once per session.
- **Personal-data categories**: None — pure aggregate counts. No
  row-level identifiers in the response.
- **Lawful basis**: Public task (ops dashboard).
- **Data minimisation**: ABAC-scoped at the counter level via
  `_scoped_codes` / `scope_q_for_field` — sub-region operators see
  only their scope's counts. One AuditEvent per call replaces what
  would have been seven dashboard-read events; quieter for the
  anomaly-detection feed.
- **Residual risk**: A sub-region with very few households
  (e.g., 3) reveals an upper bound on its scope when an operator
  in it sees `households_total = 3`. Same small-cell-suppression
  concern as RPT S4-004; mitigation tracked in that DPO action.

### US-S12-002 — Live Audit chain tab on household detail

- **New processing activity**: Operator-facing view of the
  `AuditEvent` chain for a single household via
  `/api/v1/security/audit-events/?entity_id={ulid}`. Renders
  who/when/action/reason/hash inline on the household-detail
  screen.
- **Personal-data categories**: Meta-only on the audit event
  (actor_id, action, entity_id, reason). The reason field MAY
  contain a free-text note an operator wrote during a UPD action
  — operators are coached not to put personal data in those.
- **Lawful basis**: Public task (accountability + transparency
  under DPPA §15).
- **Data minimisation**: The serializer (S2-001) doesn't expose
  field_changes' values in detail beyond what's already on the
  AuditEvent row. ABAC at the household level: operators can only
  open this screen for households in their scope, so the audit
  chain they see is naturally bounded.
- **Residual risk**: An operator who can read the audit chain
  learns the identities of upstream actors (parish chiefs, CDOs).
  Acceptable — accountability is the point.

### US-S12-003 — Live Updates history tab on household detail

- **New processing activity**: Lists `ChangeRequest` rows for one
  household via `/api/v1/upd/change-requests/?entity_id={ulid}`,
  with click-through to the existing UPD reviewer screen.
- **Personal-data categories**: ChangeRequest carries `changes`
  (the before/after field values) — sensitive when the field is a
  phone number, NIN-related, or address. The screen renders
  metadata only (change_type, status, PMT-relevance, actor); the
  full diff lives behind the click-through to the UPD reviewer
  which already audit-emits on read.
- **Lawful basis**: Public task.
- **Data minimisation**: Decision: list-view shows summary fields
  only; the personal-data-bearing `changes` block stays one screen
  away (UPD reviewer) where the existing per-record audit is
  already in place. Same ABAC scope as the household itself.
- **Residual risk**: None new.

### US-S12-004 — Celery beat for pending Kobo landings

- **New processing activity**: Every 5 minutes, walk every Kobo
  RawLanding without a StageRecord and drive it through
  canonicalize → stage → DQA/IDV/DDUP, then run the geo backfill.
  Runs under the `celery-beat` system actor identity.
- **Personal-data categories**: Indirect — touches the same
  household/member data the manual `process_pending_landings_action`
  admin already touches.
- **Lawful basis**: Public task (the DPA covering the Kobo source
  authorises ingestion; this story just automates the cadence).
- **Data minimisation**:
  - System actor is recorded on each AuditEvent so the audit chain
    still shows who/what touched a record, just not a human.
  - Sources without credentials are skipped (not errored) — no
    repeated failures noise the audit feed.
  - Per-row failures captured as quarantine counts, not retried
    forever; operators handle them through the existing
    Quarantine admin.
- **Residual risk**:
  - **Operator surprise**: a household promoted by the beat shows
    `celery-beat` in the audit chain instead of a named operator.
    Acceptable: the lineage back to the Kobo submission's
    `_submitted_by` is preserved in `_source_keys`.
  - **No throttle on the beat task**. If a Kobo pull lands 50,000
    rows in one go, the beat tick will try to process all of them
    in one 5-min window. **New DPO action**: track a soft cap
    (e.g. 500 rows per tick) before scaling to a real volume.

### US-S12-005 — DPIA Sprint 12 follow-up

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Small-cell suppression for `households_total` when scope size < 5 | DPO | US-S12-001 |
| Coaching: operators should not put personal data in UPD reason / note free-text | DPO + Ops | US-S12-002 |
| Define a per-tick row cap (≈ 500) on `process_pending_kobo_landings_task` before national scale | DPO + Ops | US-S12-004 |

Plus the 27 actions still outstanding from prior instalments.

---

## Next review

Sprint 13 close. Sprint 13 candidate set:
- Wire the home dashboard's queue panels (not just KPIs) to live data
- Per-region drill-down from the home dashboard
- DDUP merge UI live wiring (currently mock)
- DPIA Sprint 13 follow-up
