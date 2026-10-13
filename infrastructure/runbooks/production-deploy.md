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

## Deploying (pull from git, build on the box)

```bash
ssh <box> 'cd /home/jmwebaze/nsr_uganda && ./deploy-demo.sh'
```

That is the whole thing: fetch `origin/main`, back the database up,
build the image **here**, `up -d`, and wait for `/healthz` to answer
200 before claiming success. `./deploy-demo.sh --rollback` returns to
the previous image, which the script tags before every build.

The image is `nsr-mis:demo`, passed to compose through `NSR_IMAGE`,
which `compose.prod.yml` already reads
(`${NSR_IMAGE:-ghcr.io/...}`). Nothing is pushed anywhere.

### Why not the GitHub Actions workflow that used to do this

`.github/workflows/deploy.yml` built `linux/amd64`, pushed to GHCR and
sshed in to `docker compose pull`. It was deleted on 12 October 2026
after two failures that are worth remembering, because both are easy
to reintroduce:

* **It was gated on CI passing, and said nothing when it did not.**
  CI went red on 25 September; `Deploy` then *skipped* on every push
  for three weeks while the box served a September image and every
  push looked like it had shipped. A deploy that silently does
  nothing is worse than one that fails.
* **Building elsewhere hid an architecture difference.** The dev
  machine is aarch64 and this box is x86_64. An image built on dev and
  copied over will not exec here — four minutes of downtime on
  11 October proved it. Building where the thing runs cannot get the
  architecture wrong.

A red CI no longer blocks a deploy, which is a deliberate trade and
not an accident: the gate was costing more than it caught. Run the
suites on dev before pushing.

### First-time setup on a box that is not yet a checkout

This box was a copy of the tree, not a clone, until 12 October 2026.
To convert another one, from inside the compose directory:

```bash
tar czf ~/pre-git-local-files.tgz .env backups   # the only untracked things
git init -b main
git remote add origin https://github.com/jmwebazeutamu/nsr_uganda.git
git fetch origin main
git reset --hard origin/main                      # overwrites the stale copies
ls -la .env backups                               # both must still be there
```

`.env` and `backups/` are gitignored, so the reset leaves them alone —
but check, because that file is the one thing on the box that cannot
be recreated from the repository.

## Public site (`public` container)

The public site runs as a **separate container from the same image**, with
`ROOT_URLCONF=nsr_mis.urls_public`, published on `127.0.0.1:8006`. That
URLconf carries the landing page and `/healthz` and nothing else — no
console, no admin, no `/api/`, no `/login/`. Spec LP-O-10 wants the public
site in a zone with no route to the registry; on a single shared box the
strongest available form of that is a process in which those routes do not
exist. `tests/contract/test_public_site.py` asserts they 404.

**One hostname, two containers.** `nsr-sris-dev.quasar.ug` serves the
public site at `/` from the `public` container, and Apache path-routes
`/login/`, `/logout/`, `/home/`, `/console/`, `/admin-console/`,
`/admin/`, `/api/`, `/manual/`, `/static/` and `/healthz` to `web`. Staff
sign in at `/login/` on the same host. Order matters in that vhost: the
catch-all `/` must stay last.

Two consequences worth holding in mind:

* `LOGIN_REDIRECT_URL` is `/home/`, not `/`, because `/` is now the
  public page. Signing **out** still goes to `/`, which is the right
  place to land once a session is gone.
* The two sites now share an origin, which is a step away from LP-O-10.
  The vhost strips `Cookie` on public routes so an operator session never
  reaches the public process, and that process still has no registry
  routes. What is lost is browser-level origin separation — if the public
  site ever echoes user-supplied content, move it to its own hostname.

**Until the vhost is installed the public site is dark.** CD brings the
container up (`up -d --remove-orphans` picks up the new service), but
nothing proxies to 8006 until someone installs the updated vhost. The
container can be running and verified while the site stays unreachable.

Before it goes public, three things must close:

| | |
|---|---|
| LP-O-01 / LP-O-02 | Does this replace `nsr.mglsd.go.ug` or run beside it? The hostname in `nsr-public.conf` is a placeholder until this is answered. Do not point a `.go.ug` name at it first. |
| LP-O-06 | The DPO signs off the §8.3 disclosure floor. Until then `NSR_PUBLIC_STATS_LIVE` stays `False` and the page renders placeholder slots. |
| Copy | The spec is a draft. The page still carries ~59 `{{slot}}` placeholders awaiting approved MGLSD wording. |

Verify the container without exposing it:

```bash
docker compose -f compose.prod.yml ps public
curl -fsS http://127.0.0.1:8006/healthz          # -> ok
curl -s http://127.0.0.1:8006/ | head -40        # the landing page
# the zone must NOT route the registry:
for p in console admin api/v1/data-management/households login; do
  printf '%s -> %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8006/$p/)"
done                                             # all 404
```

Expose it, once the three rows above are closed. This REPLACES the
existing vhost, so config-test before reloading — a bad file on this box
breaks every site Apache fronts:

```bash
sudo cp infrastructure/apache/nsr-sris-dev.conf /etc/apache2/sites-available/
sudo apache2ctl configtest          # must pass BEFORE the reload
sudo systemctl reload apache2
# certbot has already run for this hostname; it rewrites the :443 vhost
# from the :80 one, so re-run it after changing the routes:
sudo certbot --apache -d nsr-sris-dev.quasar.ug
```

Check the split landed, from the box:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://nsr-sris-dev.quasar.ug/         # public page
curl -s -o /dev/null -w '%{http_code}\n' https://nsr-sris-dev.quasar.ug/login/   # registry
curl -s https://nsr-sris-dev.quasar.ug/ | grep -c 'Staff sign in'                 # 1
```

Turning figures on is a separate, deliberate act with an owner — set
`NSR_PUBLIC_STATS_LIVE=True` in the box's `.env` and restart `public`.
Do not set it in `compose.prod.yml`.

## Rollback

```bash
cd /home/jmwebaze/nsr_uganda && ./deploy-demo.sh --rollback
```

`deploy-demo.sh` tags the running image `nsr-mis:previous` before every
build, so there is always exactly one step back. There is no second
step: the registry that used to hold every `:<sha>` is out of the
path, and a deploy older than the last one means checking that commit
out and building it.
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
