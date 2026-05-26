# DQA Violations Dashboard

!!! info "Status"
    **Built and in use** — US-082 ships the dashboard scaffold; violation record downloads are live (US-050).

The violations dashboard is your daily inbox for everything the DQA engine flagged.

## Where to find it

| Surface | Path |
|---|---|
| Console screen | `/console/` → "DQA → Violations" |
| Source JSX | `/design/v0.1/screens/screens-admin-workflow-dqa.jsx` |
| API | `/api/v1/dqa/violations/` |
| Audit action | `dashboard_read` with `code=dqa_violations` |

## Columns

| Column | What it shows |
|---|---|
| Rule | The fired `rule_id` and version |
| Severity | `blocking` or `warning` chip |
| Source | DIH SourceSystem code |
| Record ref | The staged record ID, click-through to detail |
| Field | The field that failed (when known) |
| Operator | The actor whose connector or capture produced the record |
| Captured at | EAT timestamp |
| Status | `open`, `acknowledged`, `resolved`, `false_positive` |

## Filters

- Rule
- Severity
- Date range (default last 7 days)
- SourceSystem
- Sub-region (ABAC-scoped automatically)
- Status

ABAC narrows the queryset to violations whose sub-region intersects your `OperatorScope`. National-scope operators (NSR Unit Coordinator, DPO) see everything.

## What you do here

For each row:

1. **Click through to the staged record.** You see the side-by-side DQA result.
2. **Decide**: is the rule right and the data wrong, or is the rule wrong?
3. If the data is wrong: route to the source. Walk-in records can be sent back to the Parish Chief via the GRM workflow. Bulk import records get a quarantine reason.
4. If the rule is wrong: open the [Rule Editor](dqa-rules.md), create a new rule version, get it approved.
5. Mark the violation `acknowledged`, `resolved`, or `false_positive` with a reason.

## Exports

Use the Export button to download as CSV. Export writes one `AuditEvent` with the row count.

```
GET /api/v1/dqa/violations/?export=csv&rule=AC-NIN-FORMAT
```

## Related

- [DQA Rule Editor](dqa-rules.md)
- [DIH review queue](dih-review-queue.md)
- US-082 — Violations dashboard
