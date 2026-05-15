# ADR-0006: Keycloak realm design (unblocks US-S2-002)

- **Status**: Accepted (Sprint 7: design landed; provisioning + code wiring deferred)
- **Date**: 2026-05-15
- **Owner**: NSR MIS Architecture Team
- **References**: SAD v0.6 §8.2 (ABAC), §8.3 (authentication), `/CLAUDE.md` tech stack (Keycloak OIDC + SAML), ADR-0001 (modular monolith)

---

## Context

CLAUDE.md locks Keycloak as the auth provider — OIDC for first-party
operators (NSR Unit, CDO, parish chief, enumerator, DPO, SA) and SAML
federation for partner MDAs (PDM, NUSAF, WFP, NIRA). US-S2-002 was
queued in Sprint 2 to wire Keycloak end-to-end but immediately blocked
on "Keycloak realm not provisioned." Five sprints later the realm
itself is still unprovisioned, but the open question of *what shape*
the realm should take has hardened — every story that touched ABAC
(S2-003 sub-region scope, S4-001 partner scope) had to commit to a
role catalogue without naming it.

This ADR records the realm design so the eventual provisioning ticket
has nothing to invent, and so the code can stop referring to
"OperatorScope as a placeholder for Keycloak claims" in scattered
docstrings.

---

## Decision

A single `nsr-mis` realm, with:

### Realm topology

| Setting | Value | Why |
|---|---|---|
| Realm name | `nsr-mis` | Single source of truth across console + API + CAPI |
| Login theme | NSR MIS branded | Operator confidence + brand consistency |
| Token signature | RS256 | DRF + Django simplejwt both expect asymmetric |
| Access-token lifespan | 15 min | Short enough that revocation is cheap; matches NITA-U baseline |
| Refresh-token lifespan | 8 hours | One working day; forces overnight re-auth |
| SSO session idle | 30 min | Per SAD §8.3.2 idle-timeout requirement |
| SSO session max | 10 hours | Per SAD §8.3.2 hard session cap |

### Clients

| Client ID | Type | Use |
|---|---|---|
| `nsr-mis-web` | Public (PKCE) | The React console |
| `nsr-mis-api` | Confidential | The Django backend (service-to-service introspection) |
| `nsr-mis-capi` | Public (PKCE + device flow) | CAPI tablets — device flow lets the offline UI bootstrap an operator without a browser |
| `nsr-mis-import-bots` | Confidential (service accounts only) | One per partner connector (PDM, NUSAF, WFP, NIRA-reverse), each with the narrow `connector:write` role |

### Role catalogue

Seven first-party roles + two partner-facing roles. Roles are realm-level
(not client-level) so a single token carries every role the user holds,
and Django can map each to behaviour via OperatorScope rows and
`is_staff` / `is_superuser` derivations.

| Role | Maps to (in Django) | Visibility surface |
|---|---|---|
| `NSR_UNIT_COORDINATOR` | `is_superuser=True` + `ScopeLevel.NATIONAL` | Everything; the unblock-everyone-else role |
| `DPO` | `ScopeLevel.NATIONAL` + `is_staff=True` | Audit chain + DPIA actions; CAN see across geographies but NOT write |
| `SA` | `is_superuser=True` | System administration; bypasses ABAC |
| `CDO` | `ScopeLevel.DISTRICT` | Their district's data + GRM L2 |
| `PARISH_CHIEF` | `ScopeLevel.PARISH` | Their parish's data + GRM L1 |
| `FIELD_ENUMERATOR` | `ScopeLevel.PARISH` | Their parish's data only; can submit but not approve |
| `DISTRICT_M_AND_E` | `ScopeLevel.DISTRICT` | Same scope as CDO but routed for UPD escalation (S7-001) |
| `PARTNER_ANALYST` | `ScopeLevel.PARTNER` (scope_code = Partner.code) | Their partner's DSAs + DataRequests only (S4-001, S7-004) |
| `PARTNER_DPO` | `ScopeLevel.PARTNER` + `is_staff=True` | Read-only across their partner's data; for the partner's own DPIA |

### SAML federation

Partner MDAs federate their existing AD/IdM into the `nsr-mis` realm via
SAML 2.0. Per-partner identity provider config:

- **Mapper**: SAML `eduPersonAffiliation` attribute → realm role
  `PARTNER_ANALYST` or `PARTNER_DPO`.
- **Mapper**: SAML `eduPersonOrgDN` → custom realm attribute
  `partner_code` (e.g., "PDM", "NUSAF") which Django reads into
  OperatorScope at first login.

NIRA does NOT federate (NIRA pushes events at us via service-account
token; no human user from NIRA logs into the NSR console).

### JWT → OperatorScope mapping

On first OIDC sign-in, the Django auth backend (a thin wrapper around
mozilla-django-oidc) does the following in order:

1. Resolve / create the Django User (`username = preferred_username`).
2. For each realm role in the access token's `realm_access.roles`:
   - If the role implies `NATIONAL` scope, ensure an active
     `OperatorScope(user, NATIONAL, "")` row exists.
   - If the role implies a geographic level (PARISH / DISTRICT),
     read the JWT's `geographic_codes` custom claim (list of dotted
     paths like `parish:KAMPALA-CENTRAL-MENGO`) and ensure the matching
     OperatorScope rows exist.
   - If the role is `PARTNER_*`, read the `partner_code` custom claim
     and ensure an `OperatorScope(user, PARTNER, partner_code)` exists.
3. Update `is_superuser` and `is_staff` per the role table above.
4. Set `last_login = timezone.now()`.

Scopes that exist in the DB but not in the current token are NOT
deactivated automatically — leaving a stale scope active means a
revoked role still blocks a user until the next sweep. **DPO action**:
confirm whether this is acceptable (recommended: yes, with a daily
sync task that deactivates dropped scopes).

### What the code change looks like (out of scope for this ADR)

When the realm lands, US-S2-002 implements:

- `nsr_mis/settings.py`: register `mozilla_django_oidc.auth.OIDCAuthenticationBackend`
  in `AUTHENTICATION_BACKENDS`; OIDC settings (issuer, client id, etc.)
  read from env.
- A new `apps.security.oidc` module: the auth-backend subclass that
  performs the JWT → OperatorScope mapping above.
- Tests: realm-role JWT parsing, scope provisioning idempotency,
  superuser/staff derivation, partner-code mapping.

No code change in this ADR; just the design.

---

## Alternatives considered

### A. Multiple realms (one per stakeholder)

Pros: hard tenant isolation, simpler per-realm theme + branding.
Cons: cross-realm SSO via brokered IdP is a config nightmare, and the
NSR Unit + partner-analyst use cases share enough of the console that
splitting realms would force per-realm token exchange just to load the
landing page. Rejected.

### B. Client-level roles instead of realm-level

Pros: more granular — a single user could have different roles per
client (e.g., NSR Unit role only when hitting the console, not when
hitting the partner API).
Cons: every viewset has to introspect *which client* the token was
issued for; OperatorScope already encodes the geography + partner
affiliation, which is the only dimension that matters operationally.
Rejected.

### C. Skip Keycloak and use Django's built-in auth + JWT

Pros: one less service to operate; no NITA-U dependency.
Cons: CLAUDE.md tech stack locks Keycloak; partner MDAs already run
their own AD/IdM and SAML federation is the only realistic path that
doesn't require manually provisioning 200+ partner-analyst accounts;
audit + session-management requirements from SAD §8.3 are
Keycloak's bread and butter, not Django's. Rejected.

---

## Consequences

### Positive

- US-S2-002 has a complete spec to execute against — no ambiguity left.
- ABAC code (apps.security.abac) doesn't change: the same
  OperatorScope rows continue to drive every viewset; only the
  *provisioning* source flips from manual admin to JWT-driven.
- Service accounts for each connector mean DIH writes can be
  attributed to a specific partner (better audit) without
  hand-rolling a per-connector secret.

### Negative

- One more environment-specific service to keep healthy at NITA-U.
  Mitigation: the existing observability stack (OpenTelemetry +
  Prometheus per CLAUDE.md) already covers it.
- SAML federation requires per-partner IdP metadata exchange — a
  multi-week onboarding flow per partner. Mitigation: the
  service-account connector path stays available, so import-bot
  partners (PDM/NUSAF/WFP/NIRA) don't need the human-user federation
  to be in place before their data starts flowing.
- The `geographic_codes` custom JWT claim isn't a Keycloak built-in;
  it has to be populated via the per-realm "User Attribute" mapper
  pointing at a custom user attribute. Documented; not novel.

### Risks

- The role catalogue is opinionated. If MGLSD adds new operational
  roles (e.g., a "MOBILE_MONEY_AUDITOR" cross-cutting view), the
  catalogue needs a new row + a new ABAC mixin pattern. Mitigation:
  any new role triggers a new ADR.
- `last_login` updates on every token refresh add row-update
  pressure to the auth_user table. Mitigation: cap the touch to
  once-per-hour per user (post-MVP optimisation).

---

## Status notes

This ADR unblocks **US-S2-002 (Keycloak OIDC + role catalogue)**. The
remaining external dependency is operational, not architectural:
NITA-U's GDC Keycloak realm provisioning + the per-partner SAML IdP
metadata exchange.

The OperatorScope model, ABAC mixin family (5 patterns from S2-003 +
S4-001), and partner-scope work (S4-001, S7-004) all stand without
change when this ADR's implementation lands — they were designed
against the role catalogue documented here.
