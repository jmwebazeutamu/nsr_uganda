# Build prompt — Consent Management module

**Story group:** US-CONSENT-01 through US-CONSENT-18 (new Epic 19)
**Sprints:** S27 (foundations) + S28 (propagation + withdrawal)
**Owner:** implementation lead (Claude Code, sub-agent, or human dev)
**Repo:** `/Users/johnsonmwebaze/nsr_sris_dev/`
**Project memory:** read `/Users/johnsonmwebaze/nsr_sris_dev/CLAUDE.md` first. All rules in that file are binding for this build.
**Date drafted:** 2026-05-30

---

## 1. What you are building and why

The NSR MIS treats consent as a per-member, per-purpose record per SAD §5 Appendix C and DPIA §1. The `Consent` entity is named in the SAD and the DPIA but is not yet implemented. Today there is only a single `current_consent_state` string column on `Household` and a `consent` field passed through the Kobo connector. There is no purpose catalogue, no statement versioning, no withdrawal flow, no propagation into PMT/REF/DRS, and no audit chain coverage.

You are building the full module behind a feature flag (`CONSENT_MODULE_ENABLED`), wiring it into INT, DIH, DAT, DAT-DQA, DAT-DDUP, PMT, REF, UPD, API-DRS, GRM, IDV, SEC, and RPT, and delivering the four already-designed screens plus stubs for the four planned screens.

**Inputs to read before writing code:**

1. `/docs/CLAUDE.md` — binding standards.
2. `/docs/consent_management_scope.md` — full module scope (data model, purposes, withdrawal handling, integration matrix).
3. `/docs/dpia.md` — lawful-basis matrix per activity. The module reuses it.
4. `/docs/01_solution_architecture.docx` §4 (modules), §5 Appendix C (entities), §8 (security), §8.5 (retention).
5. `/design/consent-handoff/README.md` — designer handoff. Hi-fi prototypes for Screens 1, 2, 3, 4.
6. `/design/consent-handoff/SPEC - consent_management_design_prompt.md` — the design brief these screens implement.
7. `/design/consent-handoff/consent-shared.jsx` — canonical vocabulary (`PURPOSES`, `CONSENT_STATE_TONE`, `TICKET_STATE_TONE`, `LANGUAGES`). The frontend must reuse this; the backend enums must match it.
8. The existing `Consent` references already in code: `apps/data_management/models.py` (Household.current_consent_state column), `apps/ingestion_hub/connectors/kobo.py` (consent field on staging), `apps/intake/tests.py` (consent gating in form skip-logic).

**Out of scope for this build:**

- Hard erasure mechanics (US-068). This module triggers erasure requests; it does not execute hard deletes.
- USSD pixel screens. USSD self-service is a Release-2 menu-tree exercise.
- Programme-MIS-side consent UI. Partner programmes own their enrolment terms.
- Citizen-portal authentication (Keycloak realm + flows). Use a stub auth context the portal can swap in; an ADR follow-up handles the realm work.

---

## 2. Resolve before writing any line of code

The scope doc lists 10 open items (Section 13, CONSENT-O-01 through CONSENT-O-10). The build cannot proceed without decisions on these three. Surface them to the DPO + NSR Coordinator before opening the first PR.

1. **CONSENT-O-01** — Final purpose catalogue and which are withdrawable. The designer inferred 9 purposes including `IDENTITY_VERIFICATION` (public task) and `STATISTICS` (statistical exemption); the scope doc names 9 with `GRIEVANCE_CONTACT` instead of `IDENTITY_VERIFICATION` as the ninth withdrawable purpose. Reconcile to one list before seeding.
2. **CONSENT-O-03** — Withdrawal SLA. Default 30 days per DPPA §29 read with the Regulations 2021. Confirm before wiring the SLA-breach alerter.
3. **CONSENT-O-08** — DPA fast-track ratification model. Per-batch attestation or one ratification at DPA activation. Drives the DIH integration shape.

The remaining seven open items are non-blocking for the build; record them as TODOs against the relevant story and surface again in the sprint review.

---

## 3. Architecture decisions

### 3.1 New app

Create `apps/consent/`. Modular monolith per CLAUDE.md. The app owns the data, the services, the DRF endpoints, and the admin views. It exposes a `consent_state(member_id, purpose_code)` helper that DAT, PMT, REF, DRS, GRM, and IDV call. No raw SQL outside `data_management` and `ingestion_hub`; the consent app uses the Django ORM.

### 3.2 Feature flag

`CONSENT_MODULE_ENABLED` defaults to `False` in production until DPO sign-off lands. All API endpoints, admin screens, and downstream consent checks short-circuit to "transparent allow" when the flag is off so existing functionality continues. ADR follow-up: `0024-consent-management-module.md` documents the decision.

### 3.3 Data model

Per scope §5. Eight tables, all under `apps/consent/models.py`:

- `ConsentPurpose` — catalogue.
- `ConsentStatementVersion` — versioned statement text per purpose with i18n JSONB.
- `ConsentRecord` — one row per `(member_id, purpose_id)`, current state.
- `ConsentRecordVersion` — append-only history, paired-version table per SAD §5.3, hashed into the SEC audit chain.
- `ConsentWithdrawalTicket` — withdrawal workflow, owns the 30-day SLA clock.
- `ConsentEvidence` — MinIO-backed signature, thumbprint, witness-statement objects.
- `ConsentLanguage` — bootstrap table seeded with the seven languages in `consent-shared.jsx`.
- `ConsentLawfulBasis` — bootstrap enum table; 6 values matching `BASIS_LABEL` in `consent-shared.jsx`.

IDs are ULIDs per ADR-0002. Sub-region tag inherited from the parent Member's Household for partition routing per ADR-0005.

### 3.4 Audit chain

Every state change emits an `AuditEvent` (SEC) and writes a `ConsentRecordVersion` row. The hash chain BEFORE INSERT trigger established for the existing audit chain extends to `consent_record_version`. Use the same prev/self hash pattern that lives on `security_auditevent` today.

### 3.5 Migrations

Reversible per CLAUDE.md migration policy. Attach the reverse plan to the release ticket. Migration sequence:

1. `0001_consent_module_schema` — tables, indexes, triggers.
2. `0002_consent_seed_purposes` — seed the agreed catalogue from CONSENT-O-01.
3. `0003_consent_seed_statements_v3` — seed v3 statement text in English plus placeholder text for the six other languages with `is_placeholder = True`.
4. `0004_consent_migrate_household_state` — backfill `ConsentRecord` for every existing head member from the legacy `Household.current_consent_state` column. Each row gets `captured_via = LEGACY_BACKFILL`. Reversible by reading from the version history.

---

## 4. Story list (Epic 19)

Each story carries acceptance criteria. Test-first per CLAUDE.md. All consent stories touch audit-bearing code, so unit tests + contract tests are mandatory.

| ID | Title | Sprint | Priority |
|---|---|---|---|
| US-CONSENT-01 | Purpose catalogue CRUD with dual-approval | S27 | Must |
| US-CONSENT-02 | Statement version editor with i18n | S27 | Must |
| US-CONSENT-03 | Intake consent capture (Web) — Screen 1 | S27 | Must |
| US-CONSENT-04 | Intake consent capture (CAPI) | S27 | Must |
| US-CONSENT-05 | Citizen consent dashboard — Screen 2 | S27 | Must |
| US-CONSENT-06 | Withdrawal request flow — Screen 3 | S28 | Must |
| US-CONSENT-07 | DPO withdrawal queue — Screen 4 | S28 | Must |
| US-CONSENT-08 | Household / member consent badge cluster | S27 | Must |
| US-CONSENT-09 | AC-CONSENT-* DQA rules | S27 | Must |
| US-CONSENT-10 | SEC audit chain wiring | S27 | Must |
| US-CONSENT-11 | DIH fast-track synthetic consent record | S28 | Must |
| US-CONSENT-12 | PMT recompute respects ELIGIBILITY consent | S28 | Must |
| US-CONSENT-13 | REF candidate list filters on REFERRAL consent | S28 | Must |
| US-CONSENT-14 | API-DRS extract filter by purpose-mapped consent | S28 | Must |
| US-CONSENT-15 | DDUP merge inherits union of grants | S28 | Must |
| US-CONSENT-16 | UPD head-change re-captures consent | S28 | Must |
| US-CONSENT-17 | DPO coverage dashboard (stub) | S28 | Should |
| US-CONSENT-18 | DPIA addendum + ADR-0024 | S27 + S28 | Must |

Full acceptance criteria are in `03_backlog.xlsx` Epic 19. The detail per story is below.

---

## 5. Story detail

### US-CONSENT-01 — Purpose catalogue CRUD

- Migration creates `consent_purpose`, `consent_lawful_basis` tables.
- DRF endpoints under `/api/v1/consent/purposes/` per scope §10.
- Dual-approval: author ≠ approver enforced in `apps.consent.services.activate_purpose` (raise 400 on self-approval, same pattern as `apps.dqa.services.approve`).
- Admin screen wired into the existing admin console (`/design/v0.1/screens/`). Match Screen 5 from the design brief (not yet built; produce a working stub matching the SEC admin pattern).
- Audit events: `consent.purpose.created`, `consent.purpose.activated`, `consent.purpose.retired`.
- Tests: unit on the service; contract on the API; admin smoke test.

### US-CONSENT-02 — Statement version editor

- Migration creates `consent_statement_version`.
- i18n stored as JSONB `text_i18n` keyed by language code from `ConsentLanguage`.
- `effective_from` / `effective_to` columns; non-overlapping `Active` versions per purpose enforced by a unique partial index.
- `is_material` toggle: on activation, every `Granted` record on the purpose is flagged `Pending re-consent`. The count is shown to the activating DPO before commit.
- Audit events: `consent.statement.created`, `consent.statement.activated`, `consent.statement.superseded`.

### US-CONSENT-03 — Intake consent capture (Web)

- Pixel-match `/design/consent-handoff/Consent - Intake Capture.html` and `screens-consent-capture.jsx`.
- Reuse `consent-shared.jsx` vocabulary verbatim. Do not fork.
- Hard gate: `REGISTRATION = Granted` is required to proceed to the next intake step.
- `REGISTRATION = Refused` opens a refusal-reason modal, writes a `ConsentRecord` row with `state = REFUSED`, terminates the intake with outcome `declined_consent`, and writes a `ConsentRecordVersion` row to the audit chain.
- Optional per-purpose toggles for REFERRAL, PAYMENTS, COMMUNICATIONS_SMS, COMMUNICATIONS_USSD, RESEARCH, GRIEVANCE_CONTACT.
- Capture method: Signature / Thumbprint / Verbal-witnessed / Digital. Verbal requires witness-name + witness-role. Signature and Thumbprint reveal the capture pad; the captured asset uploads to MinIO and the object key writes to `ConsentEvidence.object_key`.
- API: `POST /api/v1/consent/members/{member_id}/capture` per scope §10.
- DQA hook: invoke AC-CONSENT-MANDATORY and AC-CONSENT-METHOD-VALID before commit.

### US-CONSENT-04 — Intake consent capture (CAPI)

- One question per screen per the CAPI pattern in `04_ui_design_brief.md` §11.1.
- Offline-first: writes to SQLCipher local store; queues sync per the existing intake sync pattern.
- Witness capture works offline.
- Sync resolves by `(submission_id, purpose_code)` idempotency.

### US-CONSENT-05 — Citizen consent dashboard

- Pixel-match `/design/consent-handoff/Consent - Citizen Dashboard.html` Screen 2.
- API: `GET /api/v1/consent/members/{member_id}` returns the full matrix.
- Authenticated citizen (self) or operator under assisted access (ABAC-scoped).
- `Withdraw` link visible only when purpose is withdrawable AND state is `Granted`.
- Locked purposes carry a tooltip naming the DPPA provision.

### US-CONSENT-06 — Withdrawal request flow

- Pixel-match `/design/consent-handoff/Consent - Citizen Dashboard.html` Screen 3 modal.
- API: `POST /api/v1/consent/members/{member_id}/withdraw`. Idempotent on `(member_id, purpose_code, requested_at_day)`.
- Creates a `ConsentWithdrawalTicket` with `sla_deadline = now() + interval '30 days'`.
- Returns ticket ID, deadline, and next-step copy.
- Audit event: `consent.withdrawal.ticket_opened`.

### US-CONSENT-07 — DPO withdrawal queue

- Pixel-match `/design/consent-handoff/Consent - DPO Withdrawal Queue.html` Screen 4.
- Filters per the screen.
- Three-column detail (history / impact / decision).
- Decisions: `Confirm`, `Override (public task)`, `Request clarification`, `Hold`. Each writes a `WithdrawalDecision` row and emits `consent.withdrawal.ticket_decided`.
- Bulk Confirm: only when all selected tickets share one consent-basis purpose, zero active referrals, ≤ 50. > 1000 requires a second approver.
- SLA-breach alerter: hourly Celery beat task scans tickets where `now() > sla_deadline` and emits an alert per the existing alerting pattern.

### US-CONSENT-08 — Consent badge cluster

- React component reused on household detail, member detail, DDUP compare, UPD reviewer.
- Reads `GET /api/v1/consent/members/{member_id}` (cache 60s).
- Renders the chip row at 13/18 caption size per the design.
- Click opens the per-purpose history side panel (the existing `AuditDrawer` component from `components.jsx`).

### US-CONSENT-09 — AC-CONSENT-* DQA rules

- New rule family. Author the rule packs in `scripts/seed_dqa_consent_rules.py`, dual-approved per DQA rule editor.
- Rules: `AC-CONSENT-MANDATORY` (registration required for promotion); `AC-CONSENT-METHOD-VALID` (verbal requires witness); `AC-CONSENT-PURPOSE-VERSION-CURRENT` (statement version active at capture); `AC-CONSENT-CAPTURE-TIMESTAMP-PLAUSIBLE` (within window); `AC-CONSENT-MINOR-PROXY-PRESENT` (proxy relationship set for members under 18).
- Rules wired into the existing rule engine. Severity follows the four-tier vocabulary from `04_ui_design_brief.md` §8.
- DPO ratifies the seeded rule pack before activation.

### US-CONSENT-10 — SEC audit chain wiring

- `ConsentRecordVersion` joins the existing audit-chain hash trigger.
- 11 audit event types per scope §11.
- Contract test verifies every state change emits the expected event.
- Audit-chain integrity job extended to verify `consent_record_version`.

### US-CONSENT-11 — DIH fast-track synthetic consent

- `apps.ingestion_hub.services.promote_stage_record` writes a synthetic `ConsentRecord` per purpose declared in the source `DataProvisionAgreement` scope.
- `captured_via = DIH_FAST_TRACK`; `capture_method = DIGITAL`; `evidence_object_key` points to the DPA PDF in MinIO.
- The DPA must be `Ratified` for fast-track to write. Otherwise promotion is held with `PROMOTION_BLOCKED_DPA_NOT_RATIFIED` and routed to the DPO for ratification per the new screen embedded in the DIH ConnectorRun detail.

### US-CONSENT-12 — PMT respects ELIGIBILITY consent

- `apps.pmt.services.recompute_for_household` checks `ConsentRecord` for the head member's `ELIGIBILITY` state before computing.
- `Withdrawn` blocks recompute; existing band freezes; emits `pmt.recompute.blocked.consent_withdrawn`.
- `Pending re-consent` blocks recompute until the citizen re-confirms.
- Existing PMT contract tests extend to cover both branches.

### US-CONSENT-13 — REF respects REFERRAL consent

- Candidate-list query layer filters on `consent_record.state = 'GRANTED'` for `REFERRAL`. Filter is a SQL clause, not an application-layer filter, so an accidental application-layer bug cannot leak data.
- Existing referral contract test extends to cover the filter.
- Active referrals to a member who withdraws REFERRAL flagged via `referral_withdrawal_notify` task; partner programme MIS receives a structured webhook.

### US-CONSENT-14 — DRS respects purpose-mapped consent

- The DRS query builder's preview and export read `ConsentRecord` per row.
- DSA scope maps to one or more consent purposes (RESEARCH-scoped DSA → `RESEARCH` purpose; STATISTICS-scoped DSA → aggregates only, no per-member consent gating).
- Sensitive-fields safeguards in DRS already exist; consent filter adds a row-level gate. Contract test per DSA scope confirms the filter.

### US-CONSENT-15 — DDUP merge consent inheritance

- `apps.ddup.services.commit_merge` reconciles consent records:
  - Union of `GRANTED` per purpose.
  - Any `WITHDRAWN` on either side makes the survivor `WITHDRAWN` for that purpose.
  - Conflicts (one side `GRANTED`, other `REFUSED`) surface in the dedup review queue and block the merge until reconciled.
- Merge audit shows consent reconciliation rationale per pair.

### US-CONSENT-16 — UPD head-change re-consent

- Existing head-change transaction extended: the new head must have an active `REGISTRATION` consent. If none, the transaction opens a re-capture sub-task and routes to the Parish Chief.
- Existing UPD contract tests extend.

### US-CONSENT-17 — DPO coverage dashboard (stub)

- KPI grid + alert list. Stub the charts; wire the KPI cards to live counts.
- Reuse the existing dashboard pattern from `apps/data_requests` DPO console.
- Production-quality charting deferred to a later sprint.

### US-CONSENT-18 — DPIA addendum + ADR-0024

- `/docs/dpia.md` gains a section 14 "Consent Management module" addendum, parallel to the US-S11-044 addendum already in the file.
- `/docs/adr/0024-consent-management-module.md` records the architectural decisions made in this build (feature-flag rollout, dual-approval on purpose catalogue, SLA clock, audit-chain coverage, DIH fast-track model).
- DPO signs off before the feature flag flips on in production.

---

## 6. Definition of Done (per CLAUDE.md §11.5)

Every story:

1. Code merged behind `CONSENT_MODULE_ENABLED` with passing CI (lint, SAST, unit, contract).
2. Acceptance criteria validated by the QA lead.
3. API contract published in `/docs/openapi/consent.yaml`.
4. Audit events emitted and validated by a contract test.
5. Documentation updated: ADR-0024 + DPIA §14.
6. DPIA impact recorded for any story that touches personal data.

The feature flag flips on in production only after:

- DPO sign-off on the seeded purpose catalogue and statement texts (CONSENT-O-01).
- DPO sign-off on the SLA (CONSENT-O-03).
- DPO ratification of DPA scopes for any DIH-fast-track source (CONSENT-O-08).
- All Epic-19 contract tests green.
- Audit-chain integrity job extended and passing.

---

## 7. Existing code touch list

Files you will touch outside `apps/consent/`. Surface in the PR description so reviewers know to look:

- `apps/data_management/models.py` — `Household.current_consent_state` becomes a computed property reading from the new ConsentRecord table; deprecate the column with a follow-up migration in Sprint 29.
- `apps/ingestion_hub/services.py::promote_stage_record` — fast-track consent (US-CONSENT-11).
- `apps/ingestion_hub/connectors/kobo.py` — map source `consent` field into `ConsentRecord` rows on the staged side.
- `apps/intake/views.py` (intake flow) — consent gate at start of intake.
- `apps/intake/tests.py` — existing consent skip-logic tests extend.
- `apps/pmt/services.py::recompute_for_household` — eligibility consent gate.
- `apps/referral/services.py` — referral consent filter.
- `apps/data_requests/services.py` and the query builder — DRS consent filter.
- `apps/ddup/services.py::commit_merge` — consent reconciliation.
- `apps/update_workflow/services.py` (head-change path) — re-consent sub-task.
- `apps/security/audit.py` — extend audit-chain integrity to cover `consent_record_version`.
- `apps/dqa/seed_*.py` — new `scripts/seed_dqa_consent_rules.py`.
- `apps/admin_console/views.py` — Consent (SEC) sidebar group with four entries (Purposes, Statement Versions, Withdrawal Queue, Coverage Dashboard).
- `nsr_mis/settings.py` — `CONSENT_MODULE_ENABLED` flag wiring.
- `nsr_mis/urls.py` — `path("api/v1/consent/", include("apps.consent.urls"))`.

---

## 8. Frontend integration

The four hi-fi prototypes live at `/design/consent-handoff/`. Wire them into the existing admin console under a new "Consent (SEC)" sidebar group:

- `Purposes` → US-CONSENT-01 admin screen (stub at S27, fleshed at S28).
- `Statement versions` → US-CONSENT-02 admin screen (stub at S27, fleshed at S28).
- `Withdrawal queue` → US-CONSENT-07 (prototype at `Consent - DPO Withdrawal Queue.html`).
- `Coverage dashboard` → US-CONSENT-17 (stub).

Citizen-facing screens live under the citizen portal route group (Release 3 in the SAD; for this build, expose under `/portal/consent/` with the stub auth context).

Intake consent capture replaces the existing CONSENT section in `apps/intake` form runtime; the existing skip-logic test in `apps/intake/tests.py` extends to cover the new flow.

Reuse `components.jsx` and `consent-shared.jsx` from the handoff bundle verbatim. The bundle expects them to be the source of truth.

---

## 9. Migration safety

- Migration `0004_consent_migrate_household_state` is large. Run on the staging environment first, validate row counts, then run in production behind a feature flag.
- Existing households with `current_consent_state = 'Yes'` get a `ConsentRecord` with `state = GRANTED`, `captured_via = LEGACY_BACKFILL`, `statement_version_id` pointing to v1 (seeded explicitly for backfill purposes).
- Existing households with `current_consent_state = ''` get a `ConsentRecord` with `state = PENDING_RE_CONSENT` and trigger a re-consent request at the next interaction.
- Rollback plan: drop the new tables and revert to reading the legacy column. Document on the release ticket.

---

## 10. Risks to manage actively

| ID | Risk | Mitigation in this build |
|---|---|---|
| CR1 | Operator coerces verbal consent | Witness mandatory in DQA rule AC-CONSENT-METHOD-VALID; anomaly detection on operator grant-ratio added to RPT in S28 |
| CR2 | Statement supersession invalidates millions of records | `is_material` flag forces re-consent only when set; activation modal shows the count first |
| CR3 | Withdrawal SLA missed at scale | Hourly Celery beat alerter; DPO dashboard surfaces breach risk first |
| CR4 | DIH synthetic consent diverges from DPA scope | DPA must be `Ratified` for fast-track; DPO ratifies at activation |
| CR7 | DRS leaks data without consent purpose match | Filter at SQL query layer; contract test per DSA scope |

Full risk list in `/docs/consent_management_scope.md` §17.

---

## 11. PR shape

Per CLAUDE.md, trunk-based development. Each story ships its own PR. Branch naming: `us-consent-NN-short-description`. Commits: `[US-CONSENT-NN] short description`.

Order the PRs so the dependency graph is respected:

1. US-CONSENT-01 + US-CONSENT-02 + US-CONSENT-10 (foundations) ship first.
2. US-CONSENT-03 + US-CONSENT-04 + US-CONSENT-05 + US-CONSENT-08 + US-CONSENT-09 ship behind the feature flag.
3. US-CONSENT-18 ADR + DPIA addendum lands as part of the S27 sprint review.
4. US-CONSENT-06 + US-CONSENT-07 + US-CONSENT-11 (S28).
5. US-CONSENT-12 through US-CONSENT-16 (S28 propagation PRs).
6. US-CONSENT-17 stub (S28 closing).

---

## 12. What to surface back to the user

Before opening PR 1:

- Confirm the final purpose catalogue (CONSENT-O-01).
- Confirm the SLA (CONSENT-O-03).
- Confirm the DPA ratification model (CONSENT-O-08).
- Confirm the citizen-portal authentication stub is acceptable for this build.

After PR 5 (S28 closing):

- DPO sign-off ceremony before flipping `CONSENT_MODULE_ENABLED` to `True` in production.
- Schedule the audit-chain integrity job to run the new check nightly.
- Schedule the DDUP team to walk through the consent-conflict resolution flow on a real merge before pilot.

---

End of build prompt. Paste into the AI coding agent of your choice; expect two sprints (S27 + S28) to land the full module.
