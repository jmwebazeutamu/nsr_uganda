# ADR-0024: Consent Management module (apps/consent / SEC)

- **Status**: Proposed
- **Date**: 30 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, MGLSD Legal, Engineering Lead
- **References**: SAD §4 (modules), §5 Appendix C (Consent entity), §8 (Security), §8.5 (retention); DPIA §1 (lawful-basis matrix), §14 (this module's addendum); ADR-0001 (architecture style); ADR-0002 (ULID ids); ADR-0005 (sub-region partitioning); ADR-0019 (sensitive-field encryption); ADR-0022 (DQA expression language); `/design/consent-handoff/` (designer handoff); US-CONSENT-01..18.

---

## Context

The SAD (§5 Appendix C) and the DPIA (§1) name a per-member, per-purpose `Consent` entity. It was never implemented. Until this build the registry carried only a single `Household.current_consent_state` CharField (never written by any code path — confirmed by grep: declared in the 0001 migration, read in two places, assigned nowhere) and a `consent` field threaded through the Kobo connector. There was no purpose catalogue, no statement versioning, no withdrawal flow, no propagation into PMT/REF/DRS, and no audit-chain coverage of consent changes.

That gap is a DPPA 2019 compliance hole: the Act requires consent to be specific, informed, recorded, and withdrawable, and requires the controller to demonstrate it. A single boolean cannot represent nine distinct purposes with different lawful bases, three of which are non-consent bases (public task, statistical exemption) that must NOT present a withdrawal affordance.

This ADR records the decisions made building the module across Sprints S27–S28 (US-CONSENT-01..18). The four user-facing decisions (purpose catalogue, legacy backfill, DPA fast-track ratification, citizen-portal auth) were locked with the user on 2026-05-30 before any code was written; this document records the rationale and consequences.

## Decision

### D1. New app `apps/consent/`, modular-monolith, owns its data + services + API + admin.

`apps/consent/` follows the repo app convention (models / services / api with inline serializers / urls / admin / tasks / checks / tests). It exposes one public helper, `services.consent_state(member_id, purpose_code)`, that DAT, PMT, REF, DRS, GRM, IDV, and UPD call. No raw SQL outside `data_management`/`ingestion_hub`; the consent app uses the ORM. The REF candidate-list gate (US-CONSENT-13) is the one row-level filter expressed as a SQL `WHERE` clause through the ORM, so an application-layer bug cannot leak un-consented rows (CR7).

### D2. Feature flag `CONSENT_MODULE_ENABLED`, transparent-allow when off.

All `/api/v1/consent/` endpoints return **503** when the flag is off (mirrors the Data Explorer `FeatureFlagOff` pattern, ADR-0023 — 503 not 403 so "feature dark" ≠ "forbidden"). Every downstream gate calls `consent_state()`, which returns the `TRANSPARENT_ALLOW` sentinel when the flag is off, so existing PMT/REF/DRS/DDUP/UPD/DIH behaviour is byte-for-byte unchanged until the flag flips. Default tracks `DEBUG` (on in dev/CI, off in production until DPO sign-off).

### D3. Purpose catalogue: the scope-doc nine **including `ELIGIBILITY`** (CONSENT-O-01).

The designer's handoff inferred a ninth purpose `IDENTITY_VERIFICATION` and omitted `ELIGIBILITY`; the scope doc has `ELIGIBILITY` and no `IDENTITY_VERIFICATION`. We seed the scope-doc list: `REGISTRATION, ELIGIBILITY, REFERRAL, PAYMENTS, COMMUNICATIONS_SMS, COMMUNICATIONS_USSD, RESEARCH, STATISTICS, GRIEVANCE_CONTACT`.

Rationale: PMT recompute (US-CONSENT-12) gates on `ELIGIBILITY`; seeding the designer list would leave that gate with no record to read and it would silently no-op. The DPIA (§1, and §14.2) treats NIRA identity verification as a **public-task activity**, not a consent purpose, so `IDENTITY_VERIFICATION` does not belong in a consent catalogue. The frontend `consent-shared.jsx` `PURPOSES` array is reconciled to match (add `ELIGIBILITY`, drop `IDENTITY_VERIFICATION`).

### D4. Enums are TextChoices, not seeded bootstrap tables.

`LawfulBasis`, `ConsentState`, `CapturedVia`, `CaptureMethod`, `TicketState`, lifecycle statuses, and `WithdrawalDecisionType` are Django `TextChoices` — the repo norm (`GeographicUnit.Level`, `AuditEvent.Action`, `ChoiceListStatus`). Only `ConsentLanguage` is a seeded table, because statement i18n text is keyed by language code and the language set is plausibly extended at runtime. The build prompt's `ConsentLawfulBasis` bootstrap table is dropped: it bought runtime configurability the catalogue does not need and added migration + admin surface. `ChoiceList` (US-116) is reserved for questionnaire code-lists and is deliberately not reused here.

### D5. Audit chain: emit an `AuditEvent` per change; ConsentRecordVersion is NOT hash-chained.

The only hash-chained table in the registry is `security_auditevent` (BEFORE-INSERT trigger `security_auditevent_chain_hash`, migration `apps/security/0002`; verifier `apps/security/integrity.py::verify_audit_chain`). The paired `_VersionBase` tables are not chained. So `consent_record_version` follows that precedent: **not** chained. Every consent state change emits one `AuditEvent` (which IS chained) via `apps.security.audit.emit`, and writes a plain `ConsentRecordVersion` row that records the **id of that AuditEvent** (`audit_event_id`). The audit-chain integrity job is extended (US-CONSENT-10) to assert referential completeness — every version row names an AuditEvent — rather than to chain a second table. The build prompt's §3.4 ("the hash trigger extends to consent_record_version") was a misreading of the mechanism and is explicitly not done; a genuine per-table chain would be a new decision with its own trigger and ADR.

### D6. Dual-approval on the catalogue, enforced in services.

`ConsentPurpose` and `ConsentStatementVersion` carry the author/approver lifecycle (`DRAFT → PENDING_APPROVAL → ACTIVE → RETIRED/SUPERSEDED`). `activate_purpose` / `activate_statement` raise `ApprovalError` (translated to HTTP 400 at the API layer) when `approver == author` or the approval note is blank — copied structurally from `apps.dqa.services.approve`. Activating a **material** statement version flags every `GRANTED` record on the purpose `PENDING_RE_CONSENT` (CR2); the pre-commit count is surfaced to the activating DPO.

### D7. Legacy backfill: skipped (no migration 0004).

`Household.current_consent_state` has no writers, so it is blank for every household. A backfill would either fabricate `GRANTED` (legally indefensible) or, per the prompt's literal rule, flip the entire registry to `PENDING_RE_CONSENT` (a national re-consent storm). We seed only the catalogue (0002) and the v3 statement (0003); `ConsentRecord` rows are created at the next real interaction. The deprecated column stays and will be dropped in Sprint 29 after a dual-write deprecation window (the `dwelling_tenure` / US-S22-DE-15 precedent); it is **not** converted to a computed property in this build because it is read by `apps/data_requests/builder_schema.py` and `apps/update_workflow/field_catalog.py`.

### D8. Withdrawal SLA = 30 days; DIH fast-track ratifies once at DPA activation.

Withdrawal tickets carry a 30-day SLA deadline (CONSENT-O-03; DPPA §29 + Regulations 2021), swept hourly by a Celery-beat task that emits `consent.withdrawal.sla_breached` and fires the Slack/email alerter (no-op when unset). DIH fast-track (US-CONSENT-11) writes synthetic `ConsentRecord` rows per the source DPA's declared scope, gated on the DPA being `Ratified` — ratified **once at DPA activation** (CONSENT-O-08), not per batch. A non-ratified DPA holds promotion with `PROMOTION_BLOCKED_DPA_NOT_RATIFIED`.

### D9. Citizen-portal auth is a swappable stub.

Citizen-facing screens (dashboard, withdrawal) mount under `/portal/consent/` with a stub auth context. The Keycloak citizen realm + OIDC flows are a follow-up ADR; nothing in this build depends on the real realm.

## Consequences

- Consent becomes a first-class, audited, withdrawable, per-purpose record. DPPA accountability is demonstrable from the audit chain.
- Thirteen modules gain a consent gate, every one short-circuiting to transparent-allow while the flag is off — zero behavioural change until DPO sign-off.
- The non-withdrawable bases (STATISTICS, and any public-task purpose) never present a withdrawal affordance; the API refuses a withdrawal on them with 400.
- The flag must stay off in production until: DPO sign-off on the catalogue + statement texts, DPO sign-off on the SLA, DPO ratification of DPA scopes for any fast-track source, all Epic-19 contract tests green, and the extended integrity job passing.

## Open items

The seven non-blocking CONSENT-O items (O-02, O-04..O-07, O-09, O-10) are tracked as TODOs against their stories and revisited at sprint review. The citizen-portal Keycloak realm is a named follow-up ADR.
