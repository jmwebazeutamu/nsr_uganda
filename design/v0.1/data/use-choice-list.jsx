/* global React */
// US-S23-012 — useChoiceList hook for the design harness.
//
// Per ADR-0010 §6, every <select>/<radio>/<chip> renderer reads its
// options from /api/v1/reference-data/choice-list-bundle/?lists=...
// The hook caches the bundle by ETag in a module-level Map so a
// second mount of the same list_name returns synchronously. Cross-
// process invalidation rides on the ETag — the next focus or
// remount triggers a conditional refetch.
//
// The hook is the ONLY path JSX uses to read coded options. No
// inline option arrays anywhere in the design layer per the
// global rule in the spec.
//
// Returns: [options, { loading, error, refresh, allLists }].
//   options       — array of {code,label,sort_order,parent_code}
//                   for the FIRST list_name in `names`. Use
//                   allLists[list_name] for multi-list calls.
//   loading       — true on the first fetch.
//   error         — string when the call failed; null otherwise.
//   refresh()     — force a re-fetch (bypasses the ETag cache).
//   allLists      — { [list_name]: options[] } for every requested list.

const { useState: _ucl_useState, useEffect: _ucl_useEffect, useMemo: _ucl_useMemo, useCallback: _ucl_useCallback } = React;

// Module-level cache. Keyed by the normalised CSV of list names.
// Value: { etag, asOf, lang, lists: { name: options[] } }.
const _bundleCache = new Map();

// Second index, by INDIVIDUAL list name.
//
// The bundle cache is keyed by the exact CSV that was requested, so a
// prefetch of thirty-nine lists and a later single-list call are
// different keys and the single-list call refetches. Every <select> in
// the capture wizard calls useChoiceList with one name, so the wizard
// opened thirty-nine separate HTTP requests — which is why Drinking
// water source, Toilet facility, Main livelihood, Agricultural purpose,
// Land ownership and Land title sat on "Loading…" for seconds after
// their section opened, and why on a CAPI tablet on a weak link an
// enumerator scrolls past them.
//
// This index lets one bundle request satisfy every later call for any
// list inside it. Keyed on (lang, asOf, name) because the same list at a
// different as_of or language is a different answer.
const _listCache = new Map();

const _listKey = (name, { asOf, lang } = {}) =>
  `${lang || "en"}|${asOf || ""}|${name}`;

const _rememberLists = (lists, opts) => {
  for (const [name, options] of Object.entries(lists || {})) {
    _listCache.set(_listKey(name, opts), options);
  }
};

// The lists already in hand for `names`, or null if any is missing.
const _cachedLists = (names, opts) => {
  const out = {};
  for (const name of names) {
    const hit = _listCache.get(_listKey(name, opts));
    if (!hit) return null;
    out[name] = hit;
  }
  return out;
};

const _csrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

const _bundleUrl = (names, { asOf, lang } = {}) => {
  const params = new URLSearchParams();
  if (names && names.length) params.set("lists", names.slice().sort().join(","));
  if (asOf) params.set("as_of", asOf);
  if (lang) params.set("lang", lang);
  const qs = params.toString();
  return `/api/v1/reference-data/choice-list-bundle/${qs ? "?" + qs : ""}`;
};

const _fetchBundle = async (names, { asOf, lang } = {}) => {
  const url = _bundleUrl(names, { asOf, lang });
  const cacheKey = url;
  const prev = _bundleCache.get(cacheKey);
  const headers = { "Accept": "application/json" };
  if (prev && prev.etag) headers["If-None-Match"] = prev.etag;
  const csrf = _csrf();
  if (csrf) headers["X-CSRFToken"] = csrf;
  const r = await fetch(url, { headers, credentials: "same-origin" });
  if (r.status === 304 && prev) return prev;
  if (!r.ok) {
    throw new Error(`choice-list-bundle HTTP ${r.status}`);
  }
  const etag = r.headers.get("ETag") || "";
  const body = await r.json();
  const lists = {};
  for (const entry of (body.lists || [])) {
    lists[entry.list_name] = entry.options || [];
  }
  const value = { etag, asOf: body.as_of, lang: body.lang, lists };
  _bundleCache.set(cacheKey, value);
  _rememberLists(lists, { asOf, lang });
  return value;
};

// Public clear, mainly for tests / dev-only "purge" actions.
window._nsrChoiceListClear = () => { _bundleCache.clear(); _listCache.clear(); };

const useChoiceList = (namesArg, opts = {}) => {
  const names = _ucl_useMemo(() => {
    if (!namesArg) return [];
    return Array.isArray(namesArg) ? namesArg : [namesArg];
  }, [Array.isArray(namesArg) ? namesArg.join(",") : (namesArg || "")]);

  const [state, setState] = _ucl_useState(() => {
    // Exact-CSV hit first, then the per-list index — so a list already
    // fetched as part of any earlier bundle resolves synchronously and
    // the <select> never renders a "Loading…" placeholder at all.
    const cached = _bundleCache.get(_bundleUrl(names, opts))
      || (names.length ? _cachedLists(names, opts) && { lists: _cachedLists(names, opts) } : null);
    return cached
      ? { lists: cached.lists, loading: false, error: null }
      : { lists: {}, loading: !!names.length, error: null };
  });

  const fetchNow = _ucl_useCallback(async (force = false) => {
    if (!names.length) {
      setState({ lists: {}, loading: false, error: null });
      return;
    }
    if (force) {
      _bundleCache.delete(_bundleUrl(names, opts));
      for (const name of names) _listCache.delete(_listKey(name, opts));
    } else {
      const cached = _cachedLists(names, opts);
      if (cached) {
        setState({ lists: cached, loading: false, error: null });
        return;
      }
    }
    try {
      const value = await _fetchBundle(names, opts);
      setState({ lists: value.lists, loading: false, error: null });
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: String(err.message || err) }));
    }
  }, [names.join(","), opts.asOf, opts.lang]);

  _ucl_useEffect(() => { fetchNow(false); }, [fetchNow]);

  const firstOptions = state.lists[names[0]] || [];

  return [firstOptions, {
    loading: state.loading,
    error: state.error,
    refresh: () => fetchNow(true),
    allLists: state.lists,
  }];
};

/** Warm the cache for a whole screen in ONE request.
 *
 * Call it once at the top of a screen with every list that screen's
 * selects will ask for. Each select's own useChoiceList(name) then
 * resolves out of the per-list index rather than opening its own
 * connection. Returns { ready } so a screen can hold back a section
 * until its lookups are in, instead of rendering rows of "Loading…".
 */
const usePrefetchChoiceLists = (names, opts = {}) => {
  const [, meta] = useChoiceList(names, opts);
  return { ready: !meta.loading, error: meta.error };
};

// Bind on window globals so the Babel-standalone harness picks
// them up — same pattern as components.jsx.
window.useChoiceList = useChoiceList;
window.usePrefetchChoiceLists = usePrefetchChoiceLists;
window._nsrChoiceListUrl = _bundleUrl;
