# DPIA — Sprint 2 + 3 + 4 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` between Sprint 2 start (2026-05-01)
and Sprint 4 close (2026-05-15).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).

This document satisfies **Definition of Done #6** (CLAUDE.md): every
story that touches personal data records DPIA impact. The catalogue
below is the source the DPO uses to update the master DPIA risk
register at /docs/dpia.md.

---

## How to read this

Each entry follows the same shape:

- **Story**: backlog ID + short title.
- **New processing activity**: what changed in how the system handles
  personal data.
- **Personal-data categories touched**: cross-referenced to
  `/docs/dpia.md §3`.
- **Lawful basis**: DPPA 2019 reference + the operational justification.
- **Data minimisation choice**: what we *didn't* expose or persist.
- **Residual risk**: what the DPO still needs to assess.

---

## Sprint 2 stories

### US-S2-001 — Read-side audit middleware (AuditReadMixin)

- **New processing activity**: Every read of personal data through a
  DRF viewset now writes an AuditEvent (actor, action=read/list_read,
  entity_type, entity_id, IP, user agent, timestamp).
- **Personal-data categories**: meta-only — the audit row records *who
  read what*, not the underlying data values.
- **Lawful basis**: Public task (Section 7 DPPA 2019), required by SAD
  §8.4 and DPPA accountability principle.
- **Data minimisation**: User agent capped at 255 chars; IP captured
  only when present; field-value content is NOT logged in read events.
- **Residual risk**: Audit log itself becomes a high-value target. The
  Postgres BEFORE INSERT hash-chain trigger (Sprint 0) constrains
  tampering; retention is 10 years per SAD §8.5.

### US-S2-003 — ABAC geographic scope on every read

- **New processing activity**: Every personal-data viewset now filters
  rows to the requesting user's geographic scope (sub_region_code).
  Fail-closed: unauthenticated and unscoped users see zero rows.
- **Personal-data categories**: All categories from §3 (identification
  through dwelling). Scope determines which rows are visible, not
  which fields.
- **Lawful basis**: Public task + the SAD §8.2 ABAC principle that
  operators only see data for their geography of authority.
- **Data minimisation**: Reduces operator-side visibility to the
  smallest geography their role requires. Five mixin patterns
  documented at `apps/security/abac.py` so new viewsets pick the right
  one (geographic, household-id subquery, entity-type union,
  both-ends-in-scope for pairs, partner-org affiliation).
- **Residual risk**: Sub-region-level enforcement still over-grants
  versus district / parish / village — the finer-grained scopes are
  modelled (US-S4-001 added PARTNER too) but the matching columns
  aren't on every row yet. **DPO action**: confirm sub-region
  enforcement is acceptable as MVP gating before finer-grained lands.

### US-S2-006 — Submission entity (INT)

- **New processing activity**: New table `intake_submission` captures
  enumerator + supervisor identifiers, GPS at submission point, start
  /end timestamps, and the canonical questionnaire payload routes
  through DIH before landing in DAT.
- **Personal-data categories**: GPS (location, sensitive), enumerator
  identity (operator personal data).
- **Lawful basis**: Public task. Enumerator GPS is operational
  evidence of enumeration coverage, not surveillance.
- **Data minimisation**: GPS accuracy capped at 6 decimal places
  (~11cm) — already in the canonical schema; same accuracy bound as
  the questionnaire spec (`/docs/06_questionnaire.docx`).
- **Residual risk**: Enumerator GPS could be misused for staff
  surveillance. **DPO action**: confirm purpose limitation in the
  enumerator-data privacy notice.

### US-S2-007 — DDUP tier 2 (E.164 phone normalisation)

- **New processing activity**: Phone numbers from Member.telephone_1
  and .telephone_2 are normalised to E.164 and used to discover
  candidate duplicate pairs (apps/ddup/phone.py).
- **Personal-data categories**: Contact (telephone) — §3.
- **Lawful basis**: Public task; deduplication is required by SAD
  §4.3 to prevent double enrolment in benefits.
- **Data minimisation**: Phone number is NOT logged in the audit
  chain; only the pair (record_a_id, record_b_id, match_reason="phone")
  is recorded.
- **Residual risk**: Phone-number similarity could reveal household
  relationships (shared number across two households). Operator UI
  shows both ends; the both-ends-in-scope rule (US-S3 MatchPair mixin)
  prevents cross-region leakage but same-sub-region operators see both.

### US-S2-008 — GRM intake at L1 and L2

- **New processing activity**: New table `grievance_grievance` stores
  reporter name, phone, relationship, and the narrative description
  alongside category, tier, and SLA deadline.
- **Personal-data categories**: Reporter identity + contact + family
  relationship — §3.
- **Lawful basis**: Explicit grievance lodging is consent-based
  (Section 8 DPPA 2019). Anonymous grievances permitted.
- **Data minimisation**: reporter_name/phone/relationship all optional
  (blank=True). Anonymous category allowed (OPERATOR_CONDUCT).
- **Residual risk**: Reporter identity links them to specific
  grievance content. Retention policy needs DPO sign-off — SAD §8.5
  hasn't been written for grievance data yet. **DPO action**: define
  grievance retention (proposal: 5 years after CLOSED).

### US-S2-009 — Programme referral (REF)

- **New processing activity**: New tables `referral_referral` and
  `referral_programmeenrolment`. Outbound webhook sends household ID,
  programme code, and a signed HMAC payload to the partner programme.
- **Personal-data categories**: Identification (household_id) — but
  no personal demographic fields are pushed in the referral webhook.
- **Lawful basis**: Public task; signed DSA per partner.
- **Data minimisation**: The webhook payload deliberately carries
  ONLY the household_id and programme code. The partner pulls fuller
  detail via API-DRS (US-S3-002) under their explicit DSA scope.
  Two-tier release (notify-then-pull) reduces blast radius if a
  partner's webhook endpoint leaks.
- **Residual risk**: Partner's webhook endpoint is outside MGLSD's
  control. HMAC signing detects tampering; replay window not yet
  bounded (TODO for Sprint 5).

---

## Sprint 3 stories

### US-S3-002 — API-DRS scaffold

- **New processing activity**: New tables `data_requests_*` capture
  every bulk extract request: who, under which DSA, what filters,
  what manifest SHA-256 they were given, when it expires.
- **Personal-data categories**: meta-only at this layer — the
  DataRequest row records the *intent* to share, not the data itself.
  The shared payload (rendered at delivery time) inherits the field-
  level minimisation declared in the DSA's allowed_scopes.
- **Lawful basis**: Public task + the partner's signed DSA reference.
- **Data minimisation**: DSA `allowed_scopes` is the single point of
  truth — fields, sub_region_codes, programme_codes, max_rows.
  Requests outside scope are rejected at submit, NOT silently
  truncated. SHA-256 manifest is locked at delivery so partners can
  prove what they received.
- **Residual risk**: A misconfigured DSA could over-grant. The DPO
  must review each DSA before status moves to ACTIVE (today only the
  app-side approval gate exists; the DPO-side review process needs
  a runbook). **DPO action**: draft the DSA-approval runbook.

### US-S3-003 — UPD vital-event auto-commit + 1% sample

- **New processing activity**: VITAL_EVENT (NIRA push, e.g., death)
  and PROGRAMME_STATE changes bypass approver review and commit
  immediately. A deterministic 1% subset is flagged for QA audit.
- **Personal-data categories**: All §3 categories on Member (vital
  events typically touch nin_status, residency_status). The change is
  to the existing row — no new fields persisted.
- **Lawful basis**: Public task; NIRA push under the (pending) NIRA
  MOU; programme state under the partner DSA.
- **Data minimisation**: Auto-commit uses the same diff/version
  pipeline as the manual path — `_write_version()` snapshots only the
  fields that actually changed; no full-row dump.
- **Residual risk**: Bypassing human review concentrates trust in the
  upstream source (NIRA, partner MIS). The 1% deterministic sample
  policy (`sampled_for_audit=True` per `_is_sampled()`) is the
  compensating control. **DPO action**: confirm 1% sample rate is
  defensible; SAD §4.4.4 suggests it but doesn't justify the rate.

### US-S3-004 — GRM SLA-breach reporting

- **New processing activity**: New read endpoints surface lists +
  counts of grievances past their tier SLA.
- **Personal-data categories**: same as the parent GRM table
  (reporter identity + grievance content).
- **Lawful basis**: Public task (supervisor oversight).
- **Data minimisation**: Reuses the existing ABAC scope chain —
  supervisors only see overdue grievances within their sub-region.
- **Residual risk**: None new; the visibility envelope is identical
  to the existing GRM list endpoint.

### US-S3-005 / US-S4-002 — DIH PDM + NUSAF connectors

- **New processing activity**: Two new partner-MIS sources land
  household + member data through the DIH pipeline. NUSAF data
  arrives from Northern Uganda Social Action Fund; PDM from the
  Parish Development Model MIS.
- **Personal-data categories**: All §3 categories.
- **Lawful basis**: Public task + the partner's signed DPA
  (DataProvisionAgreement on the SourceSystem). AC-DIH-DPA-REQUIRED
  rejects connector runs without an active DPA.
- **Data minimisation**: Mappers (`pdm_to_canonical`, `nusaf_to_
  canonical`) discard programme-specific fields (sacco_code,
  project_code) from the canonical payload — they're preserved under
  `_source_keys` for audit lineage but never copied to Household /
  Member columns.
- **Residual risk**: DPAs for PDM and NUSAF are placeholder
  (reference=DPA-PDM-1, DPA-NUSAF-1) — real signed agreements need to
  replace these before the connector is enabled in prod. **DPO
  action**: validate signed DPAs land before is_active=True.

### US-S3-006 — IDV NIRA client seam

- **New processing activity**: New abstraction `NiraClient` with two
  implementations. Mock stays in-process; live is placeholder. No
  data leaves the host until NIRA-O-01 closes.
- **Personal-data categories**: NIN (sensitive, §3) once live wiring
  lands; today none.
- **Lawful basis**: Public task + NIRA MOU (pending).
- **Data minimisation**: NIN sent to NIRA is the only field exposed
  in verify_nin(); demographics returned are stored in NSR only where
  needed.
- **Residual risk**: Live wiring deferred (per defer-external-deps
  policy). When it lands, the DPIA must be revisited to assess
  outbound NIN traffic and NIRA-side data residency.

---

## Sprint 4 stories

### US-S4-001 — API-DRS partner-side ABAC

- **New processing activity**: A new scope value `PARTNER` on
  OperatorScope ties a user to a Partner. DataRequest, DSA, and
  Partner viewsets are now scope-filtered so partner-affiliated users
  see only their own org's data.
- **Personal-data categories**: meta-only (visibility filter on
  existing tables).
- **Lawful basis**: Public task + data minimisation principle.
- **Data minimisation**: Closes a cross-partner leak that existed in
  S3-002 — Partner-A users could see Partner-B's pending requests.
- **Residual risk**: None new; this strengthens an existing control.

### US-S4-002 — DIH NUSAF connector

See combined entry under US-S3-005 / US-S4-002 above.

### US-S4-003 — UPD routing matrix via REF-DATA

- **New processing activity**: New table `update_workflow_
  updroutingrule` makes the (change_type, pmt_relevant) → (role, SLA)
  matrix operations-editable.
- **Personal-data categories**: none (config).
- **Lawful basis**: n/a (no personal data).
- **Residual risk**: An operator with admin access could relax SLAs
  or reassign approver role inappropriately. Admin access already
  goes through Keycloak (US-S2-002, pending); meanwhile the table is
  staff-only and every change is audit-logged by Django admin's
  built-in LogEntry.

### US-S4-004 — RPT additional aggregates (submissions/day, dedup
pending, PMT histogram)

- **New processing activity**: Three new aggregate read endpoints.
- **Personal-data categories**: all returned as counts, no row-level
  data leaves the aggregation.
- **Lawful basis**: Public task (ops oversight).
- **Data minimisation**: Scope filter applies BEFORE aggregation, so
  counts a sub-region operator sees are exactly the rows they could
  have read individually — no inference attack via aggregate
  differencing.
- **Residual risk**: Small-cell counts (e.g., 1 household in a
  sub-region's PMT band 90-99) could be re-identifying when joined
  with external data. **DPO action**: define small-cell suppression
  threshold for RPT outputs in line with UBOS practice.

### US-S4-005 — GRM admin workbench

- **New processing activity**: /admin/grievance/grievance/ now shows
  SLA badges and supports bulk escalate / close.
- **Personal-data categories**: reporter identity is visible in the
  admin list as it always was; the workbench doesn't add new fields.
- **Lawful basis**: Public task.
- **Data minimisation**: Bulk actions delegate to the same services
  used by the REST API — same guards, same audit emission.
- **Residual risk**: Admin access is staff-only; same surface as
  Django admin everywhere else in the project.

---

## DPO action summary

| Action | Owner | Tied to |
|---|---|---|
| Confirm sub-region ABAC is acceptable as MVP gating | DPO | US-S2-003 |
| Define enumerator-GPS purpose limitation in privacy notice | DPO | US-S2-006 |
| Define grievance data retention (proposed: 5y post-CLOSED) | DPO | US-S2-008 |
| Draft DSA approval runbook | DPO | US-S3-002 |
| Confirm 1% auto-commit sample rate is defensible | DPO | US-S3-003 |
| Validate signed DPAs replace placeholders before prod enable | DPO | US-S3-005 / US-S4-002 |
| Re-visit DPIA when NIRA live wiring lands | DPO + Arch | US-S3-006 |
| Define small-cell suppression threshold for RPT | DPO | US-S4-004 |

---

## Next review

Sprint 5 close. The Sprint 5 backlog (TBD) will likely touch UPD
routing extensions, RPT additional aggregates, and the first wiring
of the React console — each of which may add to the action list
above.
