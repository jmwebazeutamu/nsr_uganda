# NSR MIS — Threat Model (Sprint 0 initial draft)

**Status**: Draft for the threat-modelling workshop.
**Last updated**: 14 May 2026.
**Owners**: NSR MIS Architecture Team, Data Protection Officer.
**References**: SAD §8 (security), §4.6 (DIH), ADR-0001, ADR-0002.

This document is the input to the Sprint 0 threat-modelling workshop. It enumerates the assets, the trust boundaries, and a STRIDE matrix per module, then lists the top-10 threats the workshop should debate first. Workshop output replaces the **`[workshop]`** placeholders.

---

## 1. Assets

Ordered by sensitivity. The asset class drives the control posture.

| # | Asset | Sensitivity | Notes |
|---|---|---|---|
| A1 | Member NIN value | **Highest** | Encrypted at rest (AES-256-GCM, KMS), never logged, joins use `nin_hash`. ADR-0002. |
| A2 | Member personal record | High | Name, DOB, sex, contact, family, residency. DPPA 2019 personal data. |
| A3 | Household socio-economic record | High | PMT inputs (Health, Education, Employment, Dwelling, Utilities, Assets, Food, Shocks). |
| A4 | PMT score + band | High | Programme-eligibility-relevant. Reveals welfare status. |
| A5 | Geographic + GPS | Medium | Reveals household location. PostGIS in production. |
| A6 | Audit chain | Highest (integrity) | Hash-chained, append-only. Tampering = legal-defensibility failure. |
| A7 | Operator credentials & sessions | High | Keycloak OIDC + MFA; ABAC scope per geography. |
| A8 | Partner DSAs and extracts | Medium | DSA-scoped exports under DPPA 2019; watermarked. |
| A9 | DIH raw landings | Medium | Pre-promotion partner data; under DPA lawful basis. |
| A10 | Encryption keys (KMS) | Highest | NITA-U KMS; rotation policy per O-04. |

## 2. Actors and trust boundaries

External (untrusted) → Perimeter (Kong/Keycloak) → Application → Database.

- **Citizens** — interact via CAPI walk-in, USSD (Release 2), Web on-demand, GRM hotline. Receive SMS receipts.
- **Field Enumerator / Parish Chief / CDO** — operators inside the trust boundary, ABAC-scoped to their geography.
- **NSR Unit Coordinator / DPO** — privileged operators.
- **System Administrator** — highest privilege; sessions recorded.
- **Auditor** — read-only on audit chain.
- **Partner programmes (OPM, MoH, MoES, …)** — external systems, OAuth 2.0 client_credentials, DSA-scoped.
- **NIRA** — outbound identity verification; mTLS.
- **UBOS** — inbound reference data; periodic refresh.

Trust boundaries:
1. Internet ↔ Kong API gateway (TLS termination, rate-limit, WAF).
2. Kong ↔ Django registry app (Keycloak introspection at gateway).
3. Registry app ↔ DIH app (single internal API `POST /internal/dih/promote` + RabbitMQ events).
4. App ↔ PostgreSQL (least-privilege DB roles; column-level encryption on NIN).
5. App ↔ External systems (NIRA, UBOS, partner MIS — anti-corruption layer per integration).

## 3. STRIDE matrix per module

Legend: ✅ mitigated, 🟡 partial, ❌ workshop debate. `→` references the SAD/ADR control.

| Module | Spoofing | Tampering | Repudiation | Info disclosure | DoS | Elevation |
|---|---|---|---|---|---|---|
| INT (intake)            | ✅ Keycloak+MFA | ✅ DQA rule pack + signed CAPI submissions | ✅ AuditEvent on submit | 🟡 [workshop] CAPI device theft | 🟡 rate limits at gateway | ✅ ABAC scope |
| DAT (data management)   | ✅              | ✅ paired _Version tables + audit trigger | ✅ AuditEvent on every write | ✅ NIN encrypted; nin_hash for joins | 🟡 partitioning by sub_region helps | ✅ |
| DAT-DQA                 | ✅              | ✅ dual approval + rule versioning        | ✅ rule changes audited      | n/a                              | n/a              | ✅ author≠approver |
| DAT-DDUP                | ✅              | ✅ merge transaction + 30d reverse window  | ✅ MergeDecision + AuditEvent | 🟡 [workshop] inference via match pairs | 🟡 nightly sweep budget    | ✅ |
| IDV (NIRA)              | ✅ mTLS         | ✅ signed responses                       | ✅ verification_request_id   | ✅ never logs NIN plaintext      | ❌ [workshop] NIRA outage | ✅ |
| UPD                     | ✅              | ✅ ChangeRequest workflow + diff           | ✅ field-level audit chain   | ✅ scope-filtered                | n/a              | ✅ no-self-approve |
| PMT                     | ✅              | ✅ model version dual approval             | ✅ PMTResult records inputs  | 🟡 score is sensitive            | n/a              | ✅ |
| REF (referral)          | ✅              | ✅ programme webhook signatures            | ✅ Referral state machine    | 🟡 partner-side leakage          | 🟡 webhook backoff | ✅ |
| GRM (grievance)         | ✅              | ✅ case audit                              | ✅ case timeline              | 🟡 reporter PII                  | n/a              | ✅ |
| API (Kong)              | ✅ OAuth2 cc    | ✅ TLS + WAF                              | ✅ access log                | n/a                              | ✅ rate limits + autoscale | ✅ |
| API-DRS                 | ✅              | ✅ DSA scope at runtime                    | ✅ ExtractJob audited        | ✅ field-level masking, watermark | 🟡 query budgets per DSA | ✅ DPO approval |
| DIH                     | ✅ DPA required | ✅ landing append-only + mapping versions | ✅ ConnectorRun + AuditEvent | 🟡 raw landings hold partner PII | 🟡 bulk batches  | ✅ NSR Unit review |
| SEC                     | ✅ MFA + ABAC   | ✅ AuditEvent hash chain (Postgres trigger) | n/a                          | ✅ anomaly detection             | ✅ session recording for admins | ✅ |
| RPT                     | ✅              | ✅ aggregates only                         | ✅ query log                 | ✅ no row-level PII in public RPT | n/a              | ✅ |
| REF-DATA                | ✅              | ✅ versioned UBOS hierarchy                | ✅ version log               | n/a                              | n/a              | ✅ |

## 4. Top-10 threats for the workshop

Ordered by expected likelihood × impact. Workshop assigns owner + due-by.

| # | Threat | Asset(s) | Likelihood | Impact | Mitigation status |
|---|---|---|---|---|---|
| T1  | **Insider operator dumps records** (scrolls beyond geographic scope, exports via DRS-like path) | A2, A3, A4 | Medium | High | ABAC per parish; anomaly detection on read volume; mandatory MFA; session recording for SA; quarterly access review. SAD §8.6. |
| T2  | **CAPI tablet lost / stolen** with offline draft submissions | A2, A3 | Medium | Medium | SQLCipher local store; device PIN; MDM remote wipe; sync-and-clear after upload. Open: enforce wipe after 14d offline. |
| T3  | **NIN plaintext leaks via logs or admin** | A1 | Low | Critical | EncryptedBinaryField; admin never displays `nin_value`; logging redaction at framework boundary (TBD: confirm log sink filters). |
| T4  | **Audit chain tampering** (direct DB write, dropped row) | A6 | Low | Critical | Postgres trigger (security_auditevent_immutable + chain hash). DB role separation. Backup tamper-evidence via hash chain verification job (TBD). |
| T5  | **Partner-side leak after DSA extract** | A2, A3, A8 | Medium | High | Minimised scope per request, watermarked outputs, DSA legal terms, encrypted 7z delivery, periodic access review. DRS-O-04 sets password policy. |
| T6  | **Compromised partner OAuth2 client_credentials** | A8, A9 | Medium | High | 15-min tokens; client rotation policy (TBD: cadence); credential vault per partner; revocation playbook in runbook. |
| T7  | **NIRA outage stalls intake** | service availability | High | Medium | IDV state `idv_pending`; nightly retry; "promote pending IDV" override for known-NIN updates only (DIH-O-05). |
| T8  | **Mass enumeration burst overruns the registry** (UBOS bulk load) | A6, A9 | High | Medium | DIH staging buffers; PromotionBatch dual-approval at >10k (DIH-O-02); per-source residence policy (DIH-O-01). |
| T9  | **PMT score inversion or model tampering** | A4 | Low | High | PMTModelVersion dual-approval activation; backfill on activation; PMTResult records inputs snapshot. |
| T10 | **Cross-NIN attack** (NIN re-issued at NIRA, attacker links to wrong identity) | A1, A2 | Low | High | Quarterly cross-NIN audit run (SAD §4.3.7); name normalisation strips confusables. |

## 5. Controls inventory (what's already in code or roadmap)

Tied to where each control lives so the workshop can verify rather than re-derive.

| Control | Where it lives | Status |
|---|---|---|
| ULID externally-visible IDs (not sequential) | `nsr_mis/common/fields.py` + ADR-0002 | shipped |
| NIN AES-256-GCM at column level | `nsr_mis/common/fields.py::EncryptedBinaryField` (Sprint 0 stub; KMS wiring is O-04) | partial |
| NIN SHA-256 hash for joins | `Member.nin_hash` (indexed) | shipped |
| Append-only AuditEvent + hash chain | `apps/security/migrations/0002_auditevent_chain_trigger.py` (postgres-only) | shipped |
| Paired version tables | `HouseholdVersion`, `MemberVersion` | shipped |
| DQA dual-approval (author ≠ approver) | `apps/dqa/services.py::approve` | shipped + tested |
| DDUP model version dual-approval | `apps/ddup/services.py::activate_model_version` | shipped + tested |
| DDUP merge transaction (soft-delete alias + re-point) | `apps/ddup/services.py::merge_member_pair` | shipped + tested |
| DDUP reverse-merge 30d window | `MergeDecision.reverse_window_until` (recorded; activation flow TBD) | partial |
| DIH DPA required | `apps/ingestion_hub/services.py::start_connector_run` | shipped + tested |
| Provisional Registry ID → confirmed | `apps/ingestion_hub/services.py::promote_stage_record` | shipped + tested |
| Idempotent promotion | `promote_stage_record` returns existing Household on replay | shipped + tested |
| Keycloak OIDC + MFA | infrastructure (Sprint 1) | TBD |
| Kong API gateway + rate limits | infrastructure (Sprint 1) | TBD |
| MDM + SQLCipher on CAPI | ADR-0004 Sprint 1 spike | TBD |
| Read-side audit middleware (every read writes AuditEvent) | follow-up story (SEC) | TBD |
| KMS rotation playbook | infrastructure runbook | TBD |

## 6. Workshop agenda template

1. Walk this document end-to-end (45 min).
2. Debate T1–T10 in order; assign owner + due-by (60 min).
3. Add module-level threats missed by the matrix (30 min).
4. Decide which `[workshop]` cells get controls now vs deferred (30 min).
5. Sign off on Sprint 0 DPIA initial draft (separate document) (15 min).

---

End of threat model v0.1.
