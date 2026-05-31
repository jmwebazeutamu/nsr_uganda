# NSR MIS — Data Protection Impact Assessment (Initial draft)

**Status**: Initial draft for DPO review.
**Last updated**: 14 May 2026.
**Statutory basis**: Data Protection and Privacy Act, 2019 (DPPA 2019), Republic of Uganda.
**Owners**: Data Protection Officer (MGLSD), NSR MIS Architecture Team.
**References**: SAD §8 (security), §8.1 (privacy principles), §8.5 (retention).

A DPIA is required for the NSR MIS under DPPA 2019 because the processing is large-scale, systematic, and concerns sensitive personal data of millions of data subjects. This document is the **initial draft** the DPO uses as a starting point. Each section below has a `[DPO review]` marker where the DPO records the workshop outcome.

---

## 1. Description of the processing

| | |
|---|---|
| Data controller | Ministry of Gender, Labour and Social Development (MGLSD) |
| Data processor | NSR Unit (within MGLSD), hosted at NITA-U Government Data Centre |
| Joint controllers | NIRA (identity verification), UBOS (reference data); each under their own legal mandate. |
| Purpose | Capture, validate, score (PMT), and share socio-economic household data nationally to inform social-protection programme eligibility and referral. |
| Scale | 12 million households at full national rollout; ~50 million persons. |
| Geographic scope | Republic of Uganda, 9 sub-regions, 146 districts, ~2,200 sub-counties, ~10,800 parishes. |
| Channels | CAPI offline tablet (Field Enumerator, Parish Chief), Web on-demand (sub-county), USSD pre-registration (Release 2), bulk import from UBOS, Kobo pilot. |
| Lawful basis | Public task (Section 7 DPPA 2019, ministerial mandate) + explicit consent of the head per household for inclusion. |

## 2. Categories of data subjects

- Household heads and members (children included).
- Vulnerable subjects: persons with disabilities (Washington Group fields), pregnant women, displaced persons, refugees, orphans.
- Operators (Field Enumerator, Parish Chief, CDO, NSR Unit, DPO, SA).

## 3. Categories of personal data

| Category | Examples | Sensitivity under DPPA 2019 |
|---|---|---|
| Identification | Full name, sex, DOB, NIN, passport, voter card, driving licence | NIN + ID document numbers = **sensitive** (Section 9). |
| Demographic | Marital status, nationality, residency status, birth-cert status | Personal data. |
| Contact | Telephone, mobile-money flag | Personal data. |
| Family | Relationships (parent, spouse, sibling, guardian) | Personal data. |
| Health | Chronic illness types (TB, HIV, etc.), Washington Group disability | **Sensitive** (Section 9). |
| Education | Read/write, ever attended, highest grade, reason stopped | Personal data. |
| Employment | Main activity, sector, status, programmes benefited | Personal data. |
| Dwelling + Utilities | Tenure, type, water source, sanitation, lighting | Personal data (proxies for vulnerability). |
| Assets | Asset list, livestock counts | Personal data. |
| Food + Shocks + Coping | Recent consumption, recent shock events, coping strategies | Personal data (proxies for vulnerability). |
| Consent | Per purpose, per member, with version and timestamps | Compliance data. |
| GPS + address | lat/lng/accuracy, narrative, geographic codes | Personal data (location). |
| Audit | Operator ID, IP, agent, timestamp | Operational metadata. |

## 4. Lawful basis per processing activity

| Activity | Lawful basis |
|---|---|
| Intake at parish/CAPI/web | Consent (head member) + public task |
| DIH staging of partner-supplied records | Data Provision Agreement (DPA) signed by the partner + DPPA 2019 lawful basis declared per source |
| DQA evaluation | Public task |
| DDUP matching + merge | Public task (data accuracy under DPPA 2019 §27) |
| IDV NIN verification with NIRA | Public task + statutory mandate |
| PMT scoring | Public task |
| Referral to programme MIS | Consent (purpose specified) + DSA between MGLSD and the partner MDA |
| DRS extract to research/NGO | DSA + DPO approval per request |
| Audit logging | Legal obligation (DPPA 2019 §29 accountability) |

## 5. Recipients

| Recipient | Channel | Frequency | Scope |
|---|---|---|---|
| Programme MIS (PDM, NUSAF, etc.) | Referral webhook (Release 2) / batch | Per enrolment | DSA-scoped fields only |
| Partner MDAs (MoH, MoES, OPM) | DRS extract or API | On request | DSA-scoped, watermarked, encrypted |
| Research / NGO | DRS extract | On request | DSA-scoped, DPO approval, smaller row budget (DRS-O-01) |
| NIRA | Outbound IDV call | Real-time per submission | NIN value only |
| UBOS | Inbound only | Reference refresh | n/a |
| Audit reviewers | Read-only DB role | On demand | Audit chain only |

## 6. Cross-border data transfers

**None at MVP.** NIRA is domestic. Partner programmes are MDAs operating within Uganda. SurveyCTO (CAPI option C in ADR-0004) is the only candidate involving cross-border processing, and ADR-0004 flags this as the reason for the build-vs-buy spike's data-residency criterion.

`[DPO review]` — confirm.

## 7. Retention schedule (from SAD §8.5)

| Class | Retention | Disposal |
|---|---|---|
| Household + member (active) | Lifetime; min 10y after last interaction | Soft-archive after 10y inactivity |
| Consent records | Lifetime of data subject + 7y | Hard-delete on validated erasure request |
| Audit log | 10y | Immutable; cold archive after 2y |
| Submission raw payloads | 5y | Purge; aggregates retained |
| ID document images | 3y after verification | Purge; hash retained |
| Grievance cases | 10y from closure | Closed-case archive after 2y |
| Backups | 30d online + 7y archival | Cryptographic destruction on schedule |
| DIH unpromoted staging | 30d default (90d UBOS); per DPA | Move to hard-archive with reason `retention_expired` |
| DIH rejected records | 7y per DPPA 2019 | n/a |

## 8. Security measures (from SAD §8 + ADR-0002, ADR-0003)

- TLS 1.2 minimum (1.3 preferred) on every channel.
- AES-256-GCM column-level encryption of NIN and ID document numbers (KMS-managed key; O-04 confirms NITA-U KMS).
- SHA-256 `nin_hash` with a project-pepper for joins; pepper in KMS; re-hash drill yearly.
- Keycloak OIDC + MFA mandatory for any role with write access; 10-role least-privilege catalogue.
- ABAC enforced at every read (parish/sub-county/district/region scope).
- Postgres-level audit-chain integrity trigger (BEFORE INSERT prev/self hash; BEFORE UPDATE/DELETE raise).
- Per-table version rows preserved; never dropped.
- SQLCipher on CAPI device; PIN; MDM remote wipe.
- Watermarked partner extracts; encrypted 7z delivery; password via separate channel.
- Anomaly detection on read patterns; session recording for SA.

## 9. Risk assessment

Risks are scored High/Medium/Low for likelihood × impact. Workshop refines.

| # | Risk | L | I | Residual after mitigation | Mitigation reference |
|---|---|---|---|---|---|
| R1 | Insider exfiltration | M | H | M | Threat T1 (threat_model.md) |
| R2 | CAPI device loss with offline data | M | M | L | T2 |
| R3 | NIN plaintext leak in logs | L | C | L | T3; framework-level redaction |
| R4 | Audit chain tampering | L | C | L | T4 |
| R5 | Partner leak after DSA extract | M | H | M | T5 + DSA terms |
| R6 | Cross-border / SurveyCTO data residency | L | H | TBD | ADR-0004 criterion |
| R7 | PMT inversion | L | H | L | PMT model version dual-approval |
| R8 | Consent-purpose drift | M | M | L | Per-purpose consent records, withdrawal flow |
| R9 | Child data exposure in referrals | M | H | M | DSA scope review; minor-flag filter |
| R10 | NIRA outage stalls intake (availability not confidentiality) | H | M | L | IDV pending state + 7d SLA |

`[DPO review]` — confirm residuals after the threat model workshop.

## 10. Data subject rights

| Right (DPPA 2019) | How it is operationalised |
|---|---|
| Access (§24) | Citizen portal status check (Release 2); Parish Chief request at L1 |
| Rectification (§25) | UPD workflow via Parish Chief or GRM |
| Erasure (§26) | Validated erasure request → soft delete + audit retained; hard delete pre-approved by DPO |
| Restriction | Programme referral withdrawal via REF |
| Objection | Consent withdrawal per purpose |
| Portability | DRS-style export to the subject on request (workflow TBD) |
| Withdraw consent | Consent.withdrawn_at recorded; downstream processing halts |

## 11. Consultation

`[DPO review]` — schedule with: NSR Unit, MGLSD legal, NITA-U security, NIRA liaison, programme-MDA partner reps (PDM, NUSAF). Citizens consulted via GRM pilots.

## 12. Outcome and sign-off

This DPIA is in **initial-draft** status. Sign-off requires:

- Threat model workshop completed and `[workshop]` placeholders resolved.
- KMS arrangement with NITA-U (O-04) finalised.
- DSA template approved by MGLSD legal + AG Chambers (O-06).
- Cross-border position confirmed (R6).

Signatories:

- Data Protection Officer (MGLSD): ____________________ Date: __________
- NSR Unit Coordinator: ____________________ Date: __________
- NSR MIS Systems Architect: ____________________ Date: __________
- MGLSD ICT Director: ____________________ Date: __________

---

## 13. Addendum — US-S11-044 intra-household DQA (2026-05-27)

### 13.1 Processing change

US-S11-044 introduces an intra-household data-quality evaluator (DAT-DQA `apps.dqa.household_evaluator` + `apps.dqa.pipeline`) that runs at three points in the lifecycle of a household record:

1. **DIH ingest** — when a connector mapping produces a `StageRecord`.
2. **DIH promote** — when a `StageRecord` becomes a `Household` in the registry.
3. **Registry post-promote** — invoked by `apps.pmt.services.recompute_for_household` immediately after promotion.

Each evaluation produces a `DqaEvaluation` row (`apps.dqa.models.DqaEvaluation`) and emits a `dqa.household.evaluated` `AuditEvent` per SAD §8.4.

### 13.2 New categories of personal data processed

None. The evaluator operates on the same household + member payload the SAD has already authorised under §3. The new schema fields `Household.reported_household_size` and `Member.orphan_flag` are non-PII flags / counts; `Member.mother_line_number` and `Member.father_line_number` are intra-household integer pointers, not external identifiers.

### 13.3 New persisted records

| Table | Personal data referenced | Retention |
|---|---|---|
| `dqa_dqaevaluation` | `household_id` (FK by ID, no PII duplication); `results.offending_member_ids` may carry member ids/line-numbers | Same retention as the linked Household per §7 |
| `security_auditevent` (existing) | One row per evaluation; refers to household by id only | Permanent (audit chain) |

The `results` JSON column on `DqaEvaluation` records interpolated error messages. Templates are author-controlled (Rule Editor, dual-approval) and **must not** include free-form PII — only rule code, severity, and `offending_member_ids`. Compliance is the rule author's responsibility, with the DPO empowered to retire any rule whose template breaches this constraint.

### 13.4 Data minimisation

- The evaluator reads from the canonical household payload that has already been processed under existing lawful basis (SAD §4.6 fast-track + connector flow).
- Override reasons captured under `dqa.household.override` are required to be operationally specific and may contain officer-supplied context — these are audited as supervisor decisions, not personal data about the data subject.
- Vocabulary, rules, and evaluator outputs are queryable by household_id, rule_code, actor, and date window — supporting subject-access requests under §10 without surfacing payload contents to unauthorised actors (ABAC + audit).

### 13.5 Security measures (delta from §8)

- **Audit-on-everything**: every evaluation emits `dqa.household.evaluated`; every override emits `dqa.household.override`; every FLAG opens an `dqa.household.flag` for UPD triage. Audit fields reference personal data by id, not value.
- **Feature flag**: the entire intra-household surface is gated on `DQA_INTRA_HOUSEHOLD_ENABLED`. Production deploy is staged behind the flag pending DPO sign-off on rule activation.
- **Dual-approval**: every rule activation requires author ≠ approver (`apps.dqa.services.approve` returns 400 on self-approval) — already covered by §8 controls.
- **No payload caching in the UI**: the wizard validation panel pulls live from `POST /api/v1/dqa/evaluate/household` on every field-edit batch; no localStorage / sessionStorage caching. The registry stays reconstructable from the audit chain.

### 13.6 New residual risks

| ID | Risk | Likelihood | Impact | Residual | Mitigation |
|---|---|---|---|---|---|
| R11 | Rule author writes a message template that interpolates raw PII (e.g. NIN literal) | M | M | L | Rule Editor enforces dual-approval; DPO retires offending rules; CI lint future-work to block `{nin}` / `{phone}` interpolations |
| R12 | Override reasons accumulate sensitive operator context in the audit chain | L | M | L | Operator training; supervisor sees the audit on review |
| R13 | `/dqa/evaluations/{household_id}` exposes results to operators outside the household's geographic scope | L | M | L | ABAC-scope the endpoint before flag-on in prod (P5 follow-up: route through `HouseholdIdScopedQuerysetMixin`) |

### 13.7 Sign-off impact

No new lawful-basis claim or subject-rights process is needed. The DPO MUST approve the initial rule catalog (the 8 INTRA_HOUSEHOLD rules seeded as DRAFT by `scripts/seed_dqa_intra_household_rules.py`) before any rule is moved to ACTIVE and the feature flag is enabled in production.

---

## 14. Consent Management module addendum (US-CONSENT-01..18, ADR-0024)

The Consent Management module (`apps/consent/`) implements the per-member, per-purpose `Consent` entity named in SAD §5 Appendix C and §1 of this DPIA. It is the operational mechanism by which the registry obtains, records, demonstrates, and honours the withdrawal of consent under DPPA 2019. The whole surface is gated behind `CONSENT_MODULE_ENABLED` and is dark in production until the sign-offs in §14.7.

### 14.1 What changes

Consent moves from a single, never-written `Household.current_consent_state` boolean to nine purpose-scoped, versioned, withdrawable records per member, each carrying its lawful basis, the statement version consented against, the capture method, and an append-only history hashed into the audit chain by reference.

### 14.2 Lawful-basis matrix (per purpose)

| Purpose | Lawful basis (DPPA 2019) | Withdrawable | Notes |
|---|---|---|---|
| REGISTRATION | Consent | Yes | Primary; hard gate to proceed with intake |
| ELIGIBILITY | Consent | Yes | Gates PMT recompute (US-CONSENT-12) |
| REFERRAL | Consent | Yes | Gates REF candidate list (US-CONSENT-13) |
| PAYMENTS | Consent | Yes | |
| COMMUNICATIONS_SMS | Consent | Yes | |
| COMMUNICATIONS_USSD | Consent | Yes | |
| RESEARCH | Consent | Yes | Maps to RESEARCH-scoped DSAs (US-CONSENT-14) |
| GRIEVANCE_CONTACT | Consent | Yes | |
| STATISTICS | Statistical exemption §7(2)(e) | **No** | Aggregate-only; no per-member withdrawal affordance |

NIRA identity verification is **not** modelled as a consent purpose: it is a public-task activity under DPPA §7(2)(b) handled by IDV, consistent with §1. The withdrawal API refuses (`400`) any attempt to withdraw a non-withdrawable purpose.

### 14.3 New persisted records

| Table | Personal data referenced | Retention |
|---|---|---|
| `consent_consentrecord` | `member_id` (FK by id), purpose, state, capture metadata | Same retention as the linked Member per §7 |
| `consent_consentrecordversion` | denormalised `member_id` + `purpose_code`, state transition, `audit_event_id` | Append-only; permanent (consent must be demonstrable) |
| `consent_consentwithdrawalticket` | `member_id`, reason code/note, requester | Same retention as the Member |
| `consent_withdrawaldecision` | DPO decision + rationale | Append-only |
| `consent_consentevidence` | MinIO object key, witness name/role | Asset in MinIO; key + witness metadata here |
| `security_auditevent` (existing) | One row per consent change; refers to member/purpose by id | Permanent (hash chain) |

### 14.4 Data minimisation

- `consent_state()` is the single read path; downstream modules receive only a state string, never the underlying capture metadata.
- Evidence assets (signatures, thumbprints) live in MinIO; the registry stores only the object key and, for verbal-witnessed capture, the witness name and role (required by AC-CONSENT-METHOD-VALID, CR1).
- Refusal and withdrawal reasons are controlled vocabularies; the optional free-text note is operator/citizen-supplied and audited as a decision, not as data about a third party.

### 14.5 Security measures (delta from §8)

- **Audit-on-everything**: 11 `consent.*` event types cover every state change; the version row names its AuditEvent so the integrity job can prove referential completeness.
- **Audit chain**: `consent_record_version` is not independently hash-chained; integrity derives from the chained `security_auditevent` row each change emits (ADR-0024 D5).
- **Feature flag**: the entire surface is gated on `CONSENT_MODULE_ENABLED`; gates short-circuit to transparent-allow when off.
- **Dual-approval**: purpose + statement activation require author ≠ approver (`apps.consent.services` raises, API returns 400).
- **SQL-layer consent gate for sharing**: the REF candidate filter (US-CONSENT-13) and DRS row gate (US-CONSENT-14) filter at the query layer, so an application-layer bug cannot leak un-consented rows (CR7).
- **No "we'll fix it later" caches**: consent reads hit the record live (60s cache on the badge cluster only); the registry stays reconstructable from the audit chain.

### 14.6 New residual risks

| ID | Risk | Likelihood | Impact | Residual | Mitigation |
|---|---|---|---|---|---|
| CR1 | Operator coerces verbal consent | M | H | L | Witness mandatory (AC-CONSENT-METHOD-VALID); operator grant-ratio anomaly detection in RPT (S28) |
| CR2 | Material statement supersession mass-invalidates records | L | H | L | `is_material` gates re-consent; activation surfaces the count first |
| CR3 | Withdrawal SLA missed at scale | M | M | L | Hourly Celery alerter; DPO dashboard surfaces breach risk |
| CR4 | DIH synthetic consent diverges from DPA scope | L | H | L | DPA must be `Ratified`; ratified once at activation (CONSENT-O-08) |
| CR7 | DRS/REF leak data without a consent match | L | H | L | Filter at the SQL query layer; contract test per DSA scope |

### 14.7 Sign-off impact

The flag flips on in production only after the DPO signs off on (a) the seeded purpose catalogue and statement texts (CONSENT-O-01), (b) the 30-day withdrawal SLA (CONSENT-O-03), and (c) the DPA scopes for any DIH fast-track source (CONSENT-O-08); and after all Epic-19 contract tests are green and the extended audit-chain integrity job passes. A subject-access request for consent is served from `consent_record` + `consent_record_version` by member id, supporting the §10 subject-rights process.

---

End of DPIA initial draft v0.1 + US-S11-044 addendum.
