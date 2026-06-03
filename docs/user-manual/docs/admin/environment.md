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
| `QUESTIONNAIRE_EDITOR_V2` | `DEBUG` | Gates the Sprint 19 Questionnaire builder admin UI (US-117b). |
| `CHATBOT_ENABLED` | `False` | Gates the Chatbot RAG endpoints (ADR-0021, US-CHB-001..006). |

## Email / SMTP (v0.3)

The system sends transactional email for PMT sign-off, DSA signing, Programme sign-off, DRS request lifecycle, and DPO audit-chain alerts. If SMTP credentials are present, the app defaults to the SMTP backend automatically; otherwise it falls back to the console backend so dev/CI stay side-effect free.

| Variable | Default | Notes |
|---|---|---|
| `EMAIL_BACKEND` | `django.core.mail.backends.console.EmailBackend` | Falls back to console when no SMTP creds are present. Set explicitly to `django.core.mail.backends.smtp.EmailBackend` to force delivery. |
| `EMAIL_HOST` | `comms.quasar.ug` | The quasar.ug relay (same one the rental_project uses) |
| `EMAIL_PORT` | `587` | STARTTLS port |
| `EMAIL_USE_TLS` | `True` | |
| `EMAIL_HOST_USER` | (empty) | Set to `admin@quasar.ug` in prod |
| `EMAIL_HOST_PASSWORD` | (empty) | KMS-managed in prod. **Never commit this to git** — `.env` is gitignored; `.env.example` carries only the placeholder. |
| `EMAIL_TIMEOUT` | `30` | seconds |
| `DEFAULT_FROM_EMAIL` | `NSR MIS <admin@quasar.ug>` | Used as the `From:` header when callers don't override |
| `SERVER_EMAIL` | `admin@quasar.ug` | Used by Django for error mails to ADMINS |
| `DPO_EMAIL` | (empty) | DPO inbox for chain-break alerts (`apps.security.tasks.verify_audit_chain_task`). Leave empty in dev to disable alerts. |
| `SLACK_WEBHOOK_URL` | (empty) | Parallel chain-break channel. Independent of email. |

To roll out real email to a new environment:

1. Get the SMTP password from the secrets manager (or copy from the `comms` rental_project — same relay).
2. Set `EMAIL_HOST_USER` + `EMAIL_HOST_PASSWORD`. The app will prefer SMTP automatically; set `EMAIL_BACKEND` explicitly only if you want to override the default.
3. Smoke-test via the Django shell:
   ```python
   from django.core.mail import send_mail
   send_mail("[NSR MIS] SMTP smoke test", "body", None, ["you@example.com"], fail_silently=False)
   ```
4. Once verified, set `DPO_EMAIL` (and optionally `SLACK_WEBHOOK_URL`) so the audit-chain task starts alerting on tampering.

See [Notifications](notifications.md) for the workflow→recipient matrix.

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
