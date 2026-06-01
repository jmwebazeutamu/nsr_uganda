/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_PRIVACY, DE_COVERAGE_ROWS,
   PrivacyChip, DEShell, ScreenJumpTweak,
   useDeCatalogue, useDeCoverage, useDeMe, RoleGateBanner,
   TweaksPanel, useTweaks, TweakSection */

// NSR MIS — Data Explorer · Registration by area (screen 4 of 5)
// =========================================================
// How many households are registered in each geographic area, as a
// choropleth + sortable table. Live from GET /coverage/{dataset_id}/
// (CoverageSnapshot.row_count); mock rows are an offline-preview
// fallback only. Completeness % is kept as a secondary column.

const { useState: useCov, useMemo: useCovM } = React;

/* ================================================================
   Choropleth map — Uganda admin areas shaded by registered-household
   COUNT.

   Boundaries are NOT bundled: fetched at runtime from geoBoundaries
   gbOpen (simplified) via the Git-LFS media endpoint (CORS-friendly).
   For offline / government-data-centre use, self-host the HDX Uganda
   COD-AB GeoJSON and point window.DE_UGA_BOUNDARIES_URL at it.

   Join is by normalised admin NAME (coverage geo_label ↔ feature
   shapeName). A "matched N of M" badge makes a bad join obvious. The
   map degrades to a clear message (table still renders) when d3 is
   missing or the fetch fails.
   ================================================================ */
// geoBoundaries stores these via Git LFS — raw.githubusercontent returns
// the LFS *pointer* (not JSON). media.githubusercontent.com/media serves
// the resolved LFS content with permissive CORS.
const _GB = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/UGA";
const _UGA_BOUNDARIES = {
  region:     `${_GB}/ADM1/geoBoundaries-UGA-ADM1_simplified.geojson`,
  sub_region: `${_GB}/ADM1/geoBoundaries-UGA-ADM1_simplified.geojson`,
  district:   `${_GB}/ADM2/geoBoundaries-UGA-ADM2_simplified.geojson`,
  sub_county: `${_GB}/ADM3/geoBoundaries-UGA-ADM3_simplified.geojson`,
};
const _boundaryUrl = (level) =>
  (typeof window !== "undefined" && window.DE_UGA_BOUNDARIES_URL)
  || _UGA_BOUNDARIES[level] || _UGA_BOUNDARIES.district;

// Candidate name properties across COD-AB / geoBoundaries schemas.
const _NAME_PROPS = ["shapeName", "ADM2_EN", "ADM1_EN", "ADM3_EN",
  "DName2019", "name", "NAME_1", "NAME_2"];
const _featureName = (f) =>
  _NAME_PROPS.map(p => f && f.properties && f.properties[p]).find(Boolean) || "";
// Normalise for the name join: lowercase, drop a trailing admin word.
const _norm = (s) => String(s || "").toLowerCase()
  .replace(/\b(district|region|sub[- ]?region|sub[- ]?county|city|municipality)\b/g, "")
  .replace(/[^a-z0-9]/g, "").trim();

// Compact count formatter for legends/labels (1,842,117 → "1.8M").
const _fmtN = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
  return String(v);
};

const useGeoJson = (url) => {
  const [state, setState] = React.useState({ data: null, loading: !!url, error: null });
  React.useEffect(() => {
    if (!url) { setState({ data: null, loading: false, error: null }); return; }
    let cancelled = false;
    setState({ data: null, loading: true, error: null });
    fetch(url)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => { if (!cancelled) setState({ data: d, loading: false, error: null }); })
      .catch(e => { if (!cancelled) setState({ data: null, loading: false, error: String(e) }); });
    return () => { cancelled = true; };
  }, [url]);
  return state;
};

const _MapShell = ({ children }) => (
  <div style={{
    minHeight: 320, display: "grid", placeItems: "center",
    padding: 24, textAlign: "center", color: "var(--neutral-500)",
  }} className="t-cap">{children}</div>
);

const ChoroplethMap = ({ rows, level }) => {
  const d3 = (typeof window !== "undefined") ? window.d3 : null;
  const { data: geo, loading, error } = useGeoJson(_boundaryUrl(level));
  const byName = useCovM(() => {
    const m = {};
    rows.forEach(r => { const k = _norm(r.geo_label); if (k) m[k] = r; });
    return m;
  }, [rows]);

  if (!d3 || !d3.geoMercator || !d3.scaleSequential) {
    return <_MapShell>Map library unavailable (d3 didn't load). The table below is unaffected.</_MapShell>;
  }
  if (loading) return <_MapShell>Loading Uganda boundaries…</_MapShell>;
  if (error || !geo || !Array.isArray(geo.features)) {
    return (
      <_MapShell>
        Couldn't load Uganda boundaries ({error || "no features"}).<br/>
        The table below still shows the data. For offline use, self-host the
        HDX COD-AB GeoJSON and set <span className="t-mono">window.DE_UGA_BOUNDARIES_URL</span>.
      </_MapShell>
    );
  }

  const features = geo.features;
  const W = 640, H = 600;
  const proj = d3.geoMercator().fitSize([W, H], geo);
  const path = d3.geoPath(proj);
  const matched = features.filter(f => byName[_norm(_featureName(f))]).length;

  // Shade by registered-household COUNT.
  const maxV = Math.max(1, ...rows.map(r => r.households || 0));
  const scale = d3.scaleSequential(d3.interpolateBlues).domain([0, maxV]);
  const fill = (row) => row ? scale(row.households || 0) : "var(--neutral-200)";
  const legendBins = [0.9, 0.65, 0.4, 0.15].map(f => ({
    label: `≥ ${_fmtN(Math.round(maxV * f))}`, color: scale(maxV * f),
  }));

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderBottom: "1px solid var(--neutral-200)" }}>
        <Icon name="mapPin" size={14} color="var(--neutral-600)"/>
        <strong className="t-bodysm">Registered households by area</strong>
        <Chip size="sm" tone={matched ? "data" : "danger"}>
          {matched} of {features.length} areas matched
        </Chip>
        <div style={{ flex: 1 }}/>
        <span className="t-cap">join by area name · boundaries: geoBoundaries gbOpen</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 0, alignItems: "stretch" }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", maxHeight: 560, background: "var(--neutral-50)" }}>
          {features.map((f, i) => {
            const row = byName[_norm(_featureName(f))];
            return (
              <path key={i} d={path(f)} fill={fill(row)}
                stroke="#fff" strokeWidth={0.5} style={{ cursor: "default" }}>
                <title>
                  {_featureName(f)}{row
                    ? ` — ${(row.households || 0).toLocaleString()} households registered`
                    : " — no data"}
                </title>
              </path>
            );
          })}
        </svg>
        <div style={{ padding: "16px 18px", borderLeft: "1px solid var(--neutral-200)", minWidth: 190, display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="t-cap" style={{ fontWeight: 600 }}>HOUSEHOLDS REGISTERED</div>
          {legendBins.map((b, i) => <LegendDot key={i} color={b.color} label={b.label}/>)}
          <LegendDot color="var(--neutral-200)" label="no data"/>
          <div className="t-cap mt-1" style={{ marginTop: "auto" }}>Hover an area for its count.</div>
        </div>
      </div>
    </div>
  );
};

const CoverageScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "coverage" });
  const [datasetId, setDatasetId] = useCov("");
  const [sortKey, setSortKey] = useCov("households");
  const [sortDir, setSortDir] = useCov("desc");

  const me = useDeMe();
  const [datasets] = useDeCatalogue();

  // Snap off the mock seed onto the first real dataset so /coverage/
  // hits a live dataset id. The mock "ds_hh_profile" 404s → mock rows,
  // which is what made the figures look fabricated.
  React.useEffect(() => {
    if (datasets.length && !datasets.some(d => d.id === datasetId || d.code === datasetId)) {
      setDatasetId(datasets[0].id || datasets[0].code);
    }
  }, [datasets]);

  const ds = datasets.find(d => d.id === datasetId || d.code === datasetId)
    || DE_DATASETS.find(d => d.id === datasetId || d.code === datasetId)
    || datasets[0] || DE_DATASETS[0];
  const [coverage, covMeta] = useDeCoverage(ds?.id || ds?.code || datasetId);

  // households = registered count per area (CoverageSnapshot.row_count);
  // completeness kept as a secondary signal (0-1, or null when absent).
  const normalised = useCovM(() => coverage.map(r => ({
    ...r,
    households: r.households ?? r.rows ?? r.row_count ?? 0,
    completeness: r.completeness != null
      ? Number(r.completeness)
      : (r.completeness_pct != null ? Number(r.completeness_pct) / 100 : null),
    geo_label: r.geo_label || r.label || r.geo_code,
  })), [coverage]);

  const sortedRows = useCovM(() => {
    return [...normalised].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (typeof av === "number") return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }, [sortKey, sortDir, normalised]);

  const setSort = (k) => {
    if (k === sortKey) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("desc"); }
  };

  const level = normalised[0]?.geo_level || "area";
  const totalHouseholds = useCovM(() => normalised.reduce((s, r) => s + r.households, 0), [normalised]);
  const maxHouseholds = useCovM(() => Math.max(1, ...normalised.map(r => r.households)), [normalised]);
  const topArea = useCovM(() =>
    normalised.reduce((m, r) => (r.households > (m ? m.households : -1) ? r : m), null),
    [normalised]);
  const isLive = !!(covMeta && covMeta.isLive);

  return (
    <DEShell active="coverage" refreshed_at={ds?.refreshed_at}>
      <RoleGateBanner me={me}/>
      <PageHeader
        eyebrow="DATA EXPLORER · REGISTRATION BY AREA"
        title="Registered households by area"
        sub={<>How many households are registered in each {level}. Darker areas hold more households. Use it to spot under-registered areas before scoping a query.</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn btn-primary" onClick={() => location.href="Data Explorer - Aggregate Builder.html"}>
            <Icon name="sliders" size={14}/> Build a query
          </button>
        </>}
      />

      {/* Selector + KPIs */}
      <div className="card" style={{padding:"16px 20px", marginBottom:16,
        display:"grid", gridTemplateColumns:"1.6fr 1fr 1fr 1.2fr", gap:24, alignItems:"center"}}>
        <div>
          <div className="t-cap">DATASET</div>
          <div style={{display:"flex", alignItems:"center", gap:10, marginTop:4}}>
            <select className="field-select" style={{maxWidth:320}}
              value={ds.id} onChange={(e) => setDatasetId(e.target.value)}>
              {datasets.filter(d => d.privacy !== "sensitive").map(d =>
                <option key={d.id || d.code} value={d.id || d.code}>{d.code} — {d.label}</option>
              )}
            </select>
            <PrivacyChip klass={ds.privacy} size="sm"/>
            <Chip size="sm" tone={isLive ? "data" : "neutral"}>{isLive ? "live" : "preview · mock"}</Chip>
          </div>
          <div className="t-cap mt-1">GET /coverage/{ds.id}/</div>
        </div>
        <KPI label="Households registered" value={totalHouseholds.toLocaleString()} accent="data"
          foot={`across ${normalised.length} ${level}s`}/>
        <KPI label={`${level}s`} value={normalised.length} accent="neutral"
          foot="with registrations"/>
        <KPI label={`Most-registered ${level}`} value={topArea ? topArea.geo_label : "—"} accent="neutral"
          foot={topArea ? `${topArea.households.toLocaleString()} households` : ""}/>
      </div>

      {/* Choropleth map — Uganda admin areas shaded by household count */}
      <div className="card" style={{padding:0, marginBottom:16, overflow:"hidden"}}>
        <ChoroplethMap rows={normalised} level={normalised[0]?.geo_level || "district"}/>
      </div>

      {/* Per-area table */}
      <div className="card" style={{padding:0}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">{ds.code} · households by {level}</strong>
          <span className="t-cap">{sortedRows.length} {level}s</span>
          <div style={{flex:1}}/>
          <span className="t-cap">{isLive ? "live" : "mock"} · GET /coverage/{ds.id}/</span>
        </div>

        <div style={{overflowX:"auto"}}>
          <table className="tbl" style={{minWidth:820}}>
            <thead>
              <tr>
                <th style={{width:40}}>#</th>
                <Th sk="geo_level" sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Level</Th>
                <Th sk="geo_code"  sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Code</Th>
                <Th sk="geo_label" sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Area</Th>
                <Th sk="households" sortKey={sortKey} sortDir={sortDir} onClick={setSort} num>Households</Th>
                <th style={{width:240}}>Share of largest</th>
                <Th sk="completeness" sortKey={sortKey} sortDir={sortDir} onClick={setSort} num>Completeness</Th>
                <Th sk="last_capture" sortKey={sortKey} sortDir={sortDir} onClick={setSort}>Last capture</Th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r, i) => {
                const share = Math.round(100 * r.households / maxHouseholds);
                return (
                  <tr key={r.geo_code}>
                    <td className="t-cap t-mono">{String(i + 1).padStart(2, "0")}</td>
                    <td className="t-cap">{r.geo_level}</td>
                    <td className="t-mono" style={{fontSize:12}}>{r.geo_code}</td>
                    <td style={{fontWeight:500}}>{r.geo_label}</td>
                    <td style={{textAlign:"right", fontFamily:"'JetBrains Mono', monospace", fontWeight:600}}>
                      {r.households.toLocaleString()}
                    </td>
                    <td>
                      <div style={{height:8, borderRadius:4, background:"var(--neutral-100)", overflow:"hidden"}}>
                        <div style={{
                          width: `${share}%`, height:"100%",
                          background: "var(--accent-data)",
                          transition:"width 0.2s",
                        }}/>
                      </div>
                    </td>
                    <td style={{textAlign:"right", fontFamily:"'JetBrains Mono', monospace", color:"var(--neutral-600)"}}>
                      {r.completeness == null ? "—" : `${(r.completeness * 100).toFixed(1)}%`}
                    </td>
                    <td className="t-cap">{r.last_capture || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div style={{
          padding:"12px 20px",
          borderTop:"1px solid var(--neutral-200)",
          background:"var(--neutral-50)",
          display:"flex", alignItems:"center", gap:18,
          fontSize:12, color:"var(--neutral-500)",
        }}>
          <Icon name="info" size={12}/>
          <span>Households registered = count of household records captured in the area for this dataset (CoverageSnapshot row count). Completeness is shown as a secondary signal where available.</span>
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
