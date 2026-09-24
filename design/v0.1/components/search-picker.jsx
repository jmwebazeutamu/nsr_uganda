/* global React, Icon, window, document, fetch */
/* Search-and-pick, for the two things the GRM console used to ask
 * people to type from memory.
 *
 * Before this the console asked for:
 *   - a household by Registry ID, as free text, with a ULID for a
 *     placeholder — "01HXY7K3B2N9PVQE4M6FZRWS18". Nobody types a ULID,
 *     and a typo produced a grievance pointing at nothing;
 *   - an assignee from a <select> of four invented names, or a free
 *     text box asking for "username (e.g. parish-chief-3)". An invented
 *     assignee is a grievance nobody is working.
 *
 * Both are search problems over lists the API already serves and
 * already scopes:
 *   /api/v1/data-management/households/?q=   ABAC-scoped to the operator
 *   /api/v1/security/users/?q=       the real user catalogue
 *
 * So this component is a shape, not a data source — callers pass the
 * endpoint and a row renderer. No list of people or places is
 * hardcoded anywhere in it.
 */

const { useState: _spState, useEffect: _spEffect, useRef: _spRef } = React;

const _spDebounce = 250;

const SearchPicker = ({
  endpoint,            // the list URL; `q` is appended
  value,               // the selected object, or null
  onChange,            // (obj|null) => void
  renderRow,           // (obj) => node, for the results list
  renderSelected,      // (obj) => node, for the chosen state
  rowKey = (o) => o.id,
  placeholder = "Search…",
  emptyHint = "No matches.",
  minChars = 2,
  label,
  disabled = false,
}) => {
  const [q, setQ] = _spState("");
  const [rows, setRows] = _spState([]);
  const [state, setState] = _spState("idle");   // idle | loading | error
  const [error, setError] = _spState("");
  const [open, setOpen] = _spState(false);
  const boxRef = _spRef(null);
  const timer = _spRef(null);

  // Close on an outside click, so the results list does not sit over
  // the rest of the form once a choice is made or abandoned.
  _spEffect(() => {
    const onDocClick = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  _spEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const term = q.trim();
    if (term.length < minChars) {
      setRows([]); setState("idle"); setError("");
      return;
    }
    setState("loading");
    timer.current = setTimeout(() => {
      const sep = endpoint.includes("?") ? "&" : "?";
      fetch(`${endpoint}${sep}q=${encodeURIComponent(term)}&page_size=20`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(d => {
          setRows(Array.isArray(d) ? d : (d.results || []));
          setState("idle"); setError(""); setOpen(true);
        })
        .catch(err => {
          // Say so. An empty list that means "the search broke" reads
          // exactly like an empty list that means "no such household".
          setRows([]); setState("error");
          setError(String(err.message || err));
        });
    }, _spDebounce);
    return () => timer.current && clearTimeout(timer.current);
  }, [q, endpoint, minChars]);

  if (value) {
    return (
      <div>
        {label && <div className="t-cap" style={{ marginBottom: 4 }}>{label}</div>}
        <div className="row gap-2" style={{
          alignItems: "center", justifyContent: "space-between",
          border: "1px solid var(--neutral-300)", borderRadius: 6,
          padding: "8px 10px", background: "var(--neutral-50)",
        }}>
          <div style={{ minWidth: 0 }}>{renderSelected ? renderSelected(value) : renderRow(value)}</div>
          {!disabled && (
            <button type="button" className="btn sm" onClick={() => { onChange(null); setQ(""); }}>
              Change
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      {label && <div className="t-cap" style={{ marginBottom: 4 }}>{label}</div>}
      <input
        className="field-text" type="search" style={{ width: "100%" }}
        placeholder={placeholder} value={q} disabled={disabled}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => rows.length && setOpen(true)}
      />
      {state === "loading" && (
        <div className="t-cap muted" style={{ marginTop: 4 }}>Searching…</div>
      )}
      {state === "error" && (
        <div className="t-cap" style={{ marginTop: 4, color: "var(--accent-critical, #b3261e)" }}>
          Search failed: {error}
        </div>
      )}
      {open && state === "idle" && q.trim().length >= minChars && (
        <div style={{
          position: "absolute", zIndex: 20, left: 0, right: 0, marginTop: 4,
          maxHeight: 220, overflowY: "auto", background: "var(--neutral-0)",
          border: "1px solid var(--neutral-300)", borderRadius: 6,
          boxShadow: "0 8px 24px rgba(0,0,0,.12)",
        }}>
          {rows.length === 0 && (
            <div className="t-cap muted" style={{ padding: "10px 12px" }}>{emptyHint}</div>
          )}
          {rows.map(row => (
            <button
              key={rowKey(row)} type="button"
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "8px 12px", border: 0, background: "none",
                cursor: "pointer", borderBottom: "1px solid var(--neutral-100)",
              }}
              onClick={() => { onChange(row); setOpen(false); setQ(""); }}
            >
              {renderRow(row)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

/* The two concrete pickers. Their row shapes are the only thing that
   differs, and both read from an endpoint that already exists — no
   parallel search, no hardcoded directory. */

// The registry app is mounted under /api/v1/data-management/, not at
// the bare /api/v1/ prefix. The first cut of this component guessed
// the latter and every search returned 404 — the picker said "Search
// failed: HTTP 404" and no household could be attached to a grievance.
// tests/contract/test_console_api_paths.py now resolves every
// /api/v1/ path in the design layer against Django's URLconf.
const HOUSEHOLD_SEARCH_API = "/api/v1/data-management/households/";
const USER_SEARCH_API = "/api/v1/security/users/";

const HouseholdPicker = ({ value, onChange, disabled, label = "Household" }) => (
  <SearchPicker
    endpoint={HOUSEHOLD_SEARCH_API}
    value={value} onChange={onChange} disabled={disabled} label={label}
    placeholder="Search by head's name, district, parish, or Registry ID…"
    emptyHint="No household matches — check the spelling, or the record may be outside your area."
    renderRow={(h) => (
      <>
        <div style={{ fontWeight: 600 }}>
          {h.head_member_name || h.head_name || "(no head recorded)"}
        </div>
        <div className="t-cap muted">
          {[h.village_name, h.parish_name, h.sub_county_name, h.district_name]
            .filter(Boolean).join(" · ")}
        </div>
        <div className="t-mono muted" style={{ fontSize: 11 }}>{h.id}</div>
      </>
    )}
  />
);

/* The user picker, moved here from screens-admin.jsx when the GRM
   console needed the same search over the same endpoint. Kept as it
   was — the admin surfaces are built around its behaviour (it lists on
   mount rather than waiting for a query) and this move is about having
   one of it, not about changing it. */
const UserPicker = ({ value, onChange, disabled }) => {
  const [q, setQ] = _spState("");
  const [results, setResults] = _spState([]);
  const [loading, setLoading] = _spState(false);

  _spEffect(() => {
    let cancelled = false;
    setLoading(true);
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    fetch(`${USER_SEARCH_API}${qs}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        setResults(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q]);

  return (
    <div>
      <input
        type="text" value={q} onChange={e => setQ(e.target.value)}
        placeholder="Search by username or name"
        disabled={disabled}
        style={{width:"100%", padding:"8px", border:"1px solid var(--neutral-300)",
                borderRadius:"4px", fontSize:13, marginBottom:8}}
      />
      <div style={{
        border:"1px solid var(--neutral-300)", borderRadius:"4px",
        maxHeight:"160px", overflowY:"auto", background:"var(--neutral-50)",
      }}>
        {loading && <p className="t-cap muted" style={{padding:"8px"}}>Searching…</p>}
        {!loading && results.length === 0 && (
          <p className="t-cap muted" style={{padding:"8px"}}>No users match.</p>
        )}
        {results.map(u => {
          const selected = value?.id === u.id;
          return (
            <button
              key={u.id} type="button"
              onClick={() => onChange(u)}
              disabled={disabled}
              style={{
                display:"block", width:"100%", textAlign:"left",
                padding:"6px 8px", fontSize:13,
                background: selected ? "var(--accent-data-bg)" : "transparent",
                border:"none", borderBottom:"1px solid var(--neutral-200)",
                cursor:"pointer",
              }}
            >
              <strong>{u.username}</strong>
              {u.display_name !== u.username && (
                <span className="muted"> — {u.display_name}</span>
              )}
              {u.groups.length > 0 && (
                <div className="t-cap muted">{u.groups.join(", ")}</div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

window.HOUSEHOLD_SEARCH_API = HOUSEHOLD_SEARCH_API;
window.USER_SEARCH_API = USER_SEARCH_API;
window.SearchPicker = SearchPicker;
window.HouseholdPicker = HouseholdPicker;
window.UserPicker = UserPicker;
