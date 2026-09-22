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

**2026-09-17.** Approved by the project owner, who had already disabled
Apache and granted `jmwebaze` passwordless sudo before the run.

### External reconnaissance (from dev, before any login)

```
dig +short nsr-sris.mglsd.go.ug          -> 154.72.204.74   (correct)
dig +short mglsd.go.ug                   -> Cloudflare (parent only; our record is direct)
tcp connect 154.72.204.74:22             -> open
tcp connect 154.72.204.74:80             -> open  (Apache 2.4.66, default page)
tcp connect 154.72.204.74:443            -> refused
curl -I http://154.72.204.74/            -> Apache/2.4.66 (Ubuntu), stock index.html
```

### Access

```
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_nsr_prod      # on dev; admin key
# public half installed by the project owner with ssh-copy-id
ssh nsr-prod 'whoami; hostname'                          # -> jmwebaze, nsr-sris
```

### Read-only audit (no changes)

```
lsb_release -ds; uname -r; dpkg --print-architecture
nproc; lscpu; free -h; df -hT /; lsblk
ss -tlnp
systemctl list-unit-files --state=enabled --type=service
dpkg -l | grep -E 'apache2|nginx|postgresql|docker|fail2ban|ufw|certbot'
ls -l /etc/apache2/sites-enabled/ ; ls -la /var/www/html/
grep -vE '^\s*#|^\s*$' /etc/ssh/sshd_config
systemctl is-enabled unattended-upgrades; timedatectl; ls -la /opt/
```

Findings: Ubuntu 26.04 LTS, amd64, 4 vCPU, 15 GiB RAM, 86 GB free of
98 GB, UTC. Only Apache's default vhost was enabled and `/var/www/html`
held only the stock page, so nothing depended on Apache. Docker, nginx
and all database engines absent. `unattended-upgrades` already enabled.
66 packages pending upgrade. `/opt` empty.

Disk check: dev data is ~100 MB; 3x = ~300 MB; 86 GB available. Passes.

### Preparation script

Written on dev, copied to the server, reviewed by the project owner,
then run once. Idempotent.

```
scp phase3_setup.sh nsr-prod:/tmp/phase3_setup.sh
# sha256 c1e2ea4151e3c14e12141cff278e7095d3c66908ac03c400128879513cdcfa9e
ssh nsr-prod 'sudo bash /tmp/phase3_setup.sh'
```

What it did:

| Step | Result |
|---|---|
| 1. Apache | stopped + disabled (package kept — reversible) |
| 2. Packages | 66 pending upgrades applied |
| 3. Docker | Engine 29.8.1 + Compose 5.5.1 from Docker's official repo |
| 3b. daemon.json | json-file log rotation 10m x 5, `live-restore: true` |
| 3c. docker.service | **enabled at boot** — required for persistence across reboot |
| 4. docker group | `jmwebaze` added |
| 5. ufw | 22, 80, 443 allowed; default deny incoming; enabled |
| 6. fail2ban | installed, `jail.local` with `backend = systemd`, sshd jail on |
| 7. unattended-upgrades | confirmed enabled |
| 8. Directories | `/opt/nsrmis` (jmwebaze, 755), `/opt/nsrmis/migration` (700) |

The `backend = systemd` setting is load-bearing: Ubuntu 26.04 is
journald-only, so fail2ban's default backend would have watched a
non-existent `/var/log/auth.log` and banned nobody. Within minutes of
starting it had banned 7 addresses, so the box is actively scanned.

### Verification

```
sudo ufw status verbose
sudo fail2ban-client status sshd
docker ps                       # as jmwebaze, no sudo -> works
systemctl is-enabled docker containerd
```

SSH password login and root login were NOT changed — deferred until the
project owner confirms key login from an independent session.

---

## Phase 4 — GitHub → production

**2026-09-17.** In progress; blocked awaiting the project owner.

```
ssh nsr-prod 'ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_github_deploy'   # Key A
ssh nsr-prod 'cat ~/.ssh/config'                                          # Host github-nsr
```

Key A (prod -> GitHub, read-only) generated. Its public half must be
registered as a repository Deploy Key before the clone can proceed.

Key B (GitHub Actions -> prod) was NOT generated by the assistant: adding
an entry to `authorized_keys` is an SSH persistence change, and the
tooling correctly refused it. The project owner runs that step.

Deploy key A was registered by the project owner, after which:

```
ssh nsr-prod 'cd /opt/nsrmis && git init && git remote add origin ... && git fetch && git checkout main'
ssh nsr-prod 'cd /opt/nsrmis && git checkout -b prod-setup origin/prod-setup'
ssh nsr-prod 'cd /opt/nsrmis && cp .env.production.example .env && chmod 600 .env'
```

`.env` was then completed on the server. `DJANGO_SECRET_KEY` and
`POSTGRES_PASSWORD` were generated in place and never displayed;
`POSTGRES_USER`/`POSTGRES_DB` were set to `nsr`/`nsr` to match dev, with
both `DATABASE_URL`s derived from them so they cannot disagree. The
`EMAIL_*` block was commented out — the template forced the SMTP backend
while `EMAIL_HOST` was still a placeholder, which would raise on every
send; it now falls back to the console backend.

Prod remains on `prod-setup` at the project owner's instruction; only
`main` will deploy to production once the branch is merged.

---

## Phase 5 — first deploy (HTTP, empty database)

**2026-09-17. Complete.**

### DNS and proxy name

```
dig +short nsr-sris.mglsd.go.ug     -> 154.72.204.74   (correct)
grep server_name infrastructure/nginx/nsr-sris.http.conf  -> nsr-sris.mglsd.go.ug
```

### Image

Built on the server, because prod tracks `prod-setup` and CI only
publishes images from `main`:

```
ssh nsr-prod 'cd /opt/nsrmis && docker build -t nsr-mis:c4fdefe -t nsr-mis:prod-current .'
```

`NSR_IMAGE=nsr-mis:c4fdefe` — pinned to the commit, never `:latest`.
The postgis, redis, nginx and certbot images were pre-pulled.

### The security gate, and what it cost

The first `up -d` failed. `web` crash-looped on:

```
SystemCheckError: (security.E001) NSR_NIN_PEPPER is still the dev default
                  (security.E002) NSR_DATA_KEY is still the dev default
```

`apps/security/checks.py` fails closed against the dev defaults when
`DEBUG=False`, exactly as designed — those values are published in
`.env.example` and so in git history. Copying the dev keys, which had
been the plan, is something the application deliberately prevents. The
gate was **not** softened (CLAUDE.md anti-pattern).

Resolution: fresh production keys, plus a new
`manage.py rotate_encryption_keys` command (commit `1ff7659`) so the
Phase 6 restore can re-encrypt dev ciphertext under them rather than
losing it. The project owner generated the keys on the server; they were
never displayed.

`web` was stopped between attempts to halt the crash loop. No volume was
ever touched.

### Bring-up

```
ssh nsr-prod 'cd /opt/nsrmis && docker compose -f compose.production.yml --env-file .env up -d'
```

All 8 services up; 114 migrations applied, 0 unapplied.

### Verification (from outside the server)

| Path | Result | Served by |
|---|---|---|
| `/` | 200 | public container |
| `/healthz` | 200 | registry |
| `/login/` | 200 | registry |
| `/console/` | 302 -> login | registry |
| `/admin/` | 302 -> login | registry |
| `/api/schema/` | 403 (`NSR_PUBLIC_API_DOCS=False`) | registry |
| `/static/...coat-of-arms.svg` | 200, 149,500 bytes | WhiteNoise |
| unknown `Host:` header | connection closed (444) | nginx default server |

Host ports listening: **80 and 443 only**. Postgres (5432) and Redis
(6379) are visible only inside the `backend` compose network.

### Persistence test

Requirement: data must survive a restart. Verified with a full teardown,
not just a restart:

```
psql -c "create table _persistence_probe(...); insert ..."   # 114 migrations, 1 probe row
docker compose ... down          # containers AND networks removed (no -v)
docker compose ... up -d
                                  # 114 migrations, 1 probe row, note intact
```

The probe table was dropped afterwards. All nine named volumes survive
`down`/`up`; only `down -v` would destroy them, which is why no
procedure in this repository uses it.

---

## Phase 6 — data migration

**2026-09-17. Complete.** Cut-off `20260917T020653Z` (UTC), confirmed by
the project owner as "now". Dev was never stopped, locked or modified.

### On dev (read-only)

```
mkdir -p migration
docker exec nsr_dev_db pg_dump -U nsr -d nsr -Fc --no-owner --no-acl > migration/nsr_dev_<cutoff>.dump
cp nsr_dev_<cutoff>.dump work_nsr_<cutoff>.dump        # work from the copy
tar czf migration/drs_bundles_<cutoff>.tar.gz -C . .drs-bundles
sha256sum ... > migration/SHA256SUMS.txt
```

Dump 8.7 MB (custom format, from a 96 MB database), pg_dump stderr empty.
`media/`, `.upd-evidence/` and `.consent-evidence/` were empty or absent
on dev, so only the DRS bundles needed archiving. The original dump stays
on dev as the fallback.

`migration/dev_counts.txt` holds exact `COUNT(*)` per table — 125 tables,
113,990 rows — plus file counts. Not `pg_stat` estimates: those were
stale by a factor of 50 and produced a badly wrong figure earlier in
this work.

### Transfer

```
rsync -av work_nsr_<cutoff>.dump drs_bundles_<cutoff>.tar.gz dev_counts.txt \
      CUTOFF.txt SHA256SUMS.txt nsr-prod:/opt/nsrmis/migration/
ssh nsr-prod 'cd /opt/nsrmis/migration && sha256sum -c SHA256SUMS.txt'
```

All four transferred artefacts verified OK on prod.

### On prod

Version gate (step 9) confirmed before restoring: PostgreSQL 16.4 /
PostGIS 3.4.3 on both sides.

```
docker compose ... stop nginx public worker beat web     # db + redis stay up
psql -c "DROP DATABASE nsr;" ; psql -c "CREATE DATABASE nsr OWNER nsr;"
pg_restore -h db -U nsr -d nsr --no-owner --no-acl -j 2 work_nsr_<cutoff>.dump
```

The dropped database was the empty Phase 5 one — verified 0 households,
0 members, 0 users, 0 audit events immediately beforehand. pg_restore
exited 0 with no warnings; all 6 extensions and 131 table-data entries
restored.

### Key rotation

The restored ciphertext was written under the dev key, which production
does not have. `manage.py rotate_encryption_keys` re-encrypted it under
the production key:

```
# old dev secrets piped to /opt/nsrmis/migration/.oldkeys (mode 600),
# forwarded with `docker compose run -e NAME` (pass-through form, so the
# values never appear in `ps`), then shredded.
/opt/nsrmis/migration/run_rotation.sh --dry-run        # 993, 0 unreadable
/opt/nsrmis/migration/run_rotation.sh --batch-size=500 # 993, 0 unreadable
```

Result: 992 Member NINs + 1 Kobo token re-encrypted, 0 unreadable.
Verified afterwards through the ORM under the production key:

```
members with NIN      : 992
decrypt under PROD key: 992
failed to decrypt     : 0
nin_hash matches      : 992
```

`.oldkeys` was shredded from prod immediately after.

### File volumes (step 12)

`.drs-bundles` restored into the `drs_bundles` named volume, 4 files,
`chown 999:999` to match the image's `app` user — a fresh volume would
otherwise be root-owned and every write would fail with EACCES.

### Count comparison (step 13)

| | dev | prod |
|---|---|---|
| Tables | 125 | 125 |
| Total rows | 113,990 | 113,990 |
| Row-count differences | **none — identical on every table** | |
| `.drs-bundles` files | 4 | 4 |
| `media` files | 0 | 0 |

### Clean-up list (step 15) — listed, NOT changed

Project owner instruction: **keep all accounts.** All 11 restored and
left active, including the 8 superusers.

Dev-only values still present in the data, for a later decision:

| Location | Rows | Example |
|---|---|---|
| `auth_user.email` | 2 | `admin@example.com`, `dev@example.com` |
| `partners_dsasignature.signer_email` | 1 | `@quasar.ug` |
| `partners_programmesignoff.expected/actual_email` | 2+2 | `@quasar.ug` |
| `chatbot_manualchunk.content` | 7 | doc text mentioning localhost |
| `ddup_mergedecision.reason`, `pmt_pmtmodelsignoff.decision_note` | 1+2 | free text |
| `security_auditevent.actor_id` / `.reason` | 5+4 | historical audit rows — **must not be edited**, the chain is hash-linked |

`ingestion_hub_kobocredential` holds one row pointing at the real
`https://kf.kobotoolbox.org`, marked `(pre-minted)` and never tested.
The six DIH source systems are all seeded and active.

### Clean-up of the migration staging area (step 16)

The project owner confirmed the migration was good, so the transferred
artefacts were destroyed on production.

```
ssh nsr-prod 'cd /opt/nsrmis/migration
  shred -u -z work_nsr_<cutoff>.dump drs_bundles_<cutoff>.tar.gz
  rm -f CUTOFF.txt SHA256SUMS.txt dev_counts.txt prod_counts.txt run_rotation.sh'
```

`shred` rather than `rm` for the dump and archive: both carry live
personal data under the DPPA 2019, and the directory sits on an
ordinary ext4 filesystem where `rm` only unlinks.

Verified afterwards: `/opt/nsrmis/migration` is empty, still `700`
`jmwebaze:jmwebaze`, and a sweep of `/opt`, `/home/jmwebaze` and `/tmp`
found no stray dump, archive or key file.

`prod_counts.txt` was copied back to dev first, so the count evidence
survives off-production; it holds table names and integers only, no
personal data. The dev-side dumps are retained until the project owner
says otherwise.

Post-deletion check: all 8 containers healthy, 1,283 members / 992 NINs
/ 80,430 audit events still present, 4 DRS bundle files still in the
volume.

---

## Phase 7 — SSL and go-live

**2026-09-17. SSL complete.** The GitHub Actions trigger (step 4) is
still pending — see below.

### Pre-flight (steps 1-2)

```
dig +short nsr-sris.mglsd.go.ug          -> 154.72.204.74
tcp connect 154.72.204.74:80             -> open from outside
```

The ACME path was proved end-to-end BEFORE any certificate was
requested, so a misconfigured webroot could not burn Let's Encrypt rate
limit:

```
docker run --rm -v nsr-sris-prod_certbot_www:/w alpine \
  sh -c 'echo probe > /w/.well-known/acme-challenge/probe'
curl http://nsr-sris.mglsd.go.ug/.well-known/acme-challenge/probe   -> 200
```

### Certificate (step 3)

Staging first, exactly as the plan required:

```
docker compose ... run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot -d nsr-sris.mglsd.go.ug --staging ...
# success -> delete the staging cert (browsers do not trust it)
docker compose ... run --rm --entrypoint certbot certbot delete --cert-name nsr-sris.mglsd.go.ug
docker compose ... run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot -d nsr-sris.mglsd.go.ug ...
```

Issued: `issuer=C=US, O=Let's Encrypt, CN=YE1`,
`subject=CN=nsr-sris.mglsd.go.ug`, valid 2026-09-17 to **2026-12-16**.

Registration e-mail: `jmwebaze@gmail.com` (expiry notices). Worth moving
to a ministry address before handover — `certbot update_account`.

Auto-renew is the long-running `certbot` container, which loops
`certbot renew` every 12h; nginx reloads every 6h to pick up a new cert.
Renewal verified: `--dry-run` reported *"all simulated renewals
succeeded"*.

Then `NGINX_CONF=nsr-sris.ssl.conf` and `NSR_SECURE_SSL=True` in `.env`,
and the stack was recreated.

### Two defects found by going live

**Conflicting `Referrer-Policy`.** nginx sent
`strict-origin-when-cross-origin` while Django's SecurityMiddleware sent
`same-origin`, so every response carried both.
`X-Content-Type-Options` and `X-Frame-Options` were duplicated too. The
edge now sets only what Django does not; Django's stricter value wins.
HSTS stays deliberately duplicated — it must appear on responses the app
never generates (502, the 444 default server), and both values are
identical. Commit `773e897`.

**Stale nginx config surviving a deploy.** A single-file bind mount pins
that file's inode, and `git reset --hard` replaces files rather than
editing them. After a pull the container kept serving the OLD config,
and `nginx -t` passed because the test read the same stale file — so it
failed silently in both directions. Found when a removed `ssl_stapling`
directive kept warning after a pull and reload.

Fixed by mounting the whole directory (inode-stable) and copying the
`NGINX_CONF`-selected file into `conf.d` at container start, with
`nginx -t` run on the copy before the server starts. Commit `bbaa930`.

**Operator note: an nginx config change needs `up -d`, not just
`nginx -s reload`.**

`ssl_stapling` was also dropped — Let's Encrypt no longer publishes an
OCSP responder URL, so it only produced a warning on every config test.
Commit `9552dad`.

### Verification

| Check | Result |
|---|---|
| `https://nsr-sris.mglsd.go.ug/` | **200, HTTP/2, cert valid (`ssl_verify_result=0`)** |
| `http://...` -> HTTPS | **301** to the https URL |
| `/`, `/healthz`, `/login/` | 200 |
| `/console/`, `/admin/` | 302 -> login |
| `/api/schema/` | 403 (`NSR_PUBLIC_API_DOCS=False`) |
| Security headers | one each; HSTS twice by design |
| Migrated data | 1,283 members / 992 NINs still served |

### Outstanding (step 4)

Automatic production deploys are NOT yet enabled. Three things remain,
all needing repository access the deploy key does not have:

1. `.github/workflows/deploy.yml` — the `deploy-production` job has never
   been pushed; the repo's SSH credential is a repo-scoped deploy key and
   GitHub refuses workflow-file pushes from one.
2. `prod-setup` -> `main` merge, since only `main` should deploy to prod.
3. The `PROD_DEPLOY_ENABLED` repository variable set to `true`.

`PROD_SSH_KEY`, `PROD_HOST` and `PROD_USER` were created by the project
owner. The Actions key was verified to authenticate by loopback SSH on
the server before use.

### Step 4 — automatic deploys armed

The workflow reached `main` the long way round. A repo-scoped deploy key
may not push workflow files, so the job was added through the GitHub web
editor, which auto-indents pasted text: the first attempt silently nested
`deploy-production` inside the preceding job (valid YAML, but only one
job registered), and the second shifted the entire file two spaces right
(invalid YAML). `Ctrl+A`, `Shift+Tab` fixed it — the displacement was
uniform, so un-shifting was too.

**If workflow files need editing again, use a Personal Access Token with
`workflow` scope and push normally. The web editor is not worth it.**

Merged in order, which matters: `prod-setup` first, so `main` carried
`compose.production.yml` before anything tried to deploy from it, then
the workflow PR, then the `PROD_DEPLOY_ENABLED` repository variable.

`PROD_DEPLOY_ENABLED` is a **variable, not a secret** — the `secrets`
context is unavailable in a job-level `if:`, so storing it as a secret
leaves the job permanently skipped with no error to explain why.

---

## Phase 8 — backups and rollback

**Rollback: done.** `scripts/deploy_prod.sh` keeps the last three built
images and supports `deploy.sh <sha> --rollback`, guarded by the same
health check; a failed deploy restores the previous image automatically.
Documented in `docs/PRODUCTION.md` §4.

**Backups: DEFERRED TO THE BACKLOG** at the project owner's instruction,
2026-09-17. Not started, and production therefore has no automated
backup and no tested restore.

This is a known and accepted gap, recorded here so it is not mistaken for
an oversight. It is the largest outstanding operational risk on the
system: 113,990 rows including 992 encrypted NINs, recoverable only from
a fresh dev dump — which would lose anything entered on production.

What the backlog item needs:

- nightly database dump + file-volume archive;
- 14-day retention;
- copies stored off the server — **pull-based** preferred (an external
  host fetching), so that compromise of production cannot reach the
  archive;
- a restore tested into a throwaway container, not just written down;
- a stated RPO/RTO agreed with the NSR Unit;
- DPPA 2019 handling for the archives: dumps carry live personal data,
  so they need encryption at rest, access limited to named custodians,
  and `shred` rather than `rm` on disposal.

The manual dump and restore commands are in `docs/PRODUCTION.md` §6 as
the interim procedure — run one before anything risky.

---

## Post-go-live — IPv6 disabled on production

**2026-09-17.** Approved by the project owner.

### Why

A production deploy failed with:

```
Image nginx:1.27-alpine  Error failed to resolve reference
  "docker.io/library/nginx:1.27-alpine": dial tcp
  [2600:1f18:2148:bc00:...]:443: connect: network is unreachable
```

The host has **no IPv6 address and no IPv6 default route**, but Docker
resolves AAAA records and dials them anyway. `docker compose pull`
fetches *every* image in the compose file, so one unreachable Docker Hub
image aborted the whole step under `set -e` — after the job had already
moved the checkout and rewritten `NSR_IMAGE`, leaving `.env` naming an
image the box did not have.

The GHCR application image was never the problem; it pulled fine.

### Prerequisite: nginx had to stop listening on IPv6 first

`infrastructure/nginx/*.conf` carried three `listen [::]` directives.
With IPv6 disabled at the kernel, nginx refuses to start —
`Address family not supported by protocol` — and would have taken the
site down on its next restart. **The listeners were removed and deployed
first** (commit `0c750a7`), nginx restarted and verified serving, and
only then was IPv6 disabled.

Checked inside the container rather than on the host: `ss` on the host
shows docker-proxy's `[::]` sockets regardless of nginx's configuration,
so it cannot answer this question.

### The change

```
sudo tee /etc/sysctl.d/99-nsr-disable-ipv6.conf   # all/default/lo disable_ipv6 = 1
sudo sysctl --system
```

Reverse by deleting that file and rebooting — and restore the nginx IPv6
listeners at the same time.

### Verification

| Check | Result |
|---|---|
| `disable_ipv6` | 1, no global IPv6 addresses |
| nginx restart with IPv6 off | starts clean, healthy, no address-family error |
| Site | `/` `/healthz` `/login/` 200, `/console/` 302, `/admin-console/` 403 (permission gate), cert valid, HTTP/2 |
| `docker pull nginx:1.27-alpine` | **succeeds** — the exact failure that killed the deploy |
| `docker compose pull` | Docker Hub images pull; only the local-only `nsr-mis:` tag fails, as expected |

### Still to do

The deploy job should pull **only** the application image rather than
`docker compose pull`. The other images are pinned and already present,
and pulling them puts Docker Hub in the deploy path for no reason. The
corrected job also verifies before mutating server state, and refuses a
commit that is not an ancestor of `origin/main`. It needs a credential
with `workflow` scope to land.

## 2026-09-18 20:30Z — production unreachable (open incident)

Reported: https://nsr-sris.mglsd.go.ug/ returns nothing.

Probed from the dev VM (no commands could be run on prod — it does not
answer):

| Probe | Result |
|---|---|
| DNS `nsr-sris.mglsd.go.ug` | resolves to 154.72.204.74, correct |
| ICMP to 154.72.204.74 | 4/4 lost, 100% |
| TCP 22 / 80 / 443 | no connection, 3 attempts each |
| HTTPS `/` and `/healthz` | timeout at 30s, no TCP handshake |
| Path to the host | reaches provider edge 41.173.8.5 (hop 16), dies after |
| 41.173.8.5 itself | answers, 0% loss, 230ms |
| Dev VM outbound | fine — github.com 200, nsr-sris-dev.quasar.ug 200 |

The route into the hosting provider is healthy and its edge router
answers; the server behind it answers nothing on any port, including
ICMP. That is a host that is down, disconnected, or dropping everything
at the network layer — not a web-tier fault, which would still complete
a TCP handshake.

Last confirmed healthy: 2026-09-18T02:09Z, deploy cc0177c -> 8a160b7.
Health check passed on the first attempt, all eight containers up, 38G
free. The bundles were then fetched successfully over HTTPS from
outside at ~02:15Z. So the box was serving after the deploy, and went
away some time in the ~18 hours since.

The deploy is not implicated: it changes containers only — checkout,
build, `up -d`, migrate — and never touches host networking, firewall
rules or power state.

Needs out-of-band access (provider console / IPMI) to diagnose further.
Nothing further can be established from here.

## 2026-09-19 17:50Z — production restored (incident closed)

The box is back. Verified from the dev VM, then on the host itself.
All read-only checks; nothing on prod was changed.

Remote probes:

| Probe | Result |
|---|---|
| DNS `nsr-sris.mglsd.go.ug` | 154.72.204.74, unchanged |
| TCP 22 / 80 / 443 | all open (all three refused on 18 Sep) |
| `https://.../healthz` | 200, body `ok`, 0.77s |
| `https://.../` | 200, 1.24s |
| `http://` -> `https://` | 301, correct |
| TLS certificate | `CN=nsr-sris.mglsd.go.ug`, valid to 16 Dec 2026 |
| ICMP | still 0/4 — this host does not answer ping at all, so ping is not a liveness signal for it and its use as evidence on 18 Sep was weak |

On the host:

```
ssh nsr-prod 'hostname; uptime; cd /opt/nsrmis && git log -1; docker compose ... ps; df -h /'
ssh nsr-prod 'date -u; uptime -s; sudo journalctl --list-boots'
ssh nsr-prod 'docker compose ... exec -T db psql -tAc "select counts"'
ssh nsr-prod 'sudo journalctl -b -1 --since "2026-09-18 17:00"'
```

| Check | Result |
|---|---|
| `git log -1` | `8a160b7` — unchanged, as expected |
| Containers | all eight up 8 hours, seven healthy, `beat` running (no healthcheck) |
| Disk | 38G free, unchanged |
| Rows | 284 households, 1,283 members, 87,941 audit events |

**What actually happened.** The host rebooted cleanly at 09:45:04Z on 19 Sep.
The journal from the *previous* boot runs continuously through the whole
outage window and ends with an orderly `systemd-reboot` at 09:44:50Z — so the
machine was powered on and logging the entire time it was unreachable. This
was not a dead box: it was alive and isolated at the network layer. The 18 Sep
entry's conclusion ("down, disconnected, or dropping everything at the network
layer") was right on the third option and wrong to imply power state.

Containers came back by themselves on boot, so the restart policy did its job
and no manual intervention was needed.

Root cause of the isolation is provider-side and not established from here.
Both open backlog items are untouched: no automated backup (deferred), and
`web` still runs 3 gunicorn workers (question never answered).

## 2026-09-21/22 — deploy 8a160b7 → 98f45ed (US-S23/S24)

Console defects, home charts, CSPro review, household detailed review.

**Pre-deploy backup.** `pg_dump -Fc` → `/opt/nsrmis/backups/pre-us-s24-20260921-233403Z.dump`
(9.5M, exit 0). Verified with `pg_restore -l`: 131 tables with data, including every
table the four new migrations touch. Prod still has no automated backup (Phase 8
deferred by the user), so this manual dump is the only rollback point for the data.

**Blocker hit, then cleared.** The first two `deploy.sh` runs failed at `docker build`
with an i/o timeout pulling base images. Diagnosis: `auth.docker.io` 200 in 0.79s,
`github.com` 200, `pypi.org` 200, but `production.cloudfront.docker.com` (Docker Hub's
blob CDN) timed out. Six pre-pull attempts failed; neither `python:3.12-slim` nor
`node:22-slim` was cached locally. Roughly 20 minutes later the same CDN completed a
TLS handshake in 2.2s and both pulls succeeded first try. Transient CDN reachability,
not a code or config fault — the box has prior form for this (a similar build failure
on 2026-09-17). **No network or Docker config was changed.** If it recurs, retry before
investigating; a registry mirror would fix it permanently but the container-registry
pipeline was deliberately rejected, so that is the user's call.

Failed builds never stopped the running containers, so the site served `8a160b7`
throughout both failures.

**Commands run on prod**

```
ssh nsr-prod 'cd /opt/nsrmis && ./deploy.sh'     # as jmwebaze, NOT root —
                                                 # github-nsr is an SSH alias in
                                                 # jmwebaze's ~/.ssh/config, and
                                                 # jmwebaze is in the docker group.
                                                 # sudo ./deploy.sh fails on git fetch.
docker pull python:3.12-slim
docker pull node:22-slim
pg_dump -Fc  (see backup path above)
```

**Result.** `deploy complete: 8a160b7 -> 98f45ed`, build 4m38s, healthz ok on
attempt 1, all 8 services up, 35G free.

**Verification (post-deploy, on the box)**

- Migrations applied: `reference_data` 0018, 0019, 0020 and `ingestion_hub` 0007 all `[X]`.
- `https://nsr-sris.mglsd.go.ug/` `/home/` `/console/` `/healthz` → 200.
- The React #185 crash fix is in the shipped bundle:
  `/app/static/console/js/v0.1-components-household-review.js` contains
  `HhReviewSection`, `HhReviewRow`, `HhCodedCell`, `HhRepeatTable` and declares no
  bare `ReviewSection` — so it can no longer collide with the one
  `app-change-request.jsx` owns.

**Two verification traps worth remembering.**

1. `docker compose exec` from `/opt/nsrmis` without `-f compose.production.yml`
   picks up the unrelated `docker-compose.yml` and reports *"service web is not
   running"* while the site is perfectly healthy. Always use the `dc()` wrapper
   deploy.sh defines: `docker compose -f compose.production.yml --env-file .env`.
2. Fetching a console asset unauthenticated returns the **sign-in page** with
   HTTP 200, not the asset. A grep for component names against that response finds
   nothing and looks exactly like a failed deploy. Verify console assets inside the
   image, not over HTTP — and note the build flattens paths, so
   `design/v0.1/components/household-review.jsx` ships as
   `/app/static/console/js/v0.1-components-household-review.js`. `find -name
   '*.jsx'` will not find it.

## 2026-09-22 — deploy 98f45ed → 0a69762 (US-S24 registry field dictionary)

Household review reads its field vocabulary from the active FormVersion
instead of hardcoded maps. Five new `intake` migrations, two of which
mutate data.

**Pre-deploy backup.** `pg_dump -Fc` →
`/opt/nsrmis/backups/pre-us-s24-fielddict-20260922-012653Z.dump` (9.5M,
exit 0). Verified: 131 tables with data, including `intake_formquestion`,
`intake_formversion`, `ingestion_hub_stagerecord`,
`reference_data_choiceoption` and `data_management_household`.

**Verification trap (new).** `pg_restore -l` is **not installed on the
host**, and piping a dump into `docker compose exec -T db pg_restore -l
/dev/stdin` fails with *"did not find magic string in file header"* — the
dump is fine, the pipe is not. That looks exactly like a corrupt backup.
Verify by mounting the directory into a throwaway container instead:

```bash
docker run --rm -v /opt/nsrmis/backups:/b:ro postgis/postgis:16-3.4 \
  pg_restore -l /b/<dumpfile>
```

**Deploy.** `ssh nsr-prod 'cd /opt/nsrmis && ./deploy.sh'` (as jmwebaze,
not root). Build 4m18s, healthz ok on attempt 1, all 8 services up,
33G free. No retries needed; the Docker Hub CDN behaved this time.

**Migrations applied:** intake 0007, 0008, 0009, 0010, 0011 — all `[X]`.

**Post-deploy verification**

- 156 questions carry `payload_aliases`; dictionary serves 221 entries,
  0 conflicts.
- Both producers' names resolve to one question: `rooms_sleeping` (Kobo)
  and `sleeping_rooms` (wizard) both → "How many rooms are used for
  sleeping?".
- All 18 coping questions resolve; `L01.i` and `L02.i` keep their codes
  because both strip to "Begging".
- Repeat columns name the column: `shock_type` → "Shock type",
  `strategy_type` → "Coping strategy".
- `/healthz` `/` `/home/` `/console/` → 200. The field-dictionary
  endpoint returns **403 unauthenticated** and serves no content — it
  describes the questionnaire, not personal data, but it is not public.

**Two prod-only findings — NOT changed, they need a decision.**

1. **Two age-boundary DQA rules are not approved on prod.**
   `AC-HOH-AGE` is active, but `AC-HOH-AGE-CHILD-LED` is **draft** and
   `AC-ORPHAN-FLAG` is **pending_approval** (both are active on dev).
   The composition panel reads thresholds only from ACTIVE rules, by
   design, so on prod it now shows "not configured" for Child-headed,
   Members-under-N and Dependency ratio where it previously drew them
   from hardcoded 12/18/60. The panel is telling the truth: no approved
   rule defines those boundaries on prod. Fixing it is an **approval
   action through the dual-approval workflow** and is the Ministry's to
   make — nothing here activates a rule on production. See CLAUDE.md,
   "do not soften approval gates".

2. **29 active questions carry no payload alias**, including
   `a8_enumeration_area`, `a9_household_number`, `b5_observations`,
   `c21_id_documents` and `c22_id_number`. That is consistent — no
   payload carries them, which is why field coverage is still 0
   unresolved — but it means the questionnaire collects answers the
   canonical payload does not carry. Worth checking against the
   connector mapping; not touched here.
