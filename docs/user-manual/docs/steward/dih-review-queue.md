# DIH review queue

!!! info "Status"
    **Built and in use** — DIH review queue (US-109 scaffolded by S0), ConnectorRun dashboard (US-107), fast-track auto-promote (US-111).

Every record entering the Registry passes through DIH. Most of them auto-promote. The ones that don't land here. You decide whether to Promote, Promote-as-merge, Hold, or Reject.

## Where to find it

| Surface | Path |
|---|---|
| Console screen | `/console/` → "DIH" |
| Source JSX | `/design/v0.1/screens/screens-dih.jsx → DIHScreen` (Review tab) |
| API | `/api/v1/dih/runs/` and `/api/v1/dih/staged-records/` |
| Audit action | `dih_record_promoted`, `dih_record_rejected`, `dih_record_held` |

## Layout

Three columns:

| Column | Shows |
|---|---|
| Staged record | The pending submission, parsed and validated. DQA badges and IDV outcome visible. |
| Registry match | A discovered match (when DDUP found a candidate ≥ 0.80) or "No registry match found" empty state. |
| Decision panel | Your action buttons + DDUP candidate list + reason field. |

## Quick filters

- All
- **Walk-in fast-tracked** — Parish Chief walk-ins that auto-promoted (1% sampled for your review)
- Quarantined (blocking DQA failure)
- Awaiting IDV outcome
- Has DDUP candidate
- My queue (assigned to you)

## Actions

| Action | When to use | What happens |
|---|---|---|
| **Promote** | Clean record with no candidates | Writes to canonical Household. PMT recompute queued. |
| **Promote-as-merge** | DDUP found a candidate, both records are the same household | Routes through the [Dedup workbench](dedup.md) for compare-and-commit |
| **Hold** | You need more info | Record stays in `pending_review`. You can attach a note and assign back to the source |
| **Reject** | Bad data, fraud, duplicate of a voided record | Quarantines with reason. The source can resubmit corrected data |

Bulk approve is enabled only when every selected record has zero warnings and zero DDUP candidates. This guards against habitual click-through.

## The audit panel

A side panel on every record shows the chain from raw landing to your decision: connector run, MappingRule application, DQA result, IDV result, DDUP candidates, your action.

## ConnectorRun dashboard

A sister screen on the same JSX file. KPI strip: Active runs, Records 24h, Quarantined, Pending review. Table with 12 columns per Brief §11.4. Live counts poll every 5 seconds while a run is `running`. Row click opens the run detail with log tail.

## Fast-track auto-promote

CAPI walk-ins from Parish Chiefs auto-commit when:

- Zero blocking DQA failures.
- Zero DDUP candidates.
- IDV outcome is `verified` or `not_checked` (NIRA not required for walk-in).

1% of fast-tracked records are sampled into your review queue for spot-check, deterministic by `submission_id`. If you reject a sampled record, the system surfaces correlated records from the same source for a wider review.

## When the queue gets long

The dashboard exposes per-source backlog age. If a source is producing more than you can clear:

1. Talk to the source owner (NSR Unit + Connector owner) about throttling.
2. Open a ticket to add a second steward seat for the source.
3. Tighten the DQA rules — many quarantined records often mean a fixable upstream defect.

Do not lower the DQA thresholds without an approved rule change. That bypasses the audit trail.

## Related

- [Dedup workbench](dedup.md)
- [DIH connectors (admin)](../admin/connectors.md)
- [DIH module reference](../modules/dih.md)
- US-107 / US-109 / US-111 acceptance criteria
