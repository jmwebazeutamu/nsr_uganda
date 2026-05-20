/* global React */
// NSR MIS — live nav counters.
//
// The sidebar shows "needs attention" badges next to workflow links
// (DIH review, Updates, Duplicates, Grievances, Data Requests, My
// requests). Each badge mirrors what the corresponding workbench
// screen counts as its working queue:
//
//   DIH review      → stage_records WHERE state = pending_promotion
//   Updates         → change_requests WHERE status = pending_approval
//   Duplicates      → match_pairs WHERE status = pending
//   Grievances      → grievances WHERE status NOT IN (closed, resolved)
//   Data Requests   → drs_requests WHERE status = submitted
//   My requests     → drs_requests/mine WHERE status = submitted
//   Captures        → local-draft count (no API yet); stays on the
//                     hardcoded fallback until the intake endpoint
//                     lands.
//
// We use page_size=1 wherever the API supports a server-side filter,
// reading data.count from DRF's pagination wrapper. For grievances
// the screen does its filter client-side, so we mirror that here
// (no status filter on the endpoint yet — see apps/grievance/api.py).
//
// If a request fails the counter falls back to the screen's mock
// fixture value so the design harness preview still renders.

const {
  useState: _navUseState,
  useEffect: _navUseEffect,
  useCallback: _navUseCallback,
} = React;

// Mock fallbacks — match the previously hardcoded values in app.jsx
// so an offline preview looks identical to before this change.
const NAV_COUNT_MOCK = {
  capture: 14,
  dih: 342,
  upd: 23,
  dedup: 47,
  grm: 7,
  drs: 9,
  "partner-drs": 5,
};

// Read DRF's paginated count, fall back to results.length, then 0.
// The /api/v1/.../?page_size=1 pattern works on every endpoint that
// uses LimitOffsetPagination or PageNumberPagination.
const _countOf = (data) => {
  if (data == null) return null;
  if (typeof data.count === "number") return data.count;
  if (Array.isArray(data.results)) return data.results.length;
  if (Array.isArray(data)) return data.length;
  return null;
};

const _getJson = (url) =>
  fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: { "Accept": "application/json" },
  }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} on ${url}`);
    return r.json();
  });

// Each entry returns { id, fetch: () => Promise<number|null> }.
// Keeping the list declarative makes it trivial to add another nav
// counter — just append a new fetcher.
const _FETCHERS = [
  {
    id: "dih",
    fetch: () =>
      _getJson("/api/v1/dih/stage-records/?state=pending_promotion&page_size=1")
        .then(_countOf),
  },
  {
    id: "upd",
    fetch: () =>
      _getJson("/api/v1/upd/change-requests/?status=pending_approval&page_size=1")
        .then(_countOf),
  },
  {
    id: "dedup",
    fetch: () =>
      _getJson("/api/v1/ddup/match-pairs/?status=pending&page_size=1")
        .then(_countOf),
  },
  {
    id: "grm",
    // No server-side status filter yet — fetch the active page and
    // filter client-side to match the screen's title-chip logic
    // (status not in closed/resolved).
    fetch: () =>
      _getJson("/api/v1/grm/grievances/?page_size=200").then((data) => {
        const rows = (data && (data.results || data)) || [];
        if (!Array.isArray(rows)) return null;
        return rows.filter(
          (r) => r.status !== "closed" && r.status !== "resolved"
        ).length;
      }),
  },
  {
    id: "drs",
    // DRS uses ?status=submitted on the chip; the same filter on the
    // endpoint gives us the badge in one row.
    fetch: () =>
      _getJson("/api/v1/drs/requests/?status=submitted&page_size=1")
        .then(_countOf),
  },
  {
    id: "partner-drs",
    fetch: () =>
      _getJson("/api/v1/drs/requests/mine/?status=submitted&page_size=1")
        .then(_countOf),
  },
];

// Refresh every 60s. Long enough not to hammer the API, short enough
// that a freshly-approved DIH record disappears from the badge while
// the operator is still looking at the screen.
const REFRESH_MS = 60_000;

const useNavCounts = () => {
  const [counts, setCounts] = _navUseState(NAV_COUNT_MOCK);

  const refresh = _navUseCallback(() => {
    _FETCHERS.forEach(({ id, fetch }) => {
      fetch()
        .then((n) => {
          if (typeof n === "number" && n >= 0) {
            setCounts((prev) => ({ ...prev, [id]: n }));
          }
        })
        .catch(() => {
          // Swallow — leave the previous (or mock) value in place.
          // Console noise is suppressed deliberately; the screen
          // itself will surface a more visible offline indicator
          // when the operator navigates into it.
        });
    });
  }, []);

  _navUseEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  return [counts, { refresh }];
};

window.useNavCounts = useNavCounts;
window.NAV_COUNT_MOCK = NAV_COUNT_MOCK;
