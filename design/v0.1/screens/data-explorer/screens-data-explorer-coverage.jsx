/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_PRIVACY, DE_COVERAGE_ROWS,
   PrivacyChip, DEShell, ScreenJumpTweak,
   useDeCatalogue, useDeCoverage, useDeMe, RoleGateBanner,
   navigateDeScreen,
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
const _localMapAsset = (path) =>
  (typeof window !== "undefined" && window.NSR_EMBEDDED_CONSOLE)
    ? `assets/maps/${path}`
    : `../../../assets/maps/${path}`;

// District boundaries are vendored locally so the console does not
// flicker from a fallback map into a runtime network fetch.
const _GB = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/UGA";
const _UGA_BOUNDARIES = {
  region:     `${_GB}/ADM1/geoBoundaries-UGA-ADM1_simplified.geojson`,
  subregion:  `${_GB}/ADM1/geoBoundaries-UGA-ADM1_simplified.geojson`,
  sub_region: `${_GB}/ADM1/geoBoundaries-UGA-ADM1_simplified.geojson`,
  district:   _localMapAsset("uganda-adm2.geojson"),
  sub_county: `${_GB}/ADM3/geoBoundaries-UGA-ADM3_simplified.geojson`,
};
const _hasCustomBoundaries = () =>
  typeof window !== "undefined" && !!window.DE_UGA_BOUNDARIES_URL;
const _boundaryUrl = (level) =>
  (typeof window !== "undefined" && window.DE_UGA_BOUNDARIES_URL)
  || _UGA_BOUNDARIES[level] || _UGA_BOUNDARIES.district;

// Candidate name properties across COD-AB / geoBoundaries schemas.
const _NAME_PROPS = ["shapeName", "ADM2_EN", "ADM1_EN", "ADM3_EN",
  "DName2019", "name", "NAME_1", "NAME_2"];
const _featureName = (f) =>
  _NAME_PROPS.map(p => f && f.properties && f.properties[p]).find(Boolean) || "";
const _CODE_PROPS = ["shapeID", "shapeISO", "ADM2_PCODE", "ADM1_PCODE", "ADM3_PCODE", "code", "CODE"];
const _featureCodes = (f) =>
  _CODE_PROPS.map(p => f && f.properties && f.properties[p]).filter(Boolean);
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

const _coverageColor = (value, maxV) => {
  const v = Math.max(0, Number(value) || 0);
  if (!v) return "var(--neutral-200)";
  const t = Math.min(1, v / Math.max(1, maxV));
  if (t >= 0.8) return "#084081";
  if (t >= 0.6) return "#0868ac";
  if (t >= 0.4) return "#2b8cbe";
  if (t >= 0.2) return "#4eb3d3";
  return "#a8ddb5";
};

const _geoBounds = (features) => {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = (coords) => {
    if (!Array.isArray(coords)) return;
    if (typeof coords[0] === "number" && typeof coords[1] === "number") {
      minX = Math.min(minX, coords[0]);
      maxX = Math.max(maxX, coords[0]);
      minY = Math.min(minY, coords[1]);
      maxY = Math.max(maxY, coords[1]);
      return;
    }
    coords.forEach(walk);
  };
  features.forEach(f => walk(f.geometry && f.geometry.coordinates));
  return Number.isFinite(minX) ? { minX, minY, maxX, maxY } : null;
};

const _geoPath = (geometry, bounds, width, height) => {
  if (!geometry || !bounds) return "";
  const pad = 18;
  const dx = Math.max(0.0001, bounds.maxX - bounds.minX);
  const dy = Math.max(0.0001, bounds.maxY - bounds.minY);
  const scale = Math.min((width - pad * 2) / dx, (height - pad * 2) / dy);
  const xOffset = (width - dx * scale) / 2;
  const yOffset = (height - dy * scale) / 2;
  const project = ([x, y]) => [
    xOffset + (x - bounds.minX) * scale,
    yOffset + (bounds.maxY - y) * scale,
  ];
  const ringPath = (ring) => {
    if (!Array.isArray(ring) || ring.length < 2) return "";
    return ring.map((pt, i) => {
      const [x, y] = project(pt);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(" ") + " Z";
  };
  if (geometry.type === "Polygon") {
    return geometry.coordinates.map(ringPath).join(" ");
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.flatMap(poly => poly.map(ringPath)).join(" ");
  }
  return "";
};

// Local fallback geography. It is deliberately simple, but it keeps
// the coverage view rendering a recognisable Uganda map when external
// GeoJSON or d3 is unavailable in the data centre.
const _UGA_OUTLINE = "M172 10 L207 28 L242 54 L270 94 L310 134 L300 184 L320 230 L300 276 L266 322 L236 374 L188 398 L154 430 L110 398 L74 356 L58 308 L30 266 L52 218 L42 172 L72 128 L88 84 L124 50 Z";
const _UGA_LAKE_VICTORIA = "M236 362 C260 340 302 340 338 354 L338 430 L214 430 C210 404 218 380 236 362 Z";
const _UGA_LABEL_POINTS = {
  acholi: [132, 92],
  ankole: [158, 344],
  buganda: [176, 280],
  bugandasouth: [168, 306],
  bukedi: [250, 272],
  bunyoro: [130, 210],
  busoga: [238, 250],
  elgon: [276, 228],
  kampala: [204, 306],
  karamoja: [246, 116],
  kigezi: [144, 386],
  lango: [168, 158],
  rwenzori: [92, 294],
  teso: [226, 184],
  tooro: [108, 330],
  westnile: [92, 78],
};
const _fallbackPoint = (row, i, total) => {
  const key = _norm(row.geo_label || row.geo_code);
  if (_UGA_LABEL_POINTS[key]) return _UGA_LABEL_POINTS[key];
  const angle = -Math.PI / 2 + (Math.PI * 2 * i / Math.max(total, 1));
  return [176 + Math.cos(angle) * 88, 238 + Math.sin(angle) * 138];
};

const UgandaFallbackMap = ({ rows, reason }) => {
  const maxV = Math.max(1, ...rows.map(r => r.households || 0));
  const ordered = [...rows].sort((a, b) => (b.households || 0) - (a.households || 0));
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderBottom: "1px solid var(--neutral-200)" }}>
        <Icon name="mapPin" size={14} color="var(--neutral-600)"/>
        <strong className="t-bodysm">Uganda coverage map</strong>
        <Chip size="sm" tone="quality">local fallback</Chip>
        <div style={{ flex: 1 }}/>
        <span className="t-cap">{reason || "external boundaries unavailable"} · bubbles sized by registered households</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 280px", gap: 0, alignItems: "stretch" }}>
        <svg viewBox="0 0 360 430" role="img" aria-label="Map of Uganda showing registered households by area"
             style={{ width: "100%", height: "auto", maxHeight: 560, background: "var(--neutral-50)" }}>
          <path d={_UGA_OUTLINE} fill="var(--accent-data-bg)" stroke="var(--accent-data)" strokeWidth="2"/>
          <path d={_UGA_LAKE_VICTORIA} fill="#D7ECFA" stroke="#9CC6DF" strokeWidth="1"/>
          <text x="276" y="400" textAnchor="middle" style={{fontSize:10, fill:"var(--neutral-500)", fontWeight:600}}>Lake Victoria</text>
          {ordered.map((r, i) => {
            const [x, y] = _fallbackPoint(r, i, ordered.length);
            const radius = 5 + Math.sqrt((r.households || 0) / maxV) * 24;
            return (
              <g key={r.geo_code || r.geo_label || i}>
                <circle cx={x} cy={y} r={radius} fill="var(--accent-data)" opacity="0.78" stroke="#fff" strokeWidth="2">
                  <title>{r.geo_label}: {(r.households || 0).toLocaleString()} households registered</title>
                </circle>
                <text x={x} y={y - radius - 5} textAnchor="middle"
                      style={{fontSize:10.5, fill:"var(--neutral-800)", fontWeight:600}}>
                  {String(r.geo_label || r.geo_code).replace(/^SR-/, "")}
                </text>
              </g>
            );
          })}
        </svg>
        <div style={{ padding: "16px 18px", borderLeft: "1px solid var(--neutral-200)", minWidth: 220, display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="t-cap" style={{ fontWeight: 600 }}>LARGEST AREAS</div>
          {ordered.slice(0, 8).map((r) => (
            <div key={r.geo_code || r.geo_label} style={{display:"grid", gridTemplateColumns:"1fr auto", gap:8, alignItems:"center"}}>
              <span className="t-bodysm" style={{fontWeight:500, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{r.geo_label}</span>
              <span className="t-mono">{_fmtN(r.households)}</span>
            </div>
          ))}
          <div className="t-cap mt-1" style={{ marginTop: "auto" }}>
            Uses local coordinates for the 15 Uganda sub-regions when administrative boundary GeoJSON is not reachable.
          </div>
        </div>
      </div>
    </div>
  );
};

const useGeoJson = (url) => {
  const [state, setState] = React.useState({ data: null, loading: !!url, error: null });
  React.useEffect(() => {
    if (!url) { setState({ data: null, loading: false, error: null }); return; }
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    setState({ data: null, loading: true, error: null });
    fetch(url, { signal: controller.signal })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => { if (!cancelled) setState({ data: d, loading: false, error: null }); })
      .catch(e => { if (!cancelled) setState({ data: null, loading: false, error: String(e && e.name === "AbortError" ? "timeout" : e) }); })
      .finally(() => clearTimeout(timeout));
    return () => { cancelled = true; clearTimeout(timeout); controller.abort(); };
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
  const levelKey = String(level || "").toLowerCase().replace(/-/g, "_");
  const shouldUseLocalSubRegionMap = ["region", "subregion", "sub_region", "area"].includes(levelKey)
    && !_hasCustomBoundaries();
  const { data: geo, loading, error } = useGeoJson(shouldUseLocalSubRegionMap ? null : _boundaryUrl(levelKey));
  const byName = useCovM(() => {
    const m = {};
    rows.forEach(r => {
      [_norm(r.geo_label), _norm(r.geo_code)].filter(Boolean).forEach(k => { m[k] = r; });
    });
    return m;
  }, [rows]);

  if (shouldUseLocalSubRegionMap) {
    return <UgandaFallbackMap rows={rows} reason="stable sub-region map"/>;
  }
  if (loading) {
    return <UgandaFallbackMap rows={rows} reason="loading external boundaries"/>;
  }
  if (error || !geo || !Array.isArray(geo.features)) {
    return <UgandaFallbackMap rows={rows} reason={`boundary fetch failed${error ? `: ${error}` : ""}`}/>;
  }

  const features = geo.features;
  const W = 720, H = 640;
  const bounds = _geoBounds(features);
  const featureRow = (f) =>
    byName[_norm(_featureName(f))]
    || _featureCodes(f).map(c => byName[_norm(c)]).find(Boolean)
    || null;
  const matched = features.filter(f => featureRow(f)).length;
  if (!bounds) {
    return <UgandaFallbackMap rows={rows} reason="boundary geometry unavailable"/>;
  }

  // Shade by registered-household COUNT.
  const maxV = Math.max(1, ...rows.map(r => r.households || 0));
  const legendBins = [0.9, 0.65, 0.4, 0.15].map(f => ({
    label: `≥ ${_fmtN(Math.round(maxV * f))}`, color: _coverageColor(maxV * f, maxV),
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
        <span className="t-cap">join by district name/code · local Uganda ADM2 boundaries</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 0, alignItems: "stretch" }}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Uganda district choropleth map"
             style={{ width: "100%", minHeight: 420, height: "auto", maxHeight: 640, background: "var(--neutral-50)" }}>
          {features.map((f, i) => {
            const row = featureRow(f);
            const d = _geoPath(f.geometry, bounds, W, H);
            if (!d) return null;
            return (
              <path key={i} d={d} fill={row ? _coverageColor(row.households, maxV) : "var(--neutral-200)"}
                stroke="#fff" strokeWidth={0.7} style={{ cursor: "default" }}>
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
  const normalised = useCovM(() => (Array.isArray(coverage) ? coverage : []).map((r, i) => {
    const households = Number(r.households ?? r.rows ?? r.row_count ?? r.count ?? 0) || 0;
    const geoLabel = r.geo_label || r.label || r.name || r.geo_code || `Area ${i + 1}`;
    return {
      ...r,
      households,
      completeness: r.completeness != null
        ? Number(r.completeness)
        : (r.completeness_pct != null ? Number(r.completeness_pct) / 100 : null),
      geo_level: r.geo_level || r.level || "sub_region",
      geo_code: r.geo_code || r.code || r.key || _norm(geoLabel) || `area-${i + 1}`,
      geo_label: geoLabel,
    };
  }), [coverage]);

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

  const level = normalised[0]?.geo_level || "sub_region";
  const levelLabel = String(level || "area").replace(/_/g, " ");
  const totalHouseholds = useCovM(() => normalised.reduce((s, r) => s + r.households, 0), [normalised]);
  const maxHouseholds = useCovM(() => Math.max(1, ...normalised.map(r => r.households)), [normalised]);
  const topArea = useCovM(() =>
    normalised.reduce((m, r) => (r.households > (m ? m.households : -1) ? r : m), null),
    [normalised]);
  const isLive = !!(covMeta && covMeta.isLive);
  const sourceLabel = covMeta?.source === "reporting"
    ? "live · reporting"
    : (isLive ? "live" : "preview · mock");

  return (
    <DEShell active="coverage" refreshed_at={ds?.refreshed_at}>
      <RoleGateBanner me={me}/>
      <PageHeader
        eyebrow="DATA EXPLORER · REGISTRATION BY AREA"
        title="Registered households by area"
        sub={<>How many households are registered in each {levelLabel}. Darker areas hold more households. Use it to spot under-registered areas before scoping a query.</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn btn-primary" onClick={() => navigateDeScreen("builder")}>
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
            <Chip size="sm" tone={isLive ? "data" : "neutral"}>{sourceLabel}</Chip>
          </div>
          <div className="t-cap mt-1">GET /coverage/{ds.id}/</div>
        </div>
        <KPI label="Households registered" value={totalHouseholds.toLocaleString()} accent="data"
          foot={`across ${normalised.length} ${levelLabel}s`}/>
        <KPI label={`${levelLabel}s`} value={normalised.length} accent="neutral"
          foot="with registrations"/>
        <KPI label={`Most-registered ${levelLabel}`} value={topArea ? topArea.geo_label : "—"} accent="neutral"
          foot={topArea ? `${topArea.households.toLocaleString()} households` : ""}/>
      </div>

      {/* Choropleth map — Uganda admin areas shaded by household count */}
      <div className="card" style={{padding:0, marginBottom:16, overflow:"hidden"}}>
        <ChoroplethMap rows={normalised} level={normalised[0]?.geo_level || "district"}/>
      </div>

      {/* Per-area table */}
      <div className="card" style={{padding:0}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">{ds.code} · households by {levelLabel}</strong>
          <span className="t-cap">{sortedRows.length} {levelLabel}s</span>
          <div style={{flex:1}}/>
          <span className="t-cap">{sourceLabel} · GET /coverage/{ds.id}/</span>
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

const KPI = ({ label = "", value, accent = "data", foot }) => (
  <div>
    <div className="t-cap">{String(label || "").toUpperCase()}</div>
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

Object.assign(window, { DataExplorerCoverageScreen: CoverageScreen });
if (!window.NSR_EMBEDDED_CONSOLE) {
  ReactDOM.createRoot(document.getElementById("app")).render(<CoverageScreen/>);
}
