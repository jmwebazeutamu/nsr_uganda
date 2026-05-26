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
| Reference data — Geography | `screens-admin-refdata-geography.jsx` | Browse UBOS, mark superseded, version splits |
| Reference data — ChoiceLists | `screens-admin-refdata-choicelists.jsx` | Edit ChoiceLists with dual-approval |
| Workflow — DQA | `screens-admin-workflow-dqa.jsx` | DQA Rule Editor |
| Workflow — DDUP | `screens-admin-workflow-ddup.jsx` | Match-model versioning |
| Workflow — Routing | `screens-admin-workflow-routing.jsx` | UPD + GRM routing matrix |
| Security — Roles | `screens-admin-security-roles.jsx` | Role catalogue (read-only mirror of Keycloak) |
| Security — Audit | `screens-admin-security-audit.jsx` | Audit chain reader |
| Partners | `screens-partners.jsx`, `screens-dsas.jsx` | Partner catalogue + DSA management |
| Programmes | `screens-programmes.jsx`, `screens-programme-detail.jsx` | Programme catalogue |

## Permissions

Gated by `IsAdminConsoleUser` (membership in the `admin-console` Django group, mirrored from Keycloak roles `NSR_UNIT_COORDINATOR` and `SA`).

## Snapshots

The console captures point-in-time snapshots of mutable config (rules, models, routing matrix) so a rollback can target a known-good baseline.

## ADRs

- [ADR-0009](../appendices/adrs.md) — Admin and Console UI strategy

## Stories

US-S10-002, US-S10-005, US-S11-001, US-S12 (Admin Console UI strategy).
