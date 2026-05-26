# Household lookup

!!! info "Status"
    **Built and in use** — household list and detail ship in `screens-registry.jsx → RegistryScreen` and `screens-household.jsx → HouseholdScreen`.

You can look up any household within your scope. ABAC narrows what you see.

## Where to find it

| Surface | Path |
|---|---|
| Console | `/console/registry` |
| Source JSX | `/design/v0.1/screens/screens-registry.jsx` |
| API | `/api/v1/data-management/households/` |
| Audit action | `household_read` |

## Searching

| Search field | Notes |
|---|---|
| Registry ID (ULID) | Exact match, fastest |
| Head NIN | Hash match (no plaintext is sent to the server) |
| Head name | Fuzzy, ranked by Soundex + edit distance |
| Phone | Normalised to E.164 |
| Parish + name | Useful when you know roughly where they live |

ABAC happens at the queryset level. If a result is outside your scope, you get a "not found" message rather than "access denied" so attackers cannot enumerate. The audit chain still logs your attempt.

## The result row

Each row shows:

- Registry ID (click to open detail).
- Head of household name.
- Parish.
- Status chip (`registered`, `pending`, `voided`).
- Last updated, in EAT.

## Viewing detail

Click a row to open the household detail page. See [Household detail](../steward/household-detail.md) for the layout and what each tab shows.

## Reading sensitive fields

If the household has sensitive flags (disability, health condition, child-headed), opening detail prompts you for a reason. The reason is recorded in the audit chain. Reading without typing a reason is blocked.

## Exporting

You can export your search results as CSV from the **Export** button. Export writes an `AuditEvent` with the row count and reason. Large exports (over 1000 rows) require DPO sign-off via the DPO Console.

## Related

- [Household detail](../steward/household-detail.md)
- [DAT module reference](../modules/dat.md)
- [SEC module reference](../modules/sec.md) — ABAC details
