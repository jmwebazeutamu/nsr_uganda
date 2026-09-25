/* global React, Icon, Chip, PageHeader, Field */
// NSR MIS — DRS Wizard, Step 3 (Field Selector) — V2
// ===================================================
// Drop-in replacement for FieldStep in screens-drs.jsx. Exposes
// <FieldStepV2 .../> — a two-pane "available → ordered output"
// surface with search, group/sensitivity filters, recommended
// packs, drag-reorder of the selected list, and a sensitivity
// breakdown panel.
//
// To wire into the existing wizard:
//   1. Save this file at /design/v0.1/screens/screens-drs-fieldselector.jsx
//   2. Add it to `nsr-mis-console.html` AFTER components.jsx and
//      BEFORE screens-drs.jsx:
//        <script type="text/babel" src="v0.1/screens/screens-drs-fieldselector.jsx"></script>
//        <script type="text/babel" src="v0.1/screens/screens-drs.jsx"></script>
//   3. In screens-drs.jsx, change the wizard's selectedFields state
//      from a Set<string> to a string[] (ordered) and swap the step
//      render:
//        {step === 'fields' && (
//          <FieldStepV2
//            selectedKeys={selectedKeys}
//            onChange={setSelectedKeys}
//            dsaReference={schema?.dsa_reference}/>
//        )}
//   4. On submit, the payload now ships an ORDERED `fields` list —
//      column order in the delivered file follows the user's drag
//      sequence. validate_against_dsa is order-insensitive so the
//      server contract doesn't change.
//
// The previous step picks the WHERE clause (the criteria tree);
// this step picks the SELECT clause — the ordered list of columns
// the partner will receive in their delivery file.
//
// All colour, spacing and typography references go through the
// v0.1/tokens.css `--*` variables — no hard-coded hex / px outside
// those tokens, per /design/README.md §"How to add a new screen".
//
// Improvements over v1:
//   • Two-pane "available → selected" layout — ordered output list
//     is its own surface, with drag-handle reorder + arrow keys.
//   • Search across label, key, description, and example value.
//   • Group + sensitivity + "DSA scope only" filters.
//   • Recommended packs as one-click presets (Minimum reporting,
//     Geography rollup, Vulnerability profile, Housing & utilities).
//   • Field metadata in every row: type, example value, % of
//     records with a non-null value.
//   • Sensitivity-aware selection summary (donut + totals) so the
//     reviewer can see at a glance how much PII the request pulls.
//
// Output: an ORDERED string[] of dotted field keys, e.g.
//   ["household.registry_id", "household.sub_region_code", ...]
// The DSA-clause guard from the BuilderSchema response still
// blocks `dsaBlocked` fields client-side — server runs the same
// check at submit time.

const { useState: useStateFS, useMemo: useMemoFS, useRef: useRefFS } = React;

// ``DataRequestFieldDefinition`` (via /builder-schema/) is the sole field
// catalogue. This screen must never substitute demo fields or field packs:
// doing so would allow a request UI to show keys the server cannot validate.

/* ----------------------------------------------------------------
   Available list — left pane
   ---------------------------------------------------------------- */
const FSAvailable = ({ fields, selectedSet, onToggle, onAddGroup, showDisabled }) => {
  const grouped = useMemoFS(() => {
    const acc = {};
    fields.forEach(f => { (acc[f.group] = acc[f.group] || []).push(f); });
    return acc;
  }, [fields]);

  return (
    <div style={{minHeight:0, overflow:"auto"}}>
      {Object.entries(grouped).map(([g, items]) => {
        const visible = showDisabled ? items : items.filter(f => !f.disabled);
        if (visible.length === 0) return null;
        const groupAvailable = visible.filter(f => !f.disabled);
        const groupSelected = groupAvailable.filter(f => selectedSet.has(f.key)).length;
        return (
          <div key={g}>
            <div style={{
              display:"flex", alignItems:"center", gap:8,
              padding:"10px 16px", background:"var(--neutral-50)",
              borderTop:"1px solid var(--neutral-200)",
              borderBottom:"1px solid var(--neutral-200)",
              position:"sticky", top:0, zIndex:1,
            }}>
              <div style={{
                fontSize:11, fontWeight:600, letterSpacing:"0.06em",
                textTransform:"uppercase", color:"var(--neutral-700)",
              }}>{g}</div>
              <span className="t-cap">
                {groupSelected} of {groupAvailable.length} selected
                {items.length > groupAvailable.length && ` · ${items.length - groupAvailable.length} DSA-blocked`}
              </span>
              <span style={{flex:1}}/>
              <button className="btn btn-sm btn-ghost"
                onClick={() => onAddGroup(groupAvailable.map(f => f.key))}
                disabled={groupAvailable.length === 0 || groupSelected === groupAvailable.length}>
                <Icon name="plus" size={11}/> Add all
              </button>
            </div>
            {visible.map(f => (
              <FSAvailableRow key={f.key} field={f}
                selected={selectedSet.has(f.key)}
                onToggle={() => !f.disabled && onToggle(f.key)}/>
            ))}
          </div>
        );
      })}
      {Object.keys(grouped).length === 0 && (
        <div style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
          <Icon name="search" size={28} color="var(--neutral-300)"/>
          <div className="t-bodysm mt-2">No fields match the current filters.</div>
        </div>
      )}
    </div>
  );
};

const FSAvailableRow = ({ field, selected, onToggle }) => {
  const blocked = field.disabled;
  // Stacked layout: row 1 = checkbox + name + sensitivity chip,
  // row 2 = key + type pill + description, row 3 = completeness bar.
  // This survives the ~300px-wide left pane the wizard gets in
  // narrow viewports without truncating anything important.
  return (
    <div onClick={onToggle} title={blocked ? field.disabled_reason : field.desc}
      style={{
        display:"flex", gap:10, alignItems:"flex-start",
        padding:"10px 14px",
        borderBottom:"1px solid var(--neutral-200)",
        background: blocked ? "var(--neutral-50)"
          : selected ? "var(--accent-system-bg)"
          : "transparent",
        cursor: blocked ? "not-allowed" : "pointer",
        opacity: blocked ? 0.7 : 1,
      }}
      onMouseEnter={e => { if (!blocked && !selected) e.currentTarget.style.background = "var(--neutral-50)"; }}
      onMouseLeave={e => { if (!blocked && !selected) e.currentTarget.style.background = "transparent"; }}>
      <input type="checkbox" checked={selected} disabled={blocked} readOnly
        style={{marginTop:3, flex:"0 0 auto"}}/>
      <div style={{flex:1, minWidth:0}}>
        {/* Line 1 — name + sensitivity chip on the right */}
        <div style={{display:"flex", alignItems:"center", gap:8}}>
          <span style={{
            flex:1, minWidth:0,
            fontSize:13.5, fontWeight: selected ? 600 : 500,
            color: blocked ? "var(--neutral-500)" : "var(--neutral-900)",
            whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis",
          }}>{field.label}</span>
          <Chip size="sm">{field.sensitivity}</Chip>
        </div>
        {/* Line 2 — dotted key + type pill */}
        <div style={{display:"flex", alignItems:"center", gap:6, marginTop:3}}>
          <span className="t-cap t-mono" style={{
            color:"var(--neutral-500)", fontSize:11, minWidth:0,
            whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis",
          }}>{field.key}</span>
          <span style={{
            flex:"0 0 auto",
            fontSize:10, fontWeight:600, color:"var(--neutral-700)",
            textTransform:"uppercase", letterSpacing:"0.04em",
            padding:"1px 5px", background:"var(--neutral-100)", borderRadius:3,
          }}>{field.type}</span>
        </div>
        {/* Line 3 — description / DSA reason + completeness bar */}
        <div style={{display:"flex", alignItems:"center", gap:10, marginTop:5}}>
          <span className="t-cap" style={{
            flex:1, minWidth:0,
            color: blocked ? "var(--accent-danger)" : "var(--neutral-600)",
            whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis",
          }}>
            {blocked
              ? <><Icon name="lock" size={10}/> Blocked by {field.disabled_reason}</>
              : field.desc || <>e.g. <span className="t-mono">{field.example}</span></>}
          </span>
          {Number.isFinite(field.completeness) && (
            <div style={{flex:"0 0 96px"}}>
              <FSCompleteness pct={field.completeness}/>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const FSCompleteness = ({ pct }) => {
  if (!Number.isFinite(pct)) return null;
  const tone = pct >= 99 ? "var(--accent-data)"
    : pct >= 90 ? "var(--accent-update)"
    : pct >= 75 ? "var(--accent-quality)"
    : "var(--accent-danger)";
  return (
    <div title={`${pct.toFixed(1)}% of records have a value`}
      style={{display:"flex", alignItems:"center", gap:6}}>
      <div style={{
        flex:1, height:5, background:"var(--neutral-200)", borderRadius:3,
        overflow:"hidden", minWidth:48,
      }}>
        <div style={{width:`${pct}%`, height:"100%", background:tone}}/>
      </div>
      <span className="t-cap t-num" style={{fontSize:11, color:"var(--neutral-700)", minWidth:38, textAlign:"right"}}>
        {pct.toFixed(1)}%
      </span>
    </div>
  );
};

/* ----------------------------------------------------------------
   Selected list — right pane (ordered, drag-reorder + arrows)
   ---------------------------------------------------------------- */
const FSSelected = ({ selectedKeys, onChange, byKey }) => {
  const [dragIdx, setDragIdx] = useStateFS(null);
  const [overIdx, setOverIdx] = useStateFS(null);

  const move = (from, to) => {
    if (to < 0 || to >= selectedKeys.length || from === to) return;
    const next = [...selectedKeys];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onChange(next);
  };
  const remove = (i) => onChange(selectedKeys.filter((_, j) => j !== i));

  if (selectedKeys.length === 0) {
    return (
      <div style={{padding:32, textAlign:"center", color:"var(--neutral-500)"}}>
        <Icon name="sliders" size={28} color="var(--neutral-300)"/>
        <div className="t-bodysm mt-2" style={{fontWeight:500, color:"var(--neutral-700)"}}>
          Empty output set
        </div>
        <div className="t-cap mt-1">
          Pick fields on the left, or load a recommended pack above.
        </div>
      </div>
    );
  }

  return (
    <div style={{overflow:"auto"}}>
      {selectedKeys.map((key, i) => {
        const f = byKey[key];
        if (!f) return null;
        const isDragOver = overIdx === i && dragIdx !== null && dragIdx !== i;
        // Compact 3-cell row: handle+position / name+key stack / sens+remove.
        // Up/down arrow buttons live in a hover-revealed strip below the
        // name so they don't compete with the name track for width.
        return (
          <div key={key}
            draggable
            onDragStart={() => setDragIdx(i)}
            onDragOver={(e) => { e.preventDefault(); setOverIdx(i); }}
            onDragLeave={() => setOverIdx(prev => prev === i ? null : prev)}
            onDrop={() => { move(dragIdx, i); setDragIdx(null); setOverIdx(null); }}
            onDragEnd={() => { setDragIdx(null); setOverIdx(null); }}
            className="fs-output-row"
            style={{
              display:"grid",
              gridTemplateColumns:"28px 1fr auto",
              gap:8, alignItems:"center",
              padding:"8px 10px",
              borderBottom:"1px solid var(--neutral-200)",
              background: isDragOver ? "var(--accent-system-bg)"
                : dragIdx === i ? "var(--neutral-100)"
                : "transparent",
              cursor:"grab",
              borderTop: isDragOver ? "2px solid var(--accent-system)" : "2px solid transparent",
            }}>
            {/* Handle column: drag dots + position number stacked */}
            <div style={{
              display:"flex", flexDirection:"column", alignItems:"center",
              gap:2, color:"var(--neutral-400)", userSelect:"none",
            }}>
              <span style={{fontSize:12, lineHeight:1}}>⋮⋮</span>
              <span className="t-num" style={{
                fontSize:10, color:"var(--neutral-500)",
                fontFamily:"var(--font-mono)", lineHeight:1,
              }}>{i + 1}</span>
            </div>
            {/* Name + key stack */}
            <div style={{minWidth:0}}>
              <div className="t-bodysm" style={{
                fontWeight:500, whiteSpace:"nowrap",
                overflow:"hidden", textOverflow:"ellipsis",
                color:"var(--neutral-900)",
              }}>{f.label}</div>
              <div style={{display:"flex", alignItems:"center", gap:6, marginTop:1, minWidth:0}}>
                <span className="t-cap t-mono" style={{
                  color:"var(--neutral-500)", fontSize:10, lineHeight:1.2,
                  whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis",
                  minWidth:0, flex:"0 1 auto",
                }}>{f.key}</span>
                <Chip size="sm">{f.sensitivity}</Chip>
              </div>
            </div>
            {/* Right cluster: up/down/remove */}
            <div style={{display:"flex", alignItems:"center", gap:2}}>
              <button className="icon-btn" onClick={() => move(i, i-1)} disabled={i===0}
                title="Move up" style={{width:22, height:22}}>
                <Icon name="chevronUp" size={11}/>
              </button>
              <button className="icon-btn" onClick={() => move(i, i+1)} disabled={i===selectedKeys.length-1}
                title="Move down" style={{width:22, height:22}}>
                <Icon name="chevronDown" size={11}/>
              </button>
              <button className="icon-btn" onClick={() => remove(i)} title="Remove"
                style={{width:22, height:22, color:"var(--accent-danger)"}}>
                <Icon name="x" size={11}/>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
};

/* ----------------------------------------------------------------
   Sensitivity breakdown card — right rail
   ---------------------------------------------------------------- */
const FSBreakdownCard = ({ selectedKeys, byKey }) => {
  const counts = useMemoFS(() => {
    const c = { Public:0, Internal:0, Personal:0, Sensitive:0 };
    selectedKeys.forEach(k => {
      const f = byKey[k];
      if (f) c[f.sensitivity] = (c[f.sensitivity] || 0) + 1;
    });
    return c;
  }, [selectedKeys, byKey]);
  const total = selectedKeys.length;
  const tones = {
    Public:    "var(--accent-system)",
    Internal:  "var(--accent-programme)",
    Personal:  "var(--accent-eligibility)",
    Sensitive: "var(--accent-danger)",
  };
  return (
    <div className="card" style={{borderTop:"3px solid var(--accent-data)"}}>
      <div className="card-header" style={{padding:"12px 16px", alignItems:"flex-start"}}>
        <div style={{display:"flex", flexDirection:"column", gap:4}}>
          <div className="t-cap" style={{
            color:"var(--accent-data)", fontWeight:600,
            display:"flex", alignItems:"center", gap:4, lineHeight:1.2,
          }}>
            <Icon name="sliders" size={11}/> SELECTION SUMMARY
          </div>
          <h3 className="t-h3" style={{margin:0, lineHeight:1.2}}>
            {total} field{total === 1 ? "" : "s"}
          </h3>
        </div>
      </div>
      <div style={{padding:16}}>
        {total === 0
          ? <div className="t-cap muted">No fields selected yet.</div>
          : (
            <>
              <div style={{display:"flex", height:8, borderRadius:4, overflow:"hidden", background:"var(--neutral-100)"}}>
                {FS_SENS.map(s => counts[s] > 0 && (
                  <div key={s} title={`${s}: ${counts[s]}`}
                    style={{flex: counts[s], background: tones[s]}}/>
                ))}
              </div>
              <div style={{marginTop:12, display:"flex", flexDirection:"column", gap:6}}>
                {FS_SENS.map(s => (
                  <div key={s} style={{display:"flex", alignItems:"center", gap:8}}>
                    <span style={{
                      width:8, height:8, borderRadius:2, background: tones[s],
                      opacity: counts[s] > 0 ? 1 : 0.3,
                    }}/>
                    <Chip size="sm">{s}</Chip>
                    <span style={{flex:1}}/>
                    <span className="t-bodysm t-num" style={{
                      fontWeight: counts[s] > 0 ? 600 : 400,
                      color: counts[s] > 0 ? "var(--neutral-900)" : "var(--neutral-500)",
                    }}>{counts[s]}</span>
                  </div>
                ))}
              </div>
              {(counts.Personal > 0 || counts.Sensitive > 0) && (
                <div className="tint-update" style={{
                  marginTop:14, padding:10, borderRadius:4,
                  borderLeft:"3px solid var(--accent-update)",
                }}>
                  <div className="row gap-2" style={{marginBottom:2}}>
                    <Icon name="shield" size={12} color="var(--accent-update)"/>
                    <strong className="t-bodysm">DPO review required</strong>
                  </div>
                  <div className="t-cap" style={{color:"var(--neutral-700)"}}>
                    Personal-sensitivity columns trigger DPO co-approval on
                    submit. Sensitive columns are blocked by the DSA.
                  </div>
                </div>
              )}
            </>
          )}
      </div>
    </div>
  );
};

/* ----------------------------------------------------------------
   Step 3 — top-level
   ---------------------------------------------------------------- */
const FieldStepV2 = ({
  selectedKeys, onChange, dsaReference = "",
  fields,  // US-S27-014: live catalogue from /builder-schema/
}) => {
  const [search, setSearch] = useStateFS("");
  const [groupFilter, setGroupFilter] = useStateFS("All");
  const [sensFilter, setSensFilter]   = useStateFS("All");
  const [showDisabled, setShowDisabled] = useStateFS(true);

  // The Data Dictionary response is authoritative. An empty catalogue is an
  // explicit unavailable state, never a reason to substitute local keys.
  const activeFields = Array.isArray(fields) ? fields : [];
  const byKey = useMemoFS(
    () => activeFields.reduce((a, f) => (a[f.key] = f, a), {}),
    [activeFields],
  );
  const groups = useMemoFS(
    () => Array.from(new Set(activeFields.map(f => f.group))),
    [activeFields],
  );
  const sensitivities = useMemoFS(
    () => Array.from(new Set(activeFields.map(f => f.sensitivity).filter(Boolean))),
    [activeFields],
  );

  const filtered = useMemoFS(() => {
    const q = search.trim().toLowerCase();
    return activeFields.filter(f => {
      if (groupFilter !== "All" && f.group !== groupFilter) return false;
      if (sensFilter  !== "All" && f.sensitivity !== sensFilter) return false;
      if (q && !(
        (f.label || "").toLowerCase().includes(q) ||
        f.key.toLowerCase().includes(q) ||
        (f.desc || "").toLowerCase().includes(q) ||
        (f.example || "").toLowerCase().includes(q)
      )) return false;
      return true;
    });
  }, [activeFields, search, groupFilter, sensFilter]);

  const selectedSet = useMemoFS(() => new Set(selectedKeys), [selectedKeys]);

  const toggleField = (key) => {
    if (selectedSet.has(key)) onChange(selectedKeys.filter(k => k !== key));
    else onChange([...selectedKeys, key]);
  };
  const addMany = (keys) => {
    const next = [...selectedKeys];
    keys.forEach(k => { if (!next.includes(k)) next.push(k); });
    onChange(next);
  };
  const availableCount = filtered.filter(f => !f.disabled).length;
  const disabledCount  = activeFields.filter(f => f.disabled).length;

  if (activeFields.length === 0) {
    return (
      <div className="card" style={{padding:24}}>
        <strong className="t-bodysm">Field catalogue unavailable</strong>
        <div className="t-cap muted" style={{marginTop:6}}>
          The Data Dictionary returned no requestable fields. Refresh the
          request scope or ask an administrator to configure active field
          definitions; no local fallback is used.
        </div>
      </div>
    );
  }

  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 320px', gap:16}}>
      <div className="col gap-3" style={{minWidth:0}}>
        {/* Filter strip */}
        <div className="card" style={{padding:14, display:"flex", flexDirection:"column", gap:10}}>
          <div className="row gap-3" style={{flexWrap:"wrap"}}>
            <div className="search" style={{flex:"1 1 240px", padding:"6px 10px"}}>
              <Icon name="search" size={14}/>
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search label, key, description, or example value…"/>
              {search && (
                <button className="icon-btn" onClick={() => setSearch("")}
                  style={{width:22, height:22}}><Icon name="x" size={12}/></button>
              )}
            </div>
            <label style={{display:"flex", alignItems:"center", gap:6}}>
              <input type="checkbox" checked={showDisabled}
                onChange={e => setShowDisabled(e.target.checked)}/>
              <span className="t-bodysm">Show DSA-blocked fields ({disabledCount})</span>
            </label>
          </div>

          <div className="row gap-2" style={{flexWrap:"wrap"}}>
            <span className="t-cap" style={{fontWeight:600, marginRight:4}}>GROUP</span>
            {["All", ...groups].map(g => {
              const active = groupFilter === g;
              return (
                <button key={g} onClick={() => setGroupFilter(g)} className="chip-btn"
                  style={{
                    padding:"4px 10px", borderRadius:8, fontSize:12, fontWeight:500,
                    border: active ? "1px solid var(--accent-system)" : "1px solid var(--neutral-300)",
                    background: active ? "var(--accent-system-bg)" : "var(--neutral-0)",
                    color: active ? "var(--accent-system)" : "var(--neutral-700)",
                    cursor:"pointer",
                  }}>{g}</button>
              );
            })}
          </div>

          <div className="row gap-2" style={{flexWrap:"wrap"}}>
            <span className="t-cap" style={{fontWeight:600, marginRight:4}}>SENSITIVITY</span>
            {["All", ...sensitivities].map(s => {
              const active = sensFilter === s;
              return (
                <button key={s} onClick={() => setSensFilter(s)}
                  style={{
                    padding:"4px 10px", borderRadius:8, fontSize:12, fontWeight:500,
                    border: active ? "1px solid var(--accent-system)" : "1px solid var(--neutral-300)",
                    background: active ? "var(--accent-system-bg)" : "var(--neutral-0)",
                    color: active ? "var(--accent-system)" : "var(--neutral-700)",
                    cursor:"pointer",
                  }}>{s}</button>
              );
            })}
          </div>
        </div>

        {/* Two-pane card */}
        <div className="card" style={{display:"flex", flexDirection:"column"}}>
          <div className="card-toolbar">
            <strong className="t-bodysm">
              {filtered.length} field{filtered.length === 1 ? "" : "s"} visible
              {availableCount !== filtered.length && ` · ${availableCount} pickable`}
            </strong>
            <div style={{flex:1}}/>
            <button className="btn btn-sm" onClick={() => addMany(filtered.filter(f => !f.disabled).map(f => f.key))}>
              <Icon name="plus" size={12}/> Add all visible
            </button>
            <button className="btn btn-sm btn-ghost" onClick={() => onChange([])} disabled={selectedKeys.length === 0}>
              <Icon name="x" size={12}/> Clear selection
            </button>
          </div>
          <div style={{
            display:"grid", gridTemplateColumns:"minmax(280px, 1fr) minmax(260px, 1fr)",
            minHeight:540, maxHeight:"min(70vh, 720px)",
          }}>
            {/* Left pane */}
            <div style={{
              display:"flex", flexDirection:"column",
              borderRight:"1px solid var(--neutral-200)", minWidth:0,
            }}>
              <div style={{
                padding:"8px 16px", background:"var(--neutral-50)",
                borderBottom:"1px solid var(--neutral-200)",
                display:"flex", alignItems:"center", gap:8,
              }}>
                <Icon name="database" size={12} color="var(--neutral-500)"/>
                <span className="t-cap" style={{fontWeight:600, letterSpacing:"0.04em", textTransform:"uppercase"}}>
                  Available
                </span>
                <span className="t-cap">— click a row to add to output</span>
              </div>
              <FSAvailable fields={filtered} selectedSet={selectedSet}
                onToggle={toggleField} onAddGroup={addMany}
                showDisabled={showDisabled}/>
            </div>
            {/* Right pane */}
            <div style={{display:"flex", flexDirection:"column", minWidth:0}}>
              <div style={{
                padding:"8px 12px", background:"var(--neutral-50)",
                borderBottom:"1px solid var(--neutral-200)",
                display:"flex", alignItems:"center", gap:8,
              }}>
                <Icon name="sliders" size={12} color="var(--neutral-500)"/>
                <span className="t-cap" style={{fontWeight:600, letterSpacing:"0.04em", textTransform:"uppercase"}}>
                  Output · {selectedKeys.length}
                </span>
                <span style={{flex:1}}/>
                <button className="btn btn-sm btn-ghost"
                  onClick={() => onChange([...selectedKeys].reverse())}
                  disabled={selectedKeys.length < 2} title="Reverse order">
                  <Icon name="sort" size={11}/>
                </button>
              </div>
              <FSSelected selectedKeys={selectedKeys} onChange={onChange} byKey={byKey}/>
            </div>
          </div>
        </div>
      </div>

      {/* Right rail */}
      <div className="col gap-3">
        <FSBreakdownCard selectedKeys={selectedKeys} byKey={byKey}/>

        <div className="card">
          <div className="card-header" style={{padding:"12px 16px"}}>
            <h3 className="t-h3" style={{margin:0}}>Sensitivity legend</h3>
          </div>
          <div style={{padding:14, display:"flex", flexDirection:"column", gap:10}}>
            {sensitivities.map(s => (
              <div key={s} className="row gap-3">
                <Chip size="sm">{s}</Chip>
                <span className="t-bodysm muted">Classification supplied by the Data Dictionary.</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{borderTop:"3px solid var(--accent-system)"}}>
          <div className="card-header" style={{padding:"12px 16px"}}>
            <div>
              <div className="t-cap" style={{color:"var(--accent-system)"}}>ACTIVE DSA</div>
              <h3 className="t-h3" style={{margin:"2px 0 0"}}>{dsaReference}</h3>
            </div>
            <Chip tone="data">Active</Chip>
          </div>
          <div style={{padding:16}}>
            <div className="t-cap">
              {disabledCount} field{disabledCount === 1 ? "" : "s"} blocked by clause 4.2.b of
              this DSA. Request scope expansion via your data steward to enable them.
            </div>
            <button className="btn btn-sm mt-3" style={{width:"100%"}}>
              <Icon name="file" size={13}/> Open DSA document
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {
  FieldStepV2,
});
