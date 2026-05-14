# NSR MIS — Uganda National Social Registry

Implementation of the National Social Registry MIS for the Ministry of Gender, Labour and Social Development (MGLSD). Target scale: 12 million households across 9 sub-regions.

## Status

Sprint 0 — repo scaffolding in progress. See `CLAUDE.md` §"Sprint 0 deliverables" for the build order.

## Where things live

| Path | What |
|---|---|
| `CLAUDE.md` | Project memory: locked stack, architecture, coding standards, anti-patterns. Read first. |
| `/docs/` | Canonical specs: SAD, ERD, backlog, requirements, questionnaire, framework, UI brief. Read-only inputs. |
| `/design/` | Design source-of-truth: tokens, components contract, JSX screens for the operator console. See `/design/README.md`. |
| `/apps/` | Django apps — one per functional module. 12 modules + 3 cross-cutting. |
| `/infrastructure/` | Helm charts, Terraform, runbooks. |
| `/tests/` | unit / integration / contract / e2e. |
| `/scripts/` | One-off loaders and seeds. |
| `nsr_mis/` | Django project package (settings, root URLs, WSGI/ASGI). |

## Local development

Not yet wired. Sprint 0 item 1 in progress.

## Reference

- Master spec: `/docs/01_solution_architecture.docx` (SAD v0.6).
- User stories: `/docs/03_backlog.xlsx`.
- UI brief: `/docs/04_ui_design_brief.md`.
