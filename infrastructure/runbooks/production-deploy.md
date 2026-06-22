# Runbook — NSR MIS dev/staging deploy (nsr-sris-dev.quasar.ug)

Single-host Docker deploy on the shared `104.225.218.102` box, fronted by
the host's Apache + certbot. See ADR-0027. **Dev/staging only — no real
PII until the NITA-U k8s environment exists.**

## Topology

```
Internet ──443──> Apache (host, certbot TLS)
                    └─ vhost nsr-sris-dev.quasar.ug ─proxy─> 127.0.0.1:8005
                                                              └─ web (gunicorn, WhiteNoise static)
   compose project `nsr-sris-dev`:  web + worker + beat + db(postgis) + redis
   db/redis: private network only (never published)
```

- Compose dir on host: `/home/jmwebaze/nsr_uganda`
- Secrets: `/home/jmwebaze/nsr_uganda/.env` (0600, generated on the box, never committed)
- Image: `ghcr.io/jmwebazeutamu/nsr_uganda:latest`

## First bring-up (manual)

```bash
cd /home/jmwebaze/nsr_uganda
# .env already generated (DJANGO_SECRET_KEY / NSR_NIN_PEPPER / NSR_DATA_KEY /
# POSTGRES_PASSWORD created server-side). Image built locally or pulled from GHCR.
docker compose -f compose.prod.yml --env-file .env up -d
docker compose -f compose.prod.yml ps          # all healthy?
curl -fsS -H 'Host: localhost' http://127.0.0.1:8005/healthz   # -> ok
docker compose -f compose.prod.yml exec web python manage.py createsuperuser
```

Migrations + collectstatic run automatically in the web entrypoint.

## Go-live (TLS) — after DNS resolves

1. Create a DNS **A record**: `nsr-sris-dev.quasar.ug -> 104.225.218.102`. Confirm: `getent hosts nsr-sris-dev.quasar.ug`.
2. Install the vhost + issue the cert:
   ```bash
   sudo cp /home/jmwebaze/nsr_uganda/infrastructure/apache/nsr-sris-dev.conf /etc/apache2/sites-available/
   sudo a2ensite nsr-sris-dev
   sudo apache2ctl configtest && sudo systemctl reload apache2
   sudo certbot --apache -d nsr-sris-dev.quasar.ug --redirect -m <ops-email> --agree-tos -n
   ```
3. Tell Django the proxied scheme is https — add to the certbot-generated
   `nsr-sris-dev-le-ssl.conf` inside the `<VirtualHost *:443>`:
   ```apache
   RequestHeader set X-Forwarded-Proto "https"
   ```
   then `sudo apache2ctl configtest && sudo systemctl reload apache2`.
4. Verify: `curl -fsI https://nsr-sris-dev.quasar.ug/healthz` (200), and the
   admin at `https://nsr-sris-dev.quasar.ug/admin/`.

> certbot edits ONLY the nsr-sris-dev vhost; the five co-tenant sites are
> untouched. Always `apache2ctl configtest` before reload.

## CD (auto-deploy on push to main)

`.github/workflows/deploy.yml` runs after CI passes on `main` (or via
manual *Run workflow*): builds `linux/amd64`, pushes to GHCR, SSHes in to
`docker compose pull && up -d`. Repo secrets: `DEPLOY_SSH_KEY`,
`DEPLOY_HOST`, `DEPLOY_USER`. Watch: `gh run watch` / the Actions tab.

## Rollback

```bash
cd /home/jmwebaze/nsr_uganda
# images are tagged :latest and :<sha>; pin the previous good sha:
NSR_IMAGE=ghcr.io/jmwebazeutamu/nsr_uganda:<previous-sha> \
  docker compose -f compose.prod.yml --env-file .env up -d web worker beat
```
Forward-only migrations (CLAUDE.md): a rollback that crosses a migration
needs the reverse plan from the release ticket — do not assume `down`.

## Backups (operational follow-up)

```bash
docker compose -f compose.prod.yml exec -T db pg_dump -U nsr nsr | gzip > nsr-$(date +%F).sql.gz
docker run --rm -v nsr-sris-dev_media_data:/m -v "$PWD":/b alpine tar czf /b/media-$(date +%F).tgz -C /m .
```

## Troubleshooting

- **web unhealthy / 400 on /healthz** — `ALLOWED_HOSTS` must include `localhost` (the healthcheck Host). Check `.env`.
- **502 from Apache** — web container down or not on 8005: `docker compose ps`, `docker compose logs web`.
- **static missing** — entrypoint collectstatic failed: `docker compose logs web`; confirm `NSR_WHITENOISE=True`.
- **CSRF 403 on admin login** — `CSRF_TRUSTED_ORIGINS=https://nsr-sris-dev.quasar.ug` and the :443 vhost sets `X-Forwarded-Proto https`.
- **CD pull denied** — GHCR login on the host; the workflow logs in with the run token each deploy.

## Hardening follow-ups

- Dedicated **non-sudo deploy user** for CD (current key is `jmwebaze`, who has passwordless sudo).
- Nightly pg_dump + media backup to off-box storage.
- Slim the image (multi-stage; make the chatbot `sentence-transformers`/torch dep optional) to cut build/pull time.
