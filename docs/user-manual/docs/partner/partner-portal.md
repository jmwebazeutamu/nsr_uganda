# Partner portal

!!! info "Status"
    **Built and in use** — partner-side DRS list, request detail, and download surface live (US-S3-002 baseline, partner-side ABAC US-S4-001, dashboards US-S7-004 / US-S8-003 / US-S9-003).

The partner portal is your view into NSR. It is the same React console operators use, scoped to your partner code by ABAC.

## Where to find it

| Surface | Path |
|---|---|
| Console URL | `/console/partner` |
| Source JSX | `/design/v0.1/screens/screens-partner-drs.jsx → PartnerDRSScreen` |
| Detail screen | `/design/v0.1/screens/screens-partner-detail.jsx → PartnerDetailScreen` |
| API | `/api/v1/partners/dashboards/`, `/api/v1/drs/requests/` |

## What you see

| Tab | Contents |
|---|---|
| **My requests** | Every DataRequest you have ever submitted, with status |
| **Drafts** | Half-built requests, resumable |
| **Deliveries** | The files generated for you, with download buttons |
| **DSAs** | Your DSA scope, expiry, and renewal status |
| **Activity** | The audit timeline scoped to your partner |

## Request states

| State | What it means for you |
|---|---|
| `draft` | You are still building it |
| `submitted` | In the steward queue |
| `pending_steward` | A steward is reviewing scope and intent |
| `pending_dpo` | A DPO is reviewing for sensitive / large extracts |
| `approved` | About to generate the file |
| `generating` | File generation in progress |
| `delivered` | Ready to download |
| `rejected` | Steward or DPO declined, with reason |
| `expired` | Delivered but the download window closed |

## Downloads

| Format | Notes |
|---|---|
| CSV | Default. Newline-delimited. UTF-8. |
| XLSX | Single sheet, headers in row 1 |
| JSON Lines | One record per line |
| Parquet | (Planned) S6 |
| Webhook push | (Planned) S6 — you register an HTTPS endpoint and we POST signed payloads |

## Download links expire

Download URLs are short-lived (24 h default). You can re-issue from the delivery row. Every issued URL writes a `download_url_issued` AuditEvent.

## Volume gauges

The dashboard shows a monthly gauge against your DSA's `volume_cap_per_month`. Submitting past the cap is rejected. The cap is enforced by row count, not file size.

## Related

- [DRS Query Builder](query-builder.md)
- [Data Sharing Agreement (DSA)](dsa.md)
- [API reference](api-reference.md)
