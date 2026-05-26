# Glossary

## Acronyms

| Term | Definition |
|---|---|
| **ABAC** | Attribute-Based Access Control. Permission decided by attributes (geographic scope, role, programme) rather than fixed roles alone. |
| **ADR** | Architecture Decision Record. A short markdown doc that pins a design choice. Stored under `/docs/adr/`. |
| **CAPI** | Computer-Assisted Personal Interviewing. The tablet-based field channel for household capture. |
| **CDO** | Community Development Officer. Sub-county-level operator. |
| **DAT** | Data Management module. Owns the canonical Household and Member records. |
| **DAT-DDUP** | Deduplication sub-module of DAT. |
| **DAT-DQA** | Data Quality Assessment sub-module of DAT. |
| **DIH** | Data Integration Hub. Every record entering the registry passes through DIH first. |
| **DPA** | Data Provision Agreement. Inbound agreement; one per DIH source system. |
| **DPIA** | Data Protection Impact Assessment. Required under DPPA 2019 for every sprint that touches personal data. |
| **DPO** | Data Protection Officer. Reviews DPIAs and large-volume DRS extracts. |
| **DPPA 2019** | Data Protection and Privacy Act, 2019 (Uganda). |
| **DRS** | Data Request Service. The outbound surface MDA partners use to extract data. |
| **DSA** | Data Sharing Agreement. Outbound agreement; one per partner consuming data via DRS. |
| **DQA** | Data Quality Assessment. Pre-promotion rule engine. |
| **EAT** | East Africa Time (UTC+3). The rendering timezone for every UI. |
| **GRM** | Grievance Redress Mechanism. Citizen-facing complaints and corrections. |
| **IDV** | Identity Verification. NIRA lookup and reconcile module. |
| **INT** | Intake module. Walk-in, web, and CAPI submission entrypoints. |
| **KMS** | Key Management Service. NITA-U-managed for production secrets. |
| **MDA** | Ministry, Department or Agency. The downstream consumers of DRS data. |
| **MGLSD** | Ministry of Gender, Labour and Social Development. |
| **MIS** | Management Information System. |
| **MoU** | Memorandum of Understanding. Required with NIRA before live IDV. |
| **NIN** | National Identification Number. Issued by NIRA. Format `^(CM\|CF)[A-Z0-9]{12}$`. |
| **NIRA** | National Identification and Registration Authority. |
| **NITA-U** | National Information Technology Authority, Uganda. Owns the Government Data Centre. |
| **NSR** | National Social Registry. The dataset this MIS produces. |
| **NUSAF** | Northern Uganda Social Action Fund. A programme that pulls referrals from NSR. |
| **PDM** | Parish Development Model. A programme connected to NSR via DIH. |
| **PMT** | Proxy Means Test. Eligibility score computed for every household. |
| **REF** | Referral module. Pushes eligible households to programme MIS systems. |
| **REF-DATA** | Reference data module. Owns the UBOS geographic hierarchy and ChoiceList catalogue. |
| **RPT** | Reporting module. |
| **SAD** | Solution Architecture Document. The master spec at `/docs/01_solution_architecture.docx`. |
| **SEC** | Security cross-cutting module. Audit, ABAC, encryption, integrity. |
| **UBOS** | Uganda Bureau of Statistics. Owns the geographic hierarchy. |
| **UPD** | Update Workflow module. Routes change requests through approval. |
| **WFP-SCOPE** | World Food Programme's SCOPE platform. Connector lands records via DIH. |

## Uganda-specific terms

| Term | Definition |
|---|---|
| **Region** | Top-level UBOS administrative unit. Uganda has 4 regions. |
| **Sub-region** | UBOS administrative unit below region. Uganda has 9. The system is partitioned by sub-region. |
| **District** | Below sub-region. ~135 districts. |
| **County** | Below district. |
| **Sub-county** | Below county. |
| **Parish** | Below sub-county. The smallest unit a Parish Chief covers. |
| **Village** | Below parish. The data-collection unit. |
| **Enumeration Area** | UBOS-defined census tracking unit. Anchored to a village but with its own code. |
| **Head of household** | The household member designated as head. Enforced by DQA rule AC-HEAD-ONE. |
| **Provisional Registry ID** | Temporary ULID issued at walk-in capture before DIH promotes the record. |
| **Walk-in submission** | A household captured by a Parish Chief at the office, not on a CAPI tablet. |
| **Fast-track auto-promote** | DIH path that auto-commits Parish Chief walk-ins with zero blocking failures, sampling 1% for steward review. |

## System statuses

| Status | Where it appears | Meaning |
|---|---|---|
| `provisional` | Submission | Captured, not yet promoted to the Registry. |
| `pending` | Submission, ChangeRequest, DataRequest | Awaiting review. |
| `registered` | Household | Live in the Registry. |
| `rejected` | Submission, ChangeRequest | Reviewer rejected; reason recorded. |
| `voided` | Household | Soft-deleted after merge or fraud. |
| `blocking` | DQA result | The record cannot promote until fixed. |
| `warning` | DQA result | The record can promote, but the reviewer must acknowledge. |
| `active` / `superseded` / `retired` | GeographicUnit, ChoiceList | Reference-data lifecycle states. |
| `draft` / `pending_approval` / `active` | DqaRule, MatchModel | Dual-approval lifecycle for audit-bearing config. |
