# Update requests

!!! info "Status"
    **Partial** — ChangeRequest scaffold and routing matrix live. Walk-in update UI is Planned for S5.

When a household's circumstances change (member added or removed, address moved, dwelling type updated), the change is routed through UPD for approval before it commits to the canonical record. This is not the same as walk-in capture; you raise an UPD against an existing Household ID.

## Where to find it

| Surface | Path |
|---|---|
| Console | `/console/upd/new?household=<id>` |
| Source JSX | `/design/v0.1/screens/screens-upd.jsx → UPDScreen` |
| API | `POST /api/v1/upd/change-requests/` |
| Audit action | `upd_submitted` |

## Raising an update request

1. Open the [Household detail](../steward/household-detail.md) page.
2. Click **Request update**.
3. Pick the section to change (Members, Dwelling, Utilities, ...).
4. Make your edits. The diff card highlights what changed.
5. Type a reason (required).
6. Click **Submit for review**.

The request lands in the [UPD reviewer queue](../steward/upd-review.md) at the level the routing matrix decides.

## What you cannot do

- You cannot approve your own request. Author ≠ approver, enforced by `apps.update_workflow.services`.
- You cannot change Registry ID, NIN, or DOB through UPD. Those need an L3 ticket (data correction by NSR Unit).
- You cannot commit a change that would create a blocking DQA failure. The submit blocks.

## When NIRA delivers a vital event

If the change is a birth or death, the NIRA vital event connector files an UPD that auto-commits with `committed_by=system`. You don't raise these by hand; they come from the integration. You can see them in the household audit timeline.

## Tracking your request

The "My requests" tab on the UPD screen shows your open requests, their current state, and the assigned reviewer. SLA countdowns show against each.

## Related

- [UPD reviewer](../steward/upd-review.md)
- [UPD module reference](../modules/upd.md)
- [Grievances (GRM)](grievances.md) — most updates start as a grievance
