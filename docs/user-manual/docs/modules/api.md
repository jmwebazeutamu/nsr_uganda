# API — Gateway

!!! info "Status"
    **Built and in use** — versioned API surface, drf-spectacular OpenAPI 3.1, OAuth client credentials (DRF auth), per-module routers.

API is the cross-cutting surface every other module mounts under. Kong (or APISIX) sits in front of Django in production; this app holds the in-process surface.

## What it does

Mounts per-module DRF routers under `/api/v1/<module>/`. Generates the OpenAPI schema. Surfaces the Swagger UI. Provides the global authentication and permission defaults.

## Where it lives

| Path | What |
|---|---|
| `apps/api_gateway/` | Django app (mostly cross-cutting config) |
| `nsr_mis/urls.py` | Module router mounts |
| `nsr_mis/settings.py` | DRF defaults |

## Public endpoints

| Endpoint | Purpose |
|---|---|
| `/api/schema/` | OpenAPI 3.1 JSON (browsable, no auth) |
| `/api/docs/` | Swagger UI (browsable, no auth) |
| `/api/v1/<module>/...` | Per-module routers |

## Authentication

| Path | Default |
|---|---|
| Console | Session cookie (Django) |
| API for partners | OAuth 2.0 client credentials against Keycloak `nsr-mis` realm |
| Connector bots | Service-account JWTs |

## Per-module mounts

See `nsr_mis/urls.py`. Every module ships its own OpenAPI tag.

## ADRs

- [ADR-0008](../appendices/adrs.md) — Pagination and throttling

## Stories

US-041, US-042, US-043, US-044, US-045, US-046.
