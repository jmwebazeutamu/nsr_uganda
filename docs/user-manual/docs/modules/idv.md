# IDV — Identity Verification

!!! info "Status"
    **Partial** — NIRA client seam in place; vital-event auto-commit policy live (US-S3-003). Live MoU + sandbox toggle pending (DEP-02 in SAD §12).

IDV verifies operator-claimed identities against NIRA and processes inbound vital events from NIRA.

## What it does

Two paths:

1. **Verify** — given a NIN, ask NIRA for the corresponding identity. Cache, decode, and surface the result against the Member record.
2. **Reverse stream** — receive birth and death notifications from NIRA via the `nira_vital` DIH connector. Auto-commit the corresponding Member updates with `committed_by=system`.

## Where it lives

| Path | What |
|---|---|
| `apps/identity_verification/` | Django app |
| `/api/v1/idv/nira-mock/verify` | DRF surface |
| `apps/ingestion_hub/connectors/nira_vital.py` | The inbound connector |
| `scripts/sandbox NIRA mock` (per CLAUDE.md §11.4 item 9) | Dev sandbox |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/idv/nira-mock/verify` | POST | The sandbox NIRA responder (SAD §11.4 item 9) |

!!! danger "There is no live IDV API yet"
    This page used to list `/api/v1/idv/nira-mock/verify` and
    `/api/v1/idv/nira-mock/verify`. **Neither exists.** The only route the
    module serves is the sandbox mock above.

    Verification logic exists in `apps/identity_verification/` and is
    called in-process; it is not exposed over HTTP. If you have built
    an integration against the endpoints this page used to list, it has
    never worked. Corrected 25 September 2026 by resolving every path
    in this manual against the URLconf.

## Key entities

- `NiraVerificationAttempt` — one row per verification attempt.
- A NIRA birth or death arrives as a `ChangeRequest` with
  `change_type = vital_event`. There is **no `VitalEvent` model** —
  this page described one and it was never built.

## Auto-commit policy

When a NIRA vital event lands and matches a Member, the system auto-commits an UPD with `committed_by=system`, with a reason naming the inbound event. This policy also covers PMT reassessment trigger (US-021).

## ADRs

- See SAD §11.4 item 9 and DEP-02 open item

## Stories

US-017, US-018, US-019, US-020, US-021, US-096.
