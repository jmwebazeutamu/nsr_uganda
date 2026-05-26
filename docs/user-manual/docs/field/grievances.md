# Grievances (GRM)

!!! info "Status"
    **Built and in use** — GRM L1 intake (US-032), triage and routing (US-033), and the GRM↔UPD auto-close tween (US-034, US-094) are live.

GRM is the channel citizens use to report a problem with their record, raise a complaint, or ask for a correction. As a Parish Chief or CDO, you sit at L1 or L2 of the triage queue.

## Where to find it

| Surface | Path |
|---|---|
| Console | `/console/grm` |
| Source JSX | `/design/v0.1/screens/screens-grm.jsx → GRMScreen` |
| API | `/api/v1/grm/grievances/` |
| Audit action | `grievance_created`, `grievance_triaged`, `grievance_resolved` |

## Intake channels

| Channel | Status | Notes |
|---|---|---|
| Walk-in (parish office) | Built | Operator types the citizen's complaint |
| Phone (call centre) | Built | Same form, channel marked `phone` |
| SMS | Scaffolded | The inbound SMS gateway lands in S6 |
| Web | Built | Public form posts to the GRM API |
| MDA referral | Built | A partner forwards a complaint about NSR data |

## Triage levels

| Level | Who handles | Examples |
|---|---|---|
| L1 | Parish Chief | Wrong household member listed, GPS misplaced |
| L2 | CDO (District) | Disputed head of household, sub-county dispute |
| L3 | NSR Unit | Fraud, identity theft, DSA misuse |

The router fires on intake based on `category`, `severity`, and the parish. The matrix lives in REF-DATA as a ChoiceList.

## The grievance lifecycle

```
opened → triaged → in_progress → resolved
                ↘ escalated → in_progress (L2 or L3)
```

| State | Who acts |
|---|---|
| `opened` | System (auto-routed) |
| `triaged` | The assigned operator at the routed level |
| `in_progress` | Same operator, with the corrective action queued |
| `escalated` | Same operator, escalating up one level |
| `resolved` | Closer of the loop |

## Linking to UPD

If the resolution requires a data change, click **Open ChangeRequest** on the grievance. The system creates a UPD ChangeRequest pre-filled with the proposed change and links the two records. On commit, the grievance auto-closes via the GRM↔UPD tween (US-094).

## SLA and breach

Each category has an SLA (e.g. L1 walk-in: 7 days, L3 fraud: 30 days). The SLA breach dashboard (US-095) shows tickets approaching or past their SLA. Triage these first.

## Confidentiality

Reports of fraud, identity theft, or DPPA breaches are marked sensitive. The case body is visible only to L3 NSR Unit operators and the DPO. L1 and L2 operators see only the case ID, severity, and routing reason.

## Related

- [Update requests](update-requests.md) — what happens when the resolution needs a data change
- [GRM module reference](../modules/grm.md)
