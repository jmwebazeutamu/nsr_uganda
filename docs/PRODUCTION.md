# NSR MIS — Production

**Host:** `nsr-sris.mglsd.go.ug` · **Version 1.0, 17 September 2026**

Operating manual for the MGLSD production server. Contains no secrets.

---

## 1. The server

| | |
|---|---|
| Hostname | `nsr-sris.mglsd.go.ug` |
| IP | `154.72.204.74` (IPv4 only — see §9) |
| OS | Ubuntu 26.04 LTS, amd64, 4 vCPU, 15 GiB RAM, 98 GB disk |
| Admin user | `jmwebaze` (sudo, in the `docker` group) |
| App directory | `/opt/nsrmis` (a git checkout of `main`) |
| Secrets | `/opt/nsrmis/.env`, mode `600`, never committed |
| Compose file | `compose.production.yml` (project `nsr-sris-prod`) |
| TLS | Let's Encrypt, auto-renewing |
| Timezone | UTC (rendered as EAT in the UI) |

**The training/testing server is a different machine**: `nsr-sris-dev.quasar.ug`
(`104.225.218.102`), using `compose.prod.yml`. The two files are not
interchangeable — check the hostname before running anything.

### Services

Eight containers. **Only nginx is reachable from the internet.**

| Service | Image | Exposed | Purpose |
|---|---|---|---|
| `nginx` | `nginx:1.27-alpine` | **80, 443** | TLS, path routing |
| `web` | `nsr-mis:<sha>` | — | the registry (gunicorn) |
| `public` | `nsr-mis:<sha>` | — | public site (`ROOT_URLCONF=urls_public`) |
| `worker` | `nsr-mis:<sha>` | — | Celery worker |
| `beat` | `nsr-mis:<sha>` | — | Celery scheduler |
| `db` | `postgis/postgis:16-3.4` | — | PostgreSQL 16.4 + PostGIS 3.4.3 |
| `redis` | `redis:7-alpine` | — | broker + result backend |
| `certbot` | `certbot/certbot:v3.1.0` | — | certificate renewal loop |

`db` and `redis` sit on the `backend` network and publish **no ports at
all** — they are unreachable from the host, let alone the internet.

### Routing

One hostname, two application containers, path-routed by nginx:

```
/                          -> public    (cookies stripped — LP-O-10)
/login/ /logout/ /home/    -> web
/console/ /admin-console/  -> web
/admin/ /api/ /manual/     -> web
/static/                   -> web (WhiteNoise serves both sites)
/healthz                   -> web, NOT redirected to HTTPS (probes use it)
unknown Host header        -> 444, connection closed
```

### Persistent data

Nine named volumes. They survive `restart`, `stop`, `down`, `up -d`,
image upgrades and host reboots (`restart: unless-stopped` plus
`docker.service` enabled at boot).

```
pgdata  redisdata  media_data  drs_bundles  upd_evidence
consent_evidence  certbot_conf  certbot_www  nginx_logs
```

> **The only command that destroys them is `docker compose down -v`.**
> Nothing in this document, and no script in this repository, uses it.
> There is never a reason to.

---

## 2. How a change reaches production

```
dev branch ──PR──> main ──CI──> training (automatic)
                     │
                     └──> production (one command, deliberate)
```

1. Branch from `main` (`us-xxx-short-description`), commit as
   `[US-XXX] short description`.
2. Open a PR into `main`. CI runs lint, SAST, unit and contract tests.
3. Merge. CI runs on `main`; on success the **training** box deploys
   automatically. Training is the canary.
4. **If training is green, deploy production:**

```bash
ssh nsr-prod /opt/nsrmis/deploy.sh
```

Production builds its own image from the checkout. No registry is
involved — see §10 for why.

---

## 3. Deploying

```bash
ssh nsr-prod /opt/nsrmis/deploy.sh          # deploy tip of origin/main
ssh nsr-prod /opt/nsrmis/deploy.sh --yes    # no prompts (cron/scripted)
```

What it does, in order: fetch `origin/main` → refuse anything not on
`main` → check out → **build** → switch `NSR_IMAGE` → `up -d` →
`restart nginx` → migrate → health check → prune old images.

Takes 30–60 seconds with warm layers; several minutes on a cold cache.

**Safety properties:**

- Containers are never stopped until a new image has built successfully.
  A failed build leaves the site serving and restores the checkout.
- A commit that is not an ancestor of `origin/main` is refused.
- Deploying an *older* commit requires an explicit `--rollback`.
- A failed health check restores the previous image automatically and
  exits non-zero.
- The last 3 builds are kept for fast rollback; older ones and week-old
  build cache are pruned (each image is ~2.7 GB).

Log: `/opt/nsrmis/deploy.log`.

---

## 4. Rolling back

```bash
ssh nsr-prod '/opt/nsrmis/deploy.sh <older-sha> --rollback'
```

Near-instant if that image is still on disk, otherwise it rebuilds. The
health check guards it either way; if the rollback itself is unhealthy,
the script restores what was running before.

To see what is available:

```bash
ssh nsr-prod 'docker images nsr-mis --format "{{.Tag}}  {{.CreatedSince}}"'
ssh nsr-prod 'cd /opt/nsrmis && git log --oneline -10'
```

A **bad migration** is not covered by this: rolling the image back does
not roll the schema back. Migrations are reversible through Sprint 5
(CLAUDE.md), so the reverse plan on the release ticket is the procedure —
restore from backup if there is no reverse path.

---

## 5. Day-to-day operations

All commands run from `/opt/nsrmis`. `dc` below is shorthand for
`docker compose -f compose.production.yml --env-file .env`.

```bash
# Status
ssh nsr-prod 'cd /opt/nsrmis && docker compose -f compose.production.yml --env-file .env ps'

# Logs (follow one service)
... logs -f web
... logs --tail=200 nginx

# Restart one service
... restart web

# Restart everything (keeps data)
... restart

# Django shell
... exec web python manage.py shell

# Stop / start the stack (NEVER add -v)
... stop
... up -d
```

### Accounts

```bash
ssh nsr-prod /opt/nsrmis/nsr-user list            # role, scope, flags, last login
ssh -t nsr-prod /opt/nsrmis/nsr-user create <user> --role <role> --scope-code <code>
ssh -t nsr-prod /opt/nsrmis/nsr-user passwd <user>
ssh nsr-prod /opt/nsrmis/nsr-user disable <user>
ssh nsr-prod /opt/nsrmis/nsr-user roles
```

Use `ssh -t` for `create` and `passwd` — they prompt for a password and
need a terminal.

**Never delete an account that has touched personal data.** The audit
chain (SAD §8.4) references it. `disable` is the correct action for a
leaver.

An account with a role but **no scope** can sign in and will see
*nothing* — the ABAC mixins fail closed and every list returns zero rows
with no error. `nsr-user list` shows these as `NONE (blind)`.

### TLS

Renewal is automatic: the `certbot` container runs `certbot renew` every
12 h and nginx reloads every 6 h to pick up a new certificate.

```bash
# Check expiry
echo | openssl s_client -servername nsr-sris.mglsd.go.ug \
        -connect nsr-sris.mglsd.go.ug:443 2>/dev/null | openssl x509 -noout -dates

# Dry-run a renewal
ssh nsr-prod 'cd /opt/nsrmis && docker compose -f compose.production.yml --env-file .env \
  run --rm --entrypoint certbot certbot renew --webroot -w /var/www/certbot --dry-run'
```

Renewal notices go to the address registered with Let's Encrypt. **This
is currently a personal Gmail account and should be moved to a ministry
role address** (`certbot update_account`).

### After editing an nginx config

`up -d` is **not** enough. Compose sees no change to the service spec
when only a file inside a mounted directory differs, so the boot-time
config copy never re-runs:

```bash
ssh nsr-prod 'cd /opt/nsrmis && docker compose -f compose.production.yml --env-file .env restart nginx'
```

`deploy.sh` already does this.

---

## 6. Backups — NOT YET IMPLEMENTED

> **Production has no automated backup.** This is a known, accepted gap,
> deliberately deferred to the backlog. It is the largest outstanding
> operational risk: 113,990 rows including 992 encrypted NINs, with no
> recovery path other than a fresh dev dump.

Until it is built, take a manual dump before anything risky:

```bash
ssh nsr-prod 'cd /opt/nsrmis && docker compose -f compose.production.yml --env-file .env \
  exec -T db pg_dump -U nsr -d nsr -Fc --no-owner --no-acl' > nsr_prod_$(date -u +%Y%m%dT%H%M%SZ).dump
```

Restore (destructive — confirm the target first):

```bash
# stop the app, leave db running
... stop nginx public worker beat web
... exec -T db psql -U nsr -d postgres -c "DROP DATABASE nsr;"
... exec -T db psql -U nsr -d postgres -c "CREATE DATABASE nsr OWNER nsr;"
docker run --rm --network nsr-sris-prod_backend -v /path/to/dumps:/m:ro \
  -e PGPASSWORD=... postgis/postgis:16-3.4 \
  pg_restore -h db -U nsr -d nsr --no-owner --no-acl -j 2 /m/<dump>
... up -d
```

Dumps contain live personal data under the DPPA 2019. Keep them `600`,
off the web root, and **`shred -u`** them when finished — `rm` on ext4
only unlinks.

**What the backlog item needs:** nightly database + volume backup,
14-day retention, copies off the server, a tested restore, and a
documented RPO/RTO. Pull-based (an external host fetching) is preferable
to push-based, so that compromise of production cannot reach the archive.

---

## 7. How production was populated

A full copy of the dev registry, cut off at **`20260917T020653Z`** UTC.

| | Dev | Production |
|---|---|---|
| Tables | 125 | **125** |
| Total rows | 113,990 | **113,990** |
| Households / Members / Users | 284 / 1,283 / 11 | **284 / 1,283 / 11** |
| Audit events | 80,430 | **80,430** |
| Geographic units | 13,951 | **13,951** |
| DRS bundle files | 4 | **4** |

**Row counts were identical on every table.** Method: `pg_dump -Fc` from
the running dev container (dev never stopped), SHA-256 verified after
transfer, `pg_restore` into a freshly created database, then file volumes
restored and `chown`ed to the image's `app` user (999:999).

### The encryption key rotation

The dev `NSR_DATA_KEY` and `NSR_NIN_PEPPER` are the values published in
`.env.example` — and therefore in git history. `apps/security/checks.py`
refuses to boot with them when `DEBUG=False`, by design, so production
could not simply inherit them. Nor could it adopt fresh keys, which would
have made all 992 encrypted NINs permanently unreadable.

`manage.py rotate_encryption_keys` bridges that: it re-encrypts every
column-level secret under the new key and recomputes `Member.nin_hash`
under the new pepper.

```
993 values re-encrypted (992 NINs + 1 Kobo token), 0 unreadable
verified afterwards: 992/992 decrypt, 992/992 nin_hash match
```

Production uses keys that have never been published. The same command
works in either direction, so a future dev↔prod data refresh repeats it.

### Data not yet cleaned

Carried over from dev and **left in place** by instruction. All 11
accounts were kept, including 8 superusers (six are smoke-test accounts:
`detail-smoke`, `regression-smoke`, `regression-smoke2`, `seed-smoke`,
`nusaf-debug`, `dev`).

| Location | Rows | Example |
|---|---|---|
| `auth_user.email` | 2 | `admin@example.com`, `dev@example.com` |
| `partners_dsasignature.signer_email` | 1 | `@quasar.ug` |
| `partners_programmesignoff` expected/actual | 4 | `@quasar.ug` |
| `chatbot_manualchunk.content` | 7 | text mentioning localhost |
| `security_auditevent` | 9 | **do not edit — hash-chained (SAD §8.4)** |

These matter now that notification mail can be configured: sign-off
reminders would go to `@quasar.ug` and `@example.com` addresses.

---

## 8. Environment variables

In `/opt/nsrmis/.env`, mode `600`. Names only. Template:
`.env.production.example`.

**Deployment:** `NSR_IMAGE` (pinned, never `:latest`), `NGINX_CONF`,
`PUBLIC_HOST`

**Core:** `DEBUG` (False), `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`,
`NSR_SECURE_SSL` (True), `CSRF_TRUSTED_ORIGINS`, `NSR_WHITENOISE`

**Database:** `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`,
`DATABASE_URL`, `DATABASE_URL_ANALYTICS` — the `POSTGRES_*` trio creates
the database and the URLs connect to it; **they must agree**

**Crypto:** `NSR_NIN_PEPPER`, `NSR_DATA_KEY` — changing either without
running `rotate_encryption_keys` makes existing data unreadable

**Celery:** `CELERY_ENABLED`, `CELERY_TASK_ALWAYS_EAGER` (False),
`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`

**Storage:** `DRS_BUNDLE_STORAGE`, `UPD_EVIDENCE_STORAGE`,
`CONSENT_EVIDENCE_STORAGE` (the *directories* are set in compose so they
cannot drift from the volumes)

**Flags:** `CONSENT_MODULE_ENABLED`, `DQA_INTRA_HOUSEHOLD_ENABLED`,
`DATA_EXPLORER_ENABLED`, `CHATBOT_ENABLED`, `DQA_RULE_EDITOR_V2`,
`NSR_PUBLIC_API_DOCS` (False), `NSR_PUBLIC_STATS_LIVE` (False until DPO
sign-off, LP-O-06), `NSR_ENFORCE_DATA_PERMISSIONS` (True)

**Email (currently unset — console backend):** `EMAIL_BACKEND`,
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`

**Optional:** `DPO_EMAIL`, `SLACK_WEBHOOK_URL`, `ANTHROPIC_API_KEY`,
`NIRA_PROVIDER`

### GitHub secrets and variables

| Name | Used by |
|---|---|
| `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER` | training deploy |
| `PROD_SSH_KEY`, `PROD_HOST`, `PROD_USER` | production deploy job — **now unused**, see §10 |
| `PROD_DEPLOY_ENABLED` (variable) | **should be deleted** — see §10 |

### SSH keys

Three, with distinct jobs:

| Key | Direction | Location |
|---|---|---|
| `id_ed25519_nsr_prod` | dev box → prod | dev box, admin access |
| `id_ed25519_github_deploy` | prod → GitHub | prod; public half is a repo **Deploy key** (read-only) |
| `id_ed25519_actions` | GitHub → prod | private half is the `PROD_SSH_KEY` **secret** |

---

## 9. Server hardening

- **ufw**: default deny incoming; only 22, 80, 443 allowed.
- **fail2ban**: `sshd` jail with `backend = systemd` (Ubuntu 26.04 is
  journald-only; the default backend would watch a non-existent
  `/var/log/auth.log` and ban nobody). It banned 7 addresses within
  minutes of starting — the box is actively scanned.
- **unattended-upgrades**: enabled.
- **Apache**: stopped and disabled (it owned port 80). Package retained,
  so `systemctl enable --now apache2` reverses it.
- **IPv6**: disabled in `/etc/sysctl.d/99-nsr-disable-ipv6.conf`. The
  host has no IPv6 address or route, but Docker resolved AAAA records and
  dialled them, which broke image pulls. The nginx `listen [::]`
  directives were removed **first** — with IPv6 off, nginx would
  otherwise fail to start and take the site down.
- **SSH password and root login are unchanged.** Hardening them is a
  backlog item; key login is confirmed working.

### Security headers

Set at the edge and by Django. `Referrer-Policy` is Django's stricter
`same-origin`; HSTS is deliberately sent by both, so it also covers
responses the app never generates (502s, the 444 default server).

```
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

---

## 10. Why there is no registry in the deploy path

Production originally deployed via GitHub Actions building an image,
pushing it to GHCR, and the server pulling it. **Three deploys
half-succeeded**, each in the registry round-trip, never in the
application:

1. A **queued run from an older commit** landed after a manual fix and
   rolled the checkout backwards.
2. A `docker compose pull` **raced its own push** — the image existed
   minutes later.
3. One died dialling **Docker Hub over IPv6** on a host with no IPv6
   route. `docker compose pull` fetches *every* image in the file, so an
   unreachable `nginx:1.27-alpine` aborted a deploy that only needed the
   GHCR image.

Each had already moved the checkout and rewritten `NSR_IMAGE` before the
failing step, leaving `.env` naming an image the box did not have — the
site kept serving, but config and reality disagreed.

Building on the server removes all of it. The trade-off accepted: the
build consumes production CPU for a few minutes, and rollback rebuilds if
the image has been pruned. On a 4-vCPU box with warm layers a deploy is
~35 seconds.

**Action outstanding:** delete the `PROD_DEPLOY_ENABLED` repository
variable so the Actions production job cannot run. Two mechanisms racing
is what caused failure (1). Training continues to deploy automatically
and remains the canary.

---

## 11. Known gaps

| Gap | Impact |
|---|---|
| **No automated backups** (§6) | Largest operational risk. Backlog. |
| `PROD_DEPLOY_ENABLED` still set | A CI deploy could race a manual one. Delete it. |
| `/manual/` returns 404 | MkDocs output is not built or shipped. |
| Duplicate top-level `const` in console sources | Some screens silently lose components — see `docs/console_production_build.md`. Pre-existing. |
| Dev-only emails in the data (§7) | Notification mail would reach `@quasar.ug` / `@example.com`. |
| Certbot registered to a personal Gmail | Expiry notices depend on one individual. |
| SSH password/root login enabled | Hardening deferred. |
| Keycloak not deployed | OIDC is designed (ADR-0006) but unimplemented; Django session auth is in use. Deploying an IdP nothing authenticates against would be pure attack surface. |
