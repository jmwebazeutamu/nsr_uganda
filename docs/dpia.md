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

End of DPIA initial draft v0.1.
