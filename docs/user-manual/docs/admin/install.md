# Install and run

!!! info "Status"
    **Built and in use** — for dev and pilot. Production deployment is Planned for Sprint 7.

Two install paths. Docker is closest to production. The venv path is faster but uses sqlite by default, which means the audit-chain trigger and PostGIS columns degrade to no-ops.

## Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.12 (locked, `>=3.12,<3.13`) |
| Docker | 24 with the `compose` plugin |
| PostgreSQL | 16 with PostGIS 3.4 (handled by the Docker image) |
| Node | 20 (only if you work on the design harness) |

## Path A — Docker (recommended)

This brings up PostgreSQL+PostGIS, Redis, and the Django app on the same network.

```bash
# from the repo root
docker compose up --build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

Open `http://localhost:8000/admin/` for the Django admin and `http://localhost:8000/api/docs/` for the Swagger UI.

Code is bind-mounted, so changes auto-reload.

### Production database

The `compose` web service overrides the production CMD with `runserver` for live reload. For production-shaped local testing, run the image as built:

```bash
docker run --rm \
  -e DATABASE_URL=postgres://nsr:nsr@host.docker.internal:5432/nsr \
  -e DJANGO_SECRET_KEY=$(openssl rand -hex 32) \
  -e DEBUG=False \
  -e ALLOWED_HOSTS=localhost \
  -e NSR_NIN_PEPPER=$(openssl rand -hex 32) \
  -e NSR_DATA_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  -p 8000:8000 \
  nsr-mis:local
```

If you leave the dev-default secrets in place, the `security.E001` / `E002` / `E003` system checks fail boot. That is the point.

## Path B — venv (light, sqlite fallback)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python manage.py migrate
python manage.py runserver
```

Or use the launcher:

```bash
./start-nsr-ug.sh                   # bind 127.0.0.1:8000, opens browser
./start-nsr-ug.sh 9000              # custom port
./start-nsr-ug.sh 0.0.0.0:8000      # LAN access
NSR_NO_OPEN=1 ./start-nsr-ug.sh     # don't open the browser
NSR_NO_MIGRATE=1 ./start-nsr-ug.sh  # skip migrate
```

The launcher prints these URLs:

| URL | Purpose |
|---|---|
| `http://localhost:8000/console/` | Design harness (the React operator console) |
| `http://localhost:8000/admin/` | Django admin |
| `http://localhost:8000/api/schema/` | OpenAPI 3.1 schema (JSON) |
| `http://localhost:8000/api/docs/` | Swagger UI |

You need a Django superuser to log in to the console:

```bash
python manage.py createsuperuser
```

### sqlite caveats

- The **audit-chain trigger** (`security/0002_auditevent_chain_trigger.py`) is Postgres-only and silently no-ops on sqlite. That means the SAD §8.4 hash-chain guarantee does not hold in your dev DB.
- **PostGIS columns** stay as decimal lat/lng on sqlite. The PointField + GIST index land in a future migration.
- The `@pytest.mark.postgres` and `@pytest.mark.sqlite_only` markers auto-skip the tests that depend on either backend, so the test suite passes on both.

## First-run checklist

After `migrate` and `createsuperuser`:

```bash
# 1. Seed the UBOS administrative hierarchy
python scripts/load_ubos_geography.py /path/to/Goegraphy_final_with_codes.xlsx

# 2. Wire the three Sprint 0 DQA rules with dual-approval
python scripts/seed_dqa_rules.py

# 3. Configure the four MVP DIH source systems (UBOS, CAPI, Web, Kobo)
python scripts/seed_dih_sources.py
```

Then visit `/admin/`, log in with your superuser, and confirm you can list Households, Members, GeographicUnits, DQA Rules, and DIH SourceSystems.

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `security.E001/E002/E003` on boot | Dev-default secrets in production env | Set `NSR_NIN_PEPPER`, `NSR_DATA_KEY`, `DJANGO_SECRET_KEY` to real values |
| `security.E004` on boot | Non-Postgres DATABASE_URL with `DEBUG=False` | Switch to PostgreSQL |
| `ERROR: .venv/ not found` from `start-nsr-ug.sh` | venv missing | `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` |
| `psycopg.OperationalError` | Postgres not up | `docker compose up db` first, or check `DATABASE_URL` |

## Related

- [Environment variables](environment.md)
- [Keycloak and access](keycloak.md)
- ADR-0003 — Migration policy
- ADR-0006 — Keycloak realm design
