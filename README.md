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

Two paths. Pick whichever fits.

**Docker (recommended — closest to production):**

```bash
docker compose up --build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

Brings up Postgres+PostGIS, Redis, and the Django app at `http://localhost:8000`. Code is bind-mounted for auto-reload.

**venv (lightweight; uses sqlite fallback):**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python manage.py migrate
python manage.py runserver
```

Note: sqlite is a fallback for the dev loop only. The audit-chain trigger and PostGIS GPS columns are postgres-only and degrade to no-ops on sqlite.

## Production deployment

Image: built from the root `Dockerfile`. Targets Kubernetes on the NITA-U Government Data Centre. Helm chart lives under `/infrastructure/helm/` (to be filled in).

## Reference

- Master spec: `/docs/01_solution_architecture.docx` (SAD v0.6).
- User stories: `/docs/03_backlog.xlsx`.
- UI brief: `/docs/04_ui_design_brief.md`.
