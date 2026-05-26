# System Administrator guide

You are here to install, run, secure, and operate the NSR MIS platform. This guide covers everything from `docker compose up` to wiring Keycloak and loading the UBOS geographic hierarchy.

!!! info "Status"
    Most of what an administrator needs to run a **development or pilot** environment is built and documented. Production deployment (Helm, Terraform, NITA-U onboarding) is **Planned** for Sprint 7 onwards.

## Where to start

| If you are... | Read this first |
|---|---|
| Standing up your first dev environment | [Install and run](install.md) |
| Switching from sqlite to Postgres for the audit chain | [Install and run § Production database](install.md#production-database) |
| Setting `.env` for a deployed environment | [Environment variables](environment.md) |
| Wiring Keycloak for the first time | [Keycloak and access](keycloak.md) |
| Loading UBOS districts, parishes, and villages | [Reference data loaders](reference-data.md) |
| Configuring a new DIH source (Kobo, NIRA, UBOS) | [DIH connectors](connectors.md) |
| Running metrics or chasing a slow query | [Observability](observability.md) |
| Filing the sprint DPIA or escalating a security finding | [DPIA and threat model](dpia-and-threat-model.md) |
| Recovering from an incident | [Runbooks](runbooks.md) |

## What you must know

- **Production must run on PostgreSQL.** The audit-chain integrity trigger is Postgres-only. The `security.E004` system check blocks boot on anything else when `DEBUG=False`.
- **The `.env` defaults are markers, not credentials.** `security.E001`, `E002`, and `E003` system checks fail-closed when production env matches the dev-default `NSR_NIN_PEPPER`, `NSR_DATA_KEY`, or `DJANGO_SECRET_KEY`.
- **Migrations are reversible through Sprint 5; forward-only thereafter.** See [ADR-0003](../appendices/adrs.md).
- **NIN is encrypted at rest (AES-256) and stored with a peppered hash for joins.** See [ADR-0002](../appendices/adrs.md).
- **Time is persisted as UTC; render in EAT (UTC+3).** Use Django's `TIME_ZONE` and the i18n helpers.

## Repository tour for admins

```
nsr_sris_dev/
├── docker-compose.yml          # local stack: PostGIS, Redis, web
├── Dockerfile                  # production image (gunicorn)
├── start-nsr-ug.sh             # dev server launcher
├── pyproject.toml              # Python deps + ruff/pytest config
├── .env.example                # copy to .env
├── manage.py
├── nsr_mis/settings.py         # the one settings file
├── apps/security/checks.py     # the fail-closed system checks
├── scripts/                    # loaders and seeds (UBOS, DQA rules, DIH sources)
└── infrastructure/             # helm, terraform, runbooks (mostly Planned)
```
