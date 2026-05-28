/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_VARIABLES_BY_DATASET, DE_PRIVACY, DE_RESULT_ROWS, DE_SUPPRESSION,
   PrivacyChip, DEShell, ScreenJumpTweak, SuppressedCell,
   TweaksPanel, useTweaks, TweakSection */

// NSR MIS — Data Explorer · Results panel (screen 3 of 5)
// =========================================================
// 200 response payload from /aggregate/. Sortable table with
// suppressed cells rendered as "—" + hover tooltip pulled from
// /suppression-vocabulary/. Metadata footer carries the matview
// name, freshness, k-floor used, and suppressed-cell count.

const { useState: useRes, useMemo: useResM } = React;

const QUERY = {
  dataset_code: "HH_PROFILE",
  projection: ["subregion", "district", "roof_material", "water_source"],
  filters: [
    { variable: "urban_rural", op: "eq", value: "Rural" },
    { variable: "pmt_band",    op: "in", value: ["Poorest 20%", "Poorest 40%"] },
  ],
  geographic_scope: { level: "district", codes: ["Lyantonde", "Moroto", "Napak", "Arua", "Yumbe", "Gulu"] },
};

const COLUMNS = [
  { key: "subregion", label: "Sub-region",      group: "geo" },
  { key: "district",  label: "District",        group: "geo" },
  { key: "roof",      label: "Roof material",   group: "fact" },
  { key: "water",     label: "Water source",    group: "fact" },
  { key: "count",     label: "Households",      group: "count", num: true },
  { key: "pmt_avg",   label: "Mean PMT score",  group: "agg",   num: true, fmt: (v) => v == null ? null : v.toFixed(3) },
];

const ResultsScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "results" });
  const [sortKey, setSortKey] = useRes("count");
  const [sortDir, setSortDir] = useRes("desc");
  const [showSuppressed, setShowSuppressed] = useRes(true);

  const ds = DE_DATASETS.find(d => d.code === QUERY.dataset_code);
  const k = DE_PRIVACY[ds.privacy].k_floor;

  // Strictest class — based on projection + dataset
  const klass = useResM(() => {
    const vars = DE_VARIABLES_BY_DATASET[ds.id] || [];
    const list = QUERY.projection.map(p => vars.find(v => v.code === p)?.privacy).filter(Boolean);
    list.push(ds.privacy);
    const order = { public: 0, internal: 1, personal: 2, sensitive: 3 };
    return list.reduce((best, c) => order[c] > order[best] ? c : best, "public");
  }, [ds]);

  const sortedRows = useResM(() => {
    const rows = showSuppressed ? DE_RESULT_ROWS : DE_RESULT_ROWS.filter(r => !r.suppressed);
    return [...rows].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number") return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [sortKey, sortDir, showSuppressed]);

  const suppressedCount = DE_RESULT_ROWS.filter(r => r.suppressed).length;
  const totalCellCount = DE_RESULT_ROWS.length * COLUMNS.filter(c => c.group === "count" || c.group === "agg").length;
  const queryHash = "qh_8f3a92e4c1b6d0a7";

  const setSort = (key) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  };

  return (
    <DEShell active="results" refreshed_at={ds.refreshed_at}>
      <PageHeader
        eyebrow={<>DATA EXPLORER · RESULTS · <span className="t-mono">qh:{queryHash.slice(3, 11)}…</span></>}
        title="Aggregate results"
        sub={<>HTTP 200 · {sortedRows.length} of {DE_RESULT_ROWS.length} rows · returned in 412 ms · {suppressedCount} suppressed cell{suppressedCount === 1 ? "" : "s"}</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn"><Icon name="save" size={14}/> Save query</button>
          <button className="btn btn-primary"><Icon name="arrowRight" size={14}/> Request record-level data</button>
        </>}
      />

      {/* Query summary card — what produced these rows */}
      <div className="card" style={{padding:0, marginBottom:16, borderTop: `3px solid ${DE_PRIVACY[klass].accent}`}}>
        <div style={{padding:"16px 20px", display:"grid", gridTemplateColumns:"1.4fr 1fr 1fr auto", gap:24, alignItems:"center"}}>
          <div>
            <div className="t-cap">QUERY</div>
            <div style={{display:"flex", alignItems:"center", gap:8, marginTop:4}}>
              <span className="t-mono" style={{fontWeight:600, fontSize:14}}>{QUERY.dataset_code}</span>
              <PrivacyChip klass={klass}/>
            </div>
            <div className="t-cap mt-1">
              project [{QUERY.projection.join(", ")}] · filter {QUERY.filters.length}
              {" "}· scope {QUERY.geographic_scope.codes.length} {QUERY.geographic_scope.level}s
            </div>
          </div>
          <div>
            <div className="t-cap">FILTERS</div>
            <div style={{display:"flex", flexWrap:"wrap", gap:4, marginTop:6}}>
              {QUERY.filters.map((f, i) => (
                <span key={i} className="t-mono" style={{fontSize:11, padding:"2px 6px", border:"1px solid var(--neutral-300)", borderRadius:3, background:"#fff"}}>
                  {f.variable} {f.op} {Array.isArray(f.value) ? f.value.join("|") : f.value}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="t-cap">SCOPE</div>
            <div className="t-bodysm" style={{fontWeight:500, marginTop:4}}>
              {QUERY.geographic_scope.codes.length} {QUERY.geographic_scope.level}s
            </div>
            <div className="t-cap mt-1">{QUERY.geographic_scope.codes.slice(0, 4).join(", ")}{QUERY.geographic_scope.codes.length > 4 ? "…" : ""}</div>
          </div>
          <button className="btn" onClick={() => location.href = "Data Explorer - Aggregate Builder.html"}>
            <Icon name="edit" size={14}/> Edit query
          </button>
        </div>
      </div>

      {/* Results table */}
      <div className="card" style={{padding:0, overflow:"hidden"}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">Results</strong>
          <span className="t-cap">{sortedRows.length} row{sortedRows.length === 1 ? "" : "s"}</span>
          <div style={{flex:1}}/>
          <label style={{display:"flex", alignItems:"center", gap:6, fontSize:12.5, color:"var(--neutral-700)", cursor:"pointer"}}>
            <input type="checkbox" checked={showSuppressed} onChange={(e) => setShowSuppressed(e.target.checked)}/>
            Show suppressed rows
          </label>
          <span className="t-cap">sort: <strong className="t-mono">{sortKey} {sortDir === "asc" ? "↑" : "↓"}</strong></span>
        </div>

        <div style={{overflowX:"auto"}}>
          <table className="tbl" style={{minWidth:920}}>
            <thead>
              <tr>
                {COLUMNS.map(c => {
                  const sorted = c.key === sortKey;
                  return (
                    <th key={c.key} onClick={() => setSort(c.key)} className="sortable"
                      style={{textAlign: c.num ? "right" : "left", cursor:"pointer"}}>
                      <span style={{display:"inline-flex", alignItems:"center", gap:4}}>
                        {c.label}
                        {sorted && (sortDir === "asc"
                          ? <Icon name="chevronUp" size={11}/>
                          : <Icon name="chevronDown" size={11}/>)}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, i) => (
                <tr key={i} style={row.suppressed ? { background:"var(--neutral-50)" } : undefined}>
                  {COLUMNS.map(c => {
                    const v = row[c.key];
                    const cellSuppressed = row.suppressed && (c.group === "count" || c.group === "agg");
                    return (
                      <td key={c.key} style={{
                        textAlign: c.num ? "right" : "left",
                        fontFamily: c.num ? "'JetBrains Mono', monospace" : undefined,
                        fontSize: c.num ? 13 : 13.5,
                        color: row.suppressed ? "var(--neutral-500)" : undefined,
                      }}>
                        {cellSuppressed ? <SuppressedCell/>
                          : c.fmt ? c.fmt(v)
                          : c.num && typeof v === "number" ? v.toLocaleString()
                          : v}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Metadata footer */}
        <div style={{
          padding:"12px 20px",
          borderTop:"1px solid var(--neutral-200)",
          background:"var(--neutral-50)",
          display:"grid", gridTemplateColumns:"repeat(5, 1fr)", gap:18,
          fontSize:12.5,
        }}>
          <MetaCell label="Matview"            value={<span className="t-mono">{ds.matview}</span>}/>
          <MetaCell label="Refreshed"          value={<span className="t-mono">{ds.refreshed_at}</span>}/>
          <MetaCell label="k-floor used"       value={`k≥${k}`}/>
          <MetaCell label="Suppressed cells"   value={`${suppressedCount} of ${totalCellCount}`}
            extra={<span className="t-cap" style={{color:"var(--accent-quality)"}}>{Math.round(100 * suppressedCount / totalCellCount)}% suppressed</span>}/>
          <MetaCell label="Strictest class"    value={<PrivacyChip klass={klass} size="sm"/>}/>
        </div>
        <div style={{
          padding:"10px 20px",
          borderTop:"1px solid var(--neutral-200)",
          background:"var(--neutral-50)",
          display:"flex", alignItems:"center", gap:14,
          fontSize:12, color:"var(--neutral-500)",
        }}>
          <Icon name="info" size={12}/>
          <span>
            {DE_SUPPRESSION.long} {DE_SUPPRESSION.detail} Hover any "—" cell to read the suppression vocabulary
            (<span className="t-mono">{DE_SUPPRESSION.vocab_id}</span>).
          </span>
          <div style={{flex:1}}/>
          <span className="t-mono">query_hash: {queryHash}</span>
        </div>
      </div>

      {/* Handoff strip — always visible per spec */}
      <div className="card" style={{
        marginTop:16, padding:"16px 20px",
        borderLeft:"4px solid var(--accent-update)",
        display:"flex", alignItems:"center", gap:16,
      }}>
        <div style={{
          width:40, height:40, borderRadius:"50%",
          background:"var(--accent-update-bg)", color:"var(--accent-update)",
          display:"grid", placeItems:"center", flex:"0 0 auto",
        }}>
          <Icon name="arrowRight" size={18}/>
        </div>
        <div style={{flex:1, minWidth:0}}>
          <div style={{fontWeight:600, color:"var(--accent-update)"}}>Need record-level data?</div>
          <div className="t-bodysm" style={{color:"var(--neutral-700)", marginTop:2}}>
            Aggregate results can't answer record-specific questions. Open a DRS draft in the Operator Console with this query attached as the originating context.
          </div>
        </div>
        <button className="btn btn-primary">
          <Icon name="arrowRight" size={14}/> Request record-level data
        </button>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Navigate">
          <ScreenJumpTweak active="results"/>
        </TweakSection>
      </TweaksPanel>
    </DEShell>
  );
};

const MetaCell = ({ label, value, extra }) => (
  <div>
    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)"}}>{label.toUpperCase()}</div>
    <div style={{fontWeight:500, fontSize:13, marginTop:2}}>{value}</div>
    {extra && <div className="t-cap mt-1">{extra}</div>}
  </div>
);

ReactDOM.createRoot(document.getElementById("app")).render(<ResultsScreen/>);
