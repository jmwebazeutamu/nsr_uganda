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
