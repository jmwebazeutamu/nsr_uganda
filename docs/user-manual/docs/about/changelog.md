# Changelog

This manual tracks meaningful additions and corrections. For code-level changes see `/docs/api_changelog.md`.

## v0.4 — 25 September 2026

A week of GRM work, and a review of the whole manual against the code.

### Added

- **[GRM Officer / Case handler](../grm/index.md)** — eight new
  task-oriented pages for the people who *work* the grievance queue,
  with eleven workflow diagrams. The manual previously told Parish
  Chiefs how to raise a grievance and nobody how to handle one.
- **Case numbers.** Grievances, change requests, data requests and
  referrals now carry a number people can quote — `GRM-2026-0001`,
  `UPD-`, `DRS-`, `REF-` — beside their ULID. Documented on each
  module page and in [Finding a case](../grm/finding-a-case.md).
- **Mermaid is served from this site**, not from unpkg. Diagrams now
  render on a network with no outbound internet, which the NITA-U data
  centre may well be.

### Corrected — these pages were wrong, not merely out of date

- **[Grievances (GRM)](../field/grievances.md)** described **three**
  tiers; there are four (L1 Parish Chief, L2 CDO, L3 District M&E, L4
  NSR Unit). It gave SLAs in days; they are hours. It listed a
  `triaged` state that does not exist. It said the routing matrix
  "lives in REF-DATA as a ChoiceList"; it never did. And it described a
  per-case confidentiality flag hiding fraud cases from L1 and L2
  operators — **no such flag exists**, and that is now recorded as an
  open item rather than left implied.
- **[SEC](../modules/sec.md)** named two `AuditEvent` columns that do
  not exist: `row_hash` and `created_at` are `self_hash` and
  `occurred_at`. Any query built from this page has never worked.
- **[UPD](../modules/upd.md)** listed two entities that were never
  built — `ChangeRequestDiff` and `RoutingDecision`. It also said
  no-self-approve was pending; it is enforced, as a 403.
- **[REF-DATA](../modules/ref-data.md)** claimed ownership of the UPD
  routing matrix. Routing is `apps.update_workflow.UpdRoutingRule`.
- **[Reference data loaders](../admin/reference-data.md)** said only
  four of the seven geographic levels carried data. All seven do.

### Corrected — a sweep of every API path and entity name

Every `/api/v1/…` path and every entity name in this manual was
resolved against the code. **40 of the 122 paths did not exist**, and
eleven entities had been described that were never built.

Paths, now corrected:

| Page said | It is |
|---|---|
| `/api/v1/dih/staged-records/`, `/api/v1/dih/runs/` | `stage-records`, `connector-runs` |
| `/api/v1/ddup/candidates/`, `match-models/`, `merge/` | `match-pairs/`, `model-versions/`, `match-pairs/{id}/merge/` |
| `/api/v1/pmt/configurations/`, `scores/{id}/` | `model-versions/`, `results/` |
| `/api/v1/dqa/violations/` | `/api/v1/dqa/results/` |
| `/api/v1/admin/workflow/dqa/rules/{id}/v{n}/sign/` | `/api/v1/dqa/rules/{id}/approve/` |
| `/api/v1/partners/dsas/…` | `/api/v1/dsas/…` |
| `/api/v1/idv/verify/`, `results/{id}/` | the module serves one route, a sandbox mock |
| `/api/v1/drs/requests/{id}/deliveries/…` | `/api/v1/drs/requests/{id}/download/` |

Entities that were never built: `ChangeRequestDiff`, `RoutingDecision`,
`MatchCandidate`, `MatchModel`, `PmtConfiguration`, `PmtScore`,
`IdvResult`, `RawRecord`, `Delivery`, `BuilderSchema`,
`ProgrammeLifecycleEvent`, `VitalEvent`, `SourceCredential`,
`StagedRecord`, and a `Relationship` table.

Two routes this manual has always documented **do not exist and are not
planned**: committing a change request over HTTP (it runs in-process on
approval) and reading a household's version chain. Both are now struck
through and labelled on their pages rather than quietly deleted, so a
reader who built against them finds out.

!!! note "This cannot drift silently again"
    `tests/contract/test_manual_api_paths.py` resolves every documented
    path against the URLconf and checks every named entity against the
    app registry. Prose drifts from code — that is what prose does. The
    console has the same guard for the same reason.

### Changed

- **[UPD](../modules/upd.md)** — the routing table is now the only
  source; a combination with no active row refuses rather than falling
  back to a constant. The failure mode this created in production, and
  what to do when adding a `ChangeType`, are written up on the page.
- **[DAT-DDUP](../modules/dat-ddup.md)** — matching policy lives in the
  approved model version with no defaults. Tier 1 only in production;
  tiers 2 and 3 declared and off. Auto-merge is off. Discovery now
  actually runs.
- **[DAT](../modules/dat.md)** — geography is denormalised onto
  `Household` as seven `*_code` columns beside the seven foreign keys.
- **[SEC](../modules/sec.md)** — repeat reads inside a five-minute
  window are folded into one audit row. 91% of the chain had been one
  browser tab polling badges.

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
