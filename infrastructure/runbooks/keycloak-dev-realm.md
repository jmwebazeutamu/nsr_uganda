# Keycloak dev realm — runbook

Phase 0 of `docs/keycloak_oidc_scope.md`. Implements the realm from ADR-0006.
**No application code is wired to it yet** — that is Phase 1. This gives you a
running, reproducible identity provider to build against.

## Running it

It is part of the normal compose stack, so `docker compose up -d` (or `nsr up`)
starts it alongside the app.

| | dev default | on the `dev` VM |
|---|---|---|
| URL | http://localhost:8080 | http://192.168.2.3:8006 |
| Admin console | `/admin` | same |
| Admin login | `admin` / `admin` | same |
| Realm | `nsr-mis` | same |

Dev users, both password `dev-only-password`:

| username | realm role | `geographic_codes` |
|---|---|---|
| `dev-coordinator` | `NSR_UNIT_COORDINATOR` | `national:` |
| `dev-parish-chief` | `PARISH_CHIEF` | `parish:A-P` |

Discovery document — useful for checking the issuer:

```
curl http://192.168.2.3:8006/realms/nsr-mis/.well-known/openid-configuration
```

## The realm is code

`infrastructure/keycloak/realm-nsr-mis.json` is the source of truth. It is
re-imported on **every** container start, and the container runs with the
embedded database and **no volume**, so anything you change by clicking around
the admin UI is discarded on restart.

That is deliberate — it is the mitigation for the "realm drift" risk in
`docs/keycloak_oidc_scope.md` §6. To change the realm:

1. Edit `realm-nsr-mis.json`.
2. `docker compose up -d --force-recreate keycloak`
3. Commit.

Or, to capture something you configured in the UI, export it and reconcile it
into the JSON by hand before committing.

**Gotcha:** Keycloak's `DESCRIPTION` column is `varchar(255)`. A longer
`description` on a client fails the import with a `Value too long` error and
the container exits (1) — it does not start degraded. Keep client
descriptions short and put the reasoning here instead.

## Why `KC_HOSTNAME` matters

The token issuer must be identical for the browser and for Django, otherwise
signature/issuer validation fails in Phase 1. Compose networking would let
Django reach Keycloak at `http://keycloak:8080`, but a browser on the Mac
cannot resolve that name.

So `KC_HOSTNAME` is set to the **browser-facing** URL, and Django uses the same
one — reachable from inside the container because the port is published on the
VM. Verified from all three vantage points:

```
browser (Mac)        -> http://192.168.2.3:8006  issuer matches
web container        -> http://192.168.2.3:8006  issuer matches
VM host (native venv)-> http://192.168.2.3:8006  HTTP 200
```

If the VM's address ever changes, update `KC_HOSTNAME` in
`docker-compose.override.yml` (the `nsr` script re-syncs `~/.ssh/config` but
not this).

## Deviation from ADR-0006 — `nsr-mis-web` is confidential

ADR-0006 specifies `nsr-mis-web` as a **public client using PKCE**, which
implies a browser app that holds tokens. It also names `mozilla-django-oidc`,
which is a **server-side** client where Django performs the code exchange and
issues its own session. Those are different architectures.

The 2026-08-08 decision was server-side, so this realm defines `nsr-mis-web`
as **confidential**. The consequence is that the console needs no changes at
all — it keeps using its existing same-origin session cookie, and the ~182
`request.user` references and ~148 test authentication call sites are
untouched.

When a built React SPA exists, add a *separate* public PKCE client to the same
realm. Nothing here blocks that.

## What is in the realm

- **Roles (10):** the 9 from ADR-0006 plus `connector:write` for service accounts.
- **Clients (7):** `nsr-mis-web` (confidential, browser login), `nsr-mis-api`
  (confidential, service account), `nsr-mis-capi` (public, PKCE + device flow),
  and four connector service accounts — `pdm`, `nusaf`, `wfp`, `nira`.
- **Protocol mappers:** `geographic_codes` and `partner_code` as user-attribute
  → claim mappers on `nsr-mis-web`. ADR-0006 flagged these as non-built-in;
  they are verified working — Keycloak's example-token endpoint emits
  `geographic_codes: ["national:"]` for `dev-coordinator`.
- **Token lifespans:** access 15 min, SSO idle 30 min, SSO max 10 h, per ADR-0006.
- **Brute force protection:** on, 3 failures — a down payment on US-064.

## Known gaps to settle before Phase 1

1. **Refresh-token lifespan.** ADR-0006 asks for 8 hours. Keycloak has no
   independent knob — refresh validity follows the SSO session
   (idle 30 min / max 10 h). The 8-hour figure is therefore *not* implemented
   as stated. Confirm the intent.
2. **Role catalogue.** These are ADR-0006's 9 roles. US-063's acceptance
   criteria name 18 roles and 8 permissions. Unresolved (scope note §2.2) —
   changing it later is a JSON diff, not a re-provisioning exercise.
3. **Redirect URIs** use a `http://192.168.*/oidc/callback/` wildcard so any
   LAN dev host works. Production must narrow these to the real hostname.
4. **Secrets in git.** The client secrets here are literal `dev-only-*` strings.
   Production must source them from the secrets manager, never this file.
