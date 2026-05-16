# DPIA — Sprint 14 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 14.
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)
- `/docs/dpia/sprint_8_impacts.md` (Sprint 8)
- `/docs/dpia/sprint_9_impacts.md` (Sprint 9)
- `/docs/dpia/sprint_10_11_impacts.md` (Sprints 10 + 11)
- `/docs/dpia/sprint_12_impacts.md` (Sprint 12)
- `/docs/dpia/sprint_13_impacts.md` (Sprint 13)

---

## Sprint 14 stories

### US-S14-001 — Merge-via-REST endpoint + DDUP React Merge loop

- **New processing activity**: Two new POST endpoints on
  MatchPairViewSet — `merge` and `reject`. Both call existing
  audit-bearing service functions (`merge_member_pair`,
  `reject_pair`) unchanged; what's new is that operators can now
  perform merges from the React surface instead of Django admin.
- **Personal-data categories**: A merge commit writes the
  operator's `chosen_field_values` dict to the resulting
  MergeDecision row. Fields can include surname, first_name,
  telephone_1 — i.e. identifiers chosen between two candidate
  records. The dict is logged for AC-DDUP-MERGE-COMMIT
  reversibility (US-S5-003) and DPPA accountability.
- **Lawful basis**: Public task — duplicate resolution is a
  registry-integrity requirement (AC-DDUP-DECISION).
- **Data minimisation**: The serializer's `surviving_id` is a
  ULID, not a NIN. AC-DDUP-DUAL-ACTOR is still service-enforced —
  the operator submitting the merge cannot be the original
  capturer of either record. Note field is captured but
  truncated/audit-only (never re-surfaced in UI lists).
- **Residual risk**:
  - **Faster click-through means faster mistakes**. Before
    S14-001 a merge required opening Django admin, which is its
    own friction. Now it's two clicks from the DDUP screen. The
    30-day reverse window (US-S5-003) remains the safety net;
    the React side surfaces "reversible until <date>" on the
    confirm modal. Mitigation: operator note ≥ 6 chars is
    required (existing AC-DDUP-COMMIT-NOTE); auto-merge
    confidence rule (US-S8-002) means high-tier matches don't
    even reach the operator queue.
  - **CSRF token must be present.** The fetch uses
    `credentials: "same-origin"` and reads `csrftoken` from the
    cookie jar. If an attacker tricks the operator into mounting
    the console under a different origin, the session cookie
    doesn't flow and the POST 403s — same protection the rest of
    the REST surface relies on.

### US-S14-002 — DRS operator list view live wiring

- **New processing activity**: Operators viewing the DRS screen
  now see ALL partner data requests in their PartnerScope ABAC
  scope, not just their own. Detail rail shows requester,
  request_payload.fields, sub_region_codes, max_rows,
  decision_reason. Approve + Reject quick-actions POST to the
  existing service endpoints (US-S3-002, no service-level change).
- **Personal-data categories**: Meta-only — request id, DSA
  reference, requester username, status, row count delivered,
  manifest hash. Bundle bytes never returned by the list endpoint
  (S8-003 download is its own DPIA notes).
- **Lawful basis**: Public task. NSR Unit's role is to triage
  inbound DRS requests under each DSA — the entire reason DRS
  exists.
- **Data minimisation**:
  - The list endpoint already projects via DataRequestSerializer
    (S3-002), which excludes the bundle path; this story didn't
    widen the serializer.
  - `requester` is an operator username, not a citizen
    identifier — no DPIA delta there.
  - PartnerScopedQuerysetMixin already gates which DSAs the
    operator can see (S4-001 / S4-002); a CDO or parish operator
    would see zero rows on this page (and the screen is hidden
    from those roles in app.jsx anyway).
- **Residual risk**: An NSR Unit operator with broad scope now
  sees a continuously-refreshing list of all in-flight partner
  requests. Same data was already visible in Django admin; this
  story just brings it onto the React surface. Audit chain on
  the list endpoint captures the read (S2-001 middleware).

### US-S14-003 — Wire Programmes + Grievances tabs on household detail

- **New processing activity**: Two of the 12 household-detail
  tabs were placeholder-only; they now render live data.
  - Grievances tab fetches `/api/v1/grm/grievances/?household_
    id=<rid>`. New `household_id` filterset added to
    GrievanceViewSet for this purpose.
  - Programmes tab fans out to `/api/v1/ref/enrolments/?
    household=<rid>` and `/api/v1/ref/referrals/?household=
    <rid>` in parallel. New `household` filterset added to both
    viewsets.
  - ReferralSerializer + EnrolmentSerializer added
    `programme_code` and `programme_name` SerializerMethodFields
    sourced from the FK so the React side renders a human-
    readable programme name without an extra round-trip.
- **Personal-data categories**: Grievance rows include the
  reporter's name + phone + relationship (already captured at
  intake, S2-008). Programme rows include programme code/name +
  enrolment date — no member-level fields.
- **Lawful basis**: Public task — the registry's role includes
  showing operators the full cross-module picture of one
  household.
- **Data minimisation**:
  - GrievanceSerializer's reporter_phone is now surfaced on the
    household-detail Grievances tab. Already available via
    Django admin to operators with grievance-read role; this
    story moves it to the React surface for operators with
    household-scope access. Net effect: same data, narrower
    surface (only on a specific household, not a list).
  - Programme tab is plain meta — no NIN, no phone, no DoB.
- **Residual risk**: Operators with broad household scope (NSR
  Unit Coordinator) can now click through a household → see
  every grievance ever filed against it on one screen. Acceptable
  for triage; the AuditReadMixin on the grievance endpoint
  captures every read.

### US-S14-004 — Per-region drill-down from home dashboard

- **New processing activity**: OperatorKpisView now accepts a
  `?region=<sub_region_code>` parameter. The same aggregator
  runs, narrowed to just that sub-region. Geo-dependent counts
  (households_total, stages_*, change_requests_pending,
  grievances_open/_l2_open) honour the drill-down; DRS counts
  stay national.
- **Personal-data categories**: Counts only — no member-level
  data is returned by the aggregator.
- **Lawful basis**: Public task.
- **Data minimisation**:
  - The drill-down narrows the operator's effective ABAC scope
    further (region ⊆ user's scoped codes). Out-of-scope
    drill-downs return zeros, not 403 — this is intentional
    (preserves dashboard structure) and does not leak data.
  - Audit chain reason now records `region=<code>` so DPO can
    spot operators repeatedly drilling into regions outside their
    home sub-region (a possible curiosity/abuse signal).
- **Residual risk**:
  - **Drill-down enables sub-region comparison**. A national-
    scope operator (NSR Unit Coordinator) can switch the
    selector across regions and visually compare queue depths.
    Acceptable for operational management; no individual-level
    inference is possible from counts alone.
  - **Bug discovered during this work**: `_count_change_requests`
    had a latent bug (wrong import + wrong field name) that
    silently returned 0 in production. The drill-down test
    surfaced and fixed it. Counts on existing dashboards were
    therefore *understated* for pending change-requests since
    S12-001. No data leak — fail-closed direction. Operations
    runbook updated.

### US-S14-005 — DPIA Sprint 14 follow-up

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm 30-day reverse window UX on React merge surface is reaching operators (i.e. they read the modal copy before clicking) | DPO + UX | US-S14-001 |
| Spot-check NSR Unit operators' DRS approve/reject decisions for first 30 days post-launch — confirm `decision_reason` notes are substantive | DPO + Ops | US-S14-002 |
| Confirm Grievance reporter_phone exposure on household-detail Grievances tab is acceptable for NSR Unit Coordinator + CDO scope (DPO had flagged it on the Roster tab in S13-001 — same field, different surface) | DPO + Ops | US-S14-003 |
| Sample audit log for `region=<code>` reads to detect cross-region drilling by operators outside that region's coordinator team | DPO + Security | US-S14-004 |
| Investigate whether the `_count_change_requests` understatement (returned 0 since S12-001 launch) had any operational impact — were CRs missed because the dashboard hid them? | Ops + NSR Unit | US-S14-004 |

Plus the 33 actions still outstanding from prior instalments.

---

## Next review

Sprint 15 close. Sprint 15 candidate set:
- DDUP UI: show "Reversible until <date>" on the merge confirm modal
- DRS operator-list: surface average decision turnaround on the eyebrow
- Region drill-down: extend to queue panels (currently KPI-only)
- ADR-0008: pagination + throttling sweep for list endpoints now
  that more React screens fetch on mount
- DPIA Sprint 15 follow-up
