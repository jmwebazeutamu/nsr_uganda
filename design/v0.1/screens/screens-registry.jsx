/* global React, Icon, Chip, PageHeader */
// NSR MIS — Registry browse (US-S11-018). Operator-facing list of
// every Household the current user can see (ABAC-scoped server-side
// via /api/v1/data-management/households/). Click a row to navigate
// to the household detail screen.
//
// Falls back to a small mock when the API call fails so the design
// preview still renders something — same pattern as screens-dih.jsx.

const {
  useState: useStateReg,
  useEffect: useEffectReg,
  useMemo: useMemoReg,
} = React;


const MOCK_HOUSEHOLDS = [
  { id: "01HXY7K3B2N9PVQE4M6FZRWS18",
    head: "Sarah Nakato", parish: "Bujumba", district: "Kalangala",
    source: "dih", members: 3, pmt_band: "POVERTY", updated_at: "2026-05-14T09:11:00Z" },
  { id: "01HXP2KR3N8M2QFB7K6FZRWS41",
    head: "Akello Grace", parish: "Pageya", district: "Gulu",
    source: "capi_walkin", members: 5, pmt_band: "EXTREME_POVERTY", updated_at: "2026-05-10T15:30:00Z" },
];


// Project the API row into the table's row shape. Same pattern as
// screens-dih.jsx — the JSX stays agnostic to data source.
const _apiRowToView = (h) => {
  const members = h.members || [];
  const head = members.find(m => m.id === h.head_member) || members[0] || {};
  return {
    id: h.id,
    head: [head.surname, head.first_name].filter(Boolean).join(" ") || "(no head)",
    parish: h.parish_name || h.parish || "—",
    district: h.district_name || h.district || "—",
    sub_region: h.sub_region_name || h.sub_region || "",
    source: h.current_intake_source || "—",
    members: members.length,
    pmt_band: h.current_vulnerability_band || "",
    updated_at: h.updated_at,
  };
};


// Source chip tone — match the value coloring with the connector
// kinds the user knows.
const _sourceTone = (source) => {
  if (source === "dih" || source === "kobo") return "data";
  if (source === "capi_walkin") return "update";
  return "data";
};


const RegistryScreen = ({ onNavigate }) => {
  const [rows, setRows] = useStateReg(MOCK_HOUSEHOLDS);
  const [dataSource, setDataSource] = useStateReg("mock");
  const [loadError, setLoadError] = useStateReg(null);
  // Local filters — kept in-browser; ABAC scope is enforced server-side.
  const [filterSource, setFilterSource] = useStateReg("all");
  const [filterDistrict, setFilterDistrict] = useStateReg("all");
  const [search, setSearch] = useStateReg("");

  useEffectReg(() => {
    let cancelled = false;
    fetch("/api/v1/data-management/households/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(data => {
        if (cancelled) return;
        const apiRows = (data.results || data).map(_apiRowToView);
        if (apiRows.length === 0) {
          setDataSource("live-empty");
          return;
        }
        setRows(apiRows);
        setDataSource("live");
      })
      .catch(err => {
        if (cancelled) return;
        setLoadError(String(err.message || err));
      });
    return () => { cancelled = true; };
  }, []);

  const districts = useMemoReg(() => {
    const set = new Set(rows.map(r => r.district).filter(Boolean));
    return ["all", ...Array.from(set).sort()];
  }, [rows]);

  const sources = useMemoReg(() => {
    const set = new Set(rows.map(r => r.source).filter(Boolean));
    return ["all", ...Array.from(set).sort()];
  }, [rows]);

  const visibleRows = useMemoReg(() => {
    const term = search.trim().toLowerCase();
    return rows.filter(r => {
      if (filterSource !== "all" && r.source !== filterSource) return false;
      if (filterDistrict !== "all" && r.district !== filterDistrict) return false;
      if (term) {
        const haystack = `${r.head} ${r.parish} ${r.district} ${r.id}`.toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
  }, [rows, filterSource, filterDistrict, search]);

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow="REGISTRY · US-S11-018"
        title={<>
          Registry — Households{" "}
          <Chip>{rows.length} {dataSource === "live" ? "live" : "shown"}</Chip>
          {dataSource === "mock" && <Chip tone="quality" size="sm">mock</Chip>}
          {dataSource === "live" && <Chip tone="eligibility" size="sm">live</Chip>}
          {dataSource === "live-empty" && <Chip tone="data" size="sm">live (empty — mock shown)</Chip>}
        </>}
        sub="ABAC-scoped list of registered Households. Click a row to open the detail screen."
      />

      {/* Filter bar */}
      <div className="card" style={{padding:"14px 20px", marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:"wrap", alignItems:"center"}}>
          <input
            placeholder="Search head, parish, district, ULID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex:"1 1 320px",
              padding:"7px 10px",
              borderRadius:6,
              border:"1px solid var(--neutral-300)",
              fontSize:13.5,
            }}/>
          <label style={{fontSize:12.5, display:"inline-flex", alignItems:"center", gap:6}}>
            <span className="t-cap" style={{fontWeight:600}}>SOURCE</span>
            <select value={filterSource} onChange={(e) => setFilterSource(e.target.value)}
              style={{padding:"5px 8px", border:"1px solid var(--neutral-300)", borderRadius:4, fontSize:13}}>
              {sources.map(s => <option key={s} value={s}>{s === "all" ? "all" : s}</option>)}
            </select>
          </label>
          <label style={{fontSize:12.5, display:"inline-flex", alignItems:"center", gap:6}}>
            <span className="t-cap" style={{fontWeight:600}}>DISTRICT</span>
            <select value={filterDistrict} onChange={(e) => setFilterDistrict(e.target.value)}
              style={{padding:"5px 8px", border:"1px solid var(--neutral-300)", borderRadius:4, fontSize:13}}>
              {districts.map(d => <option key={d} value={d}>{d === "all" ? "all" : d}</option>)}
            </select>
          </label>
          {(search || filterSource !== "all" || filterDistrict !== "all") && (
            <button className="btn btn-sm" onClick={() => { setSearch(""); setFilterSource("all"); setFilterDistrict("all"); }}>
              Clear
            </button>
          )}
        </div>
      </div>

      {loadError && (
        <div className="card" style={{padding:16, marginBottom:16, borderLeft:"3px solid var(--accent-quality)"}}>
          <div className="t-bodysm">
            API call failed: <strong>{loadError}</strong>. Make sure you're logged into
            <a href="/admin/" target="_blank" rel="noreferrer"> Django admin</a> first. Showing mock data below.
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">{visibleRows.length} of {rows.length} rows</strong>
          <div style={{flex:1}}/>
          <span className="t-cap">Click a row to open detail</span>
        </div>

        <div style={{display:"grid",
                      gridTemplateColumns:"240px 1.5fr 1fr 1fr 120px 70px 120px 160px",
                      borderBottom:"1px solid var(--neutral-200)",
                      background:"var(--neutral-50)",
                      fontSize:11, fontWeight:600,
                      letterSpacing:"0.06em", textTransform:"uppercase",
                      color:"var(--neutral-700)"}}>
          <div style={{padding:"10px 12px"}}>Registry ID</div>
          <div style={{padding:"10px 12px"}}>Head</div>
          <div style={{padding:"10px 12px"}}>Parish</div>
          <div style={{padding:"10px 12px"}}>District</div>
          <div style={{padding:"10px 12px"}}>Source</div>
          <div style={{padding:"10px 12px", textAlign:"right"}}>HH</div>
          <div style={{padding:"10px 12px"}}>PMT band</div>
          <div style={{padding:"10px 12px"}}>Updated</div>
        </div>

        {visibleRows.length === 0 && (
          <div style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
            <Icon name="inbox" size={32} color="var(--neutral-300)"/>
            <div className="t-bodysm mt-2">
              {rows.length === 0
                ? "Registry is empty. Promote DIH stages to populate it."
                : "No rows match the current filter."}
            </div>
          </div>
        )}

        {visibleRows.map(r => (
          <div key={r.id}
            onClick={() => onNavigate?.("household", { householdId: r.id })}
            style={{display:"grid",
                     gridTemplateColumns:"240px 1.5fr 1fr 1fr 120px 70px 120px 160px",
                     borderBottom:"1px solid var(--neutral-200)",
                     cursor:"pointer",
                     alignItems:"center"}}
            onMouseEnter={(e) => e.currentTarget.style.background = "var(--neutral-50)"}
            onMouseLeave={(e) => e.currentTarget.style.background = "white"}>
            <div className="t-mono" style={{padding:"10px 12px", fontSize:11.5}}>
              {r.id}
            </div>
            <div style={{padding:"10px 12px", fontSize:13, fontWeight:500}}>{r.head}</div>
            <div style={{padding:"10px 12px", fontSize:13}}>{r.parish}</div>
            <div style={{padding:"10px 12px", fontSize:13}}>
              {r.district}
              {r.sub_region && <div className="t-cap muted">{r.sub_region}</div>}
            </div>
            <div style={{padding:"10px 12px"}}>
              <Chip size="sm" tone={_sourceTone(r.source)}>{r.source}</Chip>
            </div>
            <div style={{padding:"10px 12px", fontFamily:"monospace", fontSize:12, textAlign:"right"}}>
              {r.members}
            </div>
            <div style={{padding:"10px 12px"}}>
              {r.pmt_band
                ? <Chip size="sm" tone="pmt">{r.pmt_band}</Chip>
                : <span className="t-bodysm muted">—</span>}
            </div>
            <div style={{padding:"10px 12px", fontSize:12, color:"var(--neutral-700)"}}>
              {r.updated_at ? new Date(r.updated_at).toISOString().slice(0, 16).replace("T", " ") : "—"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};


Object.assign(window, { RegistryScreen });
