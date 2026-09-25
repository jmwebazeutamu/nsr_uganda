# PMT — Proxy Means Test

!!! info "Status"
    **Built and in use** — engine, feature evaluator, sign-off workflow, band threshold, v1 active seed, recompute on commit. Calibrated weights pending DEP-03 / DEP-04.

PMT scores every household for eligibility. Runs **only in the registry**, never in DIH. Triggers immediately after promotion or a committed UPD.

## What it does

Reads the household and its detail entities. Evaluates the registered feature set. Computes a continuous score, then maps the score to a band. Writes the band to the Household and queues notifications to downstream consumers (REF, RPT).

## Where it lives

| Path | What |
|---|---|
| `apps/pmt/` | Django app |
| `/api/v1/pmt/` | DRF surface |
| `/design/v0.1/screens/screens-pmt-dashboard.jsx`, `screens-pmt-configuration.jsx` | PMT dashboards and config |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/pmt/model-versions/` | GET | The versioned PMT formulae |
| `/api/v1/pmt/model-versions/{id}/` | GET | One version |
| `/api/v1/pmt/model-versions/current/` | GET | The version currently scoring |
| `/api/v1/pmt/results/` | GET | Scores, ABAC-scoped |
| `/api/v1/pmt/results/{id}/` | GET | One score with its inputs snapshot |
| `/api/v1/pmt/results/recompute/{household_id}/` | POST | Re-score one household |

!!! warning "The endpoints on this page were wrong"
    It listed `/api/v1/pmt/model-versions/`,
    `/api/v1/admin/pmt/versions/{id}/` and
    `/api/v1/pmt/results/recompute/{household_id}/`. None of those exists — the
    resources are `model-versions` and `results`. Corrected
    25 September 2026.

## Sign-off lifecycle

Three-step chain per model version: **Author (step 1, pre-signed by submitting) → MGLSD Steward (step 2) → UBOS DG (step 3)**. Each step is recorded as a `PMTModelSignOff` row and an `AuditEvent`. When step 3 lands, `activate_model_version` flips the version to ACTIVE and retires any prior active.

Rejection is **terminal**. A rejected `PMTModelVersion` stays REJECTED — sign-offs and the audit row are preserved, but the version is hidden from the default operator list. The author must clone a fresh DRAFT to revise. (Earlier rejections rolled back to DRAFT, which muddied the audit chain.)

### Email notifications (v0.3)

| Transition | Recipient(s) |
|---|---|
| `submit_for_approval` | MGLSD Steward (step 2) |
| `sign_step` (not last) | Next pending signer |
| `sign_step` (final) | Author + every prior signer with "model ACTIVE" confirmation |
| `reject_step` | Author with verbatim reason |

Every notification is itself audited (`pmt.signoff.notified` / `pmt.activation.notified` / `pmt.rejection.notified`). SMTP failures audit as `notification.failed` and never roll back the workflow.

## PMT Dashboard

Read-only operational view at `/admin-console/#admin-pmt-dashboard`. The dashboard fetches `/api/v1/admin/pmt/dashboard/` on mount; the eyebrow chip shows **LIVE** when the payload returned, **MOCK PREVIEW** when the fetch fell back (file:// preview, 401, no active model), and **loading…** during fetch.

### Empirical Thresholds card

Shows the score-threshold per band — the values that classify a household. Source: `PMTBandThreshold` table, latest row per band.

Threshold values are recomputed by `apps.pmt.tasks.recompute_band_thresholds` against the active model's PMTResult population:

1. Read `band_cutoffs` from the active model (e.g. `{extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100}` — these are **percentile ranks**, not score values).
2. Sort every `PMTResult.score` for the active model.
3. For each band, compute the score at the given percentile rank using linear interpolation between sorted neighbours (`numpy.percentile(..., interpolation="linear")` reimplemented in stdlib).
4. Append one `PMTBandThreshold` row per band; emit one `AuditEvent` per write.

The Run-now button triggers `recompute_dashboard_snapshots`, which (since v0.3) recomputes the threshold pass too — earlier it only refreshed snapshot tables, so the Empirical Thresholds card could stay stale even after Run-now until the next 02:00 EAT Celery beat. Now: one click, everything fresh.

### Downloadable run report

After a successful Run-now the dashboard shows two buttons next to Run now:

- **Report (CSV)** — downloads `pmt-recompute-<run_id>.csv` with four sections: run metadata, active-model context, thresholds written, distribution summary (n / min / p25 / median / p75 / max).
- **JSON** — opens the same payload as structured JSON in a new tab.

Operators attach the CSV to audit / sign-off tickets when triggering ad-hoc recomputes.

## Key entities

- `PMTResult` — historical chain of scores per household
- `PMTModelVersion` — versioned model weights and thresholds
- Feature registry under `apps/pmt/registered_features.py`

## Trigger surface

| Trigger | Source |
|---|---|
| Promotion | DIH commits a new Household |
| Change | UPD commits a ChangeRequest |
| Vital event | NIRA delivers a member change |
| Periodic recompute | Celery beat (per SLA in SAD §6) |

## ADRs

- [ADR-0020](../appendices/adrs.md) — FIES / FCS computed columns (feeds PMT features)

## Stories

US-022, US-023, US-024, US-025, US-026.
