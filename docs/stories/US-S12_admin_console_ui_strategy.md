# US-S12 — Admin coverage and console UI strategy

**Epic:** 18. Operator UX (new). Sits alongside Epic 1 (Intake) and Epic 17 (Questionnaire Authoring).
**Module owners:** all `apps/`, plus `nsr_mis/urls.py` for the console mount, plus `/design/` for the React shell.
**Status:** Not started.
**Filed:** 2026-05-16.
**Anchored to:** ADR-0009 (admin and console UI strategy).

## Why

The system has two UI surfaces today. `/admin/` is the audit-bearing floor that already covers most write-bearing models. `/console/` is a same-origin shim that serves `/design/` JSX mocks. Non-technical operators (Parish Chiefs, CDOs, District M&E, NSR Unit) need to reach every operational task without URL guessing, and partner analysts need a portal that isn't `/admin/` at all.

The current state has three gaps:

1. Some models have no admin registration (`NiraVerificationAttempt`, `Partner`, `DataSharingAgreement`, `DataRequest`).
2. Some admin pages carry no operator-facing tooling beyond the default form (Programme, Referral, ProgrammeEnrolment, PMTModelVersion, GeographicUnit are list-only).
3. The `/console/` route serves design assets, not a deployed React app. There is no production build pipeline.

ADR-0009 makes admin parity a Sprint-completion blocker and grades the console module by module.

## Story map

| # | Story | Priority | Sprint | Depends on |
|---|---|---|---|---|
| S12-001 | Register missing admin models | Must | 23 | — |
| S12-002 | Audit-emit on admin reads of personal data | Must | 23 | S12-001 |
| S12-003 | Operator-facing admin index page | Should | 23 | S12-001 |
| S12-004 | XLS/CSV download actions on operator admin lists | Must | 24 | S12-001 |
| S12-005 | Build pipeline for the React console | Must | 24 | — |
| S12-006 | Console role-gating via Keycloak claims | Must | 24 | S12-005, ADR-0006 |
| S12-007 | DIH review queue console screen (live) | Should | 25 | S12-005 |
| S12-008 | UPD reviewer console screen (live) | Should | 25 | S12-005 |
| S12-009 | GRM workbench console screen (live) | Should | 26 | S12-005 |
| S12-010 | Partner DRS portal (live) | Must | 26 | S12-005, S12-006 |
| S12-011 | Admin/console handoff links | Should | 26 | S12-005 |
| S12-012 | Smoke tests for every admin custom template | Must | 24 | S12-001 |

---

### US-S12-001 — Register missing admin models

**As a** System Admin
**I want** every model in the registry and DIH to be reachable from `/admin/`
**So that** I can edit, view, or audit any record without needing a Python shell

**Acceptance criteria:**

- New `apps/identity_verification/admin.py` registers `NiraVerificationAttempt` with: list_display `(requester, nin_hash_hex, status, attempts, last_error_short, queued_at, last_attempt_at)`; filters on `status`; search on `requester`. Read-only (`has_add_permission = False`, `has_change_permission = False`) since rows land via `queue_verification()`. Bulk action `requeue_failed` calls `queue_verification` on selected FAILED rows after resetting `attempts = 0`.
- New `apps/data_requests/admin.py` registers `Partner`, `DataSharingAgreement`, `DataRequest`. `Partner` is editable. `DataSharingAgreement` carries fieldsets for scope JSON + signature metadata, plus a read-only `expires_in_days` computed column. `DataRequest` is read-only in admin (writes happen through `apps.data_requests.services`); bulk actions: `admin_approve`, `admin_reject`, `admin_expire_now` — each delegates to the service layer.
- `apps/api_gateway/` and `apps/reporting/` remain admin-less (no models to register).
- A unit test in each app's `tests.py` asserts the model classes are registered with `admin.site._registry`.

**Priority:** Must.

---

### US-S12-002 — Audit-emit on admin reads of personal data

**As a** DPO
**I want** every admin GET on personal data to write an AuditEvent
**So that** the audit chain reflects admin reads, not just API reads

**Acceptance criteria:**

- `apps/data_management/admin.py`, `apps/intake/admin.py`, `apps/grievance/admin.py`, `apps/update_workflow/admin.py`, `apps/data_requests/admin.py` override `get_object()` to call `apps.security.audit.emit('record_read', entity_type, entity_id, actor=request.user.username, ...)` on admin detail views.
- Changelist (list view) reads emit one `dashboard_read` per page load with `reason=f"page={page_num},count={result_count}"` — same shape as `apps/reporting/views.py`.
- `AuditEvent` and `OperatorScope` admin do NOT emit on read (they ARE the audit log; recursion would explode).
- A `pytest` test loads each admin changelist as a superuser and asserts at least one `dashboard_read` row landed.

**Priority:** Must.
**Depends on:** S12-001.

---

### US-S12-003 — Operator-facing admin index page

**As a** Parish Chief / CDO / NSR Unit operator
**I want** the `/admin/` landing page to surface my common tasks first
**So that** I don't have to scroll through 30 model registrations

**Acceptance criteria:**

- Override `AdminSite.index_template` with `admin/index.html` under `nsr_mis/templates/admin/`.
- The template renders three sections:
  1. **My queues** — links to filtered changelists scoped to the user's role: DIH review for NSR Unit, ChangeRequest for CDO and District M&E, Grievance for Parish Chief and CDO.
  2. **Configuration** — DqaRule, ChoiceList, FormVersion, UpdRoutingRule, Programme, Partner, DataSharingAgreement, PMTModelVersion, DdupModelVersion.
  3. **Audit & reference** — AuditEvent, OperatorScope, GeographicUnit.
- A "Open the operator console" button at the top links to `/console/` and is visible only when the user has a console-eligible role claim.
- Sections that match no app the user has perms for are hidden, not greyed out.

**Priority:** Should.
**Depends on:** S12-001.

---

### US-S12-004 — XLS/CSV download actions on operator admin lists

**As a** District M&E officer
**I want** to export the current admin filter as XLSX or CSV
**So that** I can hand the data to a programme manager without writing a query

**Acceptance criteria:**

- Add a shared admin mixin `ExportableAdminMixin` in `nsr_mis/admin_utils.py` that adds two bulk actions: `export_xlsx` and `export_csv`. The mixin renders the current `list_display` columns into a streaming XLSX or CSV response.
- Apply the mixin to `HouseholdAdmin`, `MemberAdmin`, `GrievanceAdmin`, `ChangeRequestAdmin`, `ReferralAdmin`, `PMTResultAdmin`, `DqaResultAdmin`, `ConnectorRunAdmin`, `StageRecordAdmin`, `FastTrackAuditSampleAdmin`, `DataRequestAdmin`.
- The export honours the current filter and search query (uses `self.get_changelist_instance(request).get_queryset(request)`).
- Each export emits one `AuditEvent` with `action='admin_export'`, `entity_type=<model>`, `entity_id=<filter_signature>`, and a row count in `reason`.
- NIN columns are masked to last 4 chars in exports — never plaintext, never the hash.
- Cap: 50k rows per export; over that, the action raises a `messages.WARNING` instructing the operator to use DRS instead.

**Priority:** Must.
**Depends on:** S12-001.

---

### US-S12-005 — Build pipeline for the React console

**As a** NSR Unit operator
**I want** `/console/` to serve a built React bundle in production
**So that** the screens render without Babel-standalone runtime in the browser

**Acceptance criteria:**

- New `console/` folder at the repo root, NOT under `/design/`. It carries the production React + Vite project. `/design/` stays as the design source-of-truth.
- `console/package.json` declares `vite`, `react`, `react-dom`, `react-router-dom`. No Babel-standalone in production.
- The build outputs to `console/dist/`. A GitHub Actions / GitLab CI job builds on every merge to main and publishes the bundle as a CI artefact.
- The Django `console` view in `nsr_mis/views.py` is replaced with two modes: in `DEBUG=True` it serves the design harness as today; in `DEBUG=False` it serves `console/dist/index.html` with React assets under `/console/assets/`.
- The production deploy chart in `infrastructure/helm/` mounts the built bundle into nginx in front of Django. Same-origin cookies still work because nginx proxies `/api/v1/*` to Django.
- The first commit contains a "hello world" React page that lists the user's role claim — enough to prove the auth pass-through works end to end.

**Priority:** Must.

---

### US-S12-006 — Console role-gating via Keycloak claims

**As a** DPO
**I want** the console to render only the screens a user's role is allowed to see
**So that** a partner analyst never sees `AdminScreen` and an operator never sees the partner portal

**Acceptance criteria:**

- The console reads `realm_access.roles` from the Keycloak ID token via a `/api/v1/security/whoami/` endpoint (new). The endpoint returns `{username, roles, scope_level, scope_code}`.
- The console's React router gates each route by role per the table in ADR-0006: `PARTNER_ANALYST` and `PARTNER_DPO` see only `/console/partner-drs/` and `/console/home/`; `PARISH_CHIEF` and `CDO` see capture + GRM + UPD; `NSR_UNIT` sees DIH + admin tabs + everything operator-facing; `DPO` sees everything read-only plus DPIA artefacts.
- A route the role can't see returns a 403 React page with a "back to home" link. No silent redirects.
- Tests: one parametric test per role asserts the visible nav items match the expected set.

**Priority:** Must.
**Depends on:** S12-005, ADR-0006.

---

### US-S12-007 — DIH review queue console screen (live)

**As a** NSR Unit operator
**I want** the DIH review queue to render live data, not mock data
**So that** I can promote, hold, or reject staged records from the console

**Acceptance criteria:**

- Port `screens-dih.jsx → <DIHScreen>` from `/design/v0.1/screens/` into the production `console/src/screens/`.
- Reads from `/api/v1/dih/stage-records/` with the existing pagination and filter contract.
- Writes (Promote / Promote-as-merge / Hold / Reject) call `/api/v1/dih/promote/` and friends; each opens the reason modal already in the JSX mock and persists the reason on the resulting `PromotionDecision`.
- The page header carries an "Open in `/admin/ingestion_hub/stagerecord/`" link for the audit-trail fallback (per ADR-0009 §3, every console screen links to its admin equivalent).
- Per-screen acceptance gates from `/design/v0.1/acceptance.md` §3 (DIH review queue) all pass.

**Priority:** Should.
**Depends on:** S12-005.

---

### US-S12-008 — UPD reviewer console screen (live)

**As a** CDO
**I want** the UPD reviewer to render live ChangeRequests
**So that** I can approve or reject updates from the console with PMT preview

**Acceptance criteria:**

- Port `screens-upd.jsx → <UPDScreen>` into `console/src/screens/`.
- Reads `/api/v1/upd/change-requests/?status=pending_approval`.
- Writes call the existing approve/reject endpoints; AC-UPD-NO-SELF-APPROVE is enforced by the service layer and surfaced in the UI as a disabled button with the same tooltip as today.
- Bulk actions S11-004 (`Bulk approve / Bulk reject / Bulk escalate`) carry over from the mock, hitting the existing bulk endpoints.
- Header carries `/admin/update_workflow/changerequest/` link.
- Per-screen gates from `/design/v0.1/acceptance.md` §6 pass.

**Priority:** Should.
**Depends on:** S12-005.

---

### US-S12-009 — GRM workbench console screen (live)

**As a** Parish Chief
**I want** the GRM workbench to render live grievances
**So that** I can triage, escalate, resolve, and close from the console

**Acceptance criteria:**

- Port `screens-grm.jsx → <GRMScreen>` into `console/src/screens/`.
- Reads `/api/v1/grm/grievances/` with the same filter chips as the mock (`past-sla`, `open-l1`, `escalated`, `mine`).
- Writes call the existing assign/escalate/resolve/close endpoints. Reason + 6+ char note enforced client-side; server validates and returns 400 with the service-layer message on violation.
- Header carries `/admin/grievance/grievance/` link.
- Per-screen gates from `/design/v0.1/acceptance.md` §11 pass.

**Priority:** Should.
**Depends on:** S12-005.

---

### US-S12-010 — Partner DRS portal (live)

**As a** partner analyst
**I want** a portal to submit, track, and download my DRS requests
**So that** I don't need access to `/admin/`

**Acceptance criteria:**

- Port `screens-partner-drs.jsx → <PartnerDRSScreen>` into `console/src/screens/`.
- Reads `/api/v1/drs/requests/mine/` (S7-004 scoped queryset). Downloads through `/api/v1/drs/requests/{id}/download/` (S8-003, rate-limited per S9-003).
- Builder mode reuses `<DRSScreen>` with `role="partner"` per UI-PDRS-BUILDER-1.
- SHA-256 verification panel UI-PDRS-10 computes hash in-browser via Web Crypto; nothing leaves the browser.
- Role gating per S12-006: visible only to `PARTNER_ANALYST` and `PARTNER_DPO`; the side nav for these roles shows ONLY Home and Partner DRS.
- Per-screen gates from `/design/v0.1/acceptance.md` §12 pass.

**Priority:** Must.
**Depends on:** S12-005, S12-006.

---

### US-S12-011 — Admin/console handoff links

**As a** NSR Unit operator
**I want** every console screen to expose a link to its `/admin/` equivalent
**So that** I can drop down to the audit-trail surface when I need it

**Acceptance criteria:**

- Each screen's `PageHeader` (per `components.md`) carries a secondary action `Open in /admin/...` that resolves to the right Django admin URL.
- The reverse: each operator admin changelist (`Household`, `Member`, `Grievance`, `ChangeRequest`, `StageRecord`, `DataRequest`) gets a header link "Open in console" that resolves to the equivalent `/console/...` route. Visible only when the user has a console role claim.
- A unit test asserts every screen → admin URL resolves to a registered admin (`admin.site._registry` contains the model).

**Priority:** Should.
**Depends on:** S12-005.

---

### US-S12-012 — Smoke tests for every admin custom template

**As an** engineering lead
**I want** every custom admin URL and template to have a smoke test
**So that** the admin doesn't 500 in production for a model an operator depends on

**Acceptance criteria:**

- One pytest per custom admin URL: `FormVersion preview`, `XLSForm export`, `expression validator`, `reorder section`, `reorder question`, `DqaRule submit/approve/retire actions`, `DdupModelVersion nudge actions`, `MergeDecision reverse`, `Grievance escalate/close`, `ChangeRequest reject`, `ConnectorRun mark-stuck`.
- Each test logs in a superuser, hits the URL or triggers the action, and asserts a 200 (or 302 on POST), plus that exactly one `AuditEvent` lands when the action is mutating.
- Tests run in CI as part of the existing unit-test job.

**Priority:** Must.
**Depends on:** S12-001.

---

## Sprint placement

- **Sprint 23 (Foundation):** S12-001, S12-002, S12-003.
- **Sprint 24 (Pipeline + polish):** S12-004, S12-005, S12-012.
- **Sprint 25 (First two console screens):** S12-007, S12-008.
- **Sprint 26 (Partner surface + handoffs):** S12-006, S12-009, S12-010, S12-011.

Each Sprint must close all listed stories before the next Sprint's console work starts. Admin coverage is the floor; the console is the ramp.

---

## Open items

- **OI-S12-1.** Per-screen Keycloak role mapping. ADR-0006 lists the realm roles; we need one mapping table per console screen. Owner: DPO + Engineering Lead. Due before S12-006.
- **OI-S12-2.** Production console asset CDN — does NITA-U host the bundle locally or do we use an external CDN? Owner: NITA-U Infrastructure Lead. Due before S12-005.
- **OI-S12-3.** Console offline support for rural districts with intermittent connectivity. Defer to a follow-up story pack; not in scope for S12-005.

End of US-S12.
