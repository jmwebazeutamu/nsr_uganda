# How to read this manual

## The four audience guides

Each guide is written for one role. Pick the guide that matches your job and stay in it. Cross-references point you to other guides when the work crosses boundaries.

| Guide | What you will find |
|---|---|
| System Administrator | Install, run, secrets, Keycloak, reference-data loaders, observability. |
| Data Steward / DQA Officer | Rule editor, dual-approval, violations dashboard, dedup workbench, household review. |
| Parish Chief / Field officer | Walk-in capture, household lookup, grievances, update requests, CAPI tablet. |
| MDA Partner / API consumer | DSA lifecycle, query builder, field selector, partner portal, API reference. |

## The module reference

The module reference has one page per functional module (INT, DAT, DAT-DQA, DAT-DDUP, etc.). Each module page lists:

- Status (one of four badges).
- What the module does in two sentences.
- Endpoints (DRF routes, with the OpenAPI tag).
- Screens (which JSX files under `/design/v0.1/screens/`).
- Key ADRs.
- Story IDs from `/docs/03_backlog.xlsx`.

If you are deep in the code and want to know "what is the contract for this module", go straight to the [Module reference](../modules/index.md).

## Status badges

Every page carries a badge near the top.

| Badge | Meaning |
|---|---|
| **Built and in use** | The feature works end-to-end. Tests cover it. You can use the page as a manual. |
| **Partial** | The feature is usable but the page calls out gaps. Don't assume completeness. |
| **Scaffolded** | Models and URLs exist. No operator surface. The page describes the intended behaviour. |
| **Planned** | Not built. The page describes the planned slice and the target sprint. |

See the [Status legend](../appendices/status-legend.md) for the full definition.

## Conventions

- Times are persisted as UTC and rendered in **East Africa Time (UTC+3)**.
- Measurements use the **metric system**.
- Money is in **Uganda Shillings (UGX)**.
- IDs that look like `01HXYZ...` are ULIDs (see [ADR-0002](../appendices/adrs.md)).
- Code examples assume you are at the repo root.
- Commands prefixed with `$` run in your shell.
- File paths beginning with `/` are repo-relative, not absolute on your machine.

## What this manual is not

- Not the **Solution Architecture Document**. The SAD (`/docs/01_solution_architecture.docx`) is the master spec. This manual is for users; the SAD is for designers and reviewers.
- Not the **API reference**. The OpenAPI 3.1 schema at `/api/schema/` and the Swagger UI at `/api/docs/` are generated from code and stay accurate. This manual links to them.
- Not the **runbook**. Production runbooks live under `/infrastructure/runbooks/`. The Sysadmin guide points you to the relevant runbook for each task.
