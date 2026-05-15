# NSR MIS — Claude Code Project Memory

You are the implementation lead for the Uganda **National Social Registry MIS** for the Ministry of Gender, Labour and Social Development (MGLSD). This is the system that captures, validates, scores, and shares socio-economic data on households nationally. Target scale at full national load: 12 million households across 9 sub-regions.

Read `/docs/01_solution_architecture.docx` end-to-end before writing any code. It is the master spec. Everything below is a pointer to it.

---

## Tech stack (locked)

- **Backend**: Python 3.12 + Django 5.x + Django REST Framework.
- **Database**: PostgreSQL 16 with PostGIS, declarative partitioning by sub-region.
- **Search**: OpenSearch 2.x.
- **Async**: RabbitMQ + Celery + Redis.
- **Object store**: MinIO (S3-compatible).
- **Auth**: Keycloak (OIDC + SAML federation for partner MDAs).
- **API gateway**: Kong (or APISIX).
- **CAPI**: Android (Kotlin) with SQLCipher local store. Form runtime decision pending (see `/docs/01_solution_architecture.docx` §12 DDUP-O-02).
- **Observability**: OpenTelemetry + Prometheus + Grafana + Loki + Tempo.
- **Container platform**: Kubernetes (NITA-U Government Data Centre).
- **CI/CD**: GitLab CI or GitHub Actions.

Do not introduce alternative frameworks without an ADR.

## Architecture (locked)

- **Modular monolith** for the registry plus a **separately deployable Data Integration Hub (DIH)**. The two communicate over an internal promotion API.
- 12 functional modules + 4 sub-modules. See SAD §4. Codes: INT, DAT, DAT-DQA, DAT-DDUP, IDV, UPD, PMT, REF, GRM, API, API-DRS, DIH (ING), plus cross-cutting SEC, RPT, REF-DATA.
- **Every record entering the registry passes through DIH.** Direct writes to DAT are not allowed. See SAD §4.6.
- **DAT-DQA and DAT-DDUP are shared services** callable from both DIH and the registry. One implementation, two callers.
- **PMT runs only in the registry**, immediately after promotion. Never in DIH.

## Repository layout

```
/
├── CLAUDE.md                   # this file
├── README.md                   # human-readable project intro
├── /docs                       # canonical specs (read-only inputs)
│   ├── 01_solution_architecture.docx
│   ├── 02_erd.pdf
│   ├── 03_backlog.xlsx
│   ├── 04_ui_design_brief.md
│   ├── 05_requirements.docx
│   ├── 06_questionnaire.docx
│   ├── 07_framework.docx
│   └── /adr                    # architecture decision records you author
├── /apps                       # Django apps, one per module
│   ├── intake/                 # INT
│   ├── data_management/        # DAT (core + detail)
│   ├── dqa/                    # DAT-DQA
│   ├── ddup/                   # DAT-DDUP
│   ├── identity_verification/  # IDV
│   ├── update_workflow/        # UPD
│   ├── pmt/                    # PMT
│   ├── referral/               # REF
│   ├── grievance/              # GRM
│   ├── api_gateway/            # API
│   ├── data_requests/          # API-DRS
│   ├── ingestion_hub/          # DIH (ING)
│   ├── security/               # SEC
│   ├── reporting/              # RPT
│   └── reference_data/         # REF-DATA
├── /infrastructure
│   ├── helm/                   # Kubernetes charts
│   ├── terraform/              # NITA-U + DR site
│   └── runbooks/               # ops runbooks
├── /tests
│   ├── unit/
│   ├── integration/
│   ├── contract/               # OpenAPI contract tests
│   └── e2e/
├── /design                     # design source-of-truth — see /design/README.md
│   ├── nsr-mis-console.html    # runnable preview harness (React + Babel-standalone)
│   ├── styles.css, app.jsx, components.jsx, tweaks-panel.jsx   # harness
│   └── v0.1/                   # versioned design snapshot
│       ├── tokens.css          # design tokens — from /docs/04 §4
│       ├── components.md       # component library contract
│       ├── acceptance.md       # screen → user story map + acceptance gates
│       └── screens/            # JSX screens, one file per module
└── /scripts
    ├── load_ubos_geography.py
    └── seed_dqa_rules.py
```

## Sprint 0 deliverables (what to build first)

From SAD §11.4. Build these in order:

1. **Repo scaffolding** with the module structure above. Django + DRF baseline. Keycloak realm. API gateway base routes.
2. **PostgreSQL schema** for Household and Member with versioning tables and audit trigger. Migrations are forward-only in production. See SAD §5 for entities.
3. **REF-DATA**: load the UBOS GeographicUnit hierarchy (versioned). Loader script under `/scripts/load_ubos_geography.py`.
4. **DAT-DQA scaffold**: rules engine, Rule Editor admin view, dual-approval workflow. Wire 3 rules end-to-end: AC-MANDATORY, AC-NIN-FORMAT, AC-GPS-ACCURACY. See SAD §4.2.
5. **DAT-DDUP tier 1**: NIN deterministic matcher, basic Dedup Dashboard, side-by-side compare, merge-commit transaction. See SAD §4.3.
6. **DIH framework scaffold**: SourceSystem + Connector + ConnectorRun pipeline. Raw landing, mapping rule application, promotion API wired to DAT. Configure UBOS and Kobo connectors. Provisional Registry ID lifecycle. See SAD §4.6.
7. **OpenAPI 3.1 skeleton** for each module, published in the developer portal scaffold.
8. **CI pipeline**: SAST, dependency scan, unit tests, contract tests, ephemeral environment smoke test.
9. **Sandbox NIRA mock** for development before live integration.
10. **Threat model workshop** and **DPIA initial draft** (with the Data Protection Officer).

## Coding standards

- **Trunk-based development.** Short-lived feature branches. Mandatory code review.
- **Tests first** for any change touching DAT, DAT-DQA, DAT-DDUP, UPD, or DIH promotion. These are the audit-bearing modules.
- **Every API ships with an OpenAPI spec.** Contract tests run in CI.
- **Migrations are versioned and reversible** through Sprint 5; forward-only thereafter. The reverse plan is attached to the release ticket.
- **Audit on everything personal.** Any read or write of personal data writes an `AuditEvent` (SEC). See SAD §8.4.
- **No raw SQL outside `data_management` and `ingestion_hub`.** Other apps go through DRF serialisers or the Django ORM.
- **Geographic data uses PostGIS.** GPS columns are `geometry(Point, 4326)`.
- **Identifiers are ULIDs.** Never sequential integers for externally-visible IDs.
- **NIN is encrypted at rest** (column-level AES-256). Store a `nin_hash` for joins.
- **Timezone**: persist as UTC, render as EAT (UTC+3) in UI.
- **i18n**: every user-facing string goes through Django's translation framework, even the English baseline.

## Anti-patterns (do not do)

- Do not bypass DIH. Even Parish Chief walk-in submissions land in DIH first. The fast-track auto-promote handles the friction.
- Do not duplicate DQA or DDUP logic inside DIH and the registry. Call the shared service.
- Do not write `localStorage` or `sessionStorage`-style "we'll fix it later" caches. The registry must be reconstructable from the audit chain.
- Do not run PMT in DIH. PMT is a registry-only post-promotion trigger.
- Do not soften approval gates "just for testing". The audit trail must be intact from day one.
- Do not use sequential primary keys for any entity exposed externally.
- Do not commit `.env` or any KMS-managed secret. Use Keycloak service accounts and the secrets manager.

## Definition of Done (per story)

From SAD §11.5:

1. Code merged behind a feature flag with passing CI (lint, SAST, unit, contract).
2. Acceptance criteria validated by the QA lead.
3. API contract published in `/docs/openapi/{module}.yaml` where applicable.
4. Audit events emitted and validated by a contract test.
5. Documentation updated: ADR if architectural, runbook if operational.
6. DPIA impact recorded if the story touches personal data.

## How to work

- **Read before you code.** When you encounter an architectural question, the answer is almost certainly in the SAD or the backlog. If it is not, write an ADR proposing the answer and surface the open question.
- **Anchor commits to user stories.** Format: `[US-XXX] short description`. Branch names: `us-xxx-short-description`.
- **Pick stories from the backlog in order of MoSCoW.** Must-priority first, Should next, Could last. Sprint 0 stories take precedence over the rest until §11.4 is complete.
- **Ask the user when ambiguity matters.** Especially around: routing matrices (UPD), match-model weights (DDUP), DSA scope (DRS), connector schemas (DIH). Default values are in the SAD's open-item tables; do not invent new ones.
- **Stop and report when you hit an open item.** The SAD §12 lists 40+ open items with owners and deadlines. If a story touches an unresolved open item, surface it before building.

## Reference documents

| Doc | What it contains | Read when |
|---|---|---|
| `/docs/01_solution_architecture.docx` | SAD v0.6. 56 pages. Architecture, modules, ERD outline, NFRs, MVP scope, open items, risks. | Start. Refer back often. |
| `/docs/02_erd.pdf` | Visual ERD over 5 clusters: Overview, Core, Workflow, Eligibility/Programmes/GRM/Sharing, DIH. | When modelling data. |
| `/docs/03_backlog.xlsx` | 114 stories across 16 epics with acceptance criteria. | Picking stories. |
| `/docs/04_ui_design_brief.md` | UI tokens, components, screen specs, status vocabulary. | When building screens or admin views. |
| `/docs/05_requirements.docx` | Functional + NFR baseline (v0.1, 13 May 2026). | Cross-check requirements. |
| `/docs/06_questionnaire.docx` | The actual field instrument (v2, March 2026). | When modelling Member, Health, Education, Employment, Dwelling, Utilities, Food, Shock, Coping. |
| `/docs/07_framework.docx` | Operating model, geographic structure, governance. | When stakeholder context matters. |

## Project glossary (quick reference)

- **DPPA 2019** — Data Protection and Privacy Act, 2019 (Uganda).
- **DSA** — Data Sharing Agreement (outbound).
- **DPA** — Data Provision Agreement (inbound; for DIH).
- **MGLSD** — Ministry of Gender, Labour and Social Development.
- **NITA-U** — National Information Technology Authority, Uganda.
- **NIRA** — National Identification and Registration Authority.
- **UBOS** — Uganda Bureau of Statistics.
- **PMT** — Proxy Means Test.
- **PDM** — Parish Development Model.
- **NUSAF** — Northern Uganda Social Action Fund.
- **CAPI** — Computer-Assisted Personal Interviewing (tablet field channel).
- **EAT** — East Africa Time (UTC+3).

---

End of project memory. Version 1.0, 14 May 2026.
