/* global React */
// US-S23-012 — minimal API client for design-harness screens.
//
// Centralises CSRF + credentials + JSON parsing + error shape so
// each screen doesn't reinvent it. The harness mounts under
// /console/ (same-origin with Django) so session cookies and CSRF
// tokens flow through naturally. Bound on window so Babel-standalone
// JSX picks it up.
//
// Usage:
//   const partners = await window.nsrApi.get("/api/v1/partners/");
//   const draft = await window.nsrApi.post("/api/v1/dsas/", { ... });
//
// Errors are thrown as `Error` with the response status attached as
// `.status` and the parsed body (if any) as `.body`.

const _readCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

const _headers = (extra = {}) => {
  const out = {
    "Accept": "application/json",
    ...extra,
  };
  const csrf = _readCsrf();
  if (csrf) out["X-CSRFToken"] = csrf;
  return out;
};

const _request = async (method, url, body) => {
  const init = {
    method,
    credentials: "same-origin",
    headers: _headers(body !== undefined ? { "Content-Type": "application/json" } : {}),
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const r = await fetch(url, init);
  let parsed = null;
  const text = await r.text();
  if (text) {
    try { parsed = JSON.parse(text); } catch (e) { parsed = text; }
  }
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status} on ${method} ${url}`);
    err.status = r.status;
    err.body = parsed;
    throw err;
  }
  return parsed;
};

const nsrApi = {
  get: (url) => _request("GET", url),
  post: (url, body) => _request("POST", url, body || {}),
  patch: (url, body) => _request("PATCH", url, body || {}),
  delete: (url) => _request("DELETE", url),
};

window.nsrApi = nsrApi;


// Convenience hook: fetch a resource on mount + refetch on demand.
// Returns [data, { loading, error, refresh }].
const { useState: _api_useState, useEffect: _api_useEffect, useCallback: _api_useCallback } = React;

const useApi = (url, { skip = false } = {}) => {
  const [state, setState] = _api_useState({
    data: null, loading: !skip, error: null,
  });
  const fetchNow = _api_useCallback(async () => {
    if (!url || skip) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await nsrApi.get(url);
      setState({ data, loading: false, error: null });
    } catch (err) {
      setState({ data: null, loading: false, error: String(err.message || err) });
    }
  }, [url, skip]);
  _api_useEffect(() => { fetchNow(); }, [fetchNow]);
  return [state.data, { loading: state.loading, error: state.error, refresh: fetchNow }];
};

window.useApi = useApi;
