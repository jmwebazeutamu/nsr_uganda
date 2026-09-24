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

## 2026-09-22 — deploy 0a69762 → 129ee46 (US-S24 section K/L detail)

Kobo connector carries section K shock detail and section L coping rows;
promotion resolves detail rows from either producer's location.

**Code-only deploy — no migrations.** Pre-deploy dump taken anyway
(prod has no automated backup):
`/opt/nsrmis/backups/pre-us-s24-detailrows-20260922-165324Z.dump`
(9.6M, exit 0, 131 tables verified via the mounted-container method).

Build 4m54s, healthz ok on attempt 1, all 8 services up, 31G free.

**Verified:** `/healthz` `/` `/home/` `/console/` → 200; `_kobo_shock_rows`,
`_kobo_coping_rows` and `_detail_rows` present in the image.

**Registry state at deploy:** 284 households, 0 Shock rows, 0
CopingStrategy rows. The fix applies to new pulls only; existing records
need the backfill.

**Backfill NOT run.** Dry run on prod for scope:

```
scanned 377 landing(s)
  shocks:            40 stage payloads,  32 promoted households
  coping_strategies: 377 stage payloads, 284 promoted households
```

`manage.py backfill_detail_rows --apply` is required to write. It updates
staged payloads and creates registry rows for already-promoted
households, so it needs an explicit decision — it is a data change to
promoted records, not a deploy step.

**Regression scope checked before/after (evidence in the session):**

- **PMT is insulated.** No PMTModelVersion — active v1, rejected v22001-3,
  or pending v22004 — carries a shock or coping variable. Backfilling
  cannot move a PMT score or a band under any current model.
- **No DQA rule** references shocks or coping.
- **data_management API** already serialises `shocks` and
  `coping_strategies` on household detail; they have been returning `[]`
  and will start returning rows. Schema unchanged, values change.
- **choice_field_map** already decodes `shock_type`,
  `coping_strategy_type` and `coping_frequency`, so labels work with no
  further change.
- **Data Explorer** declares a `household_shocks` dataset backed by
  `mv_explorer_household_shocks_subregion` — **that matview does not
  exist in the database** (only 2 matviews are present). Pre-existing
  gap, and it becomes visible once shock rows exist.
- No reporting view, search index or DRS export reads either entity.

**Latent issue, not triggered today:** `_create_shocks()` uses
`Shock.objects.create()` and `Shock` has no uniqueness constraint, so it
is not idempotent — unlike `_create_coping_strategies()`, which uses
`get_or_create` against a unique constraint. The backfill guards this by
skipping any household that already has shock rows, and promotion's
own idempotency check prevents a second fan-out, so nothing duplicates
today. It would matter to any future re-run path.

## 2026-09-22 — deploy ea6ef12 → ad64ba8, and DQA rule revisions authored

**Deploy.** Duplicate-discovery scheduling (US-S24). Migration `ddup.0004`
applied. Build ~50 min (slow pip mirror again — the image carries
transformers/scikit-learn/numpy). healthz ok on attempt 1. Dump first:
`/opt/nsrmis/backups/pre-us-s24-ddup-20260922-*.dump`, 131 tables verified.

### "Household head not found" — root cause

Reported as still broken on prod after being fixed on dev. It was never a
code defect: **the rule lives in the database and deploys do not carry
`DqaRule` rows.**

- dev `AC-HOH-EXISTS` **v2** (active): `is_head == true` OR
  `relationship_to_head == "01"`, approved 19 Sep.
- prod `AC-HOH-EXISTS` **v1** (active): `relationship_to_head == "01"` only,
  seeded 1 June, never revised.

Every connector normalises the head to `is_head: True` and blanks the
relationship code, so on prod the rule matched nothing. **All 82
quality_failed records were blocked on this single rule.**

Third instance of the same gap — configuration living only in a database
with nothing to carry it between environments, after the questionnaire
instrument and the DQA seeds. Each time it surfaces as "we fixed that,
why is it still broken". Worth a promotion step for rule versions.

### Rule revisions authored (NOT approved)

`revise()` from `scripts/seed_dqa_intra_household_rules.py`, run against
the prod container. Dry-run first, and it authored exactly what the dry
run predicted:

```
AC-HOH-EXISTS        v1 active -> v2 DRAFT + submitted
AC-HOH-AGE           v1 active -> v2 DRAFT + submitted
AC-HOH-AGE-CHILD-LED v1 draft  -> updated + submitted
(7 other rules: "matches — nothing to do")
```

**Nothing is live.** v1 remains active for all three; the queue is
unchanged (284 promoted / 11 rejected / 82 quality_failed, same blocking
failures). Approval is the Ministry's and must not be self-approved —
the seeder itself refuses the seed author as approver.

Clearing the 82 takes three steps: author (done), approve in
Admin > Workflow > DQA rules, then re-run the gates via
`POST /api/v1/dih/stage-records/{id}/process/`. Correcting a rule does
not re-evaluate records already in `quality_failed`.

### Mistake to avoid repeating

The intended dry run **wrote to production.** The script was piped to
`docker compose exec -T web python -`, which makes `__name__ ==
"__main__"`; with no `--revise` in `sys.argv` it fell through to `seed()`
and created `AC-MEMBER-DETAIL-REQUIRED` v1 as a draft at 19:29:58.

Impact: one draft row. Draft rules do not evaluate, no active rule was
touched, nothing else changed. Still an unintended write.

**Never pipe a script with an `if __name__ == "__main__"` block into
`python -`.** Strip the block and call the function explicitly, which is
how the real run was done.

### Two observations, not acted on

- `AC-ORPHAN-FLAG` and `AC-SPOUSE-PAIR` moved pending_approval → rejected
  at 19:25 on 22 Sep. The audit chain attributes both to
  `johnsonmwebaze` via the console — a human decision, not a side effect.
- **`AC-MEMBER-AGE-MAX` has two ACTIVE versions simultaneously** (v1 and
  v2). Pre-existing, unrelated to this work, but two active versions of
  one rule means which one evaluates depends on query order. Worth
  closing.

## 2026-09-22 — head-of-household rules approved, gates re-run

**Approved** on the explicit instruction of jmwebaze@gmail.com, applied
by the agent:

```
AC-HOH-EXISTS        v2 -> active   (v1 auto-retired)
AC-HOH-AGE           v2 -> active   (v1 auto-retired)
AC-HOH-AGE-CHILD-LED v1 -> active
```

`approve()` takes `approver` and `actor` separately, so the chain records
`approved_by=jmwebaze@gmail.com` (the deciding authority) with
`actor=claude-agent` (what executed it), and the approval note says so.
The audit trail should not imply a human clicked approve when an agent
applied it under instruction.

`AC-HOH-EXISTS` v2 is the `op=or` predicate — accepts the canonical
`is_head` flag or `relationship_to_head == "01"`.

**Gates re-run** with `process_stage_record(..., allow_fast_track=False)`.
Fast-track deliberately disabled: re-running gates should return records
to the review queue, not silently promote 82 households into the
registry on the back of a rule change.

92 records, not 82 — ten more had staged in the interval (the
`process-pending-kobo-landings` beat task runs every 5 minutes).

```
before:  quality_failed 92
after:   idv_pending 69 | ddup_review 8 | pending_promotion 5 | quality_failed 10
```

`AC-HOH-EXISTS` now blocks nothing.

**The 10 that remain are real.** All ten fail the same pair,
`AC-HOH-AGE + AC-MEMBER-AGE-MAX`, and every one has a head aged **10** —
below the 12-year minimum. The rule is doing its job: before v2 it
matched nobody and so never fired, and these records passed that gate
without ever being checked. Either genuine child-headed households below
the threshold or a capture error; either way it is a human judgement,
which is what `quality_failed` is for.

**Queue now:** 284 promoted, 11 rejected, 69 idv_pending, 8 ddup_review,
5 pending_promotion, 10 quality_failed. The 69 need NIRA verification and
the 8 need duplicate review — both were previously masked behind the
broken head rule, so this is work that was always there, not new work.

## 2026-09-23 — deploy e3f177f → 3841eeb, and disk reclaimed

User management in the console (US-S25) plus the parallel-session DIH
candidate detail. Code-only, no migrations. Dump first:
`pre-us-s25-usermgmt-*.dump` (10M, 132 tables verified).

**Verified on prod, read-only by choice**

```
GET user-accounts              -> 200, 11 accounts
scope levels served            -> 8 (national..partner, from ScopeLevel)
roles served                   -> 22
superusers marked unmanageable -> True
action on a superuser          -> 400, refused
non-admin (opm-analyst)        -> 403
```

No test account was created. Account creation writes into the immutable
audit chain and a test row cannot be removed afterwards; the refusals and
the read surface prove the gate without leaving one. Exercising the
create path against production is a decision for the Ministry to take
knowingly.

**Disk: 18G → 32G free**

The problem was build cache, not old images. `deploy.sh` already keeps
images to the last three (running + two rollback targets, zero dangling)
and prunes cache `until=168h` — but seven builds in one day are all
inside that window, so the filter never fired.

```
docker builder prune -f --filter "until=6h"    ->  9.5GB
docker builder prune -f --filter "until=90m"   ->  6.1GB
```

The current build's cache was kept. **37GB is still reclaimable** and was
left deliberately: a full prune trades space for every future build, and
that is the Ministry's call. Worth noting the cache earns little as it
stands — torch (196MB) is re-downloaded on every build regardless.

Backups untouched: 97M across 10 dumps, trivial next to the images.

**Finding, not acted on: 8 of 11 accounts are superusers.**

```
admin              joined 2026-05-14  last login 2026-06-23
dev                joined 2026-05-17  last login 2026-05-17
regression-smoke   joined 2026-05-19  last login 2026-09-17
regression-smoke2  joined 2026-05-19  never
seed-smoke         joined 2026-05-19  never
detail-smoke       joined 2026-05-19  never
johnsonmwebaze     joined 2026-05-20  last login 2026-09-23
nusaf-debug        joined 2026-05-22  never
```

Five are test or debug leftovers from May and four have never signed in.
All predate this session; none were created by this work.

Each holds full Django admin access and bypasses every guard in the
user-management feature — including the one that stops an admin editing
their own roles. Nothing was changed: removing accounts is destructive,
and by the design agreed for this feature an account should be
deactivated rather than deleted so the audit chain stays readable.
Deactivating the four that have never signed in is the low-risk start,
and has to be done in the Django admin, because superusers are precisely
what the console refuses to manage.

## 2026-09-23 — dormant superuser accounts removed

Five test accounts removed from production on the instruction of
jmwebaze@gmail.com. All five held **full superuser and Django admin
access**, which put them outside every guard in the user-management
feature shipped the same day — including the one that stops an
administrator editing their own roles.

```
accounts   11 -> 6
superusers  8 -> 3
is_staff    7 -> 3
```

| Removed | Created | last_login |
|---|---|---|
| `regression-smoke2` | 2026-05-19 | never |
| `seed-smoke` | 2026-05-19 | never |
| `detail-smoke` | 2026-05-19 | never |
| `nusaf-debug` | 2026-05-22 | never |
| `regression-smoke` | 2026-05-19 | 2026-09-17 (scripted — see below) |

### Procedure

Dump first, in two stages because the fifth account was decided
separately:

```
pre-dormant-superuser-removal-20260923-021032Z.dump   (132 tables verified)
pre-regression-smoke-removal-20260923-021607Z.dump    (132 tables verified)
```

For each account: **deactivate, audit, then delete.** `is_active`,
`is_superuser` and `is_staff` were cleared and saved before the row was
removed, so the account was already inert if the delete failed for a
reason nothing anticipated. The `delete` audit event was emitted **before**
the row went, so the record of the removal outlives the thing it
describes.

The first four ran under a guard that refused any account with a
non-null `last_login`, so a typo could not reach a live account. That
guard was deliberately lifted for `regression-smoke` and replaced with an
assertion pinning the exact account (superuser, `last_login` on
2026-09-17); the reason recorded in the chain says why the login did not
count.

### Why `regression-smoke`'s login did not count

Its only `last_login` was 2026-09-17 20:20:11Z. Two things ruled out a
person:

- **It happened on production, not on dev.** The accounts arrived by a
  dev→prod restore, so the timestamp could have ridden in with the copy —
  but the dev dump cut-off was `20260917T020653Z`, roughly eighteen hours
  earlier.
- **Three accounts authenticated within three seconds.** At 20:20:11–14,
  `johnsonmwebaze`, `regression-smoke` and `demo-chief` each performed an
  identical `list_read` + `read` on households, all from `127.0.0.1` with
  **no user agent**. A browser always sends one, and nobody signs into
  three accounts in three seconds. It was a scripted ABAC scope check run
  on the box itself.

For contrast, the same account's console traffic that evening came from
`173.79.164.106` with a real session. The script had borrowed that
identity too, as one of the ones it tested.

The script itself was not found — nothing in `scripts/` or the docs
authenticates as multiple users, so it was likely an ad-hoc shell session
during that day's migration work.

### What survived, deliberately

`AuditEvent.actor_id` is a plain string, not a foreign key, so the old
entries still name the removed accounts:

```
2026-05-19  regression-smoke2  read       household
2026-05-19  detail-smoke       read       partner
2026-05-19  detail-smoke       list_read  dsa
2026-05-19  regression-smoke   read       household
2026-09-17  regression-smoke   list_read + read  household
```

They no longer resolve to a live account, which is the correct outcome:
the trail still records who read what and when, and it is provable
without the account existing. **`verify-chain` after the removals:
`ok: True`, 98,790 rows, zero breaks.**

### Still open

Two superusers remain besides the project owner's own account, and
neither is clear-cut:

- **`dev`** — last login 2026-05-17. Named like a development account and
  four months cold, but not a smoke-test account, so it may belong to
  someone.
- **`admin`** — last login 2026-06-23. A generic name that may be a shared
  break-glass account; removing it without knowing who holds it could
  strand somebody.

Both hold full Django admin access, which matters more now that the
console deliberately refuses to manage superusers: they sit outside every
control the new feature adds.

## 2026-09-23 — first duplicate-discovery run, and the scoring fix it prompted

### The run

Discovery fired at **01:00:00Z (04:00 EAT)**, the first since the
scheduling landed. `CELERY_TIMEZONE` is `Africa/Kampala`, so the 04:00
crontab is 01:00 UTC.

```
2026-09-23 01:00:00  succeeded  full sweep
  members=1289  tier1=0  tier2=2  tier3=11  comparisons=2717  0.2s
```

MatchPair 16 -> 29. **Tier 2 and tier 3 produced pairs for the first
time**: every pair in the registry until now was tier 1, from a one-off
shell run months earlier.

Auto-merge stayed off and nothing merged itself — `decisions
attributable to auto-merge: 0`. The merges recorded that day were made
by people, with human reasons.

### What the run found

Two pairs landed above the 0.95 auto-merge threshold.

**1.000 — a probable genuine duplicate.** Lilian Kato, 1994-12-27, same
village (Wasswa, Bundibugyo), in two different households, registered
2026-05-15 and 2026-09-22. No NIN on either, so identity cannot be
settled from the record; it needs someone who can check locally. Tier 1
could never have found this.

**0.967 — two different people.** Rebecca Akello (1993-06-05, NIN …01UG,
0750008881) and Rebecca Okello (1993-09-28, NIN …06UG, 0750008886) — the
same household, different NINs, different phones, different roles.

Had auto-merge been enabled, the second pair would have been collapsed
into one registry identity within the hour, soft-deleting a real
person's record inside a 30-day reversal window nobody would have known
to use. This is the evidence for the decision to ship it disabled.

### Why it scored 0.967

Two compounding faults:

- `year_proximity` compared `d.year` alone while serving as the
  `date_of_birth` feature, so two people born eleven months apart scored
  a **perfect** date match.
- `village` carries 0.15 while tier 3 blocks **by** village, so it is 1.0
  for every pair the model ever compares.

Together, 0.30 of the weight was free to anyone sharing a village and a
birth year.

### The fix — deploy 3841eeb -> 5352c65

Code-only, no migrations. Dump first:
`pre-tier3-scoring-20260923-*.dump` (132 tables verified).

`birth_date_proximity` replaces `year_proximity`, scoring the whole
date: same date 1.0; within 31 days 0.75 (a swapped day and month is a
transcription slip, not a different person); same year but further apart
0.4; a year apart 0.2; two or more 0.0. Missing dates stay 0.0.

Verified in the running image:

```
same date 1.0 · day/month swapped 0.75 · the Rebecca pair 0.4 · a year apart 0.2
year_proximity gone: replaced, not shadowed
```

Effect on the two real pairs:

```
Akello / Okello   0.967 -> 0.877   below auto-merge, still above review
Kato   / Kato     1.000 -> 1.000   the true duplicate is untouched
```

The eleven existing tier-3 pairs keep their recorded scores: those are
the audit record of what the model said at the time.

### Not changed: the weights

**The active model version carries no `tier3` section at all**, so the
weights in force are the fallback defaults in `services.py` — which
nobody has approved. A match model decides which two people the registry
treats as one, so `manage.py propose_tier3_weights` authors the proposal
as a DRAFT and stops; `--show` prints the comparison and writes nothing.

```
date_of_birth  0.15 -> 0.20    first_name  0.30 -> 0.35
surname        0.30 -> 0.35    sex         0.10 -> 0.10
village        0.15 ->  —      removed: blocking fixes it at 1.0
```

Activation is dual approval and the approver must not be the author.
Until then the unapproved defaults remain in force — but the code fix
alone already takes the false match below the auto-merge line.

### Open

- 17 pending pairs, up from 7; the Kato pair is the one to look at first.
- The weights DRAFT is not yet authored — run the command when ready.

---

## 2026-09-23 — deploy 5352c65 → 007347c (household_shocks matview)

The Data Explorer's `household_shocks` dataset has been declared since
US-DATA-EXP-001 — an unmanaged model, a privacy-class seed, a row in the
refresh list — but its `CREATE MATERIALIZED VIEW` never landed. The
dataset resolved to a table that does not exist. Invisible while it
would have been empty anyway; not invisible once section K shock detail
starts arriving.

**Pre-deploy backup.**
`/opt/nsrmis/backups/pre-shocks-matview-20260923-153621Z.dump` (10.7M,
exit 0), verified with the throwaway-container `pg_restore -l`: **132
tables with data**.

**Deploy.** `ssh nsr-prod 'cd /opt/nsrmis && ./deploy.sh'`. Build 5m09s,
healthz ok on attempt 1, all 8 services up, 28G free.

**Migration applied:** `data_management.0011_household_shocks_matview` `[X]`.

### Two shape decisions, both pinned by tests

- **`sub_region_code` holds the code.** The two matviews built in 0010
  project `h.sub_region_id::text` into a column of that name — the
  GeographicUnit primary key, `13545`, not `SR-WEST-NILE-NORTHERN`.
  Everything that reads that column expects a code: ABAC
  (`_SUB_REGION_DENORM`), `query_builder`'s filters, and the
  `Household`/`Shock` denorm columns this is a projection of. A scoped
  query against a row-id column matches nothing and returns an **empty
  dataset rather than an error**. This matview stores the code and is
  deliberately inconsistent with its two siblings; fixing those moves
  live aggregates and is recorded as a finding, not done here.
- **`household_count` counts DISTINCT households.** Section K asks
  K03/K04 once per livelihood, so one household can file up to four
  Shock rows.

### The migration populates every matview, not just its own

A matview created `WITH NO DATA` raises on any SELECT, which the
aggregate endpoint turns into a 503. The 0010 pair have carried that
hole since they were built and are readable only because beat has since
run. Migration 0011 refreshes every unpopulated `mv_explorer_*`, so
after `migrate` the whole family is readable. Idempotent — on an
established database the others are already populated and are skipped.

### What the 503 had been covering

Closing it turned six sleeping tests into real ones:

- `tests/unit/data_explorer/fixtures.py` declared an Internal variable
  with `source_field="dwelling_type"` on the **PMT** matview, which does
  not project that column — the aggregate happy path raised FieldError.
  The contract tests accept "200 OR 503", and the matview was
  unpopulated in the test database, so they took the 503 branch every
  time and asserted nothing. Pointed at `pmt_band`, they now exercise
  the 200 path.
- `test_risk_probe` skipped on "query log is empty", which coincided
  with the real precondition only while every aggregate 503'd before it
  could log. It now skips on the matview holding no rows — the actual
  unbuilt-corpus condition (US-DATA-EXP-002).
- Nothing asserted that a declared dataset resolves to a matview that
  exists. `apps/data_explorer/tests/test_dataset_matviews.py` adds that,
  with the five genuinely unbuilt matviews named in a list a migration
  has to delete from, and checks each dataset's declared variables are
  columns the matview actually projects.

Full suite green on both backends: **2690 passed, 29 skipped**.

### Verification on the box

```
mv_explorer_household_by_subcounty_demographics | t
mv_explorer_household_by_subcounty_pmt          | t
mv_explorer_household_shocks_subregion          | t
```

`SELECT * FROM mv_explorer_household_shocks_subregion` → **0 rows**, and
that is correct: prod holds 354 households and **0 Shock rows**. The
dataset now reads empty instead of erroring, which was the whole point.
It fills the first time a household with section K detail is promoted.

`/healthz` 200. `/console/` 302 to login unauthenticated.

### Open

- The 0010 pair still put a row id in `sub_region_code`. Any ABAC-scoped
  query against those two datasets matches nothing and returns empty —
  silently. Worth fixing before anyone trusts an aggregate from them.
- Five Data Explorer matviews remain unbuilt (member education, member
  employment, referrals, grievances, health chronic). They are now named
  in `UNBUILT_MATVIEWS` rather than silently broken.
- 17 pending duplicate pairs; the Kato pair is still the one to look at
  first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-23 — deploy 007347c → 4ba1f06 (the 0010 matviews hold codes)

Follow-on to the finding logged above. Both matviews built by migration
0010 projected `h.sub_region_id::text`, `h.district_id::text` and
`h.sub_county_id::text` into columns named `sub_region_code`,
`district_code` and `sub_county_code`. On the live database that read:

```
 sub_region_code | district_code | sub_county_code | household_count
 13532           | 9             | 474             | 3
```

`query_builder._apply_geographic_scope` maps a request's level onto
exactly those three columns and filters `<column>__in=codes` with the
codes the caller sent — `101.1.01`, not `474`. **Every
geographically-scoped aggregate against these two datasets returned an
empty result**: not an error, not a warning, an empty result that reads
as "no households there". Only an unscoped national query ever returned
rows.

**Pre-deploy backup.**
`/opt/nsrmis/backups/pre-matview-geo-codes-20260923-155618Z.dump`
(10.7M, exit 0), 132 tables with data.

**Deploy.** Build 4m14s, healthz ok on attempt 1, all 8 services up,
26G free. Migration `data_management.0012_matview_geography_codes`.

### How

Postgres has no `CREATE OR REPLACE MATERIALIZED VIEW` and the column
expressions change, so each matview is dropped and rebuilt, then
populated in the migration — leaving them `WITH NO DATA` until the
01:00 beat run would be a 503 window. `pg_depend` was checked first:
nothing else in the database depends on either, so the drop took
nothing with it.

`sub_region_code` comes from `Household.sub_region_code`, the
denormalised ADR-0005 partition column that ABAC matches and that
migration 0011 already used. District and sub-county have no denorm on
Household, so they join through the FK. Verified on production before
writing the change: 354 households, **zero** rows where the denorm
differs from `sub_region.code`, and no nulls in any of the three FKs.

The three columns are now `COALESCE`'d to `''`. The old definitions
selected a bare `*_id::text`, which could be NULL in a column the
unmanaged model declares non-null.

### The trap this surfaced

A matview that reads `reference_data_geographicunit.code` depends on
that column, and Postgres then refuses to alter it:

```
cannot alter type of a column used by a view or rule
DETAIL: rule _RETURN on materialized view
        mv_explorer_household_by_subcounty_demographics
        depends on column "code"
```

`reference_data.0017_alter_geographicunit_code` widens `code` to
varchar(48). It is long applied here, so the deploy was unaffected —
but on a database built **from scratch** (the test database, and the DR
site) the migration graph is free to interleave the two apps and the
build dies partway through. That is how it was found: every Postgres
test errored at setup. Fixed with an explicit dependency on
reference_data 0017. Both suites then pass from a fresh database:
**2692 Postgres / 2694 SQLite passed, 29 skipped**.

The dependency fixes ordering, not the coupling. Any future migration
altering `geographicunit.code` must drop these matviews first.

### Verification on the box

```
row: SR-KAMPALA-CENTRAL 102 102.2.01 7
  scope sub_region=SR-KAMPALA-CENTRAL: 7 rows, 16 households
  scope district=102:                  7 rows, 16 households
  scope sub_county=102.2.01:           1 rows,  7 households
  bogus row-id scope (district=9):     0 rows
```

Before this deploy every one of those returned 0. All 354 households
sit on `active` geography, so nothing is stranded on a retired frame.

Migration reverses cleanly — checked on dev, the reverse restores the
0010 definitions verbatim and the columns go back to row ids.

### Open

- **Denormalise `district_code` and `sub_county_code` onto Household**,
  the way ADR-0005 already denormalises `sub_region_code`. That removes
  the join, removes the coupling to `geographicunit.code`, and makes all
  three levels available as flat columns to ABAC as well as the
  matviews. It is a Household schema change plus a backfill (354 rows
  now, 12M at national load), so it was not smuggled into this fix.
- Five Data Explorer matviews remain unbuilt, named in `UNBUILT_MATVIEWS`.
- 17 pending duplicate pairs; the Kato pair first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-23 — deploy a506fcf → 8b97b39 (county, and one ladder)

### Confirmed: the canonical path

Region → Sub-region → District → **County** → Sub-county → Parish →
Village. `Household` carries every rung as an FK, `GeographicUnit.Level`
declares every one. County was missing from the Data Explorer, and its
absence did not error — it over-answered:

```
county   102.2          -> 322 rows, 354 households   (all of Uganda)
region   R-CENTRAL      -> 322 rows, 354 households
county   TOTAL-NONSENSE -> 322 rows, 354 households
```

County sits above the sub-county floor, so the validator accepted it;
`query_builder.field_map` listed only sub_region/district/sub_county,
found no column, and fell through to an unfiltered queryset. A national
answer wearing a county label, with k-anonymity suppression computed
against the national population — and a nonsense code returned it too.

### After (verified on the box)

```
ladder      : national > region > sub_region > district > county > sub_county > parish > village
ScopeLevel  : national region sub_region district county sub_county parish village partner
pmt scopable: county district national region sub_county sub_region
row         : R-CENTRAL SR-KAMPALA-CENTRAL 102 102.2 102.2.01  (7 households)
national    : 354 households
    region      R-CENTRAL            ->  63 households
    sub_region  SR-KAMPALA-CENTRAL   ->  16 households
    district    102                  ->  16 households
    county      102.2                ->   7 households
    sub_county  102.2.01             ->   7 households
    county      TOTAL-NONSENSE       ->   0 households
```

Every level above sub_region used to return 354.

### Geographic API returns active units by default

```
{}                     -> 13966 {'active': 13966}
{'status': 'all'}      -> 13971 {'active': 13966, 'retired': 5}
{'status': 'retired'}  ->     5 {'retired': 5}
```

Operational consumers — scope pickers, capture, DSA scope — can no
longer be handed a retired UBOS unit. Historical callers opt in with
`?status=all`. DSA scope edits additionally reject any non-active unit
id at the service layer.

### The ladder had five copies. Now it has two, and they are tested against each other

`apps/data_explorer/geography.py` (backend, derived from
`GeographicUnit.Level`) and `design/v0.1/data/geo-levels.jsx` (console).
`tests/contract/test_geo_levels_one_ladder.py` parses the JSX and
compares it to the Python — asserting on both originals rather than on
a mirror — and fails if a second top-level `const GEO_LEVELS` reappears
anywhere in the design layer. Verified by deleting county from the JSX:
three of its four tests fail.

Replaced: `validators._GEO_LEVELS` (hand-numbered ranks),
`validators._GEO_ALIASES`, `query_builder`'s inline copy of those
aliases, `query_builder.field_map` (three of seven rungs),
`screens-admin-users.jsx`'s `UM_GEO_HIERARCHY`, and the two colliding
`GEO_LEVELS` declarations in the design layer.

### Both ends now fail closed

The validator refuses a level the dataset's matview cannot filter by
(422 `geographic_level_not_available`, listing what it can serve).
`_apply_geographic_scope` raises `UnscopableLevel` if one reaches it.
`national` still passes through unfiltered — that is what national
means.

### A mistake worth recording

The first cut of `geography.py` derived the ladder from `ScopeLevel`.
Committed `ScopeLevel` had no `COUNTY` member — the addition was sitting
uncommitted in a parallel session's working tree — so it passed every
test locally and deployed **without county**:

```
LADDER: national region sub_region district sub_county parish village
```

The suite was green against a tree state that does not exist in git.
The fail-closed branch contained it — production refused the county
request instead of answering it nationally — but the rung was gone
until the follow-up. The ladder now derives from `GeographicUnit.Level`,
the frame itself, not from a mirror of it.

Lesson, and the new habit: **verify in a clean checkout, not in a shared
working tree.** A clean `git worktree` also needs the gitignored local
files (`.env`, `.ci-test.env`, built `static/console/js/`) or 37 tests
fail for reasons that have nothing to do with the change.

### Also fixed while reviewing

`no-duplicate-globals` went red on the admin console: `GEO_LEVELS` and
`GEO_LEVEL_LABEL` were declared in both
`screens-admin-refdata-geography.jsx` (array of strings) and
`components/scope-edit-modal.jsx` (array of objects). The console loads
JSX as classic scripts sharing one global scope, so the last file
loaded won and the other silently read a shape it was not written for.
The admin console is the first page to load both.

Two guard tests were green and worthless: the post_migrate catalogue
loader fails on a fresh test database (PrivacyClass FK, logged not
raised), so `Dataset.objects` was empty and every set difference was a
difference against nothing. A `catalogue` fixture loads it explicitly.

Suites: **2720 Python passed / 29 skipped; 855 JS passed / 5 skipped.**

### Open

- Denormalise `district_code`, `county_code` and `sub_county_code` onto
  Household the way `sub_region_code` already is. Removes the matview
  join, removes the coupling to `geographic_unit.code`, and gives ABAC
  flat columns at every level. Schema change plus a backfill.
- The new geographic Variables (region, sub_region, county) land
  INACTIVE and need dual approval before they can be projected as
  aggregate dimensions. Scoping does not go through Variable, so county
  scoping is already live.
- Five Data Explorer matviews remain unbuilt, named in `UNBUILT_MATVIEWS`.
- 17 pending duplicate pairs; the Kato pair first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-23 — deploy 8b97b39 → f94c618 (geography denormalised onto Household)

`sub_region_code` has mirrored `sub_region.code` since ADR-0005, as the
partition key. Every other rung was reached through a join, and that
cost more than a join:

- **ABAC** matched `district__code`, `county__code`, `sub_county__code`,
  `parish__code`, `village__code` — one join per level on the hot path
  of every scoped list query in the registry.
- **The Data Explorer matviews** joined `reference_data_geographicunit`
  for the same codes, which made them *depend* on that table's `code`
  column, so Postgres refused to alter it. Migrations 0012 and 0013 had
  to declare an explicit dependency on `reference_data.0017` just to
  make a from-scratch build work.

Household now carries `region_code`, `district_code`, `county_code`,
`sub_county_code`, `parish_code` and `village_code` beside
`sub_region_code`.

**Pre-deploy backup.**
`/opt/nsrmis/backups/pre-geo-denorm-*.dump`, 132 tables with data.

**Migrations.** `0014_household_geography_codes` (six columns, seven
indexes, chunked backfill) and `0015_matviews_off_household_denorm`.
Build 4m, healthz first attempt, 20G free.

### Verification on the box

```
 hh  | no_region | no_district | no_county | no_subcounty | no_parish | no_village
 354 |         0 |           0 |         0 |            0 |         0 |          0

drift            0
county drift     0
subcounty drift  0

ABAC columns: region_code sub_region_code district_code county_code
              sub_county_code parish_code village_code
joins left  : []

    region      R-CENTRAL    -> 63 households
    district    102          -> 16 households
    county      102.2        ->  7 households
    sub_county  102.2.01     ->  7 households
lockstep    : 0 drifted
```

`pg_depend` for the matviews now lists only `data_management_household`,
`data_management_member` and `data_management_shock`, and

```
ALTER TABLE reference_data_geographicunit ALTER COLUMN code TYPE varchar(64);
-> ALTER succeeded — coupling gone
```

Four joins per household row also leave the matview refresh.

### The mirror is maintained, not merely initialised

`Household.sync_geography_codes()` runs on every save and rewrites a
mirror whose FK has moved. The predecessor wrote `sub_region_code` only
when it was blank, so a household moved between districts kept the old
code. Harmless while nothing read it; **not** harmless now that ABAC
matches on it — a stale mirror hides a household from the operator who
should see it and shows it to one who should not.

It stays cheap: a row whose FKs have not moved and whose mirrors are
filled issues no extra query (`from_db` snapshots the loaded FK ids and
`sync` compares against that). A test pins the re-save at one query.

### Deliberate behaviour change

`test_explicit_partition_key_not_overwritten` asserted that an
explicitly-passed `sub_region_code` survived `save()` untouched, so a
backfill could write the column through the ORM. That escape hatch now
lets a caller place a household outside its own geographic scope, and
nothing uses it — 0014's backfill writes in SQL. The test asserts the
mirror is corrected instead.

### Two mistakes on the way

- `from_db` first snapshotted with `getattr`. On a deferred queryset
  that goes through `DeferredAttribute`, which issues a query, which
  calls `from_db` — RecursionError, surfacing in **eighteen**
  deduplication tests because those are what use `.only()`. It reads
  `__dict__` now, and an unloaded level is left alone rather than
  guessed at. Two regression tests cover it.
- `atomic = False` on 0014: adding seven indexed columns and
  backfilling them in one transaction fails with *"cannot CREATE INDEX
  … because it has pending trigger events"*. The backfill is
  idempotent, so a partial run re-runs.

### At national scale

The seven indexes are instant on 354 rows. At 12M households `AddField`
with `db_index=True` holds ACCESS EXCLUSIVE for the whole build, so
they would have to go in `CONCURRENTLY`. **Doing this now, while the
table is small, was the cheap moment.**

Suites: **2732 Python passed / 29 skipped; 857 JS passed / 5 skipped.**
Migrations reverse cleanly (checked on dev).

### Not mine, still failing

`tests/integration/test_drs_workflow_e2e.py::
test_drs_submit_rejects_out_of_scope_sub_region` fails on an
uncommitted change in `apps/data_requests/services.py` — the refusal
message became "outside DSA **geographic** scope" and the integration
test still expects "outside DSA scope". Left for whoever is mid-edit.

### Open

- The Data Explorer's new geographic Variables (region, sub_region,
  county) are INACTIVE pending dual approval before they can be
  projected as aggregate dimensions. Scoping does not go through
  Variable, so county scoping is live.
- Five Data Explorer matviews remain unbuilt, named in `UNBUILT_MATVIEWS`.
- 17 pending duplicate pairs; the Kato pair first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-24 — deploy f94c618 → 687e5d2 (household Location card)

Reported from the screen: a household's Overview names Village, Parish,
District and Sub-region — **no county, no sub-county**, no region.

The API was never the problem. `HouseholdSerializer` has served
`region_name`, `sub_region_name`, `district_name`, `county_name`,
`sub_county_name`, `parish_name` and `village_name` all along. The
Location card hand-listed four rows and the view-model mapper
hand-picked four keys, so three rungs came over the wire and were
dropped on the floor.

Both now derive from the shared ladder: the mapper walks
`GEO_LEVEL_CODES`, the card renders one row per `GEO_LEVELS` entry,
finest first. Adding a rung to the ladder adds it to the screen.

**Verified in the deployed bundle:**

```
household bundle: GEO_LEVELS x 1 | GEO_LEVEL_CODES x 1
household bundle: hardcoded "Sub-region" row x 0
ladder bundle labels: Region Sub-region District County Sub-county Parish Village
```

Two contract tests: the serializer exposes `<level>_name` and `<level>`
for every rung the JSX ladder declares, and the Location card still
derives its rows rather than listing them.

### Finding — 47 UBOS units have no name

Noticed while verifying, **not fixed**: some units carry `name = code`,
so those rows will read "320.02" instead of a name.

```
 level      | units | name_is_code | pct
 region     |     5 |            0 | 0.0
 sub_region |    19 |            0 | 0.0
 district   |   147 |            0 | 0.0
 county     |   329 |           15 | 4.6
 sub_county |  2225 |           16 | 0.7
 parish     | 10872 |           16 | 0.1
 village    |   374 |            0 | 0.0
```

47 of 13,971. This is reference data from the UBOS loader, not display
logic — showing the code is more honest than hiding the rung, which is
what the screen did before. Worth a loader pass.

Suites: **2734 Python passed / 29 skipped; 857 JS passed / 5 skipped.**
The one Python failure is the uncommitted DRS message change noted in
the previous entry, still outstanding.

---

## 2026-09-24 — deploy 3a0d43a → 7c83de0, and the padded-county-code merge

### The 47 were not unnamed units. They were a second code frame.

Uganda's county codes reach the registry two ways:

- The **UBOS workbook** carries the county segment unpadded, and
  `scripts/load_ubos_geography.py` composes codes verbatim — `320.2`.
- The **Kobo form** sends `a3_county_municipality` zero-padded —
  `320_02` — which the connector turns into `320.02`.

Nothing reconciled them. A staged record naming `320.02` found no
GeographicUnit, so `geo_backfill` fabricated one with `name = code` —
its documented placeholder behaviour — and promotion attached the
household to the fabrication.

Sub-county and parish segments are two-digit padded in **both** frames,
so `320.2.11.08` and `320.02.11.08` differ in exactly one place.

**The consequence was not cosmetic.** One real county existed twice
with households split between the halves:

```
 kobo_code | ubos_code |          name          | hh_kobo | hh_ubos
 414.01    | 414.1     | Kinkizi County         |       3 |       4
 428.01    | 428.1     | Bugangaizi East County |       4 |       1
 114.01    | 114.1     | Kabula County          |       1 |       1
 228.01    | 228.1     | Kween County           |       1 |       1
 301.02    | 301.2     | Adjumani West County   |       1 |       1
```

No county-scoped query ever saw all 7 Kinkizi households. 29
households, 63 child units and one operator scope (`demo-chief`, parish
`411.05.05.04`) sat on fabricated rows.

The connector's own docstring is where it started: it claimed the
loader writes `412.02`. It writes `412.2`.

### Resolved, not rewritten

Stripping the zero in the connector is the obvious fix and it is wrong.
`412.02` is a real, named, ACTIVE county ("Nyakagyeme"); `412.2` is a
*different* real county ("Rujumbura County"). Stripping would silently
move households between them.

`apps/reference_data/code_frames.resolve_geographic_unit` therefore
looks for a row that **exists**, trying the given spelling first and the
alternative only when the first finds nothing. Promotion and
`geo_backfill` both use it. Mutation-tested: restore the old literal
lookup and the regression test fails.

### The repair

`manage.py merge_padded_geo_codes` (dry run by default; `--apply` needs
`--actor`). Dry run on prod first, then:

```
47 placeholder unit(s); 47 with an unambiguous UBOS twin, 0 without.
merged:
  units retired              47
  households repointed       29
  child units reparented     63
  operator scopes rewritten  1
```

Pre-merge dump: `/opt/nsrmis/backups/pre-geo-merge-*.dump`, 132 tables.

### Verification on the box

```
active placeholders left       0
households on a retired unit   0
denorm drift                   0

 Adjumani West County       2
 Bugangaizi East County     5
 Kabula County              2
 Kinkizi County             7     <- was 3 + 4
 Kween County               2
```

76 AuditEvents written (47 `geo_unit.merged`, 29
`household.geography_corrected` — one per household, not one per
level). Audit chain re-verified: **ok True, 0 breaks, 100,664 rows**.
The 23 forks it reports are all dated 2026-08-08/09 and long predate
this work.

Explorer matviews refreshed so the county aggregates reflect the merge
without waiting for 01:00.

Nothing was deleted — placeholders are RETIRED with
`effective_to = yesterday`, still visible under `?status=all`.

### Also fixed: main was red

`tests/integration/test_drs_workflow_e2e` asserted `"outside DSA
scope"` on a geography violation. Commit `ec47793` split that message
so geography violations read `"outside DSA geographic scope"`, but the
test was not updated. Updated to the committed phrasing.

### Open

- **`412.02` "Nyakagyeme" is a county-level row for what is really a
  sub-county**, sitting under Rukungiri beside `412.1` Rubabo, `412.2`
  Rujumbura and `412.3` Rukungiri Municipality. It is *named*, so the
  merge never considered it. Probably from `scripts/seed_kigezi_geo.py`.
  Worth checking before it acquires households.
- The Data Explorer's new geographic Variables (region, sub_region,
  county) are still INACTIVE pending dual approval.
- Five Data Explorer matviews remain unbuilt.
- 17 pending duplicate pairs; the Kato pair first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-24 — deploy 7c5fb1c → 2f580d4 (GRM audit + fixes), and the Kigezi merge

### Kigezi seed level shift — repaired

`scripts/seed_kigezi_geo.py` guessed the ladder from one Kobo
submission before the UBOS workbook existed, and put every rung one
level too high. `manage.py fix_kigezi_seed_levels --apply --actor
jmwebaze`:

```
county      412.02        Nyakagyeme      -> 412.2       Rujumbura County
sub_county  412.02.05     Kabwoma         -> 412.2.05    Nyakagyeme
parish      412.02.05.01  Kabwoma Parish  -> 412.2.05.01 Kabwoma

units retired 3 · households repointed 2 · units reparented 4
```

The two households now read **Rujumbura County → Nyakagyeme → Kabwoma**.
0 active placeholders, 0 households on retired units. Matviews
refreshed; audit chain ok, 0 breaks, 100,669 rows.

### GRM audit — what it found

- **The assignee was invented.** The console offered four people who
  had no accounts ("Adong Florence · CDO Tapac" and friends), and the
  task modal a free-text username box. `no-fabricated-identities` did
  not catch them: it matches NINs, +256 numbers and go.ug addresses,
  and a bare personal name has none of those.
- **The household was a ULID typed from memory**, unvalidated.
- **Nothing connected a data-correction grievance to the Updates
  Queue**, though the service has done it since US-S21.
- **A grievance had nowhere to record work in progress** — intake
  narrative, then resolution, nothing between.
- **Closing a task explained nothing**, and a grievance cannot resolve
  until every task is closed.
- **Assignment was silent.**
- **Modals cut text off** — no `min-width: 0`, so an unbreakable token
  pushed content past the edge.

All seven addressed; see the commit. Migration
`grievance.0005_grievance_comments` applied.

### Two findings on live data

**Three grievances and six tasks are assigned to people who do not
exist.** The grievances carry the console's invented names verbatim:

```
grievances: 'Adong Florence · CDO Tapac', 'Twikirize J. · District M&E',
            'Adong Florence · CDO Tapac'
tasks     : 'Inventore consequunt', 'Et quisquam qui dolo',
            'Quisquam repudiandae', 'Aliquam quidem digni', 'Johnson' x2
```

These are live records with SLAs running, assigned to nobody. New
assignments are refused, but these predate the check and need
reassigning by hand. The lorem-ipsum task names suggest a seeding pass
rather than real work.

**Assignment emails are not being sent.** `EMAIL_BACKEND` resolves to
the *console* backend — `default_email_backend()` falls back to it
unless `EMAIL_HOST_USER` or `EMAIL_HOST_PASSWORD` is set, and neither
is, though `EMAIL_HOST` is. So notifications are written to the web
container's log and audited as sent. To actually deliver, SMTP
credentials go in the prod `.env` (a secret — not committed, and not
something to set without the owner's say-so).

```
EMAIL_BACKEND      django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL NSR MIS <admin@quasar.ug>
active users       6 (5 with an address)
```

### Verification

```
invented assignee refused: 'Adong Florence · CDO Tapac' is not an active MIS user
comments table: present, 0 rows
grievances: 10
```

Suites, with only these changes on main: **2806 passed, 29 skipped**
(Python) and **863 passed, 5 skipped** (JS).

### Main is red on work that is not mine

- 7 choice-list / label-resolution tests fail **on main**, from
  committed `choice_field_map` / `reference_data.services` changes.
- 38 more fail in the working tree from uncommitted `apps/ddup` edits
  (`services.py`, `config.py`, the two ddup test modules).

Both verified as not mine by running this change alone against main in
a clean worktree.

### Open

- Reassign the 3 grievances and 6 tasks pointing at non-existent users.
- Set SMTP credentials if assignment emails should actually leave the
  box.
- `_pmtBandLabel` exists twice in the console with different behaviour
  (title-case vs a curated map). Renamed the registry one to stop them
  overwriting each other; the two band vocabularies should converge.
- 17 pending duplicate pairs; the Kato pair first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-24 — deploy b7b3a9e → c804673, and the phantom-assignee remediation

### Two fixes to the household picker

**It called a path nobody serves.** `/api/v1/households/` — the
registry viewset is under `/api/v1/data-management/`, and the URL
already had a canonical home (`_HH_API_BASE` in screens-registry.jsx).
Every search returned 404; no household could be attached to a
grievance.

Nothing could catch it from the JS side: a wrong URL is a runtime 404
and the component tests stub fetch. `tests/contract/
test_console_api_paths.py` now resolves every `/api/v1/` literal in the
design layer against Django's URLconf, skipping prefixes cut short by
`${`. Mutation-tested.

**Then it could not find anything.** `q` matched the Registry ID, the
head's name and the PARISH name only, so an operator typing the
district they know got nothing. Now searches district / sub-county /
parish / village names and the denormalised geography codes.

Verified on the box:

```
'Byaruhanga_test'  -> 1 hit     'Maracha' (district) -> 3 hits
'Ombia-Bura'       -> 3 hits    '01KRPPW6SA' (ID)    -> 1 hit
'Nowhere-At-All'   -> 0 hits
```

### The phantom assignees — what they turned out to be

Three grievances and six tasks pointed at names that were never
accounts. Looking at them changed the fix: **all six tasks are CLOSED**
and all three grievances come from one demo run on 18 May 2026.

```
01KRXS6M58…  resolved     "This is a test grievance, submitted by Johnson"
01KRXTVG4X…  in_progress  "The use didnt not correct my data iam currently not registered"
01KRY9MMEN…  closed       "Quia ullam omnis ut" · reporter "Et incididunt expedi"
                          · household_id "Deserunt esse itaque"
```

`"Deserunt esse itaque"` is not a Registry ID and names no household —
that grievance has pointed at nothing for four months. Task titles
include "Ut et proident unde", "In sed cupiditate al" and "Test Test".

Only **one** record is live work.

**Decision (registry owner):** reassign the live grievance to
`johnsonmwebaze`; leave the two test records' assignees alone and
annotate them. Rewriting a closed record's assignee would put a real
operator's name against a task titled "Test Test" — worse than the
phantom, which implicates nobody. Who held a closed case is audit
history, not a live pointer.

`manage.py remediate_phantom_assignees --apply --actor jmwebaze`:

```
reassign 01KRXTVG4X… [in_progress] 'Twikirize J. · District M&E' -> 'johnsonmwebaze'
annotate 01KRXS6M58… [resolved]  (assignee 'Adong Florence · CDO Tapac' kept)
annotate 01KRY9MMEN… [closed]    (assignee 'Adong Florence · CDO Tapac' kept)
Done: 1 reassigned, 2 annotated.
```

Re-runnable: a record already on a real user is left alone, an existing
note is not duplicated. The two remaining phantom values are the
deliberate ones.

### Open

- The two test grievances and their six tasks are still in production.
  They are annotated, not deleted — deletion was offered and not taken.
- **Assignment emails still do not leave the box.** `EMAIL_BACKEND`
  falls back to console because `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD`
  are unset. The reassignment above wrote its notification to the web
  container's log.
- `opm-analyst` has no email address, so that account cannot be
  alerted about anything.
- `_pmtBandLabel` still exists twice in the console with different
  behaviour; renamed apart, not converged.
- 17 pending duplicate pairs; the Kato pair first.
- The tier-3 weights DRAFT is still not authored.

---

## 2026-09-24 — demo grievances deleted; the email finding

### Deleted, with the audit trail kept

`manage.py delete_test_grievances --apply --actor jmwebaze`, after a
dump to `pre-delete-demo-grievances-*.dump`:

```
delete 01KRXS6M58… [resolved] tasks=2 comments=1 desc='This is a test grievance, submitted by J'
delete 01KRY9MMEN… [closed]   tasks=2 comments=1 desc='Quia ullam omnis ut'
Deleted 2 grievance(s) and their tasks.
```

After:

```
grievances now: 8 | tasks: 2
still on a phantom: []
rows for the deleted ids: 0
audit events about them, surviving: 8
  delete event 01KRXS6M58… by jmwebaze | tasks recorded: 2
  delete event 01KRY9MMEN… by jmwebaze | tasks recorded: 2
```

A `delete` AuditEvent was emitted **before** each removal carrying the
status, assignee, description, household_id and task ids, so the chain
records what was removed rather than an empty shell. The eight events
already referencing those ids survive: AuditEvent points at entities by
string id, not foreign key.

No grievance is assigned to a phantom any more.

### Email: nothing has ever been delivered

Not a misconfiguration of the host — that was right all along.

```
EMAIL_HOST  comms.quasar.ug:587 STARTTLS      <- correct
EMAIL_BACKEND  …console.EmailBackend          <- discards everything
EMAIL_HOST_USER / PASSWORD  unset             <- the cause
```

`default_email_backend()` switches to SMTP only once one of the
credentials is set, so it fell back to console. The console backend
accepts every message and prints it, `send_mail` returns success, and
the notification is audited as sent. **Eighteen notifications are
recorded as delivered and none of them were sent** — DSA signing
invitations, password resets, and today's grievance assignment among
them.

The relay requires authentication, for local recipients as well as
external ones — the rejection names the client, not the address:

```
MAIL FROM johnson@quasar.ug -> 250 2.1.0 Ok
RCPT johnson@quasar.ug      -> 554 5.7.1 <unknown[154.72.195.66]>: Client host rejected
RCPT jmwebaze@gmail.com     -> 554 5.7.1  (the same)
```

**To deliver**, in the production `.env`:

```
EMAIL_HOST_USER=johnson@quasar.ug
EMAIL_HOST_PASSWORD=<the mailbox password>
```

then restart web + worker + beat. Nothing else changes. Credentials are
secrets and were not set from here.

Sending identity is now `NSR MIS <johnson@quasar.ug>` (was
`admin@quasar.ug`); `SERVER_EMAIL` follows it.

### So it cannot go unnoticed again

- `security.W007` warns on every management command and in the deploy
  output while a non-DEBUG deployment is on a discarding backend. It is
  already visible in the output above.
- Every `notification.sent` audit row now carries `delivered` and
  `backend`, so "sent" is checkable after the fact.
- `send_notification` logs a warning each time a discarding backend
  accepts a message.

### Open

- **SMTP credentials** — the one thing standing between the code and
  delivered mail.
- **No reverse DNS for 154.72.195.66.** The relay logs it as
  `unknown[...]`. Authentication fixes the rejection; a missing PTR may
  still cost deliverability with strict receivers. DNS change, not an
  application one.
- `opm-analyst` has no email address, so that account cannot be alerted.
- The live grievance `01KRXTVG4X…` still carries two closed
  placeholder tasks from the demo run. Annotated, left in place.

### Not mine, failing in the working tree

`tests/contract/test_nginx_routes_every_registry_url.py` fails on both
nginx confs: the `reset/` URLs added to `nsr_mis/urls.py` (uncommitted,
alongside the new `registration/password_reset_*.html` templates) are
not routed to the registry container. **A password-reset link emailed
to a user would 404 in production** while passing every Django
test-client test — which is exactly what that contract test exists to
catch. Needs a `location /reset/` block proxying to `nsr_registry`.

---

## 2026-09-24 — correction: dev sends mail, production does not

The entry above says no email has ever been sent and names DSA signing
and password resets. **That is true of production and wrong as a
general claim.** Dev has the credentials and delivers:

```
DEV  EMAIL_BACKEND …smtp.EmailBackend   HOST_USER admin@quasar.ug   PASS set
PROD EMAIL_BACKEND …console.EmailBackend HOST_USER (unset)          PASS unset
```

The password-reset mails that arrived came from dev — the link in them
points at `192.168.2.3:8005`, and the From was `admin@quasar.ug`. The
eighteen undelivered notifications are production's.

### Sending as johnson@quasar.ug needs a johnson@quasar.ug mailbox

The relay enforces sender-login match. Tested from dev, where the
credentials exist:

```
authenticated as admin@quasar.ug
  MAIL FROM admin@quasar.ug   -> 250 | RCPT -> 250 2.1.5 Ok
  MAIL FROM johnson@quasar.ug -> 553 5.7.1 Sender address rejected:
                                 not owned by user
```

So the admin@quasar.ug credentials cannot send as johnson@quasar.ug.
Either create/obtain that mailbox's credentials, or keep sending as
admin@quasar.ug.

`DEFAULT_FROM_EMAIL` now derives from `EMAIL_HOST_USER` rather than
naming an address, so the two cannot drift apart; `security.W008` warns
if an explicit override disagrees with the mailbox. Dev is unchanged —
it authenticates as admin@quasar.ug and sends as admin@quasar.ug.

### What production still needs

```
EMAIL_HOST_USER=<the mailbox>          # johnson@ or admin@quasar.ug
EMAIL_HOST_PASSWORD=<its password>
```

then restart web + worker + beat. Nothing else: `EMAIL_HOST` is already
`comms.quasar.ug:587` with STARTTLS, and the From follows the mailbox.

Still open: no reverse DNS for 154.72.195.66 — the relay logs it as
`unknown[...]`. Authentication fixes the rejection; the missing PTR may
still cost deliverability with strict receivers.
