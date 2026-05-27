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

The Open-CR wizard (v0.3) walks you through four steps:

1. **Target** — open the [Household detail](../steward/household-detail.md) page and click **Request update**. The modal opens with `entity = household` selected; switch to a specific member if the change is roster-scoped, then pick the member from the roster picker.
2. **Fields** — pick one or more fields from the catalog. Each row shows a **Before** card with the current persisted value and an **After** input matched to the field type:
    - text — free text
    - number — numeric input with `min` / `max` / `step` enforced (e.g. `hh_size` is bounded 1..30)
    - date — date picker with `min` / `max` (e.g. `member_dob` can't be in the future)
    - select / coded — dropdown populated from the active ChoiceList for that field, not a free string
3. **Evidence** — attach supporting documents (PDF / JPG / PNG / HEIC / WebP, 5 MB per file, 15 MB total, 3 files) and enter the operator note (mandatory, ≥ 6 chars). The Next button is disabled until the note is long enough — earlier this gate sat on Submit, which surprised operators who only saw the disabled state at the final step.
4. **Review** — old → new diff table, routing destination, PMT impact chip. Click **Create & submit** to send.

The request lands in the [UPD reviewer queue](../steward/upd-review.md) at the level the routing matrix decides.

### What the wizard catches before you submit

- **No-op submissions** — if every row's new value matches the current value, the wizard refuses to advance from step 2. There's nothing to commit.
- **Self-approval** — author email and approver email must differ. The server enforces this even if the UI didn't (AC-UPD-NO-SELF-APPROVE).
- **Out-of-range numbers / dates** — HTML5 validation rejects values outside the catalog's `min`/`max`/`step`. The server validates again on submit.
- **Unknown fields** — fields not in the backend catalog are silently dropped on submit. The wizard's field picker shouldn't surface them in the first place; if you see one, file a bug.

## PMT impact

A small chip in the wizard's live summary shows whether the change is PMT-relevant. The flag is **auto-derived** from the picked rows (any row whose field is PMT-relevant in the catalog flips it on), but you can override either way with the **Mark PMT-relevant** checkbox — useful when a typically-cosmetic field happens to land on a hard policy boundary, or when a PMT-relevant field's change is actually a no-op for the score.

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
