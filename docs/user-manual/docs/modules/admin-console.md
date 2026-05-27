# Admin Console

!!! info "Status"
    **Built and in use** — second front-end behind the same backend (per HANDOFF 2026-05-22). Refdata for choicelists + geography, workflow API for DQA / DDUP / routing, snapshots, group-gated permissions.

The Admin Console is a separate React bundle from the operator console. Same backend, narrower audience. NSR Unit and System Administrators live here.

## What it does

Hosts the surfaces that change system configuration: rules, models, reference data, routing, security. Gated by group membership (`IsAdminConsoleUser`).

## Where it lives

| Path | What |
|---|---|
| `apps/admin_console/` | Django app |
| `apps/admin_console/admin_api_urls.py` | The DRF surface (mounted at `/api/v1/admin/`) |
| `apps/admin_console/urls.py` | The HTML surface (mounted at `/admin-console/`) |
| `/design/v0.1/screens/screens-admin*.jsx`, `app-admin.jsx` | Admin Console screens |

## Sections

| Section | Screen | What you do |
|---|---|---|
| **Queue — Approvals** | `screens-admin-approvals.jsx` | Single round-trip across CL / DQA / PMT pending approvals — no more walking five sub-screens to find what needs signing (v0.3) |
| Eligibility — PMT Dashboard | `screens-pmt-dashboard.jsx` | Read-only operational dashboard. Live data from `/api/v1/admin/pmt/dashboard/`. Run-now button refreshes snapshots + thresholds + writes a downloadable CSV/JSON report (v0.3) |
| Eligibility — PMT Configuration | `screens-pmt-configuration.jsx` | DSL variable editor, calibration metadata, three-step sign-off chain. Lives off `/api/v1/admin/pmt/versions/` (v0.3 live wiring) |
| Reference data — Geography | `screens-admin-refdata-geography.jsx` | Browse UBOS, mark superseded, version splits |
| Reference data — ChoiceLists | `screens-admin-refdata-choicelists.jsx` | Edit ChoiceLists with dual-approval |
| Workflow — DQA | `screens-admin-workflow-dqa.jsx` | DQA Rule Editor |
| Workflow — DDUP | `screens-admin-workflow-ddup.jsx` | Match-model versioning |
| Workflow — Routing | `screens-admin-workflow-routing.jsx` | UPD + GRM routing matrix |
| Security — Roles | `screens-admin-security-roles.jsx` | Role catalogue (read-only mirror of Keycloak) |
| Security — Audit | `screens-admin-security-audit.jsx` | Audit chain reader |
| Assistant — Chatbot | `screens-chatbot-assistant.jsx` | RAG over the user manual; ADR-0021 |
| Partners | `screens-partners.jsx`, `screens-dsas.jsx` | Partner catalogue + DSA management |
| Programmes | `screens-programmes.jsx`, `screens-programme-detail.jsx` | Programme catalogue |

### Approvals queue (v0.3)

`GET /api/v1/admin/approvals/` aggregates every PENDING_APPROVAL item across:

- `ChoiceList` (reference-data drafts)
- `DqaRule` (DQA rule drafts)
- `PMTModelVersion` (sign-off chains awaiting steward / DG)

Returns one row per pending item with `kind`, `id`, `name`, `version`, `author`, `submitted_at`, `next_signer_role`. The sidebar entry under **Queue → Approvals** opens the unified workbench; clicking a row deep-links into the corresponding module's detail screen.

DDUP versions are intentionally excluded — DDUP doesn't expose a submit/sign REST surface yet (`workflow_api` only ships list/detail/clone). Add them once the lifecycle endpoints land.

## Permissions

Gated by `IsAdminConsoleUser` (membership in the `admin-console` Django group, mirrored from Keycloak roles `NSR_UNIT_COORDINATOR` and `SA`).

## Snapshots

The console captures point-in-time snapshots of mutable config (rules, models, routing matrix) so a rollback can target a known-good baseline.

## ADRs

- [ADR-0009](../appendices/adrs.md) — Admin and Console UI strategy

## Stories

US-S10-002, US-S10-005, US-S11-001, US-S12 (Admin Console UI strategy).
