# Update requests

!!! info "Status"
    **Built and in use** — full-page Open-CR submitter, live field catalog, current-value preview, multi-row + multi-category bundling, supporting documents, sticky review. Backed by `POST /api/v1/upd/change-requests/bundle/`.

When a household's circumstances change (member added or removed, address moved, dwelling type updated), the change is routed through UPD for approval before it commits to the canonical record. This is not the same as walk-in capture; you raise an UPD against an **existing** Household ID.

## Where to find it

| Surface | Path |
|---|---|
| Console | Household detail → **Open update** button |
| Source JSX | `/design/v0.1/screens/change-request/` |
| API | `POST /api/v1/upd/change-requests/bundle/` |
| Audit action | `change_request.submitted`, `change_request.committed` |

## The Open-CR screen

The screen replaces the older quick-modal flow. It's a full-page form with five numbered sections, locked progressively as you fill them out:

1. **Update scope** — pick **Household-level** or **Roster / member-level**. Member-level reveals the roster picker (live from the household payload); choose the member the change applies to.
2. **Field changes** — pick one or more fields from the live catalog (`/api/v1/upd/field-catalog/`). Each row shows the **current** persisted value alongside a **new value** input matched to the field type:
    - text — free text
    - number — numeric with `min` / `max` / `step` from the catalog
    - date — date picker with `min` / `max_today` constraints
    - select / coded — dropdown populated from the active ChoiceList for that field, not a free string
    - boolean — Yes / No
   Quick-add chips offer one PMT-flagged field per visible category. You can bundle changes across categories into one request.
3. **Reason for change** — pick a **Change type** (correction / life_event / verification / address_move / roster_change / asset_change) and write the reason (≥ 12 chars). The reason is written verbatim to the audit chain (AC-AUDIT-EVENT). The **PMT impact** chip auto-derives from your picked rows; you can force it on but not off.
4. **Supporting documents** — drop in evidence (PDF / JPG / PNG, ≤ 5 MB per file, ≤ 15 MB total, ≤ 3 files). Pick the document kind from the dropdown (Birth / Death certificate, LC1 letter, NIN photo, etc.).
5. **Review & submit** — recap of scope, member (if any), change type, PMT impact, field count, documents, reason. Routing destination is shown live (`change_type × pmt_relevant` → reviewer label) so you know which queue the request lands in before you submit.

The sticky action bar at the bottom shows the requester, the live routing target, and the **Submit for review** button. Submit is disabled until every gate passes; the disabled tooltip lists what's outstanding.

## What the screen catches before you submit

- **Missing member** — member scope without a picked member.
- **Empty rows** — every queued field needs a new value.
- **Short reason** — < 12 chars is rejected by the UI (server min is 6; UI keeps a stricter gate).
- **No-op rows** — duplicate `(category, field)` tuples are rejected server-side.
- **Unknown fields** — only fields the live `/api/v1/upd/field-catalog/` returned are pickable; drift between mock and live can't sneak in.
- **Self-approval** — author username ≠ approver username, enforced server-side regardless of UI state (AC-UPD-NO-SELF-APPROVE).

## Right-rail history

A collapsible **History** rail on the right of the page shows the last several UPD change requests against the same household (or member, if a member is picked). Each row links to the canonical CR detail surface. Useful to spot "operator already raised this last week" before duplicating.

## PMT impact

The PMT chip auto-derives from your picked rows: any row whose field is PMT-relevant in the live catalog flips it on. You can also force it on with the **Force PMT** checkbox — useful when a typically-cosmetic field happens to land on a hard policy boundary. You **cannot** force it off when the catalog says a field is PMT-relevant.

## What you cannot do

- You cannot approve your own request. Author ≠ approver, enforced by `apps.update_workflow.services`.
- You cannot change Registry ID through UPD. It needs an L3 ticket (data correction by NSR Unit).
- You cannot commit a change that would create a blocking DQA failure. The submit succeeds (CR enters PENDING_APPROVAL), but the reviewer's commit step blocks until the failure is resolved.

## When NIRA delivers a vital event

If the change is a birth or death, the NIRA vital-event connector files a system-CR that auto-commits with `committed_by=system`. You don't raise these by hand; they come from the integration. You'll see them in the household audit timeline with `change_type=vital_event`.

## Tracking your request

The "My requests" tab on the UPD screen shows your open requests, their current state, and the assigned reviewer. SLA countdowns show against each — the SLA cap comes from `apps.update_workflow.routing.DEFAULT_MATRIX[(change_type, pmt_relevant)]`.

## Related

- [UPD reviewer](../steward/upd-review.md)
- [UPD module reference](../modules/upd.md)
- [Grievances (GRM)](grievances.md) — most updates start as a grievance
- [DQA rules](../steward/dqa-rules.md) — what blocks a commit
