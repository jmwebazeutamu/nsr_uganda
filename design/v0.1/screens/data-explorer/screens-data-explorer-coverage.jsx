/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_PRIVACY, DE_COVERAGE_ROWS,
   PrivacyChip, DEShell, ScreenJumpTweak,
   useDeCatalogue, useDeCoverage, useDeMe, RoleGateBanner,
   TweaksPanel, useTweaks, TweakSection */

// NSR MIS — Data Explorer · Coverage view (screen 4 of 5)
// =========================================================
// Choropleth-friendly table per dataset: one row per geographic
// area with completeness % and row count. Used to spot data gaps
// before composing an aggregate query — analysts often filter
// to areas above a coverage threshold to avoid bias.

const { useState: useCov, useMemo: useCovM } = React;

const CoverageScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "coverage" });
  const [datasetId, setDatasetId] = useCov("ds_hh_profile");
  const [threshold, setThreshold] = useCov(0);
  const [sortKey, setSortKey] = useCov("completeness");
  const [sortDir, setSortDir] = useCov("desc");

  const me = useDeMe();
  const [datasets] = useDeCatalogue();
  const ds = datasets.find(d => d.id === datasetId || d.code === datasetId) || DE_DATASETS.find(d => d.id === datasetId);
  const [coverage] = useDeCoverage(ds?.id || ds?.code || datasetId);
  // Coverage payload may use either `completeness` or
  // `completeness_pct` (0-1 vs 0-100); normalise to 0-1.
  const normalised = useCovM(() => coverage.map(r => ({
    ...r,
    completeness: r.completeness != null
      ? Number(r.completeness)
      : (r.completeness_pct != null ? Number(r.completeness_pct) / 100 : 0),
    rows: r.rows ?? r.row_count ?? 0,
    geo_label: r.geo_label || r.label || r.geo_code,
  })), [coverage]);

  const sortedRows = useCovM(() => {
    const filt = normalised.filter(r => r.completeness >= threshold);
    return [...filt].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (typeof av === "number") return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [threshold, sortKey, sortDir, normalised]);

  const setSort = (k) => {
    if (k === sortKey) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("desc"); }
  };

  const meanCompleteness = useCovM(() =>
    sortedRows.reduce((s, r) => s + r.completeness, 0) / Math.max(1, sortedRows.length),
    [sortedRows]);
  const totalRows = useCovM(() => sortedRows.reduce((s, r) => s + r.rows, 0), [sortedRows]);
  const areasUnder80 = useCovM(() => normalised.filter(r => r.completeness < 0.8).length, [normalised]);

  return (
    <DEShell active="coverage" refreshed_at={ds?.refreshed_at}>
      <RoleGateBanner me={me}/>
      <PageHeader
        eyebrow="DATA EXPLORER · COVERAGE VIEW"
        title="Coverage by geographic area"
        sub={<>Completeness % and row count per area. Use this to scope queries to areas with sufficient data before running an aggregate.</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn btn-primary" onClick={() => location.href="Data Explorer - Aggregate Builder.html"}>
            <Icon name="sliders" size={14}/> Build a query
          </button>
        </>}
      />

      {/* Selector + KPIs */}
      <div className="card" style={{padding:"16px 20px", marginBottom:16,
        display:"grid", gridTemplateColumns:"1.4fr 1fr 1fr 1fr 1fr", gap:24, alignItems:"center"}}>
        <div>
          <div className="t-cap">DATASET</div>
          <div style={{display:"flex", alignItems:"center", gap:10, marginTop:4}}>
            <select className="field-select" style={{maxWidth:320}}
              value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
              {datasets.filter(d => d.privacy !== "sensitive").map(d =>
                <option key={d.id} value={d.id}>{d.code} — {d.label}</option>
              )}
            </select>
            <PrivacyChip klass={ds.privacy} size="sm"/>
          </div>
          <div className="t-cap mt-1">{ds.rows} rows · refresh {ds.refresh.toLowerCase()}</div>
        </div>
        <KPI label="Mean completeness" value={`${(meanCompleteness * 100).toFixed(1)}%`}
          accent={meanCompleteness >= 0.9 ? "data" : meanCompleteness >= 0.8 ? "quality" : "danger"}/>
        <KPI label="Areas under 80%" value={areasUnder80}
          accent={areasUnder80 === 0 ? "data" : "quality"}
          foot={`of ${normalised.length} ${normalised[0]?.geo_level || "areas"}`}/>
        <KPI label="Visible rows" value={totalRows.toLocaleString()} accent="neutral"
          foot={`${sortedRows.length} areas`}/>
        <div>
          <div className="t-cap">THRESHOLD FILTER</div>
          <div style={{display:"flex", alignItems:"center", gap:8, marginTop:8}}>
            <input type="range" min={0} max={1} step={0.05}
              value={threshold} onChange={(e) => setThreshold(parseFloat(e.target.value))}
              style={{flex:1}}/>
            <span className="t-mono" style={{width:48, fontSize:13, fontWeight:600}}>
              {(threshold * 100).toFixed(0)}%
            </span>
          </div>
          <div className="t-cap mt-1">show areas at or above this completeness</div>
        </div>
      </div>

      {/* Choropleth-style table */}
      <div className="card" style={{padding:0}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">{ds.code} · coverage by {normalised[0]?.geo_level || "area"}</strong>
          <span className="t-cap">{sortedRows.length} of {normalised.length} {normalised[0]?.geo_level || "area"}s</span>
          <div style={{flex:1}}/>
          <span className="t-cap">GET /coverage/{ds.id}/</span>
        </div>

        <div style={{overflowX:"auto"}}>
          <table className="tbl" style={{minWidth:780}}>
            <thead>
              <tr>
                <th style={{width:40}}>#</th>
                <Th sk="geo_level" sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Level</Th>
                <Th sk="geo_code"  sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Code</Th>
                <Th sk="geo_label" sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Area</Th>
                <Th sk="completeness" sortKey={sortKey} sortDir={sortDir} onClick={setSort} num>Completeness</Th>
                <th style={{width:240}}>Coverage bar</th>
                <Th sk="rows" sortKey={sortKey} sortDir={sortDir} onClick={setSort} num>Rows</Th>
                <Th sk="last_capture" sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Last capture</Th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r, i) => {
                const pct = r.completeness * 100;
                const tone = r.completeness >= 0.9 ? "data" : r.completeness >= 0.8 ? "quality" : "danger";
                const accent = `var(--accent-${tone})`;
                return (
                  <tr key={r.geo_code}>
                    <td className="t-cap t-mono">{String(i + 1).padStart(2, "0")}</td>
                    <td className="t-cap">{r.geo_level}</td>
                    <td className="t-mono" style={{fontSize:12}}>{r.geo_code}</td>
                    <td style={{fontWeight:500}}>{r.geo_label}</td>
                    <td style={{textAlign:"right", fontFamily:"'JetBrains Mono', monospace", fontWeight:600, color: accent}}>
                      {pct.toFixed(1)}%
                    </td>
                    <td>
                      <div style={{height:8, borderRadius:4, background:"var(--neutral-100)", overflow:"hidden"}}>
                        <div style={{
                          width: `${pct}%`, height:"100%",
                          background: accent,
                          transition:"width 0.2s",
                        }}/>
                      </div>
                    </td>
                    <td style={{textAlign:"right", fontFamily:"'JetBrains Mono', monospace"}}>
                      {r.rows.toLocaleString()}
                    </td>
                    <td className="t-cap">{r.last_capture}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Legend + footer */}
        <div style={{
          padding:"12px 20px",
          borderTop:"1px solid var(--neutral-200)",
          background:"var(--neutral-50)",
          display:"flex", alignItems:"center", gap:18,
          fontSize:12, color:"var(--neutral-500)",
        }}>
          <span>Coverage thresholds:</span>
          <LegendDot color="var(--accent-data)"    label="≥ 90% complete"/>
          <LegendDot color="var(--accent-quality)" label="80–89%"/>
          <LegendDot color="var(--accent-danger)"  label="< 80% — caution"/>
          <div style={{flex:1}}/>
          <Icon name="info" size={12}/>
          <span>Completeness = (rows with all required vars filled) / (expected rows from the UBOS sampling frame).</span>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Navigate">
          <ScreenJumpTweak active="coverage"/>
        </TweakSection>
      </TweaksPanel>
    </DEShell>
  );
};

const Th = ({ children, sk, sortKey, sortDir, onClick, num }) => {
  const sorted = sk === sortKey;
  return (
    <th onClick={() => onClick(sk)} className="sortable"
      style={{textAlign: num ? "right" : "left", cursor:"pointer"}}>
      <span style={{display:"inline-flex", alignItems:"center", gap:4}}>
        {children}
        {sorted && (sortDir === "asc"
          ? <Icon name="chevronUp" size={11}/>
          : <Icon name="chevronDown" size={11}/>)}
      </span>
    </th>
  );
};

const KPI = ({ label, value, accent = "data", foot }) => (
  <div>
    <div className="t-cap">{label.toUpperCase()}</div>
    <div style={{
      fontWeight:700, fontSize:24, marginTop:2,
      color: accent === "neutral" ? "var(--neutral-900)" : `var(--accent-${accent})`,
      fontFamily:"'JetBrains Mono', monospace",
      letterSpacing:"-0.02em",
    }}>{value}</div>
    {foot && <div className="t-cap mt-1">{foot}</div>}
  </div>
);

const LegendDot = ({ color, label }) => (
  <span style={{display:"inline-flex", alignItems:"center", gap:6}}>
    <span style={{width:10, height:10, borderRadius:2, background: color}}/>
    {label}
  </span>
);

ReactDOM.createRoot(document.getElementById("app")).render(<CoverageScreen/>);
