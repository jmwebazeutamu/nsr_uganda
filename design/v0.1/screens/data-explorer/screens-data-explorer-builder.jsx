/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_VARIABLES_BY_DATASET, DE_PRIVACY, DE_GEO_LEVELS,
   PrivacyChip, DEShell, ScreenJumpTweak,
   strictestClass, violatesFloor, FloorViolationBanner,
   useDeCatalogue, useDeDataset, useDeMe, RoleGateBanner, submitAggregate,
   TweaksPanel, useTweaks, TweakSection */

// NSR MIS — Data Explorer · Aggregate builder (screen 2 of 5)
// =========================================================
// Three-column working surface: Projection · Filters · Geographic
// scope. A "strictest class" chip updates live as variables are
// added. Picking a level below the dataset's floor surfaces the
// 422 geographic_floor_violation banner with the DRS handoff CTA.

const { useState: useBld, useMemo: useBldM, useEffect: useBldE } = React;

/* ----------------------------------------------------------------
   Filter ops per variable type
   ---------------------------------------------------------------- */
const OPS_BY_TYPE = {
  categorical: [
    { op: "eq",  label: "equals" },
    { op: "in",  label: "is one of" },
    { op: "neq", label: "not equals" },
  ],
  integer:     [{ op:"eq", label:"=" }, { op:"gt", label:">" }, { op:"gte", label:"≥" }, { op:"lt", label:"<" }, { op:"lte", label:"≤" }, { op:"between", label:"between" }],
  continuous:  [{ op:"gt", label:">" }, { op:"gte", label:"≥" }, { op:"lt", label:"<" }, { op:"lte", label:"≤" }, { op:"between", label:"between" }],
  geo:         [{ op:"in", label:"is one of" }, { op:"eq", label:"equals" }],
  string:      [{ op:"eq", label:"equals" }],
};

/* ----------------------------------------------------------------
   Seed: pre-populate so the page looks real on first paint.
   ---------------------------------------------------------------- */
const SEED = {
  datasetId: "ds_hh_profile",
  projection: ["subregion", "district", "roof_material", "water_source"],
  filters: [
    { var: "urban_rural", op: "eq", value: "Rural" },
    { var: "pmt_band",    op: "in", value: ["Poorest 20%", "Poorest 40%"] },
  ],
  scopeLevel: "district",
  scopeCodes: ["Lyantonde", "Moroto", "Napak", "Arua", "Yumbe", "Gulu"],
};

const BuilderScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "builder" });
  const [datasetId, setDatasetId] = useBld(SEED.datasetId);
  const [projection, setProjection] = useBld(SEED.projection);
  const [filters, setFilters] = useBld(SEED.filters);
  const [scopeLevel, setScopeLevel] = useBld(SEED.scopeLevel);
  const [scopeCodes, setScopeCodes] = useBld(SEED.scopeCodes);
  const [showVarPicker, setShowVarPicker] = useBld(false);

  const me = useDeMe();
  const [datasets] = useDeCatalogue();
  const [{ dataset: liveDs, variables: liveVars }] = useDeDataset(datasetId);
  const [runState, setRunState] = useBld({ pending: false, error: null });

  const ds = liveDs || datasets.find(d => d.id === datasetId || d.code === datasetId);
  const vars = (liveVars && liveVars.length) ? liveVars : (DE_VARIABLES_BY_DATASET[datasetId] || []);

  const runAggregate = async () => {
    if (!validForRun || runState.pending) return;
    setRunState({ pending: true, error: null });
    const payload = {
      dataset_code: ds.code,
      projection,
      filters: filters
        .filter(f => f.var)
        .map(f => ({ variable: f.var, op: f.op, value: f.value })),
      geographic_scope: { level: scopeLevel, codes: scopeCodes },
    };
    try {
      const resp = await submitAggregate(payload);
      // Stash the result for the Results screen to pick up.
      sessionStorage.setItem("de_last_aggregate", JSON.stringify({
        ts: Date.now(),
        payload, response: resp,
      }));
      location.href = "Data Explorer - Results.html";
    } catch (err) {
      // Preview mode (no backend) → still hand off to Results so the
      // designer can review the layout against the mock corpus.
      const noBackend = err && (err.status === 404 || /Failed to fetch/i.test(String(err.message || "")));
      if (noBackend) {
        sessionStorage.setItem("de_last_aggregate", JSON.stringify({
          ts: Date.now(), payload, response: null, preview: true,
        }));
        location.href = "Data Explorer - Results.html";
        return;
      }
      setRunState({ pending: false, error: String(err.body?.error || err.message || err) });
    }
  };

  // Strictest class — driven by projection + filter + dataset
  const involvedKlasses = useBldM(() => {
    const keys = [...projection, ...filters.map(f => f.var)];
    const classes = keys.map(k => vars.find(v => v.code === k)?.privacy).filter(Boolean);
    classes.push(ds?.privacy);
    return classes;
  }, [projection, filters, vars, ds]);
  const klass = useBldM(() => strictestClass(involvedKlasses), [involvedKlasses]);

  // Floor violation — finer than the dataset's geographic_floor
  const floorViolated = useBldM(
    () => ds && violatesFloor(scopeLevel, ds.floor),
    [scopeLevel, ds]
  );

  // Suppress estimate
  const estimatedRows = useBldM(() => {
    const factor = (projection.length || 1) * (scopeCodes.length || 1);
    return Math.min(5_000_000, factor * 1240);
  }, [projection, scopeCodes]);

  const projVars = projection.map(code => vars.find(v => v.code === code)).filter(Boolean);
  const projableVars = vars.filter(v => v.privacy !== "sensitive" && !projection.includes(v.code));
  const filterableVars = vars.filter(v => v.privacy !== "sensitive" && !filters.find(f => f.var === v.code));

  const addProj = (code) => { setProjection([...projection, code]); setShowVarPicker(false); };
  const removeProj = (code) => setProjection(projection.filter(c => c !== code));
  const addFilter = () => setFilters([...filters, { var: filterableVars[0]?.code || "", op: "eq", value: "" }]);
  const updateFilter = (i, patch) => setFilters(filters.map((f, j) => j === i ? { ...f, ...patch } : f));
  const removeFilter = (i) => setFilters(filters.filter((_, j) => j !== i));

  const validForRun = ds && projection.length > 0 && !floorViolated && ds.privacy !== "sensitive";

  return (
    <DEShell active="builder" refreshed_at={ds?.refreshed_at || "28 May 2026 06:00 UTC"}>
      <RoleGateBanner me={me}/>
      {runState.error && (
        <div style={{
          background: "var(--accent-danger-bg)",
          borderBottom: "1px solid var(--accent-danger)",
          padding: "8px 24px", color: "var(--accent-danger)",
          fontSize: 12.5, display:"flex", alignItems:"center", gap:8,
        }}>
          <Icon name="alertTriangle" size={14}/>
          <strong>Aggregate failed.</strong>
          <span style={{color:"var(--neutral-700)"}}>{runState.error}</span>
          <button className="icon-btn" onClick={() => setRunState({pending:false,error:null})}>
            <Icon name="x" size={12}/>
          </button>
        </div>
      )}
      <PageHeader
        eyebrow="DATA EXPLORER · AGGREGATE BUILDER"
        title="Build an aggregate query"
        sub={<>Pick variables to project, add filters, choose a geographic scope. Strictest class &amp; the suppression k-floor are derived from the variables you include.</>}
        right={<>
          <button className="btn"><Icon name="save" size={14}/> Save query</button>
          <button className="btn"><Icon name="arrowRight" size={14}/> Request record-level data</button>
        </>}
      />

      {/* Dataset selector + strictest-class strip */}
      <div className="card" style={{padding:"16px 20px", marginBottom:16,
        display:"grid", gridTemplateColumns:"1.6fr auto auto auto", gap:18, alignItems:"center"}}>
        <div>
          <div className="t-cap">DATASET</div>
          <div style={{display:"flex", alignItems:"center", gap:10, marginTop:4}}>
            <select className="field-select" style={{maxWidth:340}}
              value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
              {datasets.filter(d => d.privacy !== "sensitive").map(d =>
                <option key={d.id || d.code} value={d.id || d.code}>{d.code} — {d.label}</option>
              )}
            </select>
            <PrivacyChip klass={ds.privacy} showFloor/>
          </div>
          <div className="t-cap mt-1">
            <span className="t-mono">{ds.matview}</span> · {ds.rows} rows · floor {ds.floor}
          </div>
        </div>
        <div>
          <div className="t-cap">STRICTEST CLASS</div>
          <div style={{marginTop:6}}>
            <PrivacyChip klass={klass}/>
          </div>
          <div className="t-cap mt-1">
            k_floor {DE_PRIVACY[klass].k_floor ?? "—"} · {projection.length + filters.length + 1} sources
          </div>
        </div>
        <div>
          <div className="t-cap">SCOPE</div>
          <div style={{marginTop:6, fontWeight:600}}>{scopeCodes.length} {scopeLevel}{scopeCodes.length === 1 ? "" : "s"}</div>
          <div className="t-cap mt-1">level: <span className="t-mono">{scopeLevel}</span></div>
        </div>
        <div>
          <div className="t-cap">EST. ROWS</div>
          <div style={{marginTop:6, fontWeight:600, fontFamily:"'JetBrains Mono', monospace"}}>
            ~{estimatedRows.toLocaleString()}
          </div>
          <div className="t-cap mt-1">capped at 5,000,000</div>
        </div>
      </div>

      {/* Floor-violation banner */}
      {floorViolated && (
        <FloorViolationBanner
          violation={{
            floor: ds.floor,
            requested_level: scopeLevel,
            requested_codes: scopeCodes,
            scope_label: `${scopeCodes.length} ${scopeLevel}${scopeCodes.length === 1 ? "" : "s"}`,
          }}
          onRequestHandoff={() => alert("→ POST /handoff/  → /data-requests/{id}/")}
        />
      )}

      {/* 3-column workbench */}
      <div style={{display:"grid", gridTemplateColumns:"1.2fr 1.4fr 1fr", gap:16, alignItems:"flex-start"}}>
        {/* Column 1 — Projection */}
        <Column n="1" title="Projection"
          sub="Which variables to group by + count."
          right={<Chip size="sm" tone="neutral">{projection.length} selected</Chip>}>
          <div style={{padding:14}}>
            {projVars.length === 0 && (
              <EmptyHint icon="sliders" title="No projection yet" body="Add at least one variable. Each row in the result will be one combination of the variables you pick."/>
            )}
            {projVars.map((v) => (
              <ProjectionPill key={v.code} v={v} onRemove={() => removeProj(v.code)}/>
            ))}
            {showVarPicker ? (
              <VarPicker variables={projableVars} onPick={addProj} onCancel={() => setShowVarPicker(false)}/>
            ) : (
              <button className="bld-add-btn" onClick={() => setShowVarPicker(true)}>
                <Icon name="plus" size={13}/> Add variable
              </button>
            )}
            {projVars.length > 0 && (
              <div style={{
                marginTop:14, padding:"10px 12px",
                background:"var(--neutral-50)", border:"1px solid var(--neutral-200)", borderRadius:4,
              }}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>RESULTING COLUMNS</div>
                <div style={{display:"flex", flexWrap:"wrap", gap:6}}>
                  {projVars.map(v => (
                    <span key={v.code} className="t-mono" style={{fontSize:11.5, padding:"2px 6px", border:"1px solid var(--neutral-300)", borderRadius:3, background:"#fff"}}>
                      {v.code}
                    </span>
                  ))}
                  <span className="t-mono" style={{fontSize:11.5, padding:"2px 6px", border:"1px solid var(--neutral-300)", borderRadius:3, background:"var(--accent-data-bg)", color:"var(--accent-data)", fontWeight:600}}>
                    count
                  </span>
                </div>
              </div>
            )}
          </div>
        </Column>

        {/* Column 2 — Filters */}
        <Column n="2" title="Filters"
          sub="Restrict rows before aggregation. Each filter ANDs with the others."
          right={<Chip size="sm" tone="neutral">{filters.length} filter{filters.length === 1 ? "" : "s"}</Chip>}>
          <div style={{padding:14}}>
            {filters.length === 0 && (
              <EmptyHint icon="filter" title="No filters" body="Without filters the whole dataset is aggregated. Add a filter to restrict to a subset (urban/rural, PMT band, etc)."/>
            )}
            {filters.map((f, i) => {
              const v = vars.find(x => x.code === f.var);
              return <FilterRow key={i} f={f} v={v} variables={vars}
                onChange={(patch) => updateFilter(i, patch)}
                onRemove={() => removeFilter(i)}/>;
            })}
            <button className="bld-add-btn" onClick={addFilter} disabled={filterableVars.length === 0}>
              <Icon name="plus" size={13}/> Add filter
            </button>
          </div>
        </Column>

        {/* Column 3 — Geographic scope */}
        <Column n="3" title="Geographic scope"
          sub="The level and units to aggregate within."
          right={<Chip size="sm" tone={floorViolated ? "quality" : "neutral"}>
            {floorViolated ? "below floor" : "ok"}
          </Chip>}>
          <div style={{padding:14}}>
            <div className="t-cap" style={{fontWeight:600, marginBottom:6}}>LEVEL</div>
            <div style={{display:"flex", flexDirection:"column", gap:6}}>
              {DE_GEO_LEVELS.map(g => {
                const isActive = g.code === scopeLevel;
                const tooFine = violatesFloor(g.code, ds.floor);
                return (
                  <label key={g.code} style={{
                    display:"flex", alignItems:"center", gap:10,
                    padding:"8px 10px",
                    border: `1px solid ${isActive ? "var(--primary-700)" : "var(--neutral-300)"}`,
                    background: isActive ? "var(--primary-100)" : "var(--neutral-0)",
                    borderRadius:4,
                    cursor:"pointer",
                  }}>
                    <input type="radio" checked={isActive} onChange={() => setScopeLevel(g.code)}
                      style={{margin:0}}/>
                    <div style={{flex:1}}>
                      <div style={{fontWeight:500, fontSize:13}}>{g.label}</div>
                      <div className="t-cap mt-1">{g.units.toLocaleString()} units nationally</div>
                    </div>
                    {tooFine && <Chip size="sm" tone="quality" title="Finer than dataset floor">⚠ below floor</Chip>}
                  </label>
                );
              })}
            </div>

            <div style={{marginTop:14}}>
              <div className="t-cap" style={{fontWeight:600, marginBottom:6}}>UNITS ({scopeCodes.length})</div>
              <div style={{display:"flex", flexWrap:"wrap", gap:6, padding:"8px 10px",
                border:"1px solid var(--neutral-300)", borderRadius:4, background:"var(--neutral-0)", minHeight:36}}>
                {scopeCodes.map((c, i) => (
                  <span key={i} style={{
                    display:"inline-flex", alignItems:"center", gap:4,
                    background:"var(--primary-100)", color:"var(--primary-900)",
                    border:"1px solid var(--primary-700)",
                    padding:"2px 6px", borderRadius:3, fontSize:12, fontWeight:500,
                  }}>
                    {c}
                    <button onClick={() => setScopeCodes(scopeCodes.filter((_, j) => j !== i))} style={{
                      border:0, background:"transparent", padding:0, marginLeft:2, cursor:"pointer", color:"var(--primary-900)", display:"flex",
                    }}>
                      <Icon name="x" size={10}/>
                    </button>
                  </span>
                ))}
                <button className="t-cap" style={{
                  border:"1px dashed var(--neutral-300)", background:"transparent",
                  padding:"2px 6px", borderRadius:3, cursor:"pointer", color:"var(--neutral-700)",
                  display:"inline-flex", alignItems:"center", gap:4,
                }} onClick={() => setScopeCodes([...scopeCodes, `Area-${scopeCodes.length + 1}`])}>
                  <Icon name="plus" size={10}/> Add unit
                </button>
              </div>
              <div className="t-cap mt-1">
                Floor for this dataset: <strong>{ds.floor}</strong>.
                {floorViolated && <span style={{color:"var(--accent-quality)", marginLeft:4}}>
                  Current level is finer than the floor.
                </span>}
              </div>
            </div>
          </div>
        </Column>
      </div>

      {/* Query preview */}
      <div className="card" style={{marginTop:16, padding:0}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">Query preview</strong>
          <span className="t-cap">POST /api/v1/data-explorer/aggregate/</span>
          <div style={{flex:1}}/>
          <Chip size="sm" tone="neutral">JSON payload</Chip>
        </div>
        <pre style={{
          margin:0, padding:"14px 18px",
          background:"var(--neutral-50)",
          color:"var(--neutral-900)",
          fontFamily:"'JetBrains Mono', monospace",
          fontSize:12.5, lineHeight:1.55,
          overflowX:"auto",
        }}>
{`{
  "dataset_code": "${ds.code}",
  "projection":   ${JSON.stringify(projection)},
  "filters":      ${JSON.stringify(filters, null, 2).split("\n").map((l, i) => i === 0 ? l : "                  " + l).join("\n")},
  "geographic_scope": {
    "level": "${scopeLevel}",
    "codes": ${JSON.stringify(scopeCodes)}
  }
}`}
        </pre>
      </div>

      {/* Sticky action bar */}
      <div style={{
        position:"sticky", bottom:0, zIndex:20,
        marginLeft:-24, marginRight:-24, marginTop:24,
        background:"var(--neutral-0)",
        borderTop:"1px solid var(--neutral-300)",
        padding:"12px 24px",
        display:"flex", alignItems:"center", gap:12,
        boxShadow:"0 -2px 8px rgba(0,0,0,0.04)",
      }}>
        <div className="t-bodysm" style={{color:"var(--neutral-500)"}}>
          {projection.length} variable{projection.length === 1 ? "" : "s"} projected ·
          {" "}{filters.length} filter{filters.length === 1 ? "" : "s"} ·
          {" "}scope <strong style={{color:"var(--neutral-900)"}}>{scopeCodes.length} {scopeLevel}{scopeCodes.length === 1 ? "" : "s"}</strong> ·
          {" "}strictest <strong style={{color:"var(--neutral-900)"}}>{DE_PRIVACY[klass].label.toLowerCase()}</strong>
        </div>
        <div style={{flex:1}}/>
        <button className="btn"><Icon name="arrowRight" size={14}/> Request record-level data</button>
        <button className="btn"><Icon name="save" size={14}/> Save query</button>
        <button className="btn btn-primary" disabled={!validForRun || runState.pending}
          onClick={runAggregate}
          title={!validForRun ? (floorViolated ? "Geographic floor violation — fix the scope" : "Add at least one projection") : "POST /aggregate/"}>
          <Icon name={runState.pending ? "loader" : "play"} size={14}/>
          {runState.pending ? " Running…" : " Run aggregate"}
        </button>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Navigate">
          <ScreenJumpTweak active="builder"/>
        </TweakSection>
      </TweaksPanel>

      <style>{`
        .bld-add-btn {
          display: inline-flex; align-items: center; gap: 6px;
          width: 100%;
          padding: 8px 12px;
          border: 1px dashed var(--neutral-300);
          border-radius: 4px;
          background: var(--neutral-0);
          color: var(--neutral-700);
          font-size: 13px; font-weight: 500;
          cursor: pointer;
          justify-content: center;
          margin-top: 8px;
        }
        .bld-add-btn:hover:not(:disabled) {
          background: var(--neutral-50);
          border-color: var(--primary-700);
          color: var(--primary-900);
        }
        .bld-add-btn:disabled { opacity: 0.5; cursor: not-allowed; }
      `}</style>
    </DEShell>
  );
};

/* ----------------------------------------------------------------
   Column container
   ---------------------------------------------------------------- */
const Column = ({ n, title, sub, right, children }) => (
  <div className="card" style={{padding:0}}>
    <div style={{
      padding:"14px 16px",
      display:"flex", alignItems:"center", gap:10,
      borderBottom:"1px solid var(--neutral-200)",
    }}>
      <div style={{
        width:24, height:24, borderRadius:"50%",
        background:"var(--primary-900)", color:"#fff",
        display:"grid", placeItems:"center",
        fontSize:12, fontWeight:600,
      }}>{n}</div>
      <div style={{flex:1, minWidth:0}}>
        <h3 className="t-h3" style={{margin:0, fontSize:14}}>{title}</h3>
        <div className="t-cap mt-1">{sub}</div>
      </div>
      {right}
    </div>
    {children}
  </div>
);

/* ----------------------------------------------------------------
   Empty-state hint
   ---------------------------------------------------------------- */
const EmptyHint = ({ icon, title, body }) => (
  <div style={{
    display:"flex", flexDirection:"column", alignItems:"center", gap:6,
    padding:"24px 12px",
    background:"var(--neutral-50)",
    border:"1px dashed var(--neutral-300)",
    borderRadius:4,
    textAlign:"center",
  }}>
    <Icon name={icon} size={22} color="var(--neutral-500)"/>
    <div style={{fontWeight:600}}>{title}</div>
    <div className="t-bodysm muted" style={{maxWidth:280}}>{body}</div>
  </div>
);

/* ----------------------------------------------------------------
   ProjectionPill — variable chosen as a projection axis
   ---------------------------------------------------------------- */
const ProjectionPill = ({ v, onRemove }) => (
  <div style={{
    display:"grid", gridTemplateColumns:"auto 1fr auto auto", gap:10, alignItems:"center",
    padding:"10px 12px",
    border:"1px solid var(--neutral-200)",
    borderLeft: `3px solid ${DE_PRIVACY[v.privacy].accent}`,
    borderRadius:4, marginBottom:8,
    background:"var(--neutral-0)",
  }}>
    <div style={{
      width:24, height:24, borderRadius:3,
      background:"var(--neutral-100)", color:"var(--neutral-700)",
      display:"grid", placeItems:"center",
    }}>
      <Icon name={v.type === "geo" ? "mapPin" : v.type === "categorical" ? "filter" : "barchart"} size={12}/>
    </div>
    <div style={{minWidth:0}}>
      <div style={{fontWeight:500, fontSize:13}}>{v.label}</div>
      <div className="t-cap t-mono mt-1">{v.code} · {v.type}</div>
    </div>
    <PrivacyChip klass={v.privacy} size="sm"/>
    <button className="icon-btn" onClick={onRemove} aria-label="Remove">
      <Icon name="x" size={12}/>
    </button>
  </div>
);

/* ----------------------------------------------------------------
   Variable picker drop-down
   ---------------------------------------------------------------- */
const VarPicker = ({ variables, onPick, onCancel }) => {
  const [q, setQ] = useBld("");
  const filtered = q
    ? variables.filter(v => v.label.toLowerCase().includes(q.toLowerCase()) || v.code.toLowerCase().includes(q.toLowerCase()))
    : variables;
  return (
    <div style={{
      border:"1px dashed var(--primary-700)",
      background:"var(--primary-100)",
      borderRadius:4, padding:10, marginTop:8,
    }}>
      <div className="search" style={{margin:0, marginBottom:8}}>
        <Icon name="search" size={13} color="var(--neutral-500)"/>
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter variables…"/>
      </div>
      <div style={{maxHeight:240, overflowY:"auto", border:"1px solid var(--neutral-200)", borderRadius:3, background:"#fff"}}>
        {filtered.length === 0 && <div className="t-cap" style={{padding:14, textAlign:"center"}}>No matches</div>}
        {filtered.map(v => (
          <button key={v.code} onClick={() => onPick(v.code)} style={{
            display:"grid", gridTemplateColumns:"1fr auto auto", gap:10, alignItems:"center",
            padding:"8px 10px", width:"100%",
            border:0, borderBottom:"1px solid var(--neutral-200)",
            background:"transparent", cursor:"pointer", textAlign:"left",
          }}>
            <div>
              <div style={{fontWeight:500, fontSize:13}}>{v.label}</div>
              <div className="t-cap t-mono mt-1">{v.code} · {v.domain}</div>
            </div>
            <Chip size="sm" tone="neutral">{v.type}</Chip>
            <PrivacyChip klass={v.privacy} size="sm"/>
          </button>
        ))}
      </div>
      <div style={{display:"flex", gap:8, marginTop:8}}>
        <div style={{flex:1}}/>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>Done</button>
      </div>
    </div>
  );
};

/* ----------------------------------------------------------------
   FilterRow — variable · op · value
   ---------------------------------------------------------------- */
const FilterRow = ({ f, v, variables, onChange, onRemove }) => {
  const ops = v ? (OPS_BY_TYPE[v.type] || []) : [];
  const isCategorical = v && (v.type === "categorical" || v.type === "geo");
  const optionList = v && v.values && /·/.test(v.values) ? v.values.split("·").map(s => s.trim()) : null;
  return (
    <div style={{
      display:"grid",
      gridTemplateColumns:"1fr auto 1fr 32px",
      gap:8, alignItems:"center",
      padding:"8px 0",
      borderBottom:"1px solid var(--neutral-100)",
    }}>
      <select className="field-select" value={f.var} onChange={(e) => onChange({ var: e.target.value, value: "" })}>
        {variables.filter(x => x.privacy !== "sensitive").map(x =>
          <option key={x.code} value={x.code}>{x.label}</option>
        )}
      </select>
      <select className="field-select" style={{width:96}} value={f.op} onChange={(e) => onChange({ op: e.target.value })}>
        {ops.map(o => <option key={o.op} value={o.op}>{o.label}</option>)}
      </select>
      {isCategorical && optionList ? (
        <select className="field-select"
          value={f.op === "in" ? (Array.isArray(f.value) ? f.value : []) : (Array.isArray(f.value) ? f.value[0] || "" : f.value)}
          multiple={f.op === "in"}
          onChange={(e) => {
            if (f.op === "in") {
              const opts = [...e.target.selectedOptions].map(o => o.value);
              onChange({ value: opts });
            } else onChange({ value: e.target.value });
          }}
          style={{height: f.op === "in" ? 64 : 34}}>
          <option value="">Select…</option>
          {optionList.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input className="field-input" value={Array.isArray(f.value) ? f.value.join(", ") : f.value}
          onChange={(e) => onChange({ value: e.target.value })}
          placeholder={v?.type === "continuous" || v?.type === "integer" ? "number" : "value"}/>
      )}
      <button className="icon-btn" onClick={onRemove} aria-label="Remove filter">
        <Icon name="x" size={12}/>
      </button>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("app")).render(<BuilderScreen/>);
