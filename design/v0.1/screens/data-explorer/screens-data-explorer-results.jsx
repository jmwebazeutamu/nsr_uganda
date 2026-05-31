/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_VARIABLES_BY_DATASET, DE_PRIVACY, DE_RESULT_ROWS, DE_SUPPRESSION,
   PrivacyChip, DEShell, ScreenJumpTweak, SuppressedCell,
   useDeCatalogue, useDeMe, RoleGateBanner, HandoffPrompt,
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

// Columns are derived from the live aggregate response (the group-by
// dimensions + the count). COLUMNS below is only the offline-preview
// fallback shape used when there are no rows to introspect.
const COLUMNS = [
  { key: "subregion", label: "Sub-region",      group: "geo" },
  { key: "district",  label: "District",        group: "geo" },
  { key: "roof",      label: "Roof material",   group: "fact" },
  { key: "water",     label: "Water source",    group: "fact" },
  { key: "count",     label: "Households",      group: "count", num: true },
  { key: "pmt_avg",   label: "Mean PMT score",  group: "agg",   num: true, fmt: (v) => v == null ? null : v.toFixed(3) },
];

const _humanize = (k) => String(k).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
const _deriveColumns = (rows) => {
  if (!Array.isArray(rows) || !rows.length) return COLUMNS;
  const sample = rows[0];
  const keys = Object.keys(sample).filter(k => k !== "suppressed");
  const dims = keys.filter(k => k !== "count");
  const cols = dims.map(k => ({
    key: k, label: _humanize(k),
    num: typeof sample[k] === "number", group: "fact",
  }));
  if ("count" in sample) {
    cols.push({ key: "count", label: "Count", num: true, group: "count" });
  }
  return cols;
};

const _readSession = () => {
  try {
    const raw = sessionStorage.getItem("de_last_aggregate");
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
};

const ResultsScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "results" });
  const [sortKey, setSortKey] = useRes("count");
  const [sortDir, setSortDir] = useRes("desc");
  const [showSuppressed, setShowSuppressed] = useRes(true);

  const me = useDeMe();
  const [datasets] = useDeCatalogue();
  const [handoffOpen, setHandoffOpen] = useRes(false);
  // Pull the most recent aggregate response stashed by the Builder.
  // Falls back to the seeded QUERY + DE_RESULT_ROWS when nothing is in
  // sessionStorage so a fresh tab still renders a believable page.
  const session = useRes(_readSession())[0];
  const liveResponse = session?.response;
  const livePayload  = session?.payload;

  const datasetCode = livePayload?.dataset_code || QUERY.dataset_code;
  const ds = datasets.find(d => d.code === datasetCode)
    || DE_DATASETS.find(d => d.code === datasetCode)
    || datasets[0] || DE_DATASETS[0];
  const k = (DE_PRIVACY[ds.privacy] || {}).k_floor ?? 0;

  const projection = livePayload?.projection || QUERY.projection;

  // Strictest class — based on projection + dataset
  const klass = useResM(() => {
    const vars = DE_VARIABLES_BY_DATASET[ds.id] || [];
    const list = projection.map(p => vars.find(v => v.code === p)?.privacy).filter(Boolean);
    list.push(ds.privacy);
    const order = { public: 0, internal: 1, personal: 2, sensitive: 3 };
    return list.reduce((best, c) => order[c] > order[best] ? c : best, "public");
  }, [ds, projection]);

  // Live rows from the API, else the seeded mock corpus.
  const rawRows = (liveResponse && Array.isArray(liveResponse.rows))
    ? liveResponse.rows.map(r => ({
        ...r,
        count: r.count == null ? null : Number(r.count),
        suppressed: r.suppressed === true || r.count == null,
      }))
    : DE_RESULT_ROWS;

  // Backend-driven columns + query summary — derived from the response /
  // the payload that produced it. QUERY/COLUMNS are offline fallbacks.
  const columns = useResM(() => _deriveColumns(rawRows), [rawRows]);
  const filtersList = livePayload?.filters || QUERY.filters || [];
  const scope = livePayload?.geographic_scope || QUERY.geographic_scope || { level: "", codes: [] };

  const sortedRows = useResM(() => {
    const rows = showSuppressed ? rawRows : rawRows.filter(r => !r.suppressed);
    return [...rows].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number") return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [sortKey, sortDir, showSuppressed, rawRows]);

  const suppressedCount = liveResponse?.metadata?.suppressed_cell_count
    ?? rawRows.filter(r => r.suppressed).length;
  const totalCellCount = liveResponse?.metadata?.total_cell_count
    ?? rawRows.length * (columns.filter(c => c.group === "count").length || 1);
  const queryHash = liveResponse?.metadata?.query_hash || "qh_8f3a92e4c1b6d0a7";
  const matview = liveResponse?.metadata?.matview;
  const refreshedAt = liveResponse?.metadata?.refreshed_at || ds.refreshed_at;

  const handoffContext = () => ({
    dataset_code: ds.code,
    dataset_label: ds.label,
    requested_entity: "Household",
    requested_fields: projection,
    geographic_scope: livePayload?.geographic_scope || QUERY.geographic_scope,
    filter_expression: {
      and: (livePayload?.filters || QUERY.filters || []).map(f => ({
        variable: f.variable || f.var, op: f.op, value: f.value,
      })),
    },
    estimated_row_count: rawRows.length,
    source_query_hash: queryHash,
  });

  const setSort = (key) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  };

  return (
    <DEShell active="results" refreshed_at={refreshedAt}>
      <RoleGateBanner me={me}/>
      <PageHeader
        eyebrow={<>DATA EXPLORER · RESULTS · <span className="t-mono">qh:{queryHash.slice(3, 11)}…</span></>}
        title="Aggregate results"
        sub={<>HTTP 200 · {sortedRows.length} of {rawRows.length} rows{matview ? <> · matview <span className="t-mono">{matview}</span></> : null} · {suppressedCount} suppressed cell{suppressedCount === 1 ? "" : "s"}</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn"><Icon name="save" size={14}/> Save query</button>
          <button className="btn btn-primary" onClick={() => setHandoffOpen(true)}>
            <Icon name="arrowRight" size={14}/> Request record-level data
          </button>
        </>}
      />
      <HandoffPrompt
        open={handoffOpen}
        context={handoffContext()}
        onClose={() => setHandoffOpen(false)}
      />

      {/* Query summary card — what produced these rows */}
      <div className="card" style={{padding:0, marginBottom:16, borderTop: `3px solid ${DE_PRIVACY[klass].accent}`}}>
        <div style={{padding:"16px 20px", display:"grid", gridTemplateColumns:"1.4fr 1fr 1fr auto", gap:24, alignItems:"center"}}>
          <div>
            <div className="t-cap">QUERY</div>
            <div style={{display:"flex", alignItems:"center", gap:8, marginTop:4}}>
              <span className="t-mono" style={{fontWeight:600, fontSize:14}}>{datasetCode}</span>
              <PrivacyChip klass={klass}/>
            </div>
            <div className="t-cap mt-1">
              project [{projection.join(", ")}] · filter {filtersList.length}
              {" "}· scope {scope.codes.length ? `${scope.codes.length} ${scope.level}s` : `all ${scope.level || "units"}`}
            </div>
          </div>
          <div>
            <div className="t-cap">FILTERS</div>
            <div style={{display:"flex", flexWrap:"wrap", gap:4, marginTop:6}}>
              {filtersList.length === 0 && <span className="t-cap">none</span>}
              {filtersList.map((f, i) => (
                <span key={i} className="t-mono" style={{fontSize:11, padding:"2px 6px", border:"1px solid var(--neutral-300)", borderRadius:3, background:"#fff"}}>
                  {(f.variable || f.var)} {f.op} {Array.isArray(f.value) ? f.value.join("|") : f.value}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="t-cap">SCOPE</div>
            <div className="t-bodysm" style={{fontWeight:500, marginTop:4}}>
              {scope.codes.length ? `${scope.codes.length} ${scope.level}s` : `All ${scope.level || "units"}`}
            </div>
            <div className="t-cap mt-1">{scope.codes.slice(0, 4).join(", ")}{scope.codes.length > 4 ? "…" : ""}</div>
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
                {columns.map(c => {
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
                  {columns.map(c => {
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
          <MetaCell label="Matview"            value={<span className="t-mono">{matview || ds.matview}</span>}/>
          <MetaCell label="Refreshed"          value={<span className="t-mono">{refreshedAt}</span>}/>
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
        <button className="btn btn-primary" onClick={() => setHandoffOpen(true)}>
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
