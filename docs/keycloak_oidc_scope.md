# Keycloak / OIDC — implementation scope

**Date:** 2026-08-08
**Status:** scoping note for discussion — no decision taken, no code written
**Against:** `692980c`
**Reads:** ADR-0006 (Keycloak realm design, Accepted 2026-05-15), SAD §8.2–8.3,
US-063 / US-064 / US-065, DEP-01, DEP-25

---

## 1. This is execution, not design

ADR-0006 is **Accepted** and already specifies the realm topology, the four
clients, a nine-role catalogue with its Django mapping, the SAML federation
mappers, and the exact JWT → `OperatorScope` provisioning algorithm. It even
names the library (`mozilla-django-oidc`). Its own status line is
*"design landed; provisioning + code wiring deferred."*

Nothing has been implemented:

| | state |
|---|---|
| OIDC/JWT dependency | **absent** from `pyproject.toml` |
| `apps/security/oidc.py` | **does not exist** |
| Auth in use | `SessionAuthentication` + `BasicAuthentication` |
| Console auth | `credentials: "same-origin"` — plain Django session cookie, no token handling anywhere |

**The single most important fact for sizing:** ABAC does not change. ADR-0006
designed `OperatorScope` against this role catalogue, so every viewset, all
five scope-mixin patterns and the single-entity helpers keep working
unmodified. Only the *provisioning source* flips from hand-entered admin rows
to JWT claims. Likewise, the recent actor fix means all 30 state transitions
already read `request.user` — that prerequisite is now satisfied rather than
being part of this work.

---

## 2. Two problems in ADR-0006 to resolve before starting

### 2.1 The client model contradicts the library choice

ADR-0006 specifies `nsr-mis-web` as a **public client using PKCE** — that is a
browser app running the authorization-code flow and holding tokens itself. But
it also names **`mozilla-django-oidc`**, which is a *server-side* OIDC client:
Django performs the code exchange and logs the user into a normal Django
session. Those are two different architectures and the ADR asks for both.

It matters a lot for cost:

- **Server-side (Django is the OIDC client).** The console needs **zero**
  changes — it keeps sending `credentials: "same-origin"`. All 182
  `request.user` references and all 148 `force_authenticate` / `client.login`
  test call sites keep working. Small, low-risk.
- **SPA token flow.** The console must acquire, store, refresh and attach
  tokens. It is currently a Babel-standalone harness served by Django, not a
  built SPA — so this presumes a frontend build that does not exist yet.

**Recommendation: server-side.** It matches the library already chosen,
requires no frontend work, and does not block the SPA later — a public PKCE
client can be added to the same realm when a built console exists.

### 2.2 The role catalogue does not match the backlog

ADR-0006 defines **9 roles**. US-063's acceptance criteria list **18 named
roles and 8 named permissions** from the TOR. The codebase currently has
**4 Django Groups** (`nsr_admin`, `GRM Officer`, `EXPLORER`,
`Data Protection Officer`) — and US-063 is nonetheless marked *Done* in the
tracker.

Provisioning a realm against the wrong catalogue means re-provisioning. This
needs reconciling **first**, and it is a stakeholder question (MGLSD roles),
not an engineering one.

---

## 3. What is actually blocked externally — and what is not

DEP-01 (NITA-U tenancy) is *Open* and often read as blocking this work. It is
not.

Keycloak is a container. The realm can be **committed as a realm-export JSON**
and imported at start-up, which makes it reviewable, diffable and reproducible.
Everything except the production realm can be built and tested locally with no
NITA-U involvement.

| item | blocked? | by |
|---|---|---|
| Dev/CI realm, all code, all tests | **No** | — |
| Staging realm | **No** | — |
| Production realm | Yes | DEP-01 (NITA-U GDC procurement) |
| Per-partner SAML federation | Yes, per partner | partner IdP metadata exchange |
| Citizen-portal realm | Deferred | DEP-25 (Release 3) |

So: build now, cut over when NITA-U lands. Only the last mile waits.

---

## 4. Proposed phases

Sizes are rough and assume the server-side decision in §2.1.

### Phase 0 — decisions + realm as code *(small)*
Resolve §2.1 and §2.2. Add a `keycloak` service to `docker-compose.yml` with a
committed realm export; document the realm in the runbook. No application code.
*Exit:* `docker compose up` gives a working realm; `nsr` script starts it.

### Phase 1 — browser login *(medium — the core)*
`mozilla-django-oidc` in `AUTHENTICATION_BACKENDS`; new `apps/security/oidc.py`
implementing ADR-0006 §"JWT → OperatorScope mapping" (resolve/create user, map
realm roles to `OperatorScope` rows, derive `is_staff`/`is_superuser`). Keep
`SessionAuthentication` so the existing test suite is unaffected.
*Exit:* operators log into `/admin/` and `/console/` through Keycloak; scopes
provision from claims; tests green unchanged.
*Risk:* the `geographic_codes` custom claim is not a Keycloak built-in — it
needs a user-attribute mapper. ADR-0006 flags this; verify early.

### Phase 2 — machine clients *(medium)*
A DRF authentication class validating bearer JWTs, for CAPI and the
`nsr-mis-import-bots` service accounts. This is a *separate* mechanism from
Phase 1's browser flow, feeding the same `request.user` + `OperatorScope`.
Retire `BasicAuthentication` here.
*Exit:* connectors authenticate as their own service account, so DIH writes
attribute to a specific partner.

### Phase 3 — account hygiene + roles *(small, high value)*
**US-064 comes almost free**: password rotation, 3-strike lockout, 60-day
inactivity disable, MFA for privileged roles, CAPTCHA are all Keycloak *realm
settings*, not code. A Must story closed by configuration. Finish the US-063
catalogue per §2.2 in the same pass.

### Phase 4 — SAML federation *(per partner, externally gated)*
Per-partner IdP metadata exchange plus the two mappers in ADR-0006. Multi-week
per partner, and independent of the rest — the service-account path in Phase 2
means partner *data* keeps flowing without it.

### Phase 5 — production cutover *(gated on DEP-01)*
Provision at NITA-U from the same realm export, migrate existing operator
accounts, keep a break-glass Django superuser.

---

## 5. Decisions needed

1. **Console auth model** — server-side session (recommended) or SPA tokens?
2. **Role catalogue** — reconcile ADR-0006's 9 against US-063's 18. Stakeholder call.
3. **Self-host the dev/staging realm now**, or wait for NITA-U? (Recommend now.)
4. **Stale scopes** — ADR-0006 leaves an explicit *DPO action*: when a role
   disappears from a token, should the `OperatorScope` row deactivate
   immediately, or on a daily sweep? ADR recommends the sweep. Needs DPO sign-off.
5. **Break-glass** — keep one local Django superuser for when Keycloak is down?
   (Recommend yes; document it in the runbook and audit its use.)

## 6. Risks

- **Single point of failure.** Keycloak down = nobody logs in. Mitigation:
  break-glass account, plus the existing health-check/observability path.
- **Test-suite coupling.** 148 `force_authenticate` / `client.login` sites.
  Keeping `SessionAuthentication` means they are untouched — but if the SPA
  route in §2.1 is chosen instead, expect churn here.
- **Realm drift.** A realm configured by hand in the Keycloak UI diverges from
  the repo. Mitigation: realm export is the source of truth, imported on start;
  treat UI changes as you would an undocumented migration.
- **Re-provisioning cost** if §2.2 is not settled first.

## 7. What this does *not* cover

Citizen-portal identity (DEP-25, Release 3), NIRA (service-account push, no
human login), rate limiting, and the impersonation guard's interaction with
OIDC sessions — worth a look during Phase 1.
