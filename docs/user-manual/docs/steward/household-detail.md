# Household detail

!!! info "Status"
    **Built and in use** — the Household detail screen ships in `screens-household.jsx → HouseholdScreen` (US-005, US-090). Version drill-down + audit panel are live.

The household detail page is the single view of a household. Members, relationships, dwelling, utilities, food, shocks, coping, PMT score, audit chain.

## Where to find it

| Surface | Path |
|---|---|
| Console URL | `/console/registry/<household_id>` |
| Source JSX | `/design/v0.1/screens/screens-household.jsx → HouseholdScreen` |
| API | `/api/v1/data-management/households/<id>/` |
| Audit action | `household_read` |

## Tabs

| Tab | Shows |
|---|---|
| Overview | Head of household, geography, status, current PMT band, last update |
| Members | All Member rows, head highlighted |
| Detail entities | Dwelling, utilities, food, shocks, coping, asset ownership |
| History | Every HouseholdVersion + MemberVersion as a timeline |
| Audit | The audit chain for this household (last 90 days) |

## Read-only by default

You can view but not edit from this page. To change data you raise an UPD (ChangeRequest) which routes for approval. See [UPD reviewer](upd-review.md).

## Sensitive fields

Rows with health, disability, or child-headed status show a lock chip. The read writes an extra `AuditEvent` with `reason` mandatory.

ABAC narrows what you see:

| Your scope | What you see |
|---|---|
| NATIONAL | Every household |
| DISTRICT | Households whose `district` is in your scope |
| PARISH | Households whose `parish` is in your scope |
| PARTNER | Only households the partner's DSA scope grants you |

## Version history

The Members and Detail entities tabs surface a "Show all versions" toggle. Each row expands to show the version chain. Per ADR-0017, detail entities are full tables (not JSON blobs), so each detail row has its own version chain too.

## Audit timeline

The audit tab shows actions in reverse chronological order:

- Who read the record and why.
- Every write (Promote, ChangeRequest commit, merge).
- Every DQA evaluation outcome.
- IDV results.

Each row links to the source story or operator action.

## Related

- [UPD reviewer](upd-review.md) — change requests start here
- [DAT module reference](../modules/dat.md)
- [SEC module reference](../modules/sec.md) — the audit chain
- ADR-0017 — Detail entities as tables
- ADR-0018 — Repeat groups as child tables
