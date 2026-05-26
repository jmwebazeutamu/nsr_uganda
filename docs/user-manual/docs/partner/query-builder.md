# DRS Query Builder

!!! info "Status"
    **Built and in use** — Query Builder (US-S27-013) and geographic-scope enforcement at every UBOS level (US-S27-016) live as of 2026-05-21.

The Query Builder is the wizard you use to describe the data you want. It produces a structured criteria tree, validates it against your DSA, then hands you to the [Field Selector](field-selector.md).

## Where to find it

| Surface | Path |
|---|---|
| Console | `/console/drs` |
| Source JSX | `/design/v0.1/screens/screens-drs.jsx → DRSScreen` (Build step) |
| Source JSX (newer builder pane) | `/design/v0.1/screens/screens-drs-querybuilder.jsx` |
| API | `POST /api/v1/drs/requests/{id}/submit/` |
| Audit action | `data_request_submitted` |

## The wizard steps

| Step | What you do |
|---|---|
| 1. Define | Name the request, set a purpose statement, pick the DSA |
| 2. Build | Drop in criteria leaves (PMT band, vulnerability band, geography, programme, member attributes) |
| 3. Fields | Pick the columns you want delivered (next page) |
| 4. Preview | See sample rows, sensitivity breakdown |
| 5. Submit | File with the steward queue |

## Available leaves

The criteria tree supports these leaves today (US-S27-013 + 016):

| Leaf | Type | Source |
|---|---|---|
| Region / Sub-region / District / County / Sub-county / Parish / Village | enum | `/api/v1/reference-data/geographic-units/?level=<level>&status=active` |
| Programme | enum | `/api/v1/partners/programmes/` |
| Urban / Rural | enum | static |
| PMT band | enum | static |
| Vulnerability band | enum | static |
| member.sex | enum | static |
| member.age_years | number | static |

Non-geographic, non-programme leaves land in `request_payload.criteria` as audit-only for now. The criteria evaluator that filters on those is the next slice.

## Validation against DSA

On submit, the validator walks the criteria tree:

- Every geographic leaf is matched against your DSA's `geographic_scope` at the right level. Extras at any level are rejected.
- The programme leaf is matched against `programme_scope`.
- Out-of-scope leaves rise a `validate_against_dsa` error with the specific level and code.

The DSA's `geographic_scope` is an M2M to `GeographicUnit` that may carry rows at any level. Each level is enforced independently. If your DSA has no rows at a level, that level is unrestricted.

## Sensitivity breakdown

A card on the right of Step 4 (Preview) counts the requested fields by sensitivity:

| Sensitivity | What |
|---|---|
| `public` | Aggregates safe to publish |
| `internal` | Operational data, scoped to staff |
| `personal` | Identifiable to one household |
| `sensitive` | Health, disability, child-headed status |

A banner appears when your selection includes `personal` or `sensitive` columns, telling you a DPO review is needed.

## Submit

Click **Submit**. The request lands in the steward queue at `pending_review`. You see it in the [Partner portal](partner-portal.md) under "My requests".

## Related

- [DRS Field Selector](field-selector.md)
- [API reference](api-reference.md) — submit the request programmatically
- US-S27-013, US-S27-014, US-S27-016 in `/docs/api_changelog.md`
