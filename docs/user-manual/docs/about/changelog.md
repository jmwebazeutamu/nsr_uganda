# Changelog

This manual tracks meaningful additions and corrections. For code-level changes see `/docs/api_changelog.md`.

## v0.3 — 27 May 2026

End-to-end notification surface, Open-CR wizard refactor, PMT Dashboard live wiring, DDUP discard path, miscellaneous bug fixes.

### Added

- **Transactional email across 4 workflows** (`apps/security/notifications.send_notification`):
  - **PMT sign-off** — submit notifies MGLSD steward; each sign notifies the next step; final sign emails author + every prior signer with "model ACTIVE"; rejection emails author with verbatim reason.
  - **DSA signing** — chain advance notifies in-console signers (DocuSign already handles step 1); activation emails every signer + `Partner.primary_email`; decline notifies everyone with verbatim reason.
  - **Programme sign-off** — submit notifies NSR Coordinator; each sign notifies next; final sign emails creator + every signer; rejection notifies everyone with verbatim reason.
  - **DRS data requests** — approve / reject / deliver each email partner contact + requester. Delivery email carries manifest SHA-256, row count, expiry timestamp, and integrity-check guidance.
  - Every attempt is audited (`notification.sent` / `notification.failed` / `notification.skipped`). SMTP outages never roll back the workflow transaction.
- **SMTP wiring** (`nsr_mis/settings.py`) — `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_TIMEOUT`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL` read from env. Dev default is the console backend; production points at `comms.quasar.ug:587 TLS`.
- **PMT Dashboard live wiring** (`screens-pmt-dashboard.jsx`) — every section now pulls from `GET /api/v1/admin/pmt/dashboard/` instead of 605 lines of mock. Mock retained as offline fallback for design-preview; eyebrow chip shows `LIVE` / `MOCK PREVIEW` / `loading…` so the operator always knows which path is rendering.
- **PMT Run-now refreshes thresholds + downloadable report** — the operator's Run-now button now also re-runs `recompute_band_thresholds` (was previously split off into the nightly Celery beat). New endpoint `GET /api/v1/admin/pmt/recompute/runs/<id>/report/` returns the run's computational artefacts — run metadata, model context, threshold rows written, distribution summary. `?as=csv` flag for download. Dashboard surfaces "Report (CSV)" + "JSON" buttons after each Run-now.
- **DDUP "Discard duplicate" action** — third compare action between Reject and Merge. Both records ARE the same person but one is bad data; survivor stays untouched, loser is soft-deleted. Reversible through the same 30-day window as a merge. `MergeAction.DISCARD_LOSER` + `POST /api/v1/ddup/match-pairs/<id>/discard/`.
- **Open-CR wizard refactor (US-S28)** — three slices:
  - `GET /api/v1/upd/field-catalog/` — backend-owned catalog with `select` options resolved against the active ChoiceList version per ADR-0010. Modal fetches on mount, drops the duplicated JSX hardcoded `CATEGORIES`.
  - Wizard validation tightening — note gate moved from step 4 (Submit) to step 3 (Next on Evidence), so the disabled state surfaces where the missing input actually is. PMT "Mark PMT-relevant" toggle is no longer locked-on once auto-derived — operator can override either way. No-op detection: step 2 Next disabled if every row's new value matches the current value. Submit-error banner is dismissible with inline Retry. `all_members` entity option removed (no server contract).
  - Per-field input constraints — `hh_size` (1..30), `member_dob` (1900-01-01..today), `land_acres` (≥0 step 0.1), `cattle`/`goats`/`meals`/`fcs` ranges all advertised as HTML5 `min`/`max`/`step` from the catalog.
- **UPD workbench Decided + On-hold tabs** — pending queue gets two new tabs. Decided rows show a `committed` / `rejected` status chip in place of the SLA column; bulk + per-row action affordances hide since they 400 on terminal rows.
- **Unified Approvals queue** (`GET /api/v1/admin/approvals/`) — single round-trip aggregating PENDING_APPROVAL items across ChoiceList, DqaRule, PMTModelVersion. New `Queue → Approvals` sidebar entry in the standalone Admin Console.
- **Social Registry Manager role** — added to the Tweaks "Role" dropdown for testing AC-UPD-NO-SELF-APPROVE flows without swapping accounts. Home dashboard shows approval-centric KPIs.

### Changed

- **PMT rejection is terminal**. A rejected `PMTModelVersion` is now permanently REJECTED — signoffs + audit row stay on record but the version is hidden from the default operator list. Author clones a fresh DRAFT to revise. Earlier the rollback to DRAFT muddied the audit record.
- **Coded fields resolve options at request time** (ADR-0010). Fields tagged `choice_list` in `apps/update_workflow/field_catalog.py` (`urban_rural`, `member_sex`) now ship `{code, label}` pairs from the active ChoiceList. Untagged select fields ship their hardcoded options unchanged.

### Fixed

- **DIH "Staged records" counter was hardcoded `8 of 342`**. Now reads `visibleRows.length` / `rows.length`.
- **DRS Request Detail panel was stuck on a Delivered row when the filter switched to Pending decision**. `current` now resolves against the filtered list; an empty filter hides the panel cleanly.
- **Chatbot nav link unreachable in admin console**. Sidebar footer was `position:absolute` and overlapped the lower nav items; the aside is now a proper flex column with header / scrollable nav / footer slots.
- **Admin console screen polish** — null-safe DDUP projections (per `feedback_jsx_null_safe_projections`), live CL detail meta, DQA description on the list response, refdata-geography search reset on level change.

### Operational

- A two-console architecture is live: operator console at `/console/` and standalone Admin Console at `/admin-console/`. Approvals + PMT Configuration + Roles & Scopes live in the Admin Console; reviewer workflows (DIH, UPD, GRM, DRS) live in the operator console.

## v0.1 — 25 May 2026

First cut. Created the MkDocs scaffold, the four audience guide indexes, the 17 module reference pages, and the glossary. Built against sessions S0 through S4.

### What is documented

- System Administrator guide (install, env, Keycloak pointer, reference-data loaders, connectors, observability, DPIA, runbooks).
- Data Steward guide (DQA Rule Editor, violations dashboard, dedup, DIH review queue, household detail, UPD review).
- Field officer guide (walk-in capture; CAPI, lookup, grievance, update pages stubbed with Planned badges).
- MDA Partner guide (onboarding, DSA lifecycle, query builder, field selector, portal, API reference).
- Module reference (17 modules, one page each, with status badge, endpoints, screens, ADRs, story IDs).

### What is not yet documented

- CAPI tablet operating procedures (Planned — S8 once US-117 and US-118 land).
- Single Registry / Beneficiary Data Exchange (Planned — US-058 to US-062 not started).
- Production deployment runbook (Planned — once Helm chart lands under `/infrastructure/helm/`).
- The full DRS delivery flow (Planned — US-099 to US-104).
- Outbound API consumer SDK (Planned — US-S6 onwards).

### Known gaps in v0.1

- The Field officer guide leans heavily on screenshots that don't exist yet. The pages describe behaviour from the JSX screens under `/design/v0.1/screens/`.
- The Partner API reference points to the Swagger UI rather than reproducing the spec. This is on purpose — the Swagger UI is generated from code and is always current.
- Helm and Terraform runbook pages are placeholders.
