/* global React, Icon, Chip, PageHeader, Field, Modal */
// NSR MIS — Change Request submitter (US-090)
// =========================================================
// Full-page screen for opening a data-update / change request
// against a household OR one of its members. Replaces the
// quick-modal flow for substantive submissions: roster picker,
// multi-field composer, reason, supporting documents, and a
// running review panel — all in one stacked layout.

const { useState: useCR, useMemo: useCRm, useEffect: useCRe, useRef: useCRr } = React;

/* ================================================================
   Household context is supplied by the caller; this file holds no records.
   ================================================================ */
// HH fixture removed — this screen renders only what it is given.
// ROSTER fixture removed — this screen renders only what it is given.
/* ================================================================
   Live field-catalog hook — fetches /api/v1/upd/field-catalog/ on
   mount and exposes the categories + a flat (cat:field → meta)
   lookup. Mirrors the pattern from the deleted change-request-modal:
   the bundle's hardcoded HH_FIELDS/MEM_FIELDS catalog was authored
   against UI groupings (iden/loc/hous) that no longer match the
   backend's storage keys (household/dwelling/utilities/…). The
   server's validate_rows() rejects any (category, field) outside
   its catalog, so we render directly from what the server emits.
   ================================================================ */
const _catalogToFlat = (categories) => {
  const out = {};
  for (const c of categories) {
    for (const f of c.fields) {
      out[`${c.key}:${f.key}`] = {
        category: c.key,
        ...f,
        _categoryLabel: c.label,
        _tone: c.tone || "neutral",
      };
    }
  }
  return out;
};

const useFieldCatalog = () => {
  const [state, setState] = useCR({
    categories: [],
    fieldsFlat: {},
    source: "loading", // "loading" | "live" | "error"
    error: "",
  });
  useCRe(() => {
    let cancelled = false;
    const origin = window.location.origin && window.location.origin !== "null"
      ? window.location.origin
      : "http://localhost";
    const url = new URL("/api/v1/upd/field-catalog/", origin);
    fetch(url.toString(), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`field-catalog HTTP ${r.status}`)))
      .then(data => {
        if (cancelled) return;
        const cats = Array.isArray(data?.categories) ? data.categories : null;
        if (!cats || cats.length === 0) {
          throw new Error("field-catalog returned no categories");
        }
        setState({
          categories: cats,
          fieldsFlat: _catalogToFlat(cats),
          source: "live",
          error: "",
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          categories: [],
          fieldsFlat: {},
          source: "error",
          error: String(err?.message || err),
        });
      });
    return () => { cancelled = true; };
  }, []);
  return state;
};

// Visible categories for a given entity scope. The live catalog tags
// each category with `entity` ("household" | "member"); show only
// those whose entity matches.
const visibleCategoriesFor = (liveCatalog, scope) => {
  const wantMember = scope === "member";
  return (liveCatalog.categories || []).filter(c =>
    wantMember ? c.entity === "member" : c.entity !== "member",
  );
};

const catColor = (c) => ({
  label: c?.label || "—",
  tone: c?.tone || "neutral",
  accent: `var(--accent-${c?.tone || "neutral"})`,
});

/* ================================================================
   Live current-values hook — fetches /api/v1/upd/current-values/
   whenever the operator's pending rows change. Returns
   { values: { "<cat>.<field>": {raw, display} }, source }.
   Same contract the deleted ChangeRequestModal used; the screen's
   CURRENT column reads from `values[`${cat}.${field}`]`.
   ================================================================ */
const useCurrentValues = ({ householdId, entity, memberId, rows }) => {
  const [state, setState] = useCR({ values: {}, source: "idle" });
  // Stable key for the rows array — re-fetch only when the set of
  // (cat, field) pairs actually changes, not on every value edit.
  const fieldsKey = rows.map(r => `${r.cat}.${r.field}`).sort().join("|");
  useCRe(() => {
    if (rows.length === 0) {
      setState({ values: {}, source: "idle" });
      return undefined;
    }
    if (entity === "member" && !memberId) {
      setState({ values: {}, source: "idle" });
      return undefined;
    }
    if (entity !== "member" && !householdId) {
      setState({ values: {}, source: "idle" });
      return undefined;
    }
    const origin = window.location.origin && window.location.origin !== "null"
      ? window.location.origin
      : "http://localhost";
    const url = new URL("/api/v1/upd/current-values/", origin);
    url.searchParams.set("entity", entity);
    if (householdId) url.searchParams.set("household_id", householdId);
    if (entity === "member" && memberId) url.searchParams.set("member_id", memberId);
    fieldsKey.split("|").forEach(f => url.searchParams.append("fields", f));
    let cancelled = false;
    setState(s => ({ ...s, source: "loading" }));
    fetch(url.pathname + url.search, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => {
        if (cancelled) return;
        const next = {};
        for (const [fieldId, item] of Object.entries(data?.values || {})) {
          next[fieldId] = { raw: item.raw, display: item.display };
        }
        setState({ values: next, source: "live" });
      })
      .catch(() => {
        if (!cancelled) setState({ values: {}, source: "error" });
      });
    return () => { cancelled = true; };
  }, [entity, householdId, memberId, fieldsKey]);
  return state;
};

/* ================================================================
   Change types & evidence rules (per SAD §4.4.4 routing matrix)
   ================================================================ */
const CHANGE_TYPES = [
  { value: "correction",   label: "Correction",                  hint: "Fix an error in the record (no real-world event)" },
  { value: "life_event",   label: "Life event",                  hint: "Birth, death, marriage, illness, etc." },
  { value: "verification", label: "Verification update",         hint: "Confirmed by recent field visit" },
  { value: "address_move", label: "Address / move",              hint: "Household has relocated" },
  { value: "roster_change",label: "Roster change",               hint: "Add or remove a member" },
  { value: "asset_change", label: "Asset / housing change",      hint: "Roof, water, land, livestock, etc." },
];

const ROUTING_MATRIX = {
  correction:    { cosmetic: "CDO (parish)",         pmt: "M&E Officer (district)" },
  life_event:    { cosmetic: "CDO (parish)",         pmt: "M&E Officer (district)" },
  verification:  { cosmetic: "CDO (parish)",         pmt: "M&E Officer (district)" },
  address_move:  { cosmetic: "CDO + receiving CDO",  pmt: "District M&E" },
  roster_change: { cosmetic: "CDO (parish)",         pmt: "District M&E" },
  asset_change:  { cosmetic: "CDO (parish)",         pmt: "District M&E" },
};
const routingFor = (t, pmt) => (ROUTING_MATRIX[t] || ROUTING_MATRIX.correction)[pmt ? "pmt" : "cosmetic"];

// SEED_DOCS fixture removed — see docs/console_mock_data_audit.md.
// HISTORY fixture removed — see docs/console_mock_data_audit.md.
/* ================================================================
   Helpers
   ================================================================ */
const initials = (s) => (s || "").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();

const fieldDef = (fieldsFlat, cat, key) => fieldsFlat[`${cat}:${key}`] || null;

/* ================================================================
   Section header (numbered)
   ================================================================ */
const NumberedSection = ({ n, title, sub, right, locked, children }) => (
  <section className="card cr-section" data-locked={locked ? "1" : "0"}
    style={{ marginBottom: 16, opacity: locked ? 0.55 : 1, position:'relative' }}>
    <header style={{
      display:"flex", alignItems:"center", gap:14,
      padding:"16px 20px", borderBottom:"1px solid var(--neutral-200)",
    }}>
      <div style={{
        width:28, height:28, borderRadius:"50%",
        background:"var(--primary-900)", color:"#fff",
        display:"grid", placeItems:"center",
        fontSize:13, fontWeight:600, flex:"0 0 auto",
      }}>{n}</div>
      <div style={{flex:1, minWidth:0}}>
        <h3 className="t-h3" style={{margin:0}}>{title}</h3>
        {sub && <div className="t-cap mt-1">{sub}</div>}
      </div>
      {right}
    </header>
    {children}
  </section>
);

/* ================================================================
   Top — Household summary strip
   ================================================================ */
// Household context for the change-request flow. It used to render the
// HH fixture — a complete household with a head's name, village, PMT
// score, band and programme list, none of it real. Worse, the id it
// carried EXISTS in production, so the submit path's `householdId ||
// HH.id` fallback could have filed a change request against a real
// household the operator was never looking at.
//
// It now renders only what the caller passes. Nothing is inferred.
const HHContextStrip = ({ householdId, household }) => (
  <div className="card" style={{
    padding:"16px 20px",
    display:"grid", gridTemplateColumns:"auto 1.4fr 1fr 1fr 1fr auto", gap:24,
    alignItems:"center", marginBottom:16,
  }}>
    <div style={{
      width:44, height:44, borderRadius:"50%",
      background:"var(--primary-100)", color:"var(--primary-900)",
      display:"grid", placeItems:"center", fontSize:14, fontWeight:600,
    }}>{household?.head ? initials(household.head) : "—"}</div>
    <div>
      <div style={{fontWeight:600, fontSize:15, color:"var(--neutral-900)"}}>
        {household?.head || "—"}
      </div>
      <div className="t-cap t-mono" style={{marginTop:2}}>
        {householdId ? householdId.slice(0, 22) + "…" : "no household"}
      </div>
    </div>
    <div>
      <div className="t-bodysm" style={{fontWeight:500}}>
        {household?.village || household?.parish
          ? `${household.village || "—"} · ${household.parish || "—"}`
          : "—"}
      </div>
      <div className="t-cap mt-1">
        {household?.district || household?.subreg
          ? `${household.district || "—"} · ${household.subreg || "—"}`
          : "—"}
      </div>
    </div>
    <div>
      <div className="row gap-2 mt-1">
        <Chip tone="data">{household?.status || "—"}</Chip>
      </div>
      <div className="t-cap mt-1">
        {household?.lastUpdate ? `Last updated ${household.lastUpdate}` : ""}
      </div>
    </div>
    <div>
      <div className="row gap-2" style={{alignItems:"baseline"}}>
        <span className="t-mono" style={{fontSize:15, fontWeight:600}}>
          {typeof household?.pmt === "number" ? household.pmt.toFixed(3) : "—"}
        </span>
        {household?.band && <Chip size="sm" tone="eligibility">{household.band}</Chip>}
      </div>
      <div className="t-cap mt-1">
        {household?.programmes?.length ? household.programmes.join(" · ") : "—"}
      </div>
    </div>
  </div>
);

/* ================================================================
   Roster picker (member-scope only)
   ================================================================ */
const RosterPicker = ({ selected, onSelect, roster }) => {
  // No ROSTER fallback — an invented roster would let an operator pick a
  // member who does not exist and file a change request about them.
  const rows = Array.isArray(roster) ? roster : [];
  return (
  <div style={{padding:0}}>
    <div className="card-toolbar" style={{borderBottom:0, paddingTop:0, paddingBottom:0}}>
      <span className="t-cap">SELECT THE MEMBER THIS CHANGE APPLIES TO</span>
      <div style={{flex:1}}/>
      <span className="t-cap">{rows.length} members on roster</span>
    </div>
    <div style={{overflowX:"auto"}}>
    <table className="tbl" style={{width:"100%"}}>
      <thead>
        <tr>
          <th style={{width:40}}></th>
          <th style={{width:36}}>#</th>
          <th>Name</th>
          <th>Relation to head</th>
          <th>Sex</th>
          <th>Age</th>
          <th>NIN</th>
          <th style={{textAlign:"right"}}></th>
        </tr>
      </thead>
      <tbody>
        {rows.map(m => {
          const active = selected?.id ? selected.id === m.id : selected?.line === m.line;
          return (
            <tr key={m.id || m.line}
              onClick={() => onSelect(m)}
              style={{cursor:"pointer", background: active ? "var(--primary-100)" : undefined}}>
              <td>
                <span style={{
                  display:"inline-grid", placeItems:"center",
                  width:18, height:18, borderRadius:"50%",
                  border: active ? "5px solid var(--primary-900)" : "1.5px solid var(--neutral-300)",
                  background:"#fff", transition:"border-width 0.1s",
                }}/>
              </td>
              <td className="t-cap t-mono">{String(m.line).padStart(2, "0")}</td>
              <td>
                <div style={{display:"flex", alignItems:"center", gap:10}}>
                  <div style={{
                    width:28, height:28, borderRadius:"50%",
                    background:"var(--neutral-100)", color:"var(--neutral-700)",
                    display:"grid", placeItems:"center", fontSize:11, fontWeight:600,
                  }}>{initials(m.name)}</div>
                  <div>
                    <div style={{fontWeight:500}}>{m.name}</div>
                    {m.rel === "Head" && <div className="t-cap">Head of household</div>}
                  </div>
                </div>
              </td>
              <td><Chip size="sm" tone={m.rel === "Head" ? "data" : "neutral"}>{m.rel}</Chip></td>
              <td><Chip size="sm">{m.sex}</Chip></td>
              <td className="t-num">{m.age}</td>
              <td className="t-mono" style={{fontSize:12}}>
                {m.ninStatus === "verified"
                  ? <><span>{m.nin}</span> <Icon name="check" size={11} color="var(--accent-data)"/></>
                  : <span className="muted">not on file</span>}
              </td>
              <td style={{textAlign:"right"}}>
                {active && <Chip size="sm" tone="update">selected</Chip>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
  </div>
  );
};

/* ================================================================
   Field-changes section
   ================================================================ */
const FieldComposer = ({ scope, member, rows, setRows, liveCatalog, currentValues }) => {
  const [composer, setComposer] = useCR(null); // { cat, field } | null
  const newValueRefs = useCRr({});
  const valid = scope === "household" || !!member;

  const visibleCats = useCRm(() => visibleCategoriesFor(liveCatalog, scope), [liveCatalog, scope]);
  const catByKey = useCRm(() => {
    const m = {};
    for (const c of visibleCats) m[c.key] = c;
    return m;
  }, [visibleCats]);

  const usedKeys = new Set(rows.map(r => `${r.cat}.${r.field}`));

  const addRow = (cat, field) => {
    const uid = `${cat}.${field}.${Date.now().toString(36)}`;
    setRows(prev => [...prev, { uid, cat, field, value: "" }]);
    setComposer(null);
    setTimeout(() => newValueRefs.current[uid]?.focus(), 30);
  };
  const removeRow = (uid) => setRows(prev => prev.filter(r => r.uid !== uid));
  const setVal = (uid, v) => setRows(prev => prev.map(r => r.uid === uid ? { ...r, value: v } : r));

  // Quick-add chips — first PMT-flagged field of each visible category,
  // capped at 6 so the row doesn't wrap. Falls back to first field
  // when no PMT field exists in the category.
  const quick = useCRm(() => {
    const out = [];
    for (const c of visibleCats) {
      const pmtFirst = c.fields.find(f => f.pmt) || c.fields[0];
      if (pmtFirst) out.push([c.key, pmtFirst.key]);
      if (out.length >= 6) break;
    }
    return out;
  }, [visibleCats]);

  const grouped = useCRm(() => {
    const g = {};
    rows.forEach(r => { (g[r.cat] = g[r.cat] || []).push(r); });
    return visibleCats.filter(c => g[c.key]).map(c => ({ key: c.key, rows: g[c.key] }));
  }, [rows, visibleCats]);

  if (liveCatalog.source === "loading") {
    return (
      <div className="cr-empty" style={emptyStyle}>
        <Icon name="clock" size={22} color="var(--neutral-500)"/>
        <div>
          <div style={{fontWeight:600}}>Loading field catalog…</div>
          <div className="t-bodysm muted">Fetching the latest fields from <span className="t-mono">/api/v1/upd/field-catalog/</span>.</div>
        </div>
      </div>
    );
  }
  if (liveCatalog.source === "error") {
    return (
      <div className="cr-empty" style={{...emptyStyle, borderColor:"var(--accent-danger)", background:"var(--accent-danger-bg)"}}>
        <Icon name="alert" size={22} color="var(--accent-danger)"/>
        <div>
          <div style={{fontWeight:600, color:"var(--accent-danger)"}}>Couldn't load field catalog</div>
          <div className="t-bodysm muted">{liveCatalog.error || "Server unreachable"} — log into <code>/admin/</code> first, then reload.</div>
        </div>
      </div>
    );
  }
  if (!valid) {
    return (
      <div className="cr-empty" style={emptyStyle}>
        <Icon name="users" size={22} color="var(--neutral-500)"/>
        <div>
          <div style={{fontWeight:600}}>Select a member first</div>
          <div className="t-bodysm muted">
            Member-level changes must be linked to a specific person. Pick a row in the roster above to continue.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{padding:20}}>
      {rows.length === 0 && (
        <>
          <div className="cr-empty" style={emptyStyle}>
            <Icon name="edit" size={22} color="var(--neutral-500)"/>
            <div>
              <div style={{fontWeight:600}}>No field changes yet</div>
              <div className="t-bodysm muted">
                Add at least one field to submit. You can bundle several changes across categories into one request.
              </div>
            </div>
          </div>
          <div style={{display:"flex", flexWrap:"wrap", gap:8, marginTop:14, alignItems:"center"}}>
            <span className="t-cap" style={{marginRight:4}}>QUICK ADD</span>
            {quick.map(([c, f]) => {
              const fd = fieldDef(liveCatalog.fieldsFlat, c, f);
              if (!fd) return null;
              const col = catColor(catByKey[c]);
              return (
                <button key={`${c}.${f}`} className="cr-chip-btn" onClick={() => addRow(c, f)}>
                  <span style={{width:6, height:6, borderRadius:"50%", background: col.accent, marginRight:6}}/>
                  {fd.label}
                  <Icon name="plus" size={11} style={{marginLeft:6}}/>
                </button>
              );
            })}
          </div>
        </>
      )}

      {/* Grouped change rows */}
      {grouped.map(g => {
        const cat = catColor(catByKey[g.key]);
        return (
          <div key={g.key} style={{
            border:"1px solid var(--neutral-200)",
            borderLeft: `3px solid ${cat.accent}`,
            borderRadius: 4,
            marginBottom: 12,
          }}>
            <div style={{
              display:"flex", alignItems:"center", gap:8,
              padding:"10px 14px",
              background:"var(--neutral-50)",
              borderBottom:"1px solid var(--neutral-200)",
            }}>
              <span style={{width:8, height:8, borderRadius:"50%", background: cat.accent}}/>
              <strong className="t-bodysm">{cat.label}</strong>
              <span className="t-cap">{g.rows.length} {g.rows.length === 1 ? "field" : "fields"}</span>
              <div style={{flex:1}}/>
              {g.rows.some(r => fieldDef(liveCatalog.fieldsFlat, r.cat, r.field)?.pmt) && (
                <Chip size="sm" tone="eligibility"><Icon name="target" size={10}/> PMT</Chip>
              )}
            </div>
            {g.rows.map(r => {
              const fd = fieldDef(liveCatalog.fieldsFlat, r.cat, r.field);
              if (!fd) return null;
              const cv = currentValues?.[`${r.cat}.${r.field}`];
              const now = cv?.display ?? cv?.raw ?? "";
              return (
                <div key={r.uid} style={{
                  display:"grid",
                  gridTemplateColumns:"minmax(180px, 1.1fr) minmax(140px, 1fr) 22px minmax(180px, 1.2fr) 32px",
                  gap:14, alignItems:"center",
                  padding:"12px 14px",
                  borderBottom:"1px solid var(--neutral-200)",
                }}>
                  <div>
                    <div className="t-bodysm" style={{fontWeight:500, color:"var(--neutral-900)"}}>{fd.label}</div>
                    <div className="t-cap t-mono">{r.cat}.{r.field}{fd.pmt ? " · PMT" : ""}</div>
                  </div>
                  <div>
                    <div className="t-cap">CURRENT</div>
                    <div style={{
                      marginTop:2, padding:"6px 10px",
                      background:"var(--neutral-50)",
                      border:"1px solid var(--neutral-200)",
                      borderRadius:4, fontSize:13.5, color:"var(--neutral-700)",
                      minHeight:32, display:"flex", alignItems:"center",
                    }}>{now || <span className="muted">—</span>}</div>
                  </div>
                  <div style={{display:"grid", placeItems:"center", color:"var(--neutral-500)"}}>
                    <Icon name="arrowRight" size={16}/>
                  </div>
                  <div>
                    <div className="t-cap">NEW VALUE <span style={{color:"var(--accent-danger)"}}>*</span></div>
                    {(fd.type === "select" || fd.type === "boolean") ? (
                      <select className="field-select" style={{marginTop:2}}
                        ref={el => newValueRefs.current[r.uid] = el}
                        value={r.value} onChange={(e) => setVal(r.uid, e.target.value)}>
                        <option value="">Select…</option>
                        {(fd.options || []).map(o => (
                          <option key={String(o.code)} value={String(o.code)}>{o.label}</option>
                        ))}
                      </select>
                    ) : (
                      <input className="field-input" style={{marginTop:2}}
                        ref={el => newValueRefs.current[r.uid] = el}
                        type={fd.type === "number" ? "number" : fd.type === "date" ? "date" : "text"}
                        value={r.value} onChange={(e) => setVal(r.uid, e.target.value)}
                        placeholder="What the field should be"/>
                    )}
                  </div>
                  <button className="icon-btn" onClick={() => removeRow(r.uid)} aria-label="Remove field">
                    <Icon name="x" size={14}/>
                  </button>
                </div>
              );
            })}
          </div>
        );
      })}

      {/* Composer */}
      {composer ? (
        <div style={{
          padding:14, marginTop: rows.length ? 0 : 14,
          border:"1px dashed var(--primary-700)",
          background:"var(--primary-100)",
          borderRadius:4,
        }}>
          <div className="t-cap" style={{marginBottom:8, color:"var(--primary-900)", fontWeight:600}}>ADD A FIELD CHANGE</div>
          <div style={{display:"grid", gridTemplateColumns:"1fr 1.4fr auto auto", gap:10}}>
            <select className="field-select" value={composer.cat}
              onChange={(e) => setComposer({ cat: e.target.value, field: "" })}>
              <option value="">Category…</option>
              {visibleCats.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
            <select className="field-select" value={composer.field} disabled={!composer.cat}
              onChange={(e) => setComposer({ ...composer, field: e.target.value })}>
              <option value="">{composer.cat ? "Field…" : "Pick a category first"}</option>
              {((catByKey[composer.cat]?.fields) || []).map(f => {
                const used = usedKeys.has(`${composer.cat}.${f.key}`);
                return (
                  <option key={f.key} value={f.key} disabled={used}>
                    {f.label}{f.pmt ? " · PMT" : ""}{used ? " (already added)" : ""}
                  </option>
                );
              })}
            </select>
            <button className="btn btn-primary" disabled={!composer.cat || !composer.field}
              onClick={() => addRow(composer.cat, composer.field)}>
              <Icon name="plus" size={13}/> Add
            </button>
            <button className="btn btn-ghost" onClick={() => setComposer(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="cr-add-btn" onClick={() => setComposer({ cat: "", field: "" })}
          style={addBtnStyle}>
          <Icon name="plus" size={14}/> Add {rows.length ? "another" : "a"} field change
        </button>
      )}
    </div>
  );
};

const emptyStyle = {
  display:"flex", alignItems:"center", gap:14,
  padding:"20px 16px",
  border:"1px dashed var(--neutral-300)",
  borderRadius:4,
  background:"var(--neutral-50)",
};

const addBtnStyle = {
  display:"flex", alignItems:"center", gap:6,
  marginTop:14, padding:"10px 14px",
  width:"100%",
  border:"1px dashed var(--neutral-300)",
  borderRadius:4,
  background:"var(--neutral-0)",
  color:"var(--neutral-700)",
  fontWeight:500, fontSize:13,
  cursor:"pointer",
  justifyContent:"center",
};

Object.assign(window, { ChangeRequestScreen: null }); // populated below
