# DPIA Addendum — Data Explorer (US-DATA-EXP-001)

- **Status**: Initial assessment — DPO review pending
- **Date**: 28 May 2026
- **Companion to**: [ADR-0023 — Data Explorer module](../adr/0023-data-explorer.md)
- **Parent DPIA**: `/docs/dpia.md` (initial DPIA, 2026-05-14)
- **Lawful basis**: Public task (Data Protection and Privacy Act 2019 §3(1)(d))

## What the Data Explorer processes

The new `apps/data_explorer/` module is a **read-only discovery + aggregate-preview surface**. It does not deliver record-level data; that remains the exclusive responsibility of API-DRS (apps/data_requests, ADR-0023 §D1).

| Data class processed | Read? | Write? | Notes |
|---|---|---|---|
| Variable / Dataset metadata | yes | no (dual-approval activation only) | The catalogue lists what the registry holds. Metadata itself is not personal data, but enumerating it (e.g. "we hold chronic-illness status by sub-region") may signal sensitive processing. |
| Aggregate counts | yes | no | Counts of households / members grouped by sub-county or sub-region. Cell suppression below `k_floor` per PrivacyClass (Public 0, Internal 5, Personal 10, Sensitive blocked entirely from aggregate). |
| Coverage signals | yes | no | % registered / % scored per geography. Aggregate-only by construction. |
| Synthetic sample | yes | no | Generated synthetic rows that match catalogue shape; never derived from real records. |
| Audit events | no | yes (1 per endpoint hit) | Every browse, dataset read, variable read, aggregate, throttle block, geo-floor refusal, handoff, and re-identification-suspicion emits an `AuditEvent`. |
| Query log | no | yes (1 per aggregate) | `AggregateQueryLog` records actor, dataset, projection variables, filter variables, filter hash, geographic scope, result row count, suppressed cell count. Used by `detect_overlap_burst` to detect re-identification attempts. |
| Personal data fields directly | **no** | **no** | The module does not return individual records. Suppressor refuses Sensitive class at validation; Personal class is sub-region-aggregated only. |

## DPPA 2019 controls

| Principle (DPPA §3) | How DATA-EXP complies |
|---|---|
| Lawful, fair, transparent | The Explorer surfaces only what the catalogue + ACTIVE PrivacyClass authorise. Every endpoint emits an audit event; the user-facing chips show the PrivacyClass on every dataset and variable card so the user sees the constraint they're operating under. |
| Purpose limitation | The handoff payload to API-DRS captures the operator's `purpose_of_use` (≥ 30 chars) and binds it to the resulting DataRequest. The originating aggregate query is hashed and stored on `ExplorerSession.last_query_hash` so the DPO can replay the discovery trail. |
| Data minimisation | Geographic floor at sub-county (sub-region for Personal class) is enforced in both the validator and the matview shape — the matviews don't even *carry* parish-level rows for Personal-class data. |
| Accuracy | Aggregates are computed from the matview as of the last refresh. Every response carries `{matview, refreshed_at}` in metadata so the operator knows the freshness window. Stale matviews (`> 2 × cadence`) return 503; we do not silently fall back to live DAT queries. |
| Storage limitation | `AggregateQueryLog` rows retained per the audit retention policy (10 years, per `/docs/dpia.md` §retention). The `ExplorerSession` row is preserved through the DataRequest lifecycle for replay; soft-deletes follow the DataRequest's retention. |
| Integrity and confidentiality | Suppressor is the single gatekeeper for cell values; below `k_floor`, the response carries `null + suppressed: true`. No upper-bound leakage, no rounded-up approximation. Audited test (`test_no_upper_bound_leak`) asserts the suppressed value is the literal `None`. |
| Accountability | DPO sees the cumulative aggregate volume per operator over rolling windows via the existing API-DRS Cumulative-Volume console (US-103) — DATA-EXP query logs feed the same pipeline. |

## Re-identification risk surface

The novel risk this slice introduces is **multi-query reconstruction** — an operator with the `EXPLORER` role running a sequence of overlapping aggregate queries to triangulate small cells (the "small-multiples" attack).

### Mitigations applied

1. **k-anonymity at the cell level** — every aggregate response runs through `Suppressor.apply(...)`. Cells with count < k_floor return `null + suppressed: true`. Differencing on two suppressed cells yields `null - null = no information` (ADR-0023 §R2).
2. **Geographic floor** — sub-county for everything; sub-region for Personal-class data. Parish and village aggregates are refused at the validator (HTTP 422 with `geographic_floor_violation`) and routed to API-DRS where DPO review is mandatory.
3. **Query log + overlap-burst detection** — `AggregateQueryLog` records every query with a `filter_hash`. The `detect_overlap_burst` Celery task scans the trailing 24 hours and flags any (actor, dataset) pair whose queries share ≥ 3 filter dimensions across ≥ 50 queries. Flagged actors generate a `data_explorer.reidentification.suspected` audit event and a DPO notification email (via `apps.security.notifications.send_notification`).
4. **PrivacyClass throttle** — Personal class is limited to 25 queries/user/day and 500/org/day. This caps the attack surface to well below the 100-query budget the risk-probe test assumes.
5. **Risk probe** (ADR-0023 Appendix A) — a CI-gated test runs 100 sequential queries with ≤ 3 overlapping filter dimensions against the staging matview snapshot. The release is blocked if any household record's true count is reconstructible (posterior ≥ 90% on a single integer). The scenario file is reviewable + reproducible.

### Residual risk

- **Side-channel timing attacks** — out of scope for MVP-1. Suppressor returns in O(cells) but matview query time varies with size.
- **Collusion between two EXPLORER actors** — the query log is per-actor; cross-actor analytics are a Phase 2 feature.
- **External data correlation** — combining Explorer outputs with leaked partner datasets is outside the system boundary.

## New audit events introduced

| Action | Entity type | When |
|---|---|---|
| `data_explorer.catalogue.browsed` | `Dataset` | `GET /datasets` |
| `data_explorer.dataset.read` | `Dataset` | `GET /datasets/{id}` |
| `data_explorer.variable.read` | `Variable` | `GET /variables/{id}` |
| `data_explorer.variable.searched` | `Variable` | `GET /variables` faceted search |
| `data_explorer.privacy_classes.read` | `PrivacyClass` | `GET /privacy-classes` |
| `data_explorer.aggregate.executed` | `Dataset` | `POST /aggregate` 200 |
| `data_explorer.aggregate.refused_below_floor` | `Dataset` | `POST /aggregate` 422 (geographic floor) |
| `data_explorer.aggregate.rejected` | `Dataset` | `POST /aggregate` 422 (any other validation failure) |
| `data_explorer.throttle.exceeded` | `User` | Throttle service rejects |
| `data_explorer.matview.stale` | `Dataset` | `POST /aggregate` 503 |
| `data_explorer.handoff.created` | `DataRequest` | `POST /handoff` 201 |
| `data_explorer.handoff.rejected` | `DataRequest` | `POST /handoff` 422 |
| `data_explorer.reidentification.suspected` | `User` | Overlap-burst detector flags an actor |

All audited; all tested via the audit-sweep contract test (`tests/contract/data_explorer/test_audit_sweep.py`).

## Activation gate

`apps.data_explorer.DATA_EXPLORER_ENABLED` is `False` in production by default. The two pre-conditions for flipping to `True`:

1. This DPIA addendum signed off by the Data Protection Officer.
2. ADR-0023 signed off by NSR Unit Coordinator + DPO + Engineering Lead + M&E Lead.

Until both are in place, the Explorer is dev/staging-only. The new Keycloak realm role `EXPLORER` is created in pre-production at the same time the flag flips.

## Open items for DPO review

- **Daily query caps**: proposed defaults (Internal 100/user/day + 5,000/org/day; Personal 25/user/day + 500/org/day) — DPO has the final word; the architect surfaced these as OPEN-3 in ADR-0023.
- **PrivacyClass override workflow**: dual approval, with DPO mandatory on every change (OPEN-7). This is enforced in code by the `VariableApproval` model but not yet wired through the admin UI.
- **Query log retention**: assumed 10 years to match the parent DPIA's audit retention. If DPO wants a shorter window for Explorer-specific logs, the `AggregateQueryLog` rows can age separately.

## Signed off by

- Data Protection Officer: ____________________ Date: __________
- NSR Unit Coordinator: ____________________ Date: __________

End of DPIA addendum.
