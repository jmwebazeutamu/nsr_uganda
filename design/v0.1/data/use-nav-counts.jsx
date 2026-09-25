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
//   Grievances      → grievances ?active=true — the server's own
//                     ACTIVE_GRIEVANCE_STATUSES, not a fourth copy of
//                     "not closed and not resolved"
//   Data Requests   → all drs_requests visible in the operator inbox
//   My requests     → drs_requests/mine WHERE status = submitted
//   Captures        → local-draft count (no API yet); stays on the
//                     hardcoded fallback until the intake endpoint
//                     lands.
//
// We use page_size=1 everywhere and read data.count from DRF's
// pagination wrapper, so a badge never depends on how many rows came
// back. Grievances was the exception — it fetched 200 and counted them
// here — and it was wrong twice over: capped at 200, and holding its
// own idea of which statuses are still work.
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
    // `?active=true` is the server's own definition of "still
    // somebody's work" (ACTIVE_GRIEVANCE_STATUSES). This used to fetch
    // 200 rows and filter them here — which both capped the badge at
    // 200 and made this a third definition of "open", beside the
    // dashboard tile's and the workbench's.
    fetch: () =>
      _getJson("/api/v1/grm/grievances/?active=true&page_size=1")
        .then(_countOf),
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

// Screens announce that they changed something; the sidebar listens.
//
// A minute is a long time to look at a badge you have just made wrong.
// An operator who closed the last open grievance saw "1" next to
// Grievances until the timer came round, and the obvious reading of
// that is that the close did not take.
//
// A listener set rather than a prop threaded from the shell through
// every screen: the screens are loaded as classic scripts into one
// global scope, and a prop per screen is how five screens end up with
// four spellings of the same callback.
const _navCountListeners = new Set();

const navCountsChanged = () => {
  _navCountListeners.forEach((fn) => {
    try { fn(); } catch (_) { /* a bad listener must not stop the rest */ }
  });
};

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
    _navCountListeners.add(refresh);
    return () => {
      clearInterval(t);
      _navCountListeners.delete(refresh);
    };
  }, [refresh]);

  return [counts, { refresh }];
};

window.useNavCounts = useNavCounts;
window.navCountsChanged = navCountsChanged;
window.NAV_COUNT_INITIAL = NAV_COUNT_INITIAL;
