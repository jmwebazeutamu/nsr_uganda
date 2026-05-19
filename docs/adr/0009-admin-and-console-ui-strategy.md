# ADR-0009: Admin and console UI strategy — `/admin/` is the floor, `/console/` is the ramp

- **Status**: Proposed
- **Date**: 16 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Engineering Lead, NSR Project Manager
- **References**: SAD v0.6 §4, §8.2, §10; ADR-0001 (modular monolith); ADR-0006 (Keycloak realm); `/design/v0.1/acceptance.md`

---

## Context

Two UI surfaces have grown side by side without an explicit contract between them.

`/admin/` is the Django admin. It already covers most write-bearing models: `FormVersion`, `FormSection`, `FormQuestion`, `Submission`, `DqaRule`, `DqaResult`, `Household`, `Member`, `HouseholdVersion`, `MemberVersion`, `Connector`, `ConnectorRun`, `RawLanding`, `StageRecord`, `PromotionDecision`, `PromotionBatch`, `FastTrackAuditSample`, `Quarantine`, `MappingRule`, `MappingRuleVersion`, `DataProvisionAgreement`, `DdupModelVersion`, `MatchPair`, `MergeDecision`, `ChangeRequest`, `UpdRoutingRule`, `Grievance`, `Programme`, `Referral`, `ProgrammeEnrolment`, `PMTModelVersion`, `PMTResult`, `AuditEvent`, `OperatorScope`, `GeographicUnit`, `ChoiceList`, `ChoiceOption`. Several admin pages already carry custom verbs: XLSForm export, FormVersion HTML preview, DQA approve/retire actions, DDUP threshold nudge clones, GRM escalate/close, UPD reject, ConnectorRun "mark stuck", DDUP MergeDecision reverse.

`/console/` is a same-origin shim that serves `/design/` JSX through `nsr_mis.views.console`. It is a runnable design harness, not a deployed app. `/design/v0.1/acceptance.md` lists 13 screens, all built as JSX mocks. The screens cover Capture, DIH review, ConnectorRun dashboard, Dedup compare, UPD reviewer, DRS wizard, DPO console, Household detail, role-aware Home, GRM workbench, Partner DRS portal, and System Admin tabs.

Some models still have no admin registration: `NiraVerificationAttempt` (IDV queue), `Partner`, `DataSharingAgreement`, `DataRequest`. `apps/api_gateway/` and `apps/reporting/` have no admin.

The system will be used by Parish Chiefs, CDOs, District M&E officers, NSR Unit operators, DPOs, and partner analysts. Most are not developers. Field operators in particular need a UI that doesn't require URL knowledge to reach common tasks.

## Decision

We adopt a **two-surface UI strategy**:

1. `/admin/` is the **complete coverage floor**. Every model in the registry and DIH is reachable from `/admin/`. Every write that an operator role can legitimately perform is exposed as either an admin form, an inline editor, or a bulk admin action. Custom admin templates carry the heavyweight tools: FormVersion preview, XLSForm download, DQA rule editor, DDUP merge workbench, ConnectorRun health board. The admin is the audit-safe fallback when the React console is offline, unreleased, or behind for a given module. It is also the surface auditors and DPO use directly because every admin action goes through the same service layer that emits `AuditEvent`.
2. `/console/` is the **friendly ramp**. The React shell at `/design/` becomes a deployed app at `/console/` served by Django in dev and by nginx in production. It targets operator roles by persona, not by table. Every console screen has a corresponding `/admin/` page that does the same job — the console is faster and friendlier, the admin is the source of truth. The console must never carry a write that is not also reachable from `/admin/`.

Concretely:

- **Admin parity is a release blocker.** A module is not Sprint-complete until every model is registered in `/admin/` and every state transition the service layer supports is callable from either an admin form, an inline, or a bulk action. Read-only models stay read-only in admin (`has_add_permission = False`, `has_change_permission = False`).
- **Custom admin templates carry the operator-facing tooling.** The pattern established by `apps/intake/admin.py` (FormVersion preview, XLSForm export, expression validator, drag-to-reorder) is the template for every module that needs a richer surface. Custom URLs live under `admin_site.admin_view(...)` so admin auth and `AuditEvent` emission are inherited automatically.
- **All admin custom actions go through the service layer.** The admin never re-implements a state machine, never bypasses dual approval, never duplicates DQA or DDUP logic. The pattern in `apps/grievance/admin.py` and `apps/dqa/admin.py` (admin action → service function → `AuditEvent`) is binding.
- **The console is graded.** Module-by-module, we ship a React tab for a persona's daily work, while keeping the admin as the fallback. The `AdminScreen` in `screens-admin.jsx` already follows this pattern — two tabs fully built in React, three tabs stub out with a "Open in Django admin" link to the right path. New console work follows that pattern.
- **Identifier discipline carries over.** All externally visible IDs in admin lists remain ULIDs per ADR-0002. URLs to admin records use `/admin/{app}/{model}/{ulid}/change/`.
- **Audit on every admin read of personal data.** Reads of `Household`, `Member`, `Submission`, `Grievance`, `ChangeRequest`, `DataRequest`, `AuditEvent` from admin emit a `dashboard_read` or `record_read` `AuditEvent`, following the pattern in `apps/reporting/views.py`. Admin GET handlers wrap the queryset with `AuditReadMixin` where it doesn't already.
- **Role visibility is enforced at the gateway, not the UI.** Operator roles in Keycloak (per ADR-0006) gate which admin model perms the user sees and which console routes resolve. Partner roles see only `/console/partner-drs/` and have no `/admin/` access at all.

## Consequences

### Positive

- Field operators in rural districts can reach every operational task from a URL bar without a React build. Admin is fully audit-bearing today, so this is the safest fallback.
- The console can be built in slices without leaving holes. A new console screen ships only when its admin equivalent already exists, so coverage never regresses.
- Auditors and the DPO get a single canonical surface that mirrors the API contract. Every admin action emits the same `AuditEvent` as the REST API.
- Training cost stays manageable. Operators learn the admin once for any module; the console is an upgrade, not a replacement.
- No bypassing of DIH, DQA, DDUP, or dual approval is possible by switching surfaces — both surfaces call the same service functions.

### Negative

- Two surfaces means two visual styles. Operators who jump between them notice the inconsistency. We accept this; the console carries the brand and the polish, the admin carries the floor.
- Admin forms for very wide models (Member, Household) are clunky. We mitigate with `fieldsets`, `raw_id_fields`, and read-only computed columns rather than rewriting the form layer.
- Custom admin templates increase test surface. Each one needs a smoke test that the page renders for a logged-in admin user. We add these per module as the templates land.

### Neutral

- Some screens are obviously console-only (Home dashboard, Receipt slip, CAPI capture). Admin equivalents do not exist for those because there's no model to register against. The rule applies to model-bearing operations only.

## Out of scope

- The CAPI Android tablet UI. This ADR covers operator and partner surfaces over HTTPS.
- The developer portal. The OpenAPI Swagger UI at `/api/docs/` is for partner-MDA developers and stays as-is.

## Open items

- **Who signs off console parity per module?** The Engineering Lead signs off admin coverage in the Sprint review. Console parity per module needs a separate sign-off from the NSR Unit Coordinator. Defer until the first three modules' console screens land.
- **Production console deployment.** Today `/console/` is served by Django in dev. In production it ships as a built React bundle behind nginx with its own static-asset cache. The build pipeline is part of US-S12-001 (this story pack).

## Adoption plan

The story pack `docs/stories/US-S12_admin_console_ui_strategy.md` inserts the work into the backlog. The first three sprints of that pack close the admin coverage gaps and stand up the production console build. Subsequent sprints add console screens module by module, prioritised by daily-use volume (DIH review, UPD reviewer, GRM workbench first).

---

Signed off by:

- NSR Unit Coordinator: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________

End of ADR-0009.
