# Data Steward / DQA Officer guide

You are here to keep the Registry clean. You author and approve DQA rules, review violations, resolve duplicates, decide what gets promoted from DIH, and handle update requests that land on the review queue.

!!! info "Status"
    Most of the steward surface is **Built and in use** for the audit-bearing core (DQA, DDUP tier 1 + 2, DIH review queue). The UPD review screen wiring is **Partial** — back end ready, full review UI Planned for S5.

## What you do day-to-day

| Task | Page |
|---|---|
| Author or change a quality rule | [DQA Rule Editor](dqa-rules.md) |
| Review the daily violations queue | [DQA Violations Dashboard](dqa-violations.md) |
| Compare and merge duplicate households | [Dedup workbench](dedup.md) |
| Decide whether to promote a DIH-staged record | [DIH review queue](dih-review-queue.md) |
| Look up a household and its full history | [Household detail](household-detail.md) |
| Review a change request | [UPD reviewer](upd-review.md) |

## Principles

- **You are the audit owner.** Every decision you make writes an `AuditEvent`. Your username, the reason you typed, your IP, the entity, and the previous-row hash are all recorded. Treat the reason field like a public record.
- **Dual approval is not a courtesy.** You cannot approve a rule or merge model you authored. The system enforces author ≠ approver. Same applies to UPD: the operator who submits a change cannot approve it.
- **Promote with care.** A promotion writes to the canonical Household table. Rolling back a promotion is possible but writes a full audit chain (no quiet deletes).
- **Sensitivity overrides convenience.** Records with sensitive fields (health, disability, child-headed status) show a lock chip. Reads of those rows write extra audit context (`why=` reason is mandatory).

## Your tools at a glance

| Tool | Where | Status |
|---|---|---|
| Operator console | `http://<host>/console/` | Built |
| Admin Console (NSR Unit + SA) | `http://<host>/admin-console/` | Built |
| Django admin (low-level) | `http://<host>/admin/` | Built |
| Swagger UI (API) | `http://<host>/api/docs/` | Built |
