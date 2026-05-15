# DPIA — Sprint 7 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 7 (2026-05-15).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)

This document satisfies **Definition of Done #6** (CLAUDE.md): every
story that touches personal data records DPIA impact. Same shape as
the previous instalments.

---

## Sprint 7 stories

### US-S7-001 — UPD auto-escalation on SLA breach

- **New processing activity**: Background sweep flips
  PENDING_APPROVAL ChangeRequest rows past their sla_deadline to
  required_role='district_m_and_e' with a fresh 48h window. Runs
  every 15 minutes via Celery beat.
- **Personal-data categories**: meta-only on the row — the change
  is to required_role + sla_deadline, not to the Household/Member
  data the request targets.
- **Lawful basis**: Public task (operational supervision); SAD
  §4.4.7 SLA framing.
- **Data minimisation**: Audit event field_changes records ONLY the
  from_role / to_role / new_sla_deadline triple. The CR's payload
  (which carries personal-data field changes) is NOT re-logged.
- **Residual risk**: A row that's escalated then approved at the
  district level has a different approver-role lineage from the
  original supervisor route. **DPO action**: confirm that
  district-M&E approval of a sub-region operator's CR is
  acceptable cross-geography exposure. (NB: it is, by SAD's
  escalation principle, but should be explicit.)

### US-S7-002 — DIH NIRA reverse-feed connector (vital events)

- **New processing activity**: Inbound vital-event push from NIRA.
  Death events resolve NIN → Member by nin_hash and flip
  Member.residency_status to 'deceased' via the S3-003 auto-commit
  pipeline. Birth events are intentionally deferred (raise
  NiraVitalEventError pointing at NIRA-O-01).
- **Personal-data categories**: Identification (NIN — incoming,
  hashed before lookup); demographic (residency_status flips).
- **Lawful basis**: Public task + the (pending) NIRA MoU. NIN is
  sensitive per DPPA §9.
- **Data minimisation**: The raw NIN is consumed only for the
  hash lookup and never persisted on the connector side
  (NiraVitalEventError messages surface only the last-4 digits).
  CR changes dict contains only {residency_status: {old, new}}.
- **Residual risk**: A NIRA push for a NIN that doesn't resolve
  in NSR could indicate either (a) a member NSR doesn't know
  about, or (b) a NIN typo. Today we reject loudly. **DPO action**:
  define whether unresolved NIRA pushes should be queued for
  manual review (potential for false-negative drift if silently
  dropped).

### US-S7-003 — DDUP tier 3 probabilistic discovery

- **New processing activity**: Weighted-similarity matching within
  village blocks. Discovers candidate duplicate pairs based on
  surname + first_name (Jaro-Winkler), DOB year proximity, sex,
  village. Pairs land in PENDING for reviewer adjudication.
- **Personal-data categories**: Identification (surname, first_name),
  demographic (DOB, sex), geographic (village).
- **Lawful basis**: Public task; deduplication is required by SAD
  §4.3 to prevent double-enrolment in benefits.
- **Data minimisation**: Comparison happens INSIDE the village
  block — no cross-village similarity computation. Per-field
  similarity scores ARE persisted in MatchPair.per_field_scores
  so reviewers see the breakdown, but they're decimals not the
  raw field values; an attacker who steals the MatchPair table
  doesn't recover names from per_field_scores.
- **Residual risk**: Probabilistic matches at the threshold
  boundary (0.85) could include false positives. The dedup
  workbench (S4-005 / S6-001 admin surface) is the manual gate;
  the reverse-merge window (S5-003) is the safety net. **DPO
  action**: confirm the default 0.85 threshold is conservative
  enough for MVP; consider per-region tuning if false positives
  surface during pilot.

### US-S7-004 — DRS partner self-service /requests/mine/

- **New processing activity**: New read endpoint for partner-
  affiliated users to see their own DataRequests.
- **Personal-data categories**: meta-only — the endpoint shows
  the partner's own request lifecycle data (status, timestamps,
  manifest SHA, row count). The bundle bytes themselves still
  go through the dedicated render-and-deliver path.
- **Lawful basis**: Public task + the partner's signed DSA.
- **Data minimisation**: Slim partner-facing serializer
  (MyDataRequestSerializer) explicitly excludes admin fields
  (decision_reason, approver, requester, request_payload). The
  partner sees only what they need for their own ops dashboard.
  PartnerScopedQuerysetMixin from S4-001 still applies — partners
  cannot see other partners' rows.
- **Residual risk**: download_url is emitted as a placeholder
  pointing at the future signed-URL endpoint. Until DRS-O-02
  closes, the URL itself is not signed — the endpoint at the
  other end (when wired, US-S8-003 placeholder) is the real
  gate, not the URL string in the JSON. **DPO action**: confirm
  the placeholder URL pattern is acceptable in pilot.

### US-S7-005 — RPT dashboard CSV exports

- **New processing activity**: Existing 8 dashboards gain an
  ?export=csv query param that returns the same aggregate rows
  as text/csv.
- **Personal-data categories**: None new — the aggregate counts
  are identical to the JSON path. CSV doesn't change WHAT is
  exposed, only HOW.
- **Lawful basis**: Public task (ops oversight).
- **Data minimisation**: Scope filter applies BEFORE rendering;
  the CSV is just a different representation of the same scoped
  aggregate. Audit emission is identical for both formats —
  switching to CSV does NOT let a partner exfil silently.
- **Residual risk**: CSV is more partner-shareable than JSON
  (everyone has Excel; not everyone has a JSON viewer). A
  partner could copy-paste a sub-region operator's CSV into a
  partner-side spreadsheet that aggregates across geographies
  they don't have grant for. Mitigation is operational
  (training); the small-cell suppression DPO action from
  S4-004 helps here too.

### US-S7-006 — ADR-0006 Keycloak realm design

- **No new processing activity** — design only. Records the
  realm topology + role catalogue + JWT→OperatorScope mapping.
- The 9 roles map to existing OperatorScope rows, so no schema
  change lands at this ADR (the schema change for OIDC sign-in
  comes with US-S2-002 implementation).
- **DPO action**: confirm the stale-OIDC-scope sweep policy
  (recommended in the ADR: daily sync task that deactivates
  scopes dropped from the latest token).

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm district-M&E approval of escalated CR is acceptable | DPO | US-S7-001 |
| Define unresolved-NIRA-push handling (queue vs drop) | DPO | US-S7-002 |
| Confirm 0.85 tier-3 threshold is conservative for MVP | DPO | US-S7-003 |
| Confirm placeholder download_url pattern is acceptable | DPO | US-S7-004 |
| Confirm stale-OIDC-scope sweep policy (ADR-0006) | DPO | US-S7-006 |

Plus the 13 actions still outstanding from prior instalments.

---

## Next review

Sprint 8 close. The Sprint 8 backlog (S8-001 through S8-006) will
likely touch the DDUP auto-merge confidence rule (new automatic
mutation of personal data), the DRS download endpoint (first
direct bundle-bytes egress to partners), a new RPT trend view,
and — pending operational readiness — the first React console
screen.
