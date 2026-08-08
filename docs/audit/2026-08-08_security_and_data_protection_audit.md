# NSR MIS — security & data-protection audit

**Date:** 2026-08-08
**Scope:** secrets, authn/authz, ABAC + audit coverage, PII exposure, production surface, DPPA 2019 posture.
**Commit:** `4b28bdc` (branch `us-consent-foundation`)
**Includes:** live checks against the deployed site `nsr-sris-dev.quasar.ug` (read-only GETs).

Companion to `2026-08-08_delivery_and_code_health_audit.md`.

---

## Headline

**The application's own controls are in good shape.** Fail-closed auth, real NIN
encryption, ABAC enforced at every geographic level, no secrets ever committed,
no PII in logs. The findings are at the **perimeter**, not in the code.

One live issue: the complete API specification of the registry is published
unauthenticated on the public internet.

---

## F1 — HIGH — Full OpenAPI spec is public on production

`https://nsr-sris-dev.quasar.ug/api/schema/` returns **HTTP 200, 374,832 bytes,
259 documented paths**, with no authentication. `/api/docs/` serves the Swagger
UI over it.

This is deliberate — `nsr_mis/urls.py` sets `permission_classes=[AllowAny]` on
both, commented "developer convenience" — but the consequence on a
production host holding household PII is a complete map of the attack surface:
every endpoint, parameter, filter and response schema, including field names
`nin`, `nin_value`, `nin_hash`, `date_of_birth`, `surname`, `first_name`,
`telephone_1`, `gps_lat`, `gps_lng`.

The data itself is protected — `/api/v1/data-management/households/` correctly
returns **403** unauthenticated — so this is disclosure, not a breach. But it
removes reconnaissance cost entirely, and it is the sort of thing a DPPA §  audit
or a NITA-U review will raise.

`docs/threat_model.md` does not mention OpenAPI or schema exposure at all.

**Fix:** drop `AllowAny` from `schema_view`/`swagger_view`, or gate them on
`DEBUG`, or restrict at Apache. Then add the decision (and its rationale) to the
threat model either way — the current state is undocumented rather than
accepted.

## F2 — MEDIUM (latent) — `/console/` and `/manual/` are unauthenticated routes

`nsr_mis/urls.py` registers `console/` and `manual/` unconditionally. Their own
comments say *"Dev-only — production serves the built React app through nginx
with its own auth gateway"* and *"production should serve these static files
through nginx"* — but nothing enforces that: the routes are not `DEBUG`-gated,
and the production Apache vhost is a bare `ProxyPass /` with no path rules.
There is no nginx and no auth gateway in the deployed architecture (ADR-0027).

**They are not currently exposed** — both 404/503 in production, because the
Dockerfile only copies `nsr_mis`, `apps`, `manage.py`, so `design/` and
`docs/user-manual/site/` are absent from the image.

That is protection by accident. The day the image ships `design/` — for the
built console, which is the stated plan — the whole design tree becomes world
-readable with no code change and no review signal.

Path traversal *is* correctly defended (`resolve()` + `relative_to()`).

**Fix:** wrap both in `if settings.DEBUG:` or `@staff_member_required`. One line,
removes the latent trap.

## F3 — MEDIUM — Production TLS is not captured in the repo

`infrastructure/apache/nsr-sris-dev.conf` defines only `<VirtualHost *:80>` with
`ProxyPass / http://127.0.0.1:8005/` — no TLS, no redirect.

The live host **does** serve HTTPS (HTTP 301 → HTTPS, valid certificate), so
certbot added a `:443` vhost directly on the box that exists nowhere in version
control. Rebuilding the host from the repo would produce a plaintext-only
deployment serving a national PII registry.

**Fix:** commit the real `:443` vhost (with the HTTP→HTTPS redirect and HSTS)
so the repo describes the deployment that actually exists.

## F4 — LOW — `DATA_UPLOAD_MAX_MEMORY_SIZE` raised to 25 MiB

Noted for completeness: `fcedb09` raised this from Django's 2.5 MB default so the
UPD evidence caps become reachable. It widens the unauthenticated-request memory
envelope on every endpoint, not just the bundle one. Acceptable — the endpoint
is authenticated and Django still refuses beyond the ceiling — but if a request
-size limit is ever set at Apache, size it against this number.

---

## What is working

Verified rather than assumed:

| control | finding |
|---|---|
| **Secrets** | `.env` never committed (full history checked); no secret-shaped strings in any tracked file; no hardcoded credentials in tracked Python |
| **Auth default** | `DEFAULT_PERMISSION_CLASSES = IsAuthenticated`, fail-closed; **zero** `AllowAny` or empty `permission_classes` in any app module |
| **NIN at rest** | `nin_value = EncryptedBinaryField`, `nin_hash` (indexed) for joins, `nin_last4` for display — exactly ADR-0002 / CLAUDE.md |
| **PII in logs** | No `logger.*` call passes NIN, name, DOB, phone or GPS |
| **ABAC** | Enforced through two complementary mechanisms — `ScopedQuerysetMixin` (13 modules) for list views and `user_can_access_household` for single-entity views; out-of-scope reads return empty rather than 404, so existence is not confirmed |
| **Audit** | `AuditReadMixin` on 11 modules; service-layer `emit_audit` where the API layer is thin (consent alone has 17 in `services.py`); hash chain verified intact — 73,778 rows, 1 head, 0 forks, 0 dangling |
| **Dependency CVEs** | `pip-audit` green in CI |
| **SAST** | `bandit` green in CI |

## Method & caveats

Live checks were read-only GETs against the user's own deployment. No
authentication was attempted, no data was retrieved, nothing was modified.

Two false leads were found and discarded — recorded so they are not
re-derived:

- Grepping logger calls for `nin` matches `logger.war**nin**g`. Word-anchored
  re-run: no PII in logs.
- Counting ABAC/audit coverage by mixin name alone undercounts badly. `apps/dqa`
  appeared unscoped but enforces scope via `user_can_access_household`, and
  `apps/consent` appeared unaudited but emits 17 audit events from its service
  layer. Both are correctly protected.

**Not assessed:** Keycloak/OIDC (not yet integrated — DRF still uses Session +
Basic auth, and Basic auth over the API is worth revisiting before pilot),
rate limiting, DPIA completeness against the DPPA, retention-policy
implementation, key management for `NSR_DATA_KEY`/`NSR_NIN_PEPPER` in
production, backup encryption, and the CAPI/tablet channel.
