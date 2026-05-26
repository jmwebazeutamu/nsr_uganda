# Module reference

One short page per functional module. Each page carries a **status badge**, what the module does, the endpoints, the screens, the key ADRs, and the user stories that built it.

## Status matrix

| Module | Code | Status | Page |
|---|---|---|---|
| Intake | INT | Scaffolded | [int.md](int.md) |
| Data Management | DAT | Built | [dat.md](dat.md) |
| Data Quality | DAT-DQA | Built | [dat-dqa.md](dat-dqa.md) |
| Deduplication | DAT-DDUP | Built (tier 1, 2) | [dat-ddup.md](dat-ddup.md) |
| Identity Verification | IDV | Partial | [idv.md](idv.md) |
| Update Workflow | UPD | Partial | [upd.md](upd.md) |
| Proxy Means Test | PMT | Built (engine), Partial (weights) | [pmt.md](pmt.md) |
| Referral | REF | Built | [ref.md](ref.md) |
| Grievance | GRM | Built | [grm.md](grm.md) |
| API Gateway | API | Built | [api.md](api.md) |
| Data Requests | API-DRS | Partial | [api-drs.md](api-drs.md) |
| Integration Hub | DIH | Built | [dih.md](dih.md) |
| Security | SEC | Built | [sec.md](sec.md) |
| Reporting | RPT | Built | [rpt.md](rpt.md) |
| Reference Data | REF-DATA | Built (geography), Planned (ChoiceList) | [ref-data.md](ref-data.md) |
| Partners and DSA | (cross-cut) | Built | [partners.md](partners.md) |
| Admin Console | (cross-cut) | Built | [admin-console.md](admin-console.md) |

## Status badge legend

| Badge | Meaning |
|---|---|
| **Built and in use** | End-to-end. Tests cover it. Use the page as a manual. |
| **Partial** | Usable, gaps called out on the page. |
| **Scaffolded** | Models and URLs exist. No operator surface. |
| **Planned** | Not built. Page describes the planned slice and target sprint. |

See [Status legend](../appendices/status-legend.md).
