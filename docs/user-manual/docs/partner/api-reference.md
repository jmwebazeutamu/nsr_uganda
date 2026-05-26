# API reference

!!! info "Status"
    **Built and in use** for the surfaces below. The full OpenAPI 3.1 schema is generated from code and is always current.

You can do everything through the API that you can do through the partner portal. The portal calls the same endpoints.

## Live schema

| Where | URL |
|---|---|
| OpenAPI 3.1 JSON | `/api/schema/` |
| Swagger UI | `/api/docs/` |
| Module changelog | `/docs/api_changelog.md` |

`/api/docs/` is browsable without auth (developer convenience). Every actual endpoint requires `IsAuthenticated`.

## Authentication

OAuth 2.0 client credentials against the Keycloak `nsr-mis` realm. Your partner-side service account has the `connector:read` role and your partner-scoped roles.

```bash
curl -s -X POST \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=<your-client>&client_secret=<secret>" \
  https://auth.nita.go.ug/realms/nsr-mis/protocol/openid-connect/token
```

The response carries an `access_token` (15-min lifetime, RS256). Use it as `Authorization: Bearer <token>` against every endpoint.

For interactive use, log in to the console and the same session cookie works against `/api/docs/`.

## Pagination

Default page size 50, max 1000 (per [ADR-0008](../appendices/adrs.md)). Cursor pagination, not offset.

```
GET /api/v1/drs/requests/?cursor=cD0yMDI2LTA1LTIxKzExJTNBM
```

## Rate limits

Per [ADR-0008](../appendices/adrs.md). Tier defaults:

| Tier | Per-minute | Per-day |
|---|---|---|
| Partner read | 120 | 50 000 |
| Partner write (DRS submit) | 10 | 200 |
| Service account (connector) | 600 | 1 000 000 |

429 responses carry `Retry-After` in seconds.

## Endpoints you will use

### Partner

| Endpoint | Verb | What |
|---|---|---|
| `/api/v1/partners/me/` | GET | Your own Partner row |
| `/api/v1/partners/dsas/` | GET | Your DSAs |
| `/api/v1/partners/dsas/{id}/` | GET | One DSA with full scope |
| `/api/v1/partners/programmes/` | GET | Programmes your DSAs scope you to |
| `/api/v1/partners/dashboards/` | GET | Volume and request counts |

### DRS

| Endpoint | Verb | What |
|---|---|---|
| `/api/v1/drs/requests/` | GET | Your DataRequests, cursor-paged |
| `/api/v1/drs/requests/` | POST | Create a draft |
| `/api/v1/drs/requests/{id}/` | GET | One request with full payload |
| `/api/v1/drs/requests/{id}/` | PATCH | Edit a draft |
| `/api/v1/drs/requests/{id}/submit/` | POST | Submit a draft for review (validates against DSA) |
| `/api/v1/drs/requests/{id}/cancel/` | POST | Cancel a request before approval |
| `/api/v1/drs/requests/{id}/deliveries/` | GET | The files generated for this request |
| `/api/v1/drs/requests/{id}/deliveries/{delivery_id}/download_url/` | GET | A signed, short-lived download URL |
| `/api/v1/drs/requests/builder-schema/` | GET | The live field catalogue, including DSA-scoped grants |

### Reference data

| Endpoint | Verb | What |
|---|---|---|
| `/api/v1/reference-data/geographic-units/` | GET | UBOS hierarchy. Filter `?level=<level>&status=active&parent=<code>` |
| `/api/v1/reference-data/choice-lists/` | GET | ChoiceLists (income source, education level, etc.) |

## Example: submit a DataRequest

```bash
TOKEN=$(get_token)  # see Authentication

curl -s -X POST https://nsr.go.ug/api/v1/drs/requests/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MOH PMT extract Q2 2026",
    "purpose": "Routine programme planning per DSA-MOH-001",
    "dsa": "01HXYZ...",
    "format": "csv",
    "delivery": {"method": "portal"},
    "criteria": {
      "all_of": [
        {"leaf": "district", "in": ["101", "102"]},
        {"leaf": "pmt_band", "in": ["band_4", "band_5"]}
      ]
    },
    "fields": ["registry_id", "parish", "head_name", "pmt_band", "last_updated"]
  }'
```

Response:

```json
{
  "id": "01HZQR...",
  "status": "draft",
  "validation": {"errors": []},
  ...
}
```

Then:

```bash
curl -s -X POST https://nsr.go.ug/api/v1/drs/requests/01HZQR.../submit/ \
  -H "Authorization: Bearer $TOKEN"
```

## Errors

| Status | When |
|---|---|
| 400 | Payload invalid (schema or DSA validation) |
| 401 | Missing or expired token |
| 403 | Token valid, but the action is outside your ABAC scope |
| 404 | Resource not found (or hidden by ABAC) |
| 409 | State conflict (e.g. submit on an already-submitted request) |
| 429 | Rate-limited |
| 5xx | Server-side; retry with backoff |

Error bodies are RFC 7807 problem documents:

```json
{
  "type": "https://nsr.go.ug/errors/dsa-scope-violation",
  "title": "Geographic scope violation",
  "status": 400,
  "detail": "District code 105 is not in your DSA's geographic_scope.",
  "instance": "/api/v1/drs/requests/01HZQR.../submit/"
}
```

## Webhooks (Planned)

Webhook delivery is Planned for S6. You will register an HTTPS endpoint per DSA. We will POST a signed payload (Ed25519, header `X-NSR-Signature`) when a delivery is ready. Until then, poll `GET /api/v1/drs/requests/?status=delivered`.

## Related

- [DRS Query Builder](query-builder.md)
- [Partner portal](partner-portal.md)
- ADR-0008 — Pagination and throttling
- `/docs/api_changelog.md`
