# RPT — Reporting

!!! info "Status"
    **Built and in use** — coverage, PMT bands, pipeline funnel, DRS status, dedup status, DQA violation downloads, weekly trends, export controls, SLA breach dashboard.

RPT is the dashboard pack. Read-only aggregate queries against scoped data. Every dashboard read writes an `AuditEvent` so the anomaly feed sees who is pulling what.

## What it does

Reads from DAT, DQA, GRM, partners, ingestion_hub. Aggregates. Applies the requesting user's ABAC scope **before** aggregating so a sub-region operator never sees national totals. Renders JSON for the React console; supports `?export=csv`.

## Where it lives

| Path | What |
|---|---|
| `apps/reporting/` | Django app |
| `apps/reporting/views.py` | Plain `APIView` dashboards (not ModelViewSets) |
| `/api/v1/rpt/` | DRF surface |
| `/design/v0.1/screens/screens-reporting.jsx` | Reporting console |

## Dashboards

| Dashboard | What |
|---|---|
| Coverage | Households per sub-region |
| PMT bands | Distribution |
| Pipeline funnel | DIH staged → quarantined → review → promoted |
| DRS status | Partner requests by state |
| Dedup status | Open candidates, recent merges |
| DQA violations | Open violations, downloads |
| Weekly trends | Registrations and submissions |
| SLA breach | UPD and GRM aging |
| GRM by category | Lifecycle counts |

## Audit emission

Every dashboard read emits one `AuditEvent` with `action=dashboard_read`, the dashboard code, and the bucket count. Cheaper than per-row reads; still gives the anomaly feed a signal.

## Stories

US-047, US-048, US-049, US-050, US-051, US-095.
