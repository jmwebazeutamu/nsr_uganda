# DPIA — Sprint 13 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-16.
**Covers**: All stories merged to `main` during Sprint 13.
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)
- `/docs/dpia/sprint_8_impacts.md` (Sprint 8)
- `/docs/dpia/sprint_9_impacts.md` (Sprint 9)
- `/docs/dpia/sprint_10_11_impacts.md` (Sprints 10 + 11)
- `/docs/dpia/sprint_12_impacts.md` (Sprint 12)

---

## Sprint 13 stories

### US-S13-001 — Adopt claude.ai/design Registry + Household redesign

- **New processing activity**: Visual redesign of the operator-
  facing Registry browse and Household detail screens. Same DRF
  endpoints (`/api/v1/data-management/households/`, audit-events,
  change-requests) consumed under a richer layout.
- **Personal-data categories**: Same as the previous wiring —
  Household + Member rows with NIN suffix, phone, geo. No NEW
  fields exposed.
- **Lawful basis**: Public task.
- **Data minimisation**: NIN remains masked to last 4. Roster
  table now shows phone explicitly — previously hidden in the
  per-member admin only. Operators with household scope already
  saw the phone via member-detail click; surfacing it on the
  roster is a presentation change, not a scope widening.
- **Residual risk**: A more discoverable phone column on the
  roster may encourage looking up contacts. Mitigation: existing
  ABAC scope confines it to operators with household visibility;
  audit chain captures the read.

### US-S13-002 — Wire home dashboard queue panels live

- **New processing activity**: On home-screen mount, fan out
  to 1-3 list endpoints per role (DIH stages, UPD change-requests,
  GRM grievances, DRS requests). Each call emits its own
  `dashboard_read` / audit row.
- **Personal-data categories**: Top-N preview metadata — head
  name + parish for DIH; change_type + requester for UPD; category
  + tier + description preview for GRM; DSA reference + row count
  for DRS. No NIN, no GPS, no full member detail.
- **Lawful basis**: Public task.
- **Data minimisation**: page_size=4 cap; description preview
  truncated to 80 chars (prevents wholesale leak via the home
  screen for an operator who only needs to triage queue depth).
  ABAC scope at the underlying endpoints means each operator
  sees only items in their scope.
- **Residual risk**: An operator who mounts the home screen
  repeatedly drives N+M+P+Q endpoint hits per role. Acceptable —
  no new attack surface; throttling at the API layer (S9-003)
  caps abuse.

### US-S13-003 — Wire DDUP screen to live MatchPair API

- **New processing activity**: Side-by-side comparison of two
  Member rows (record_a_id + record_b_id from the MatchPair),
  including head name, NIN suffix, DoB, sex, phone, per-field
  similarity scores from the matcher.
- **Personal-data categories**: Two members worth of
  identification fields in one view. Highest-sensitivity render
  on the operator surface — by design, since the operator's job
  is to decide whether they're duplicates.
- **Lawful basis**: Public task + AC-DDUP-MODEL-VERSION.
- **Data minimisation**: Only the fields the matcher actually
  compared (surname, first_name, sex, DoB year, NIN last-4, phone)
  are surfaced. Full NIN remains encrypted at rest + never on
  the wire (S2-001 / ADR-0002 invariant unchanged).
- **Residual risk**:
  - **Cross-household visibility**: an operator viewing the
    compare sees two members from potentially different households;
    if those households are outside their normal ABAC scope, this
    leaks geography to them. **Mitigation**: MatchPairScopedQueryset
    Mixin (S2-003) already gates which pairs an operator can list
    — only pairs where BOTH members fall within scope. Same gate
    used by the React fetch.
  - **Merge service not exposed via REST today** — the React
    Merge / Reject buttons are operator muscle-memory only; real
    merge decisions still go through admin / celery. Acceptable
    pending the merge-via-REST ticket; the side-by-side compare
    surface stays in use.

### US-S13-004 — Wire DRS partner list view to live API

- **New processing activity**: Continuation of S9-005's partner-
  facing visibility — same `/api/v1/drs/requests/mine/` endpoint,
  same MyDataRequestSerializer projection, just fetched live
  instead of rendered mock.
- **Personal-data categories**: Meta-only on the row level —
  request id, DSA reference, status, row count, manifest hash.
  Bundle bytes still served only via the download endpoint
  (S8-003) which has its own DPIA notes.
- **Lawful basis**: Public task + the partner's DSA.
- **Data minimisation**: Same PartnerScope ABAC (S4-001).
  Decision_reason field is on the admin/operator surface — NOT on
  this serializer, so rejected requests show only the rejection
  status, not the reason behind it. Partner contacts the NSR Unit
  for rejection details (operations runbook).
- **Residual risk**: None new beyond S9-005.

### US-S13-005 — DPIA Sprint 13 follow-up

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm phone column on Roster tab is acceptable for CDO + parish scope | DPO + Ops | US-S13-001 |
| Throttle home-screen queue fan-out if operators are mounting it > 60×/hour (combined endpoint hits) | Ops + Security | US-S13-002 |
| Track merge-via-REST endpoint as a Sprint 14 ticket — let the React Merge button do its work end-to-end | DDUP lead | US-S13-003 |

Plus the 30 actions still outstanding from prior instalments.

---

## Next review

Sprint 14 close. Sprint 14 candidate set:
- Merge-via-REST endpoint (closes the S13-003 mock-action gap)
- Per-region drill-down from home dashboard
- DRS operator list view live wiring (mirror S13-004 on the
  operator-side `/api/v1/drs/requests/` endpoint)
- Wire Programmes + Grievances tabs on household detail
- DPIA Sprint 14 follow-up
