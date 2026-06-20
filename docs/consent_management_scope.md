# Consent Management — Scope

**Status**: Draft for product + DPO review
**Owner**: NSR MIS Architecture + Data Protection Officer (MGLSD)
**Date**: 2026-05-30
**Backlog anchors**: US-010 (intake consent), US-065 (citizen consent dashboard), US-068 (retention + erasure)
**SAD anchors**: §4 SEC, §5 (Consent entity), §8.1 lawful basis, §8.5 retention, §10 subject rights; DPIA §1, §4, §7, §10
**Statutory basis**: Data Protection and Privacy Act 2019 (Uganda) §7 (lawful basis), §8 (children), §9 (sensitive data), §24-29 (rights)

---

## 1. Summary

Consent management lets the head of household opt in or out of the National Social Registry, and where the law permits, opt in or out of specific downstream purposes. The module captures consent at intake, persists a versioned record per member per purpose, exposes a citizen-facing view and withdrawal flow, and propagates the consent state to every downstream module (DIH, DAT, PMT, REF, GRM, API-DRS, IDV).

Consent is not a single boolean. The SAD already names a `Consent` entity per member per purpose (§5 Appendix C). The DPIA already maps lawful basis per activity (§4). This scope wires those declarations into a working module.

## 2. In scope

- Configurable consent purpose catalogue (admin-managed, dual-approved).
- Versioned consent statement text per purpose, per language (English + 6 major Ugandan languages).
- Per-member, per-purpose `ConsentRecord` with capture method, witness, timestamp, version pointer.
- Granular withdrawal per purpose, plus full withdrawal from the registry.
- Consent state machine and propagation to downstream modules.
- Citizen portal consent dashboard with assisted access at parish offices.
- Operator capture screens on CAPI and Web.
- USSD lookup of current consent state (Release 2).
- Audit chain entries for every grant, refusal, change, and withdrawal.
- Lawful-basis tagging so non-consent activities (public task under §7(2)) keep running when consent is withdrawn for consent-based purposes.

## 3. Out of scope (handled elsewhere or later)

- Hard erasure mechanics. Handled by US-068 + retention service. This module triggers erasure requests; it does not execute hard deletes.
- Partner-side consent propagation. Once a record leaves under a DSA, the partner is the controller for their copy. The scope here is the source registry.
- Programme-level eligibility consent (e.g. PDM, NUSAF specific terms). Programme MISes capture their own enrolment consent. NSR records a referral-time consent; programme-side terms are out of scope.
- DPA-driven inbound provider consent. Source systems (UBOS, Kobo) declare lawful basis at DPA signing per DIH spec; this module reads but does not negotiate the DPA.
- Cross-border consent. None at MVP per DPIA §6.

## 4. Purpose catalogue (initial)

Configurable. Seeded with the purposes below. New purposes require dual-approval (author ≠ approver) under SEC rules.

| Code | Purpose | Lawful basis (DPPA 2019) | Subject to withdrawal? | Default state |
|---|---|---|---|---|
| `REGISTRATION` | Inclusion in the NSR | Consent §7(1) + Public task §7(2)(b)(i) | No (registry inclusion is statutory mandate). Withdrawal triggers de-listing review by DPO. | Required to proceed |
| `ELIGIBILITY` | Use in PMT scoring and vulnerability targeting | Public task §7(2)(b)(i) | No (statutory). DPO can override on request. | On by default |
| `REFERRAL` | Share to programme MIS for enrolment | Consent + DSA | Yes | Opt-in at intake |
| `PAYMENTS` | Use account/phone for benefit disbursement | Consent + contract §7(2)(b)(iv) | Partial (withdrawal halts new payments) | Opt-in at enrolment |
| `COMMUNICATIONS_SMS` | Status SMS, payment alerts, recertification reminders | Consent | Yes | Opt-in at intake |
| `COMMUNICATIONS_USSD` | USSD push notifications | Consent | Yes | Opt-in at intake |
| `RESEARCH` | Anonymised or pseudonymised research extracts | Consent or research exemption §7(2)(b)(v) | Yes | Opt-in at intake |
| `STATISTICS` | UBOS / public statistics aggregates | Public task + statistical exemption | No (aggregates only) | On by default |
| `GRIEVANCE_CONTACT` | Contact you about a grievance you filed | Consent | Yes | Opt-in at GRM filing |

This catalogue is the initial seed. Treat it as a draft for DPO + MGLSD legal review.

## 5. Data model

### Tables

**`consent_purpose`**
- `id` ULID
- `code` (e.g. `REFERRAL`), unique
- `display_name_i18n` JSONB
- `lawful_basis` enum (`CONSENT`, `PUBLIC_TASK`, `CONTRACT`, `VITAL_INTEREST`, `LEGAL_OBLIGATION`, `STATISTICAL_EXEMPTION`)
- `withdrawable` bool
- `default_on` bool
- `status` enum (`DRAFT`, `ACTIVE`, `RETIRED`)
- `created_by`, `approved_by`, `created_at`, `approved_at`
- Dual-approval. Author ≠ approver enforced in service layer.

**`consent_statement_version`**
- `id` ULID
- `purpose_id` FK
- `version` int, unique per purpose
- `text_i18n` JSONB (one row holds all language variants)
- `effective_from`, `effective_to`
- `approved_by` FK User
- `status` enum (`DRAFT`, `ACTIVE`, `SUPERSEDED`)

**`consent_record`** (one row per member per purpose, latest state)
- `id` ULID
- `member_id` FK
- `purpose_id` FK
- `statement_version_id` FK
- `state` enum (`GRANTED`, `REFUSED`, `WITHDRAWN`, `EXPIRED`)
- `captured_by` FK User (operator) or null if self-service
- `captured_via` enum (`CAPI`, `WEB`, `PARISH_DESK`, `CITIZEN_PORTAL`, `USSD`, `DIH_FAST_TRACK`)
- `capture_method` enum (`SIGNATURE`, `THUMBPRINT`, `VERBAL_WITNESSED`, `DIGITAL`)
- `witness_name`, `witness_role` (for verbal capture)
- `evidence_object_key` MinIO reference (signature image, thumbprint scan)
- `granted_at`, `withdrawn_at`
- `withdrawal_reason_code` enum, optional
- `withdrawn_by` FK User or null if self-service
- `proxy_relationship` enum (`SELF`, `HEAD_FOR_MINOR`, `GUARDIAN_FOR_MINOR`, `HEAD_FOR_INCAPACITATED`) — supports §8 child consent
- Unique on `(member_id, purpose_id)` with versioning trigger so prior states roll to `consent_record_version`.

**`consent_record_version`**: append-only history of every state change. Hashed into the SEC audit chain.

**`consent_event`**: optional event-stream view for OpenSearch indexing and citizen-portal timeline. Generated by trigger from `consent_record_version`.

### Relationships

- `Member 0..* ConsentRecord` (already in SAD §5 Appendix C; we are formalising it).
- `Household.current_consent_state` (existing column) becomes a computed roll-up of head member's `REGISTRATION` consent state.
- `ConsentRecord 1..1 ConsentStatementVersion` so the exact text the subject saw is preserved.

### Identifiers

ULIDs. Per CLAUDE.md no sequential PKs for externally visible IDs.

### Encryption

`witness_name` is personal data. Standard at-rest encryption. No column-level AES on `consent_record` itself; the sensitive identifiers stay on `Member`.

## 6. State machine

```
              capture                           withdraw
   (none) ────────────► GRANTED ─────────────────────────► WITHDRAWN
              capture           statement supersession
   (none) ────────────► REFUSED        │
                                       ▼
                                   re-capture against new version (new row, history preserved)
```

Rules:

- A `REFUSED` record at `REGISTRATION` halts intake. The submission is terminated and a `declined_consent` outcome is recorded against the household.
- Re-attempt is allowed but creates a new `consent_record_version` row. Operator cannot overwrite a refusal silently.
- A statement supersession (new ACTIVE version of the same purpose) does NOT auto-invalidate existing consent. It flags the member for re-consent at the next interaction. The DPO can force re-consent on activation if the change is material.
- Withdrawal is final for that record; a fresh grant creates a new record row.

## 7. Withdrawal handling per purpose

Withdrawal is not a uniform "delete everything" action. Each purpose declares its withdrawal effect.

| Purpose | Effect on withdrawal |
|---|---|
| `REGISTRATION` | Routes to DPO. Soft-flags household for de-listing review. Public-task processing continues until the DPO confirms. If confirmed: soft delete the household, retain audit + consent records per §8.5 (lifetime + 7y consent, 10y audit). |
| `ELIGIBILITY` | DPO review. PMT recompute is paused for the member; vulnerability band frozen until decision. |
| `REFERRAL` | Immediate. Active referrals to programme MISes flagged for withdrawal notification; no new referrals dispatched. |
| `PAYMENTS` | Immediate stop on new payment instructions. In-flight instructions continue per contract. |
| `COMMUNICATIONS_SMS` / `_USSD` | Immediate. All outbound channels suppressed except statutory grievance responses. |
| `RESEARCH` | Immediate stop on future extracts. Past extracts remain with the partner (DSA controlled). |
| `STATISTICS` | Not withdrawable. Aggregate-only processing. |
| `GRIEVANCE_CONTACT` | Closes the case if no other channel available; subject notified once. |

Statutory clock for handling subject rights: 30 days (DPPA §29 read with the Regulations 2021). Surface this as the withdrawal SLA.

## 8. UX touchpoints

| Channel | What happens |
|---|---|
| CAPI (Field Enumerator) | Consent screen before any personal-data fields. Statement read aloud + displayed; thumbprint or signature captured on device; declined consent terminates intake with reason. Per-purpose toggles below the registration consent. |
| Parish Office (Web) | Parish Chief assisted-capture screen. Same toggle set; print receipt with the consented purposes and the statement version. |
| Citizen Portal | Authenticated dashboard listing every active consent, its statement, its state, and a "withdraw" button per purpose. Withdrawal triggers SLA-tracked workflow. |
| USSD (Release 2) | Lookup current consent state; request a callback for assisted withdrawal. No granular toggling over USSD at MVP (security risk). |
| Operator screens (DAT, REF, UPD) | Read-only consent badge on every household and member view. Operators see what they are allowed to act on. |
| DPO console | Bulk view of pending withdrawal reviews, statement version management, purpose catalogue editor. |

The UI vocabulary follows `/docs/04_ui_design_brief.md`. Consent badges use the existing status palette (Granted / Refused / Withdrawn / Pending review).

## 9. Integration with other modules

| Module | Hook |
|---|---|
| **INT** | Consent screen gate at start of intake. Refusal terminates submission. |
| **DIH** | `StageRecord` carries the source-system consent claim. Promotion API requires `REGISTRATION` consent state to be `GRANTED` or `PUBLIC_TASK_OVERRIDE` set with DPO sign-off. Fast-track auto-promote checks the consent presence flag before promotion. |
| **DAT** | `Household.current_consent_state` and `Member` consent badges are read on every screen and serialiser. ABAC + consent filter on all PII read paths. |
| **DAT-DQA** | New rule family `AC-CONSENT-*`. The existing SAD rule `AC-CONSENT` (Table T8R15) covers the registration check; extend to `AC-CONSENT-PURPOSE-VERSION-CURRENT`, `AC-CONSENT-WITNESS-PRESENT-FOR-VERBAL`, etc. |
| **DAT-DDUP** | On merge, the surviving record inherits the union of `GRANTED` consents from both sides. If either side has `WITHDRAWN`, the survivor is `WITHDRAWN` for that purpose. Conflict surfaces in the dedup review queue. |
| **PMT** | Reads `ELIGIBILITY` consent on every recompute. `WITHDRAWN` blocks recompute; existing band freezes; emits `pmt.recompute.blocked.consent_withdrawn` event. |
| **REF** | Reads `REFERRAL` consent on every candidate-list query. Filter applied at the query layer, not the application layer, so referrals cannot escape consent by mistake. |
| **UPD** | Composition changes (split, merge, head change) require fresh consent capture from the new head. Per SAD: "both heads must consent". |
| **API-DRS** | Outbound extracts filter on the consent purpose that matches the requesting DSA. RESEARCH-scoped DSAs receive only members with `RESEARCH = GRANTED`. STATISTICS-scoped DSAs receive aggregates without per-member consent gating. |
| **GRM** | A grievance can be filed even without `GRIEVANCE_CONTACT` consent, but follow-up SMS/calls are suppressed; case progresses in writing only. |
| **IDV** | NIN verification with NIRA runs under public task; not gated on consent. |
| **SEC** | Every consent state change emits an `AuditEvent` (`consent.granted`, `consent.refused`, `consent.withdrawn`, `consent.statement_superseded`, `consent.purpose_created`, `consent.purpose_activated`). |
| **REPORTING** | Consent coverage dashboard: % of registry with active referral consent, withdrawal rate by sub-region, statement-version drift. |

## 10. APIs (initial)

All under OpenAPI 3.1, published in the developer portal, contract-tested in CI.

| Endpoint | Method | Caller | Notes |
|---|---|---|---|
| `/api/v1/consent/purposes` | GET | All authenticated | Lists active purposes. Public to citizen portal too. |
| `/api/v1/consent/purposes` | POST | DPO | Dual-approval workflow. |
| `/api/v1/consent/purposes/{code}/activate` | POST | DPO | Approver ≠ author. |
| `/api/v1/consent/statements` | GET | All | Filter by purpose + language. |
| `/api/v1/consent/statements` | POST | DPO | Creates DRAFT version. |
| `/api/v1/consent/members/{member_id}` | GET | Operator (scope-checked) or citizen (self) | Returns the full consent matrix. |
| `/api/v1/consent/members/{member_id}/capture` | POST | Operator | Body: `[{purpose, state, statement_version_id, capture_method, witness, evidence_key}]`. |
| `/api/v1/consent/members/{member_id}/withdraw` | POST | Citizen or DPO | Body: `[{purpose, reason}]`. Returns withdrawal ticket id. |
| `/api/v1/consent/withdrawal-tickets/{id}` | GET | DPO console | Tracks SLA. |
| `/api/v1/consent/withdrawal-tickets/{id}/decide` | POST | DPO | Decision: `CONFIRM`, `OVERRIDE_PUBLIC_TASK`, `REQUEST_CLARIFICATION`. |
| `/api/v1/consent/audit/{member_id}` | GET | Auditor, citizen (self) | Full history. |

## 11. Audit events

All emitted via SEC and hashed into the chain. Each carries `actor`, `target_member_id`, `purpose_code`, `statement_version`, `state_from`, `state_to`, `ip`, `user_agent`, `ts`.

- `consent.granted`
- `consent.refused`
- `consent.withdrawn`
- `consent.withdrawal.ticket_opened`
- `consent.withdrawal.ticket_decided`
- `consent.statement.created`
- `consent.statement.activated`
- `consent.statement.superseded`
- `consent.purpose.created`
- `consent.purpose.activated`
- `consent.purpose.retired`

## 12. Edge cases worth nailing now

1. **Minors (DPPA §8).** Head of household consents on behalf of members under 18. `proxy_relationship = HEAD_FOR_MINOR`. When the minor turns 18, the system flags them for re-consent at the next interaction. Open item: do we want a birthday cron job or trigger at next read?
2. **Incapacitated adults.** Same proxy mechanism, `HEAD_FOR_INCAPACITATED`. Requires documented relationship (currently captured in `Relationship` as `caregiver_of`).
3. **Head changes via UPD.** Existing per-purpose consents persist with the member, not the household. The new head's `REGISTRATION` consent is captured as part of the head-change transaction.
4. **Death of head.** Consent records become read-only; downstream processing of the deceased member halts; household carries on under the new head per UPD.
5. **Member leaves household (split).** Consent records move with the member.
6. **Statement version supersession.** Existing GRANTED records stay valid against the old version. Flag for re-consent at next interaction unless the DPO marks the new version as material, in which case force re-consent.
7. **Bulk DIH import (UBOS, Kobo).** Source system attests to consent at DPA level. NSR records a synthetic `ConsentRecord` with `captured_via = DIH_FAST_TRACK`, `capture_method = DIGITAL`, pointing to the DPA as evidence. The DPO ratifies the DPA's lawful basis at activation.
8. **No NIN.** Consent record uses `member_id` (ULID), not NIN. Verified-NIN status is irrelevant to consent capture.
9. **Reversal of refusal.** A subject who refused can come back later and grant. New row, prior `REFUSED` preserved in version history.
10. **Operator coercion risk.** Mitigate with witness capture for verbal consent, periodic supervisor spot-audit, anomaly detection on a single operator's grant/refusal ratio.

## 13. Open items to surface (need DPO + legal decision)

| ID | Question | Owner |
|---|---|---|
| CONSENT-O-01 | Initial purpose catalogue + which are withdrawable. Confirm Section 4 table. | DPO + MGLSD Legal |
| CONSENT-O-02 | Re-consent trigger on statement supersession: automatic, or DPO-marked-material only? | DPO |
| CONSENT-O-03 | Withdrawal SLA: 30 days statutory, or shorter operational target? | DPO + NSR Coordinator |
| CONSENT-O-04 | DPO override of consent withdrawal where public task applies: what counts as adequate documentation? | DPO + AG Chambers |
| CONSENT-O-05 | Age-of-majority re-consent trigger: birthday cron, or at next interaction only? | DPO |
| CONSENT-O-06 | USSD security model for self-service withdrawal: PIN, callback, branch only? | NSR Coordinator + NITA-U security |
| CONSENT-O-07 | Languages for the statement: English + which others at MVP? | NSR Coordinator |
| CONSENT-O-08 | DPA fast-track: which source systems get auto-ratified at DPA activation vs. per-batch attestation? | DPO + DIH team |
| CONSENT-O-09 | Right-to-portability format under §28: JSON, PDF, both? | DPO |
| CONSENT-O-10 | Consent for SENSITIVE data (§9: health, HIV, disability): separate purpose or layered into existing? | DPO. See ADR-0019. |

These follow the same `<MODULE>-O-NN` convention used in SAD §12.

## 14. Proposed new user stories (delta over existing US-010, US-065, US-068)

The existing stories cover capture, dashboard, and retention. The delta below scopes the granular module.

| ID | Title | Priority |
|---|---|---|
| US-S26-CONSENT-PURPOSE-CRUD | DPO can create, edit, retire consent purposes with dual-approval. | Must |
| US-S26-CONSENT-STATEMENT-VERSIONING | DPO can author and activate versioned statement text with i18n. | Must |
| US-S26-CONSENT-CAPTURE-CAPI | Field Enumerator captures per-purpose consent on CAPI with witness for verbal. | Must |
| US-S26-CONSENT-CAPTURE-WEB | Parish Chief captures per-purpose consent on web. | Must |
| US-S26-CONSENT-CITIZEN-VIEW | Citizen views their consent matrix on the portal. | Must (US-065 expansion) |
| US-S26-CONSENT-CITIZEN-WITHDRAW | Citizen requests withdrawal per purpose, ticket opens, SLA tracked. | Must |
| US-S26-CONSENT-DPO-WITHDRAWAL-QUEUE | DPO works the withdrawal queue with decision options. | Must |
| US-S26-CONSENT-PROPAGATION-PMT | PMT recompute respects ELIGIBILITY consent state. | Must |
| US-S26-CONSENT-PROPAGATION-REF | Referral candidate list filters on REFERRAL consent. | Must |
| US-S26-CONSENT-PROPAGATION-DRS | DRS extracts respect purpose-mapped consent. | Must |
| US-S26-CONSENT-AUDIT-CHAIN | Every state change hashed into SEC audit chain. | Must |
| US-S26-CONSENT-DIH-FAST-TRACK | DIH promotion records synthetic consent record from DPA evidence. | Must |
| US-S26-CONSENT-DDUP-MERGE | DDUP merge inherits union of grants; conflicts flagged. | Must |
| US-S26-CONSENT-DQA-RULES | New AC-CONSENT-* rules added to DQA catalog. | Must |
| US-S26-CONSENT-USSD-LOOKUP | USSD lookup of consent state. | Should (Release 2) |
| US-S26-CONSENT-PORTABILITY | Subject-access export under DPPA §28. | Should |
| US-S26-CONSENT-MINOR-MAJORITY | Re-consent flag on 18th birthday. | Should |
| US-S26-CONSENT-REPORTING | Consent coverage dashboard for NSR Coordinator + DPO. | Should |

## 15. Sequencing

Two sprints, behind a feature flag `CONSENT_MODULE_ENABLED`. Trunk-based per CLAUDE.md.

**Sprint A (foundations)**
1. Data model + migrations (reversible per CLAUDE.md migration policy).
2. Purpose catalogue + statement versioning + seed data + admin screens.
3. Capture API + CAPI + Web screens.
4. AC-CONSENT-* DQA rules.
5. SEC audit-chain wiring.
6. Citizen view (read-only).
7. DPIA addendum.

**Sprint B (propagation + withdrawal)**
1. Withdrawal API + ticket workflow + DPO queue.
2. PMT, REF, DRS, GRM read-side enforcement.
3. DDUP merge logic for consent inheritance.
4. DIH fast-track synthetic record.
5. UPD head-change consent capture.
6. Reporting dashboard.
7. Contract tests, ADR (this scope graduates to ADR-0024 once decisions land).

## 16. Acceptance gates

- Refusal at registration terminates intake with `declined_consent` and no PII persists in registry (allowed in DIH raw landing for evidence only).
- Granular withdrawal halts the relevant downstream activity within one minute of state change.
- Statutory withdrawal handling completes within the configured SLA (30 days default, configurable).
- Every state change has an audit-chain entry verifiable by the existing audit-chain integrity job.
- Per-purpose consent matrix renders consistently on CAPI, Web, and citizen portal.
- DDUP merge audit shows consent reconciliation rationale.
- Contract tests cover every API listed in Section 10.
- DPIA addendum filed before feature flag is enabled in production.

## 17. Risks (delta over DPIA §9 R8)

| ID | Risk | L | I | Residual | Mitigation |
|---|---|---|---|---|---|
| CR1 | Operator coerces verbal consent | M | H | M | Witness mandatory; supervisor spot-audit; anomaly detection on operator grant ratio |
| CR2 | Statement supersession invalidates millions of records | L | H | L | DPO marks materiality; re-consent at next interaction not retroactive |
| CR3 | Withdrawal SLA missed at scale | M | M | L | Queue dashboard; SLA alerting; reporting line to NSR Coordinator |
| CR4 | DIH synthetic consent diverges from DPA scope | M | M | L | DPO ratifies DPA at activation; quarterly DPA audit |
| CR5 | Children grow into adulthood under proxy consent | M | M | L | Birthday flag + next-interaction re-consent |
| CR6 | Granular toggle UX confuses citizens | M | M | L | Plain-language statements; assisted access at parish; portal usability testing |
| CR7 | API-DRS leaks data without consent purpose match | L | C | L | Filter at query layer not app layer; contract test per DSA scope |

## 18. Dependencies

- ADR-0019 (sensitive-health encryption) for §9 health data consent layering.
- ADR-0012 / 0013 / 0016 (DSA workflow) for DRS-side scope matching.
- US-067 (security incident response) for breach notification when consent records leak.
- Keycloak realm work for citizen-portal authentication.
- DQA rule editor for AC-CONSENT-* rule authoring.

---

End of scope. Next step: DPO + MGLSD Legal walk-through of Section 4 (purpose catalogue) and Section 13 (open items). Once decisions land, this graduates to ADR-0024 and the US-S26-CONSENT-* stories enter the backlog.
