# API-DRS — Data Request Service

!!! info "Status"
    **Partial** — External requester baseline (Partner / DSA / DataRequest), steward review path, partner-side ABAC, Query Builder UI, FieldSelector V2, geographic-scope validation at every UBOS level. Delivery slices (US-099 to US-104) partially built; full webhook + signed delivery Planned for S6.

DRS is the outbound surface MDA partners use to extract data from the Registry.

## What it does

Lets a partner build a data request through the Query Builder. Validates the request against the partner's active DSA. Routes to the steward queue. Routes to DPO if sensitive / large. Generates the file in the chosen format. Delivers via portal or webhook.

## Where it lives

| Path | What |
|---|---|
| `apps/data_requests/` | Django app |
| `/api/v1/drs/` | DRF surface |
| `/design/v0.1/screens/screens-drs*.jsx` | Wizard + Field Selector + Preview |

## Endpoints

See [API reference](../partner/api-reference.md) for the full list. Highlights:

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/drs/requests/` | GET, POST | List, create draft |
| `/api/v1/drs/requests/{id}/submit/` | POST | Validate against DSA, route to review |
| `/api/v1/drs/requests/{id}/approve/` | POST | Steward approval; emails partner + requester |
| `/api/v1/drs/requests/{id}/reject/` | POST | Steward rejection with reason; emails both |
| `/api/v1/drs/requests/{id}/deliver/` | POST | Mark DELIVERED with manifest SHA + row count; emails both |
| `/api/v1/drs/requests/builder-schema/` | GET | Live field catalogue |
| `/api/v1/drs/requests/{id}/deliveries/` | GET | Generated files |

## Key entities

- `DataRequest`
- `Delivery`
- `BuilderSchema` (field catalogue, generated)

## Email notifications (v0.3)

Each lifecycle transition emails the partner contact + the request requester. Recipients: `dsa.partner.primary_email` + `DataRequest.requester`.

| Transition | Subject | Includes |
|---|---|---|
| `approve_data_request` | `Data request <id>… approved` | Approver, DSA reference, "delivery email follows" |
| `reject_data_request` | `Data request <id>… REJECTED` | Verbatim reason |
| `deliver_data_request` | `Data extract ready · <id>… · <N> rows` | **Manifest SHA-256**, row count, expiry timestamp, integrity-check guidance |

The delivery email is the partner's primary delivery channel until the webhook lands. Verify the bundle against the manifest SHA-256 before processing — any mismatch indicates tampering in transit; report to the DPO.

Every notification attempt is audited (`data_request.approved.notified` / `.rejected.notified` / `.delivered.notified`). When `Partner.primary_email` is empty, the helper writes a `notification.skipped` audit row instead so DPO can reconcile gaps in partner contact data.

## Validation

Per US-S27-016 (2026-05-21): `validate_against_dsa` walks `_GEO_PAYLOAD_KEYS` and rejects extras at every UBOS level (region, sub-region, district, county, sub-county, parish, village). The DSA's `geographic_scope` M2M may carry rows at any level. Each level is enforced independently.

## ADRs

- [ADR-0011](../appendices/adrs.md) — Partners module (DRS scope edges)
- [ADR-0016](../appendices/adrs.md) — DSA scope edit and renewal

## Stories

US-052, US-053, US-054, US-055, US-056, US-057, US-097, US-098, US-099, US-100, US-101, US-102, US-103, US-104, US-S27-013, US-S27-014, US-S27-016.
