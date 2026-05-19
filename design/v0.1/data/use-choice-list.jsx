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
  return value;
};

// Public clear, mainly for tests / dev-only "purge" actions.
window._nsrChoiceListClear = () => _bundleCache.clear();

const useChoiceList = (namesArg, opts = {}) => {
  const names = _ucl_useMemo(() => {
    if (!namesArg) return [];
    return Array.isArray(namesArg) ? namesArg : [namesArg];
  }, [Array.isArray(namesArg) ? namesArg.join(",") : (namesArg || "")]);

  const [state, setState] = _ucl_useState(() => {
    const cached = _bundleCache.get(_bundleUrl(names, opts));
    return cached
      ? { lists: cached.lists, loading: false, error: null }
      : { lists: {}, loading: true, error: null };
  });

  const fetchNow = _ucl_useCallback(async (force = false) => {
    if (!names.length) {
      setState({ lists: {}, loading: false, error: null });
      return;
    }
    if (force) _bundleCache.delete(_bundleUrl(names, opts));
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

// Bind on window globals so the Babel-standalone harness picks
// them up — same pattern as components.jsx.
window.useChoiceList = useChoiceList;
window._nsrChoiceListUrl = _bundleUrl;
