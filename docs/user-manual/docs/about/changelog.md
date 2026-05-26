# Changelog

This manual tracks meaningful additions and corrections. For code-level changes see `/docs/api_changelog.md`.

## v0.1 — 25 May 2026

First cut. Created the MkDocs scaffold, the four audience guide indexes, the 17 module reference pages, and the glossary. Built against sessions S0 through S4.

### What is documented

- System Administrator guide (install, env, Keycloak pointer, reference-data loaders, connectors, observability, DPIA, runbooks).
- Data Steward guide (DQA Rule Editor, violations dashboard, dedup, DIH review queue, household detail, UPD review).
- Field officer guide (walk-in capture; CAPI, lookup, grievance, update pages stubbed with Planned badges).
- MDA Partner guide (onboarding, DSA lifecycle, query builder, field selector, portal, API reference).
- Module reference (17 modules, one page each, with status badge, endpoints, screens, ADRs, story IDs).

### What is not yet documented

- CAPI tablet operating procedures (Planned — S8 once US-117 and US-118 land).
- Single Registry / Beneficiary Data Exchange (Planned — US-058 to US-062 not started).
- Production deployment runbook (Planned — once Helm chart lands under `/infrastructure/helm/`).
- The full DRS delivery flow (Planned — US-099 to US-104).
- Outbound API consumer SDK (Planned — US-S6 onwards).

### Known gaps in v0.1

- The Field officer guide leans heavily on screenshots that don't exist yet. The pages describe behaviour from the JSX screens under `/design/v0.1/screens/`.
- The Partner API reference points to the Swagger UI rather than reproducing the spec. This is on purpose — the Swagger UI is generated from code and is always current.
- Helm and Terraform runbook pages are placeholders.
