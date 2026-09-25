/* global React */
// NSR MIS — live nav counters.
//
// The sidebar shows "needs attention" badges next to workflow links
// (DIH review, Updates, Duplicates, Grievances, Data Requests, My
// requests). Each badge mirrors what the corresponding workbench
// screen counts as its working queue:
//
//   DIH review      → stage_records ?queue=review — the server's own
//                     definition of "still somebody's work". This badge
//                     used to count state=pending_promotion alone and
//                     read 0 while the screen it points at held twelve
//                     records in idv_pending and quality_failed.
//   Updates         → change_requests WHERE status = pending_approval
//   Duplicates      → match_pairs WHERE status = pending
//   Grievances      → grievances WHERE status NOT IN (closed, resolved)
//   Data Requests   → all drs_requests visible in the operator inbox
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
// If a request fails the badge is HIDDEN. It is never replaced with a
// fixture value: a fabricated "342" next to DIH review is worse than no
// badge at all, because an operator cannot tell it is fabricated and
// will plan work around it.

const {
  useState: _navUseState,
  useEffect: _navUseEffect,
  useCallback: _navUseCallback,
} = React;

// Every badge starts unknown (null = render nothing) and only becomes a
// number when an endpoint returns one. `capture` has no endpoint yet, so
// it stays null and its badge simply does not appear.
const NAV_COUNT_INITIAL = {
  capture: null,
  dih: null,
  upd: null,
  dedup: null,
  grm: null,
  drs: null,
  "partner-drs": null,
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
      _getJson("/api/v1/dih/stage-records/?queue=review&page_size=1")
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
    // The DRS inbox opens on "All". Count the same server collection,
    // rather than a status-filtered subset that can disagree with its list.
    fetch: () =>
      _getJson("/api/v1/drs/requests/?page_size=1")
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
  const [counts, setCounts] = _navUseState(NAV_COUNT_INITIAL);

  const refresh = _navUseCallback(() => {
    _FETCHERS.forEach(({ id, fetch }) => {
      fetch()
        .then((n) => {
          if (typeof n === "number" && n >= 0) {
            setCounts((prev) => ({ ...prev, [id]: n }));
          }
        })
        .catch(() => {
          // Drop the badge rather than show a stale or invented number.
          // The screen the operator navigates into surfaces the outage
          // properly; a wrong count in the sidebar just misleads quietly.
          setCounts((prev) => ({ ...prev, [id]: null }));
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
window.NAV_COUNT_INITIAL = NAV_COUNT_INITIAL;
