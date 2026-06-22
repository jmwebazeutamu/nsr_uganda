# ADR-0027: Single-host Docker deployment for the dev/staging environment

- **Status**: Proposed
- **Date**: 21 June 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Engineering Lead, NITA-U liaison
- **References**: CLAUDE.md (locked stack — Kubernetes at the NITA-U Government Data Centre); SAD §8.3 (TLS), §8.6 (threat model); ADR-0005 (sub-region partitioning); ADR-0026 (ABAC); `compose.prod.yml`, `.github/workflows/deploy.yml`, `infrastructure/apache/nsr-sris-dev.conf`, `infrastructure/runbooks/production-deploy.md`.

---

## Context

The locked target platform (CLAUDE.md) is **Kubernetes at the NITA-U Government Data Centre**, with Helm charts under `/infrastructure/helm`. That environment is not yet provisioned. We need a running, internet-reachable deployment now for stakeholder review, integration testing, and demos — a **dev/staging** environment, explicitly **not** the sanctioned production registry.

The available host is `104.225.218.102` — a commercial VPS (Ubuntu 24.04, 12 vCPU / 62 GB / 1.1 TB) that is **already a live multi-tenant box**: Apache + certbot front five sites (sris.quasar.ug, rentals, grm-sl, comms/mail, survey-solutions) on ports 80/443, each proxied to its own container. A separate, older `sris` application (`github.com/jmwebazeutamu/sris`, not this `nsr_uganda` repo) already runs at sris.quasar.ug.

## Decision

### D1. Deploy as a single-host Docker Compose stack, fronted by the host's existing Apache.

`compose.prod.yml` runs the **core stack**: `web` (gunicorn) + Celery `worker` + `beat` + PostgreSQL/PostGIS + Redis. The original design used Caddy on 80/443 for automatic TLS; that is **incompatible with this box** (Apache owns 80/443 for five live sites). Instead:

- `web` publishes gunicorn on **127.0.0.1:8005** (localhost only — never externally bound).
- A new host **Apache vhost** (`nsr-sris-dev.quasar.ug`) reverse-proxies to it, with TLS from the existing **certbot** — identical to the five co-tenant sites.
- **WhiteNoise** serves static from inside gunicorn, so Apache only proxies the app (no static `Alias`, no host bind-mount, no volume-permission coupling on the shared box). Non-manifest compressed storage (the manifest backend fails hard on the vendored `babel.min.js` missing `.map`).
- `db` and `redis` stay on the project's **private** Docker network — never published (the box already runs other postgres/redis on 5432/6379; ufw DENYs those externally regardless).

### D2. New site, co-tenant — touch nothing already running.

NSR is deployed as a brand-new site (own compose project `nsr-sris-dev`, own domain, own port) alongside the five existing services. The older `sris` deployment is left untouched. This is a co-tenancy decision, not a replacement.

### D3. CI-gated auto-deploy to GHCR + SSH.

`.github/workflows/deploy.yml` triggers on `workflow_run` after the **CI** workflow succeeds on `main` (so a red main never ships), plus manual `workflow_dispatch`. It builds a `linux/amd64` image, pushes it to **GHCR** (`ghcr.io/jmwebazeutamu/nsr_uganda`), then SSHes to the host to `docker compose pull && up -d` (migrations + collectstatic run in the web entrypoint). The image is built on GitHub runners, **not** on the shared box, so deploys don't contend with the live services for CPU/IO. The deploy SSH key is a GitHub Actions secret.

### D4. Production hardening is opt-in via env, so the test suite is unaffected.

`NSR_SECURE_SSL` gates the TLS block (proxy SSL header, secure cookies, HSTS, CSRF trusted origins); `NSR_WHITENOISE` gates the WhiteNoise storage backend. Both are set only in the server `.env`, never in CI — so the test suite (which runs `DEBUG=False` over plain HTTP, no collectstatic) is byte-for-byte unaffected.

## Consequences

- This is **explicitly a dev/staging environment**. It diverges from the locked k8s-at-NITA-U target and must **not** hold real household PII until the sanctioned environment exists. The consent module stays OFF (`CONSENT_MODULE_ENABLED=False`) pending DPO sign-off (ADR-0024). The Helm/k8s path under `/infrastructure/helm` remains the production target; this ADR does not supersede it.
- **Co-tenancy risk**: a heavy operation here (build, OOM, disk fill) could affect five live sites. Mitigations: image built off-box in CI; db/redis unpublished; deploy is `pull`-only on the host.
- **Deploy-key privilege**: the CD key authenticates as `jmwebaze`, who has passwordless sudo. The deploy itself needs only the `docker` group, so a dedicated **non-sudo deploy user** is a recommended hardening follow-up (a leaked secret would otherwise grant root on the shared box).
- **Single host, no HA**: no replication or failover. Backups (pg_dump of the `nsr` DB + the media volume) are an operational follow-up in the runbook.

## Status note

Proposed. Ratifies the dev/staging deployment only; the NITA-U Kubernetes production deployment remains a separate, future ADR.
