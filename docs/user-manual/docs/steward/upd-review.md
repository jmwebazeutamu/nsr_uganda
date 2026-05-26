# UPD reviewer

!!! info "Status"
    **Partial** — ChangeRequest scaffold + routing matrix in REF-DATA are live (US-S1-009, US-089, US-S4-003). The no-self-approve enforcement (US-091) is pending. Full reviewer screen wiring is Planned for S5.

UPD is the workflow that takes a change request from any source (citizen via GRM, Parish Chief walk-in, NIRA vital event, partner correction) through review to commit.

## Where to find it

| Surface | Path |
|---|---|
| Console screen | `/console/` → "Updates" |
| Source JSX | `/design/v0.1/screens/screens-upd.jsx → UPDScreen` |
| API | `/api/v1/upd/change-requests/` |
| Audit actions | `upd_submitted`, `upd_approved`, `upd_committed`, `upd_rejected` |

## The ChangeRequest lifecycle

```
submitted → routed → in_review → approved → committed
                              ↘ rejected
```

| State | Who acts | Next |
|---|---|---|
| `submitted` | Auto-routed by the matrix (REF-DATA) | `routed` |
| `routed` | Reviewer claims the request | `in_review` |
| `in_review` | Reviewer + (if needed) a second approver | `approved` or `rejected` |
| `approved` | System commits | `committed` |
| `committed` | n/a | Terminal |

The routing matrix lives in `apps.reference_data` as a `ChoiceList` so it can be updated by an Admin Console operator without code change.

## The review screen

When built (S5), the screen shows:

- **Before / After diff card** — every changed field highlighted with `--accent-update` border (per `components.md §5.2`).
- **Source signal** — where the change came from (GRM ticket, NIRA event, Parish Chief, partner).
- **Routing trail** — every operator who touched it.
- **PMT preview** — what the recomputed PMT band would be after commit, so the reviewer sees programme-eligibility implications.
- **DQA preview** — re-evaluates rules against the proposed state.
- **Approve / Reject** action bar with mandatory reason.

Until the screen lands, you use the Django admin at `/admin/update_workflow/changerequest/` or the API.

## Auto-commit cases

Some changes commit without operator review.

| Source | Auto-commit when | ADR / Story |
|---|---|---|
| NIRA vital event | Birth or death event from `nira_vital` connector | US-S3-003, US-096 |
| GRM → UPD tween | A GRM ticket was resolved by data correction with reviewer sign-off | US-094 (tween 572531b) |

Auto-commit writes a `committed_by=system` AuditEvent and the source connector ID.

## SLA breach dashboard

The reporting module surfaces an SLA breach dashboard (US-095, Done). It shows ChangeRequests older than the configured SLA per routing rule. Use this as your daily triage signal.

## Related

- [Household detail](household-detail.md) — start a ChangeRequest from here
- [UPD module reference](../modules/upd.md)
- ADR-0014 — Programme registration data model (touches UPD routing)
