# Environment variables

!!! info "Status"
    **Built and in use**

Every NSR MIS environment is configured through env vars. The `.env.example` file lists every variable with its dev-default value. Copy it to `.env` for local work. For deployed environments, source values from the NITA-U KMS or your secrets manager.

## Required in every environment

| Variable | Purpose | How to generate |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django session signing, CSRF, password reset tokens | `openssl rand -hex 32` |
| `ALLOWED_HOSTS` | Comma-separated hostnames Django will serve | List your domains |
| `DEBUG` | `True` for dev only | Always `False` outside dev |

## Required in production

The three security-relevant secrets that the `apps.security.checks` system checks fail-closed against.

| Variable | Purpose | Failure mode if not set |
|---|---|---|
| `NSR_NIN_PEPPER` | Peppered hash for NIN join key (per ADR-0002) | `security.E001` blocks boot |
| `NSR_DATA_KEY` | Fernet key for column-level NIN encryption | `security.E002` blocks boot |
| `DJANGO_SECRET_KEY` | Must not start with `dev-only-` | `security.E003` blocks boot |

Generate the data key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generate the pepper with:

```bash
openssl rand -hex 32
```

Both belong in the NITA-U KMS. Rotate per the rotation runbook (Planned in Sprint 8).

## Database and message bus

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgres://nsr:nsr@db:5432/nsr` | If unset, sqlite is used for dev. `security.E004` blocks non-Postgres in production. |
| `REDIS_URL` | `redis://redis:6379/0` | Celery broker + result backend |
| `CELERY_BROKER_URL` | inherits `REDIS_URL` | Override only if you split brokers |

## Feature flags

| Variable | Default | Effect |
|---|---|---|
| `PARTNERS_MODULE_ENABLED` | `True` | Gates the partners-module UI + write endpoints (US-S23). Read endpoints stay open. |
| `PARTNERS_DOCUSIGN_ENABLED` | `False` | Switches DSA signature backend from the in-memory stub to DocuSign (per ADR-0012). CI keeps this false. |

## Per-environment values

Suggested matrix:

| Variable | Dev (venv) | Dev (docker) | Pilot | Production |
|---|---|---|---|---|
| `DEBUG` | True | True | False | False |
| `DATABASE_URL` | (unset → sqlite) | postgres://nsr:nsr@db:5432/nsr | KMS-managed | KMS-managed |
| `ALLOWED_HOSTS` | localhost,127.0.0.1 | localhost,127.0.0.1,web | pilot.nsr.go.ug | nsr.go.ug |
| `NSR_NIN_PEPPER` | dev default | dev default | KMS | KMS |
| `NSR_DATA_KEY` | dev default | dev default | KMS | KMS |
| `PARTNERS_DOCUSIGN_ENABLED` | False | False | False | True (when MoU lands) |

## .env hygiene

- `.env` is in `.gitignore`. Never commit it.
- The dev-default values in `.env.example` are markers, not credentials. They are public on purpose so the system checks can recognise and reject them.
- Helm and Terraform pull secrets from the NITA-U KMS, not from a baked-in `.env`. The Helm chart and Terraform modules are Planned (Sprint 7+).

## Related

- [Install and run](install.md)
- ADR-0002 — Identifier and encryption strategy
- `/docs/dpia/` — sprint DPIAs that touch secrets
