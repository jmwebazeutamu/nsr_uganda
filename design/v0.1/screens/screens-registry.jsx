/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — Registry browse (US-005)
// Visual design from the claude.ai/design redesign deposited
// at design/v0.1/html/Registry.html and stashed for reference at
// design/v0.1/screens/_redesign_reference.jsx.
// Data layer: live fetch against /api/v1/data-management/households/
// with mock fallback for design-preview / unauthenticated sessions.

const {
  useState: useStateReg,
  useEffect: useEffectReg,
  useMemo: useMemoReg,
} = React;


// Mock dataset preserved for the design-preview path. Mirrors the
// shape the live projection produces so the rendering code stays one
// path. Twelve rows is enough to exercise pagination.
const MOCK_HOUSEHOLDS = [
  { rid: "01KRPPW6WRGRJZY0N4XN8R1YC2", head: "Nsubuga Ruth",      sex:"F", hh: 7, subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmt:0.39, band:"Poorest 40%", source:"DIH",     status:"Registered", regDate:"08 Mar 2026", lastUpdate:"22 Apr 2026", programmes:["OPM-PDM"] },
  { rid: "01HXY7K3B2N9PVQE4M6FZRWS18", head: "Lokol Naume",       sex:"F", hh: 6, subreg:"Karamoja",      district:"Moroto",    parish:"Nakiloro",  village:"Lopuwapuwa A",   pmt:0.32, band:"Poorest 20%", source:"Walk-in", status:"Provisional", regDate:"14 May 2026", lastUpdate:"—",            programmes:[] },
  { rid: "01HXZ9MR4N8P2QFB7K6FZRWS33", head: "Akello Grace",      sex:"F", hh: 5, subreg:"Acholi",        district:"Gulu",      parish:"Pageya",    village:"Aywee",         pmt:0.41, band:"Poorest 40%", source:"Walk-in", status:"Pending",     regDate:"14 May 2026", lastUpdate:"—",            programmes:[] },
  { rid: "01HXP02CN4QFB7K6FZRWS00111", head: "Mukasa Patrick",    sex:"M", hh: 4, subreg:"West Nile",     district:"Arua",      parish:"Anyiribu",  village:"Anyiribu A",    pmt:0.55, band:"Poorest 40%", source:"DIH",     status:"Registered", regDate:"15 Feb 2026", lastUpdate:"03 May 2026", programmes:["NUSAF","OPM-PDM"] },
];


// Project the API row into the table's row shape. The redesign's
// table consumes a flat object with head/parish/district/etc.; the
// API serializer ships nested geo names so the projection is direct.
const _apiRowToView = (h) => {
  const members = h.members || [];
  const head = members.find(m => m.id === h.head_member) || members[0] || {};
  const isF = (head.sex || "").toUpperCase().startsWith("F");
  return {
    rid: h.id,
    head: [head.surname, head.first_name].filter(Boolean).join(" ") || "(no head)",
    sex: isF ? "F" : "M",
    hh: members.length,
    subreg: h.sub_region_name || h.sub_region || "",
    district: h.district_name || h.district || "",
    parish: h.parish_name || h.parish || "",
    village: h.village_name || h.village || "",
    pmt: h.current_pmt_score != null ? Number(h.current_pmt_score) / 100 : null,
    band: h.current_vulnerability_band || "",
    source: (h.current_intake_source || "").toUpperCase().replace("_", " ") || "—",
    status: "Registered",
    regDate: (h.created_at || "").slice(0, 10) || "—",
    lastUpdate: (h.updated_at || "").slice(0, 10) || "—",
    programmes: [],  // populated when REF/programme data lands
  };
};


const RegistryScreen = ({ onNavigate }) => {
  const [households, setHouseholds] = useStateReg(MOCK_HOUSEHOLDS);
  const [dataSource, setDataSource] = useStateReg("mock");

  const [q, setQ] = useStateReg("");
  const [status, setStatus] = useStateReg("");
  const [subreg, setSubreg] = useStateReg("");
  const [band, setBand] = useStateReg("");
  const [prog, setProg] = useStateReg("");
  const [sortBy, setSortBy] = useStateReg("lastUpdate");
  const [page, setPage] = useStateReg(0);
  const pageSize = 12;

  useEffectReg(() => {
    let cancelled = false;
    fetch("/api/v1/data-management/households/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        const rows = (data.results || data).map(_apiRowToView);
        if (rows.length === 0) {
          setDataSource("live-empty");
          return;
        }
        setHouseholds(rows);
        setDataSource("live");
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const rows = useMemoReg(() => {
    let r = households.filter(h => {
      if (q && !(h.head.toLowerCase().includes(q.toLowerCase())
                || h.rid.toLowerCase().includes(q.toLowerCase())
                || (h.parish || "").toLowerCase().includes(q.toLowerCase()))) return false;
      if (status && h.status !== status) return false;
      if (subreg && h.subreg !== subreg) return false;
      if (band && h.band !== band) return false;
      if (prog && !h.programmes.includes(prog)) return false;
      return true;
    });
    if (sortBy === "head") r = [...r].sort((a, b) => a.head.localeCompare(b.head));
    if (sortBy === "pmt") r = [...r].sort((a, b) => (a.pmt ?? 99) - (b.pmt ?? 99));
    if (sortBy === "hh") r = [...r].sort((a, b) => b.hh - a.hh);
    return r;
  }, [households, q, status, subreg, band, prog, sortBy]);

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const visible = rows.slice(page * pageSize, page * pageSize + pageSize);
  const reset = () => { setQ(""); setStatus(""); setSubreg(""); setBand(""); setProg(""); setPage(0); };

  const subregs = [...new Set(households.map(h => h.subreg).filter(Boolean))].sort();
  const programmes = [...new Set(households.flatMap(h => h.programmes))].sort();

  // KPIs computed from the full set.
  const total = households.length;
  const registered = households.filter(h => h.status === "Registered").length;
  const provisional = households.filter(h => h.status === "Provisional" || h.status === "Pending").length;
  const programmesEnrolled = households.filter(h => h.programmes.length).length;

  return (
    <div className="page">
      <PageHeader
        eyebrow={dataSource === "live" ? "REGISTRY · US-005 · LIVE" : "REGISTRY · US-005"}
        title="Household registry"
        sub={dataSource === "live"
          ? `Live ABAC-scoped data — ${households.length.toLocaleString()} households in your scope.`
          : "Search, browse, and open any household. Read-only — edits go through the UPD workflow."}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> Start capture</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Total households" value={total.toLocaleString()}
          foot={dataSource === "live" ? "in your ABAC scope" : "of 12.1M national target"}/>
        <KPI title="Registered" value={registered.toLocaleString()}
          trend={total ? "up" : undefined}
          trendValue={total ? `${Math.round(registered / total * 100)}%` : undefined}
          foot="Confirmed in registry"/>
        <KPI title="Provisional / Pending" value={provisional.toLocaleString()}
          foot="Awaiting NSR Unit review"/>
        <KPI title="Programme-enrolled" value={programmesEnrolled.toLocaleString()}
          foot="At least one active enrolment"/>
      </div>

      {/* Filter bar */}
      <div className="card mt-5" style={{padding:"14px 16px"}}>
        <div className="row gap-3" style={{flexWrap:"wrap"}}>
          <div className="search" style={{maxWidth:380, height:34, background:"var(--neutral-0)"}}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }}
              placeholder="Search by name, Registry ID, or parish…"/>
          </div>
          <select className="field-select" style={{height:34, width:"auto", minWidth:140}}
            value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
            <option value="">Any status</option>
            <option>Registered</option><option>Provisional</option>
            <option>Pending</option><option>Rejected</option><option>Voided</option>
          </select>
          <select className="field-select" style={{height:34, width:"auto", minWidth:160}}
            value={subreg} onChange={(e) => { setSubreg(e.target.value); setPage(0); }}>
            <option value="">Any sub-region</option>
            {subregs.map(s => <option key={s}>{s}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:"auto", minWidth:140}}
            value={band} onChange={(e) => { setBand(e.target.value); setPage(0); }}>
            <option value="">Any PMT band</option>
            <option>Poorest 20%</option><option>Poorest 40%</option>
            <option>Middle 40%</option><option>Top 20%</option>
          </select>
          {programmes.length > 0 && (
            <select className="field-select" style={{height:34, width:"auto", minWidth:160}}
              value={prog} onChange={(e) => { setProg(e.target.value); setPage(0); }}>
              <option value="">Any programme</option>
              {programmes.map(p => <option key={p}>{p}</option>)}
            </select>
          )}
          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost" onClick={reset}>
            <Icon name="x" size={13}/> Reset
          </button>
          <div style={{width:1, height:24, background:"var(--neutral-200)"}}/>
          <span className="t-cap">Sort:</span>
          <select className="field-select" style={{height:30, width:"auto"}}
            value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="lastUpdate">Most recent</option>
            <option value="head">Head name (A→Z)</option>
            <option value="pmt">PMT score (low→high)</option>
            <option value="hh">Household size (large→small)</option>
          </select>
        </div>
      </div>

      {/* Active filter chips */}
      {(status || subreg || band || prog || q) && (
        <div className="row gap-2 mt-3" style={{flexWrap:"wrap"}}>
          <span className="t-cap">Active filters:</span>
          {q && <Chip size="sm">"{q}"</Chip>}
          {status && <Chip size="sm">{status}</Chip>}
          {subreg && <Chip size="sm">{subreg}</Chip>}
          {band && <Chip size="sm">{band}</Chip>}
          {prog && <Chip size="sm">{prog}</Chip>}
        </div>
      )}

      {/* Results table */}
      <div className="card mt-4">
        <div className="card-toolbar">
          <strong className="t-bodysm">{rows.length.toLocaleString()} households</strong>
          <span className="t-cap">Page {page+1} of {totalPages} · click any row to open</span>
          <div style={{flex:1}}/>
          {dataSource === "mock" && <Chip size="sm" tone="quality">mock data</Chip>}
          {dataSource === "live" && <Chip size="sm" tone="eligibility">live</Chip>}
          {dataSource === "live-empty" && <Chip size="sm" tone="data">live · queue empty (mock shown)</Chip>}
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Registry ID</th>
              <th>Head of household</th>
              <th>HH</th>
              <th>Location</th>
              <th>PMT band</th>
              <th>Source</th>
              <th>Last update</th>
              <th>Status</th>
              <th>Programmes</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {visible.map(h => (
              <tr key={h.rid} onClick={() => onNavigate?.("household", { householdId: h.rid })}
                style={{cursor:"pointer"}}>
                <td className="col-id">{h.rid.slice(0, 20)}…</td>
                <td>
                  <div className="row gap-3">
                    <div style={{width:28, height:28, borderRadius:"50%",
                                 background:"var(--primary-100)", color:"var(--primary-900)",
                                 display:"grid", placeItems:"center", fontSize:11, fontWeight:600}}>
                      {h.head.split(" ").map(w => w[0]).slice(0, 2).join("")}
                    </div>
                    <div>
                      <div style={{fontWeight:500}}>{h.head}</div>
                      <div className="t-cap">{h.sex === "F" ? "Female" : "Male"}-headed</div>
                    </div>
                  </div>
                </td>
                <td className="t-num">{h.hh}</td>
                <td>
                  <div>{h.parish} · {h.district}</div>
                  <div className="t-cap">{h.subreg} · {h.village}</div>
                </td>
                <td>
                  {h.band ? <Chip size="sm" tone="eligibility">{h.band}</Chip> : <span className="muted">—</span>}
                  {h.pmt != null && (
                    <div className="t-cap t-mono mt-1" style={{marginTop:2}}>
                      score {h.pmt.toFixed(2)}
                    </div>
                  )}
                </td>
                <td className="t-bodysm">{h.source}</td>
                <td className="t-cap" style={{whiteSpace:"nowrap"}}>{h.lastUpdate}</td>
                <td><Chip size="sm">{h.status}</Chip></td>
                <td>
                  {h.programmes.length === 0
                    ? <span className="muted t-cap">none</span>
                    : <div className="row-wrap">
                        {h.programmes.map(p => <Chip key={p} size="sm" tone="programme">{p}</Chip>)}
                      </div>}
                </td>
                <td className="col-actions">
                  <Icon name="chevronRight" size={16} color="var(--neutral-500)"/>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination */}
        <div className="row gap-2" style={{padding:"12px 16px",
              borderTop:"1px solid var(--neutral-200)",
              justifyContent:"space-between"}}>
          <span className="t-cap">
            Showing {page*pageSize + 1}–{Math.min((page+1)*pageSize, rows.length)} of {rows.length.toLocaleString()}
          </span>
          <div className="row gap-2">
            <button className="btn btn-sm" disabled={page === 0}
              onClick={() => setPage(0)}><Icon name="chevronsLeft" size={14}/></button>
            <button className="btn btn-sm" disabled={page === 0}
              onClick={() => setPage(p => p - 1)}><Icon name="chevronLeft" size={14}/></button>
            <span className="t-bodysm" style={{padding:"0 8px"}}>{page+1} / {totalPages}</span>
            <button className="btn btn-sm" disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}><Icon name="chevronRight" size={14}/></button>
            <button className="btn btn-sm" disabled={page >= totalPages - 1}
              onClick={() => setPage(totalPages - 1)}><Icon name="chevronsRight" size={14}/></button>
          </div>
        </div>
      </div>
    </div>
  );
};


Object.assign(window, { RegistryScreen });
