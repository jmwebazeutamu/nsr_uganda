# Production server setup — command log

Every command run against the production host **154.72.204.74**
(`nsr-sris.mglsd.go.ug`) is recorded here, in order, with its date and
what it was for.

Rules this log follows:
- **No secret values.** Secrets are referred to by name only
  (`DJANGO_SECRET_KEY`, `PROD_SSH_KEY`, …). Commands that would print a
  value are recorded with the value redacted.
- Commands run on **dev** are logged only where they are part of the
  migration (dumps, checksums, transfers). Routine dev work is not.
- Destructive commands are recorded together with the approval that
  authorised them.

Host facts (no secrets):

| | |
|---|---|
| IP | 154.72.204.74 |
| Hostname | nsr-sris.mglsd.go.ug |
| Admin user | jmwebaze (sudo) |
| App directory | /opt/nsrmis |
| Migration staging | /opt/nsrmis/migration (chmod 700) |
| Compose file | compose.production.yml |

---

## Phase 1 — audit of dev (read only)

No commands were run on production. The dev audit is summarised in
`docs/PRODUCTION.md`; nothing on the production host was touched.

---

## Phase 2 — repository preparation

Repository-only changes, committed from dev. No production commands.

| Date | Change |
|---|---|
| 2026-09-17 | `.gitignore` extended: `migration/`, dumps, archives, backups, `docker-compose.override.yml`, `.ci-test.env`, `.consent-evidence/` |
| 2026-09-17 | `.env.production.example` added — every variable, no values |
| 2026-09-17 | `.env.example` extended with the full variable catalogue |
| 2026-09-17 | `compose.production.yml` added — fully containerised prod stack |
| 2026-09-17 | `infrastructure/nginx/` added — HTTP and TLS vhosts + proxy snippet |
| 2026-09-17 | `Dockerfile` — `/app/data/*` mountpoints pre-created as `app:app` |
| 2026-09-17 | `compose.prod.yml` — header clarified as TESTING/TRAINING only |
| 2026-09-17 | `.github/workflows/deploy.yml` — `deploy-production` job added, disabled |
| 2026-09-17 | `docs/BRANCHING.md` added |

---

## Phase 3 — production server preparation

_Not started. Awaiting Checkpoint 2 approval._

---

## Phase 4 — GitHub → production

_Not started._

---

## Phase 5 — first deploy (HTTP, empty database)

_Not started._

---

## Phase 6 — data migration

_Not started._

---

## Phase 7 — SSL and go-live

_Not started._

---

## Phase 8 — backups and rollback

_Not started._
