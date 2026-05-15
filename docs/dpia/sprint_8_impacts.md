# DPIA — Sprint 8 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 8 (2026-05-15).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)

This document satisfies **Definition of Done #6** (CLAUDE.md): every
story that touches personal data records DPIA impact. Same shape as
the previous instalments.

---

## Sprint 8 stories

### US-S8-001 — DPIA Sprint 7 impact recording

- **No new processing activity** — documentation only.
- Records the 5 new DPO follow-up actions from S7 stories. See
  the parent file `/docs/dpia/sprint_7_impacts.md` for the action
  catalogue.

### US-S8-002 — DDUP tier-3 auto-merge confidence rule

- **New processing activity**: Recurring Celery beat task (hourly,
  see `nsr_mis/celery.py`) picks PENDING tier-3 MatchPair rows with
  `composite_score >= auto_merge_threshold` (default 0.95) and
  commits a merge — no manual reviewer in the loop. The older
  ULID wins as the survivor; `chosen_field_values` is empty (the
  survivor's existing fields stay).
- **Personal-data categories**: All Member fields covered in §3.
  The merge soft-deletes the loser and re-points
  Household.head_member references; nothing new is *added* but the
  AUTOMATIC pathway is.
- **Lawful basis**: Public task; deduplication required by SAD
  §4.3 to prevent double-enrolment. Threshold and surviving-side
  selection rule are documented in code so the audit chain shows
  the decision reasoning (each row emits two events: the standard
  `merge` from `merge_member_pair`, AND an additional
  `auto_merge` action with composite_score + threshold in
  field_changes).
- **Data minimisation**: Snapshot for un-merge (S5-003's
  pre_merge_snapshot) is captured the same way as for manual
  merges, so the 30-day reverse window applies identically. The
  decision rationale is in `services.auto_merge_high_confidence_
  pairs.__doc__` so future readers can audit WHY a row was
  auto-merged.
- **Residual risk**: A false positive auto-merge wastes the
  reviewer's reverse-window grace and could trigger a citizen
  grievance. The 0.95 default threshold is conservative; the
  `auto_merge_threshold` is overridable per DdupModelVersion so
  operations can tighten it without code change. **DPO action**:
  confirm 0.95 is acceptable for MVP; consider tighter for the
  first month post-launch (e.g., 0.98) while reviewers calibrate.

### US-S8-003 — DRS partner download endpoint

- **New processing activity**: First DIRECT bundle-bytes egress
  path to partners. Previously the manifest SHA was locked at
  delivery but the bytes never left NSR — operators dropped the
  bundle to MinIO through an out-of-band path. This endpoint
  streams NDJSON over HTTPS straight from the bundle store.
- **Personal-data categories**: Same fields as the rendered
  bundle (S5-002 + S6-002). Whatever the DSA's `allowed_scopes`
  permits.
- **Lawful basis**: Public task + the partner's DSA. The
  endpoint is partner-scoped via the existing
  PartnerScopedQuerysetMixin (S4-001) — partner-A 404s on
  partner-B's request id.
- **Data minimisation**: Status guard rejects everything except
  DELIVERED. Audit emits `action=download` with manifest
  fingerprint (`manifest_sha256[:8]`), row count, IP, user-agent
  — partner egress patterns are fully observable.
- **Residual risk**: Today the endpoint streams bytes directly;
  partners cache the bundle locally and the NSR audit trail
  cannot prove re-distribution. When MinIO wiring lands
  (DRS-O-02), this flips to a short-lived signed URL — limits
  the re-share window. **DPO action**: confirm direct-stream is
  acceptable until DRS-O-02 closes; the signed-URL variant is
  the long-term plan.

### US-S8-004 — RPT weekly registrations trend dashboard

- **New processing activity**: New aggregate read endpoint
  (`/api/v1/rpt/dashboards/weekly-household-registrations/`).
  TruncWeek over Household.created_at, last 12 weeks.
- **Personal-data categories**: None — counts per ISO week.
- **Lawful basis**: Public task (ops oversight).
- **Data minimisation**: Same scope-before-aggregate as the
  other RPT dashboards; sub-region operators only see their
  geography's weekly counts.
- **Residual risk**: A small sub-region with a sudden week of
  high registrations (e.g., refugee influx) is identifiable in
  the trend even before names are shipped. Covered by the
  open small-cell-suppression DPO action (S4-004).

### US-S8-005 — DIH connector framework

- **No new processing activity** — refactor only. The four
  existing connectors (PDM/NUSAF/WFP-SCOPE/NIRA-reverse) gain a
  wrapper class + register against `CONNECTOR_REGISTRY`. No
  behaviour change, no new field, no new audit emission.
- **DPO note**: When the eventual generic POST endpoint
  (`/api/v1/dih/connectors/{code}/push/`) lands, it must enforce
  the same DPA gate (AC-DIH-DPA-REQUIRED) that the existing
  `start_connector_run` already does.

### US-S8-006 — GRM workbench (first React screen)

- **New processing activity**: Browser-side display of grievance
  data (reporter name + phone, narrative, subject household_id,
  audit lifecycle). NO new server-side processing — the screen
  reads through `/api/v1/grm/grievances/` which has been audit-
  emitted since S2-001.
- **Personal-data categories**: All fields from the GrievanceSerializer
  (already documented under US-S2-008).
- **Lawful basis**: Public task (operator triage). Same as the
  existing admin surface.
- **Data minimisation**: Filters list rows pre-fetch via the
  existing PartnerScopedQuerysetMixin → HouseholdIdScopedQueryset­
  Mixin chain. Mock data is used today; real fetch wiring comes
  when OIDC auth (US-S2-002) lands so the browser can present a
  bearer token.
- **Residual risk**: A React app on a personal device caches DOM
  state in memory. If a CDO leaves their browser open at a
  shared workstation, the next user could read the queue. **DPO
  action**: confirm session-idle behaviour matches SAD §8.3.2
  (30-min idle, 10-hour max session) — the realm-side enforcement
  lands with US-S2-002 + ADR-0006.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm 0.95 auto-merge threshold is acceptable for MVP | DPO | US-S8-002 |
| Confirm direct-stream download until DRS-O-02 closes | DPO | US-S8-003 |
| Confirm session-idle behaviour matches SAD §8.3.2 (post US-S2-002) | DPO | US-S8-006 |

Plus the 18 actions still outstanding from prior instalments.

---

## Next review

Sprint 9 close. The Sprint 9 backlog (S9-001 through S9-006) will
likely touch the per-field-scores admin display, a new grievances-
by-category dashboard, API throttling, the GRM→UPD handoff, and
the second React screen — the partner DRS portal. The partner
portal will be the first surface a non-MGLSD user logs into and
warrants its own DPIA section.
