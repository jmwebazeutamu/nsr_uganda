# DRS Field Selector

!!! info "Status"
    **Built and in use** — FieldStepV2 with two-pane available → ordered output, search, group + sensitivity filters, recommended packs, drag-reorder (US-S27-014, 2026-05-21).

The Field Selector is Step 3 of the Query Builder. It is where you pick the columns that will appear in your extract.

## Where to find it

| Surface | Path |
|---|---|
| Console | `/console/drs` → wizard Step 3 |
| Source JSX | `/design/v0.1/screens/screens-drs-fieldselector.jsx → FieldStepV2` |
| Live catalogue | `/api/v1/drs/requests/builder-schema/` |
| Audit action | logged as part of `data_request_submitted` |

## The two panes

| Pane | What |
|---|---|
| Left — Available | All fields your DSA grants. Search and filter. |
| Right — Selected | Your chosen fields, in delivery order. Drag to reorder. |

## Search and filters

- **Search**: matches across field label, key, description, and example.
- **Group filter**: Household, Member, Dwelling, Utilities, Food, Shock, Coping, Programme.
- **Sensitivity filter**: Public, Internal, Personal, Sensitive.
- **DSA-blocked toggle**: shows the fields your DSA does not grant, with the reason. Useful when you want to negotiate a scope change.

## Recommended packs

One-click presets that load an ordered selection.

| Pack | What it gives you |
|---|---|
| **Minimum reporting** | Registry ID, parish, head name, head NIN hash, PMT band, last updated |
| **Geography rollup** | Aggregated counts by sub-county and parish. No PII |
| **Vulnerability profile** | PMT band, vulnerability band, disability count, food-insecurity score |
| **Housing and utilities** | Dwelling type, walls, roof, water source, sanitation, electricity, cooking fuel |

Click a pack, the right pane fills with the pack's fields in pack order. You can edit from there.

## Ordering

The order of fields in the right pane is the **column order** in your delivered file. Drag to reorder. The submit payload's `fields` array preserves this order. The server validator is order-insensitive, so reordering does not change your DSA validation outcome.

## Sensitivity breakdown card

A card at the bottom of the Selected pane shows counts of selected fields by sensitivity, with a bar. A DPO-review banner appears when you select any `personal` or `sensitive` fields.

## DSA-blocked fields

Fields outside your DSA scope are visible but disabled, with a tooltip showing the reason:

- `Outside DSA field scope`
- `Sensitivity ceiling exceeded`
- `Programme scope mismatch`

To widen scope, talk to the NSR Unit about a DSA scope edit (ADR-0016). Narrowing your live scope is immediate; widening needs counter-signature.

## What you cannot do

- You cannot select a field that fires a downstream validator (e.g. `member.health.hiv_status` always requires `sensitive` sensitivity ceiling AND a DPO review threshold of 0).
- You cannot bypass the order limit (250 columns per extract).
- You cannot submit zero fields. The validator rejects.

## Related

- [DRS Query Builder](query-builder.md)
- [Data Sharing Agreement (DSA)](dsa.md)
- US-S27-014 — Field Selector design and acceptance
