# Keycloak and access

!!! info "Status"
    **Scaffolded** — the realm design is locked ([ADR-0006](../appendices/adrs.md)), the role catalogue and OperatorScope tables are wired. Live Keycloak provisioning is Planned for Sprint 8 once the NITA-U realm is created.

Keycloak is the auth provider for the NSR MIS. OIDC for operators, SAML federation for partner MDAs.

## The realm

One realm: `nsr-mis`.

| Setting | Value |
|---|---|
| Realm name | `nsr-mis` |
| Token signature | RS256 |
| Access-token lifespan | 15 min |
| Refresh-token lifespan | 8 hours |
| SSO session idle | 30 min |
| SSO session max | 10 hours |

## Clients

| Client ID | Type | Use |
|---|---|---|
| `nsr-mis-web` | Public (PKCE) | React operator console |
| `nsr-mis-api` | Confidential | Django backend (service-to-service introspection) |
| `nsr-mis-capi` | Public (PKCE + device flow) | CAPI tablets (offline bootstrap) |
| `nsr-mis-import-bots` | Confidential (service accounts) | One per partner connector (PDM, NUSAF, WFP, NIRA-reverse), each with `connector:write` |

## Roles

Realm-level roles. A single token carries every role the user holds.

| Role | Maps to in Django | Visibility |
|---|---|---|
| `NSR_UNIT_COORDINATOR` | `is_superuser=True`, scope NATIONAL | Everything; the unblock-everyone role |
| `SOCIAL_REGISTRY_MANAGER` | scope NATIONAL | Approval-focused persona. Sees the unified Approvals queue (CL / DQA / PMT) + bulk DRS dual-approval. Designed for testing AC-UPD-NO-SELF-APPROVE flows without swapping accounts. |
| `DPO` | `is_staff=True`, scope NATIONAL | Audit chain + DPIA; reads only |
| `SA` | `is_superuser=True` | System administration; bypasses ABAC |
| `CDO` | scope DISTRICT | District data + GRM L2 |
| `PARISH_CHIEF` | scope PARISH | Parish data + GRM L1 |
| `FIELD_ENUMERATOR` | scope PARISH | Submit only, no approve |
| `DISTRICT_M_AND_E` | scope DISTRICT | Same scope as CDO, different routing for UPD escalation |
| `PARTNER_ANALYST` | scope PARTNER (Partner.code) | Their partner's DSAs and DataRequests |
| `PARTNER_DPO` | scope PARTNER, `is_staff=True` | Read-only across their partner's data |

The Tweaks panel in the design preview also offers a **Render as** dropdown matching these role values. Picking one switches the home dashboard persona, KPI cards, and queue projections — it does NOT change the authenticated session (the server still enforces ABAC against whoever is actually logged in via `/admin/`).

## SAML federation for partner MDAs

Each partner federates their existing AD or IdM into the realm via SAML 2.0.

- **Affiliation mapper**: `eduPersonAffiliation` → realm role `PARTNER_ANALYST` or `PARTNER_DPO`.
- **Organisation mapper**: `eduPersonOrgDN` → custom realm attribute that resolves to `Partner.code`.

Per-partner config lives in the realm export under `/infrastructure/keycloak/realm-nsr-mis.json` (Planned — currently in ADR-0006 only).

## Wiring it into Django (when the realm exists)

The DRF auth class lookup is already wired:

```python
# nsr_mis/settings.py (already in place)
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        # OIDC class lands here when the realm is provisioned
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}
```

The pending change adds `mozilla_django_oidc` (or `django-oauth-toolkit`) with the realm URLs in env vars:

| Variable | Example |
|---|---|
| `OIDC_RP_CLIENT_ID` | `nsr-mis-api` |
| `OIDC_RP_CLIENT_SECRET` | KMS |
| `OIDC_OP_AUTHORIZATION_ENDPOINT` | `https://auth.nita.go.ug/realms/nsr-mis/protocol/openid-connect/auth` |
| `OIDC_OP_TOKEN_ENDPOINT` | `https://auth.nita.go.ug/realms/nsr-mis/protocol/openid-connect/token` |
| `OIDC_OP_USER_ENDPOINT` | `https://auth.nita.go.ug/realms/nsr-mis/protocol/openid-connect/userinfo` |
| `OIDC_OP_JWKS_ENDPOINT` | `https://auth.nita.go.ug/realms/nsr-mis/protocol/openid-connect/certs` |

## Until then: Django superuser + session auth

While Keycloak is unprovisioned, you log in to the console using a Django superuser with session cookies. The Swagger UI at `/api/docs/` accepts the same session.

```bash
python manage.py createsuperuser
```

This is fine for dev. It is not acceptable for pilot or production.

## OperatorScope (the ABAC table)

Every operator has zero or more `OperatorScope` rows. ABAC narrows querysets to rows where the operator's scope intersects the row's geographic hierarchy.

```python
# apps/security/abac.py
scope_q_for_field("sub_region", request.user)
```

For Partner operators, the scope is the partner code, not a geography. See [ADR-0011](../appendices/adrs.md) for the partner-side ABAC details.

## Related

- ADR-0006 — Keycloak realm design
- ADR-0011 — Partners module ABAC
- `apps/security/abac.py` — the queryset narrower
- [Reference data loaders](reference-data.md) — operator-scope seed if you need test users
