# ADR-0008: Pagination + throttling policy for list endpoints

- **Status**: Accepted (Sprint 15)
- **Date**: 2026-05-15
- **Owner**: NSR MIS Architecture Team
- **References**: SAD §8 (NFR — security), SAD §10 (NFR — performance), US-S9-003 (DRS download throttling), US-S14-004 (per-region drill-down), US-S15-003 (drill-down extended to queues), US-S15-004 (this sweep)

---

## Context

Twelve React screens now hit live REST endpoints on the NSR MIS console
(home dashboard, registry browse, household detail, DIH, DDUP, DRS
operator + partner, GRM, UPD, partner-DRS request builder, admin,
DPO). The home screen alone mounts 6-9 endpoint calls per visit
(operator-kpis + reference-data + 3-5 queue panels).

Two issues surfaced as the surface grew:

1. **Page-size hint is silently dropped.** DRF's stock
   `PageNumberPagination` does NOT honour `?page_size=N` — the
   class-level `page_size_query_param` defaults to `None`. The
   React side has been passing `?page_size=4` for home queue
   previews, `?page_size=100` for household-detail tabs, and
   `?page_size=200` for the Audit chain. The server has been
   returning the global default (50) for all of them. The home
   queue panels were over-fetching by 12× (4 needed, 50 returned).
   The Audit chain was *under*-fetching (200 needed, 50 returned)
   — a real correctness gap on the household-detail Audit tab,
   which silently dropped audit rows beyond row 50.

2. **No cap on `page_size`.** Even once `?page_size=` is honoured,
   a hostile or careless client could request `?page_size=10000`
   and turn a list endpoint into an enumeration vector that
   bypasses the rate-limit budget (since one request = thousands
   of rows). The ABAC scope filter narrows the result set, but
   enumerable rows within scope (e.g. NSR Unit Coordinator with
   national scope) still warrant a cap.

Throttling is in a better state already (per US-S9-003): every API
call goes through `UserRateThrottle` at 1000/min (default) plus
`AnonRateThrottle` at 60/min, and the DRS download has a scoped
`drs-download` throttle at 10/min. The home dashboard's 6-9 fan-out
calls fit comfortably under the 1000/min default; no new scoped
throttle is needed for the queue endpoints today.

---

## Decision

1. **Project-owned pagination class.** Adopt
   `apps.security.pagination.DefaultPagination` as the global
   `DEFAULT_PAGINATION_CLASS`:

   ```python
   class DefaultPagination(PageNumberPagination):
       page_size = 50
       page_size_query_param = "page_size"
       max_page_size = 500
   ```

   The class lives in `apps.security` rather than a generic
   `apps.core` because pagination is a security primitive — the
   `max_page_size` cap is the enumeration-attack mitigation.

2. **Global PAGE_SIZE stays at 50.** Sensible default for an
   operator's "show me the queue" page. Consumers that need a
   smaller window (home queue previews → 4) or a larger window
   (household-detail Audit tab → 200) pass `?page_size=` and the
   server honours it up to the cap.

3. **MAX_PAGE_SIZE = 500.** Big enough that legitimate consumers
   (Audit tab, registry browse with broad scope) don't hit it;
   small enough that an attacker can't pull a million rows in
   one request. Tuning knob: bump or lower the constant in
   `apps.security.pagination` (no settings flag — the cap is a
   security property, not an operations one).

4. **No new scoped throttles in this sweep.** The current
   `user: 1000/min` default is adequate headroom for the
   operator-kpis + queue-panel fan-out (a busy operator mounting
   the home screen every 30 seconds for an hour issues ~1080
   requests, just under the cap). DRS-download stays scoped
   because bundle assembly is genuinely expensive. Add a scoped
   throttle when telemetry shows a specific endpoint is at risk;
   do not pre-add scopes "just in case."

5. **Audit chain emit on schema-narrowing changes.** Read-side
   `AuditReadMixin` already emits a `dashboard_read` / `list_read`
   per list call — this sweep does NOT change that; the audit
   trail captures the page_size param the operator passed
   (system reads `request.query_params` in the existing audit
   serializer).

## Consequences

**Better.**
- React queue panels stop over-fetching by 12× (4 vs 50 rows).
  Latency on home-screen mount drops correspondingly.
- Household-detail Audit tab stops silently truncating audit
  rows past row 50 — a correctness fix masquerading as a
  performance fix.
- Enumeration attacks via `?page_size=10000` are blocked at the
  pagination layer rather than relying on the throttle bucket.

**Same.**
- Existing tests that don't pass `?page_size=` continue to see
  the global default of 50. Behaviour is purely additive.

**Worse.**
- One more place to look when an endpoint behaves unexpectedly
  ("did the client cap kick in?"). Mitigation: the response
  includes `count` plus `results.length`; mismatch + 500-ish
  result count is the tell.

## Implementation

`apps.security.pagination.DefaultPagination` is the new global
pagination class. `nsr_mis.settings.REST_FRAMEWORK` points at it.
A contract test in `apps/security/tests.py` asserts:
- default behaviour (no `?page_size=`) returns 50 rows.
- `?page_size=10` returns 10 rows.
- `?page_size=10000` clamps to `max_page_size=500`.

## Open items

- **OI-PAG-01**: Should `max_page_size` be lower for endpoints
  that return PII-heavy rows (e.g. members, grievances)? Today
  it's a uniform 500. Per-endpoint caps are simple to add — sub-
  class `DefaultPagination` and override on the viewset. Defer
  until the DPO flags a specific risk.
- **OI-PAG-02**: Should we add a `?page_size=` audit reason
  trail so the DPO anomaly feed can spot a single operator
  requesting page_size=500 on every call? Currently the audit
  emits via `AuditReadMixin` but the page_size param is not in
  the reason string. Defer until we have telemetry to act on.
