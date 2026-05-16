# DPIA — Sprint 15 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 15.
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
- `/docs/dpia/sprint_14_impacts.md` (Sprint 14)

---

## Sprint 15 stories

### US-S15-001 — DDUP merge modal "Reversible until <date>"

- **New processing activity**: Presentation change only — the
  merge confirm modal now renders the concrete date today + 30
  days as a "Reversible until" hint, and resolves the surviving
  and archived member ULIDs from the live MatchPair (previously
  shown as hardcoded mock ULIDs even in live mode).
- **Personal-data categories**: Two member ULIDs (already shown
  elsewhere on the same screen — the side-by-side compare table
  lists them in the Registry ID column). No new fields exposed.
- **Lawful basis**: Public task.
- **Data minimisation**: Same — two ULIDs the operator already
  sees. No additional rendering of personal data.
- **Residual risk**: None new. The DPO's S14 action item
  ("confirm reverse-window UX is reaching operators") is closed
  by this story.

### US-S15-002 — DRS operator list avg decision turnaround

- **New processing activity**: The operator-side DRS inbox now
  shows an aggregate "avg 4.2h (n=12)" hint on its eyebrow,
  computed client-side from the already-fetched list.
- **Personal-data categories**: Aggregate counts only — no
  partner identity, no NIN, nothing PII. Just two numbers.
- **Lawful basis**: Public task — NSR Unit self-monitoring.
- **Data minimisation**: The metric is computed off the list
  the operator was already shown by S14-002. No new fetch, no
  new field exposure.
- **Residual risk**: None new. The DPO's S14 action item
  ("spot-check NSR Unit decision turnaround") is partially
  addressed: operators can now self-monitor their own
  performance against this metric.

### US-S15-003 — Region drill-down extended to queue panels

- **New processing activity**: Three list endpoints (DIH stages,
  UPD change-requests, GRM grievances) now accept
  `?sub_region_code=`. The home dashboard's queue panels now
  refetch with that filter when the operator changes the
  region selector.
- **Personal-data categories**: Same rows the queue panels
  already returned, just narrower set. Stage records expose
  provisional Registry IDs + parish/village names (already in
  the panel projection). Change requests expose
  entity_type/entity_id + change_type. Grievances expose
  category + tier + truncated description.
- **Lawful basis**: Public task.
- **Data minimisation**:
  - The filter applies AFTER the operator's ABAC scope mixin.
    An operator's effective view is (their scope) ∩ (requested
    region) — drilling out of scope produces zero rows, never
    leaks data.
  - The new `get_queryset` overrides do an IN-subquery into
    Household by sub_region_code. Member-typed change requests
    are excluded by design (no usable household join from a
    Member ULID alone — same trade-off taken in
    `_count_change_requests` S14-004).
- **Residual risk**:
  - **Region selection is auditable but not tagged**. Each list
    fetch emits an AuditEvent via AuditReadMixin (S2-001), so
    the read is logged. The `sub_region_code` param is captured
    in the request URL but isn't echoed in the audit reason
    string today. DPO Sprint 14 action item ("sample audit log
    for region= reads") is now broader because S15-003 expands
    the surface beyond just the KPI aggregator. Recommend the
    DPO follow-up extend that sampling to the DIH/UPD/GRM list
    endpoints when filtered by sub_region_code.

### US-S15-004 — ADR-0008 pagination + throttling sweep

- **New processing activity**: Backend change — every list
  endpoint now honours `?page_size=` (previously silently
  ignored) up to a hard cap of 500. ADR-0008 documents the
  policy.
- **Personal-data categories**: No new data exposed. The change
  is purely about HOW MUCH data per round-trip, not WHAT.
- **Lawful basis**: Public task + security best practice
  (enumeration cap).
- **Data minimisation**:
  - **Material improvement**: home queue panels were
    over-fetching by 12× (4 wanted, 50 returned). They now
    return only what's rendered. Less data on the wire =
    smaller blast radius if a session cookie is compromised.
  - **Audit chain correctness gap fixed**: the household-
    detail Audit tab was silently truncating beyond row 50
    (it requested `?page_size=200` which DRF dropped). DPO
    audits that relied on the React surface may have been
    incomplete since US-S12-002. Recommend the DPO re-run
    any household-level audit traces opened between
    2026-05-13 (S12-002 close) and 2026-05-15 (this fix).
  - **Enumeration cap**: `max_page_size=500` blocks a
    `?page_size=10000` attack vector. The 1000/min user
    throttle was the only previous defence; the cap is the
    deterministic backstop.
- **Residual risk**:
  - **Some operators may have been making decisions on
    truncated audit data**. This is the second correctness gap
    surfaced by Sprint 14-15 (first was
    `_count_change_requests` zero counts). Recommend a brief
    operations note in the DPO runbook to spot-check any
    high-stakes household actions taken in that window.
  - **No per-endpoint cap today**. ADR-0008 OI-PAG-01 leaves
    the option open. If/when the DPO flags a specific endpoint
    as PII-heavy enough to warrant a tighter cap (e.g. /api/v1/
    data-management/members/ at 100 instead of 500), it's a
    one-line subclass override.

### US-S15-005 — DPIA Sprint 15 follow-up

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Extend Sprint 14's region-audit sampling to cover the DIH / UPD / GRM list endpoints when filtered by ?sub_region_code= | DPO + Security | US-S15-003 |
| Re-run any household-level audit traces opened 2026-05-13 → 2026-05-15 against the now-fixed Audit chain pagination | DPO | US-S15-004 |
| Spot-check household actions taken during the truncated-audit window for evidence of decisions made on incomplete data | DPO + NSR Unit | US-S15-004 |
| Confirm `max_page_size=500` is acceptable for the Member endpoint specifically, or recommend a tighter per-endpoint cap | DPO + Security | US-S15-004 |

Plus the 38 actions still outstanding from prior instalments.

---

## Next review

Sprint 16 close. Sprint 16 candidate set:
- Audit-reason enrichment: include sub_region_code and page_size
  in AuditEvent.reason so DPO sampling has structured context
- DRS partner-side: surface "avg decision turnaround" reciprocally
  on the partner list (so partners see expected wait time)
- Member endpoint: per-endpoint max_page_size cap if DPO concurs
- Audit chain integrity check job (Postgres-only test exists, no
  scheduled run yet)
- DPIA Sprint 16 follow-up
