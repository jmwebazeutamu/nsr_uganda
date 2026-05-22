/* global React, Icon, Chip, PageHeader, KPI, useApi */
// NSR MIS — Registry browse + Household detail (US-005, US-090 read-only registry view)

const { useState: useStateReg, useMemo: useMemoReg } = React;

// ────────────────────────────────────────────────────────────────
// Live-data helpers for the Households browse (US-005).
// Filters round-trip through query params on
// /api/v1/data-management/households/; KPIs read off
// /api/v1/data-management/households/aggregates/. The aggregates
// endpoint honours the same filter params so the KPI strip reflects
// the visible slice.
// ────────────────────────────────────────────────────────────────

const _HH_API_BASE = "/api/v1/data-management/households/";

const _registryQS = (params) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v != null && v !== "") qs.set(k, String(v));
  }
  return qs.toString();
};

const _buildHouseholdListUrl = (filters, page, pageSize) => {
  const s = _registryQS({ ...filters, page, page_size: pageSize });
  return s ? `${_HH_API_BASE}?${s}` : _HH_API_BASE;
};

const _buildHouseholdAggregatesUrl = (filters) => {
  const s = _registryQS(filters);
  return s
    ? `${_HH_API_BASE}aggregates/?${s}`
    : `${_HH_API_BASE}aggregates/`;
};

// Project a live Household payload (HouseholdSerializer shape) onto
// the row shape the existing table render expects. Head is the
// nested member with relationship_to_head === "01" (the "Head" code
// from the ChoiceList seed). Falls back to line-1 if the head isn't
// flagged, then to "—".
const _projectHousehold = (h) => {
  const members = h.members || [];
  const head = members.find(m => m.relationship_to_head === "01")
    || members.find(m => m.line_number === 1)
    || members[0]
    || null;
  return {
    rid: h.id,
    head: head
      ? `${head.surname || ""} ${head.first_name || ""}`.trim() || "—"
      : "—",
    // Member.sex is ChoiceList code: 1=Male, 2=Female.
    sex: head ? (head.sex === "2" ? "F" : head.sex === "1" ? "M" : "—") : "—",
    hh: members.length,
    subreg: h.sub_region_name || "",
    district: h.district_name || "",
    parish: h.parish_name || "",
    village: h.village_name || "",
    pmt: h.current_pmt_score != null ? Number(h.current_pmt_score) : null,
    band: h.current_vulnerability_band || "",
    source: h.current_intake_source || "",
    // Every post-promotion Household is Registered by definition;
    // pre-promotion records live in StageRecord (DIH).
    status: "Registered",
    regDate: (h.created_at || "").slice(0, 10),
    lastUpdate: (h.updated_at || "").slice(0, 10),
    // ProgrammeEnrolment lives in apps.referral — wire when the
    // HouseholdSerializer nests it. Follow-up.
    programmes: [],
  };
};

/* ============================================================
   REGISTRY SCREEN
   ============================================================ */
const RegistryScreen = ({ onOpen, onOpenMember, initialView = "households" }) => {
  // Top-level entity toggle — registry is two-headed (households + members).
  // initialView lets a route or nav link land you on the Members tab from
  // outside; default is the household list (the original screen).
  const [view, setView] = useStateReg(initialView === "members" ? "members" : "households");

  const [q, setQ] = useStateReg("");
  // sub-region picker is keyed by GeographicUnit.code (matches the
  // backend filter param exactly).
  const [subreg, setSubreg] = useStateReg("");
  const [band, setBand] = useStateReg("");
  const [intakeSrc, setIntakeSrc] = useStateReg("");
  const [prog, setProg] = useStateReg("");
  const [sortBy, setSortBy] = useStateReg("lastUpdate");
  const [page, setPage] = useStateReg(0);
  const pageSize = 12;

  const _hhFilters = {
    q, sub_region: subreg, band, intake_source: intakeSrc, programme: prog,
  };
  // DRF is 1-indexed; expose the same `page` state on screen and add 1
  // when building the URL.
  const _orderingMap = {
    lastUpdate: "-updated_at",
    head: "id",                  // head A→Z needs a SerializerMethodField; defer
    pmt: "current_pmt_score",
    hh: "id",                    // hh size needs a denormalised member_count; defer
  };
  const listUrl = view === "households"
    ? _buildHouseholdListUrl(
        { ..._hhFilters, ordering: _orderingMap[sortBy] || undefined },
        page + 1, pageSize,
      )
    : null;
  const aggUrl = view === "households"
    ? _buildHouseholdAggregatesUrl(_hhFilters)
    : null;
  // Sub-region picker reads the live UBOS catalogue at sub_region
  // level. The choice-list bundle endpoint pulls all 15 in one round-
  // trip.
  const subregUrl = view === "households"
    ? "/api/v1/reference-data/geographic-units/?level=sub_region&status=active&page_size=500"
    : null;

  const [listResp, listMeta] = useApi(listUrl);
  const [aggResp] = useApi(aggUrl);
  const [subregResp] = useApi(subregUrl);

  const liveRows = ((listResp && listResp.results) || []).map(_projectHousehold);
  const liveCount = (listResp && typeof listResp.count === "number")
    ? listResp.count
    : liveRows.length;
  const totalPages = Math.max(1, Math.ceil(liveCount / pageSize));

  const subregs = (subregResp && subregResp.results) || subregResp || [];

  const reset = () => {
    setQ(""); setSubreg(""); setBand(""); setIntakeSrc(""); setProg(""); setPage(0);
  };

  // KPIs read off the aggregates endpoint so they reflect the visible
  // slice — same filter params, no client-side aggregation.
  const total = aggResp?.total ?? 0;
  const registered = aggResp?.registered ?? 0;
  const provisional = aggResp?.provisional_pending ?? 0;
  const programmesEnrolled = aggResp?.programme_enrolled ?? 0;

  return (
    <div className="page">
      <PageHeader
        eyebrow="REGISTRY · US-005"
        title="National Social Registry"
        sub={view === "members"
          ? "Search and browse individuals across every household. Read-only — edits go through the household's UPD workflow."
          : "Search, browse, and open any household. Read-only — edits go through the UPD workflow."}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> Start capture</button>
        </>}
      />

      {/* Entity toggle — Households · Members */}
      <div role="tablist" aria-label="Registry entity"
        style={{
          display:"flex", alignItems:"flex-end", gap:0,
          borderBottom:"1px solid var(--neutral-300)",
          marginBottom:16,
        }}>
        {[
          { id:"households", label:"Households", icon:"home",  count:"12.1M", sub:"primary entity"  },
          { id:"members",    label:"Members",    icon:"users", count:"48.1M", sub:"per-individual" },
        ].map(tab => {
          const active = view === tab.id;
          return (
            <button key={tab.id} role="tab" aria-selected={active}
              onClick={() => setView(tab.id)}
              style={{
                display:"inline-flex", alignItems:"center", gap:10,
                padding:"10px 18px", border:0, background:"transparent",
                cursor:"pointer", marginBottom:-1,
                borderBottom: active ? "2px solid var(--primary-900)" : "2px solid transparent",
                color: active ? "var(--primary-900)" : "var(--neutral-700)",
                fontWeight: active ? 600 : 500, fontSize:14,
              }}>
              <Icon name={tab.icon} size={15} color={active ? "var(--primary-900)" : "var(--neutral-500)"}/>
              <span>{tab.label}</span>
              <span style={{
                display:"inline-flex", flexDirection:"column", lineHeight:1.1,
                padding:"2px 8px", borderRadius:10,
                background: active ? "var(--primary-100)" : "var(--neutral-100)",
                color: active ? "var(--primary-900)" : "var(--neutral-700)",
                fontSize:11, fontWeight:600,
              }}>
                <span className="t-num">{tab.count}</span>
                <span className="t-cap" style={{fontSize:9, fontWeight:500, color:"inherit", opacity:0.75}}>
                  {tab.sub}
                </span>
              </span>
            </button>
          );
        })}
        <div style={{flex:1}}/>
        <span className="t-cap" style={{padding:"0 4px 12px"}}>
          Sourced from the same NSR — different lens.
        </span>
      </div>

      {/* ---------- MEMBERS VIEW ---------- */}
      {view === "members" && (
        typeof MembersListView === "function"
          ? <MembersListView onOpenHousehold={onOpen} onOpenMember={onOpenMember}/>
          : <div className="card" style={{padding:20}}><span className="muted">Members view requires screens-registry-members.jsx</span></div>
      )}

      {/* ---------- HOUSEHOLDS VIEW (default) ---------- */}
      {view === "households" && (<>

      {/* Headline KPIs */}
      <div className="grid grid-4">
        <KPI title="Total households" value={total.toLocaleString()} foot="of 12.1M national target" spark={[8,9,11,10,12,13,14,15]}/>
        <KPI title="Registered" value={registered.toLocaleString()} trend="up" trendValue={`${Math.round(registered/total*100)}%`} foot="Confirmed in registry" spark={[5,6,8,8,9,10,10,11]}/>
        <KPI title="Provisional / Pending" value={provisional.toLocaleString()} trend="up" trendValue="+2 today" foot="Awaiting NSR Unit review" spark={[1,2,2,3,3,4,3,3]}/>
        <KPI title="Programme-enrolled" value={programmesEnrolled.toLocaleString()} foot="At least one active enrolment" spark={[4,5,5,6,7,7,8,8]}/>
      </div>

      {/* Filter bar */}
      <div className="card mt-5" style={{padding:'14px 16px'}}>
        <div className="row gap-3" style={{flexWrap:'wrap'}}>
          <div className="search" style={{maxWidth:380, height:34, background:'var(--neutral-0)'}}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Search by name, Registry ID, or parish…"/>
          </div>

          <select className="field-select" style={{height:34, width:'auto', minWidth:140}} value={intakeSrc} onChange={(e) => { setIntakeSrc(e.target.value); setPage(0); }}>
            <option value="">Any intake source</option>
            <option value="DIH">DIH</option>
            <option value="Walk-in">Walk-in</option>
            <option value="Bulk">Bulk</option>
            <option value="capi">CAPI</option>
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:200}} value={subreg} onChange={(e) => { setSubreg(e.target.value); setPage(0); }}>
            <option value="">Any sub-region</option>
            {subregs.map(s => <option key={s.id || s.code} value={s.code}>{s.name}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:140}} value={band} onChange={(e) => { setBand(e.target.value); setPage(0); }}>
            <option value="">Any PMT band</option>
            <option>Poorest 20%</option><option>Poorest 40%</option><option>Middle 40%</option><option>Top 20%</option>
          </select>
          <input
            type="text" value={prog}
            onChange={(e) => { setProg(e.target.value); setPage(0); }}
            placeholder="Programme code (e.g. OPM-PDM)"
            className="field-input"
            style={{height:34, width:'auto', minWidth:160}}/>

          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost" onClick={reset}><Icon name="x" size={13}/> Reset</button>
          <div style={{width:1, height:24, background:'var(--neutral-200)'}}/>
          <span className="t-cap">Sort:</span>
          <select className="field-select" style={{height:30, width:'auto'}} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="lastUpdate">Most recent</option>
            <option value="head">Head name (A→Z)</option>
            <option value="pmt">PMT score (low→high)</option>
            <option value="hh">Household size (large→small)</option>
          </select>
        </div>
      </div>

      {/* Active filter chips */}
      {(intakeSrc || subreg || band || prog || q) && (
        <div className="row gap-2 mt-3" style={{flexWrap:'wrap'}}>
          <span className="t-cap">Active filters:</span>
          {q && <Chip size="sm">"{q}" <button onClick={() => setQ("")} style={{marginLeft:4, border:0, background:'transparent', cursor:'pointer'}}>×</button></Chip>}
          {intakeSrc && <Chip size="sm">{intakeSrc}</Chip>}
          {subreg && <Chip size="sm">{
            (subregs.find(s => s.code === subreg)?.name) || subreg
          }</Chip>}
          {band && <Chip size="sm">{band}</Chip>}
          {prog && <Chip size="sm" tone="programme">{prog}</Chip>}
        </div>
      )}

      {/* Results table */}
      <div className="card mt-4">
        <div className="card-toolbar">
          <strong className="t-bodysm">{liveCount.toLocaleString()} households</strong>
          <span className="t-cap">
            {listMeta.loading ? "Loading…" : `Page ${page+1} of ${totalPages} · click any row to open`}
          </span>
          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost"><Icon name="sliders" size={14}/> Columns</button>
        </div>
        {listMeta.error && (
          <div style={{padding:'12px 16px', color:'var(--accent-danger)'}} className="t-bodysm">
            Couldn’t load households: {listMeta.error}
          </div>
        )}
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
            {liveRows.length === 0 && !listMeta.loading && (
              <tr><td colSpan={10} style={{padding:'20px', textAlign:'center'}} className="muted t-bodysm">
                No households match the current filters.
              </td></tr>
            )}
            {liveRows.map(h => (
              <tr key={h.rid} onClick={() => onOpen?.(h.rid)} style={{cursor:'pointer'}}>
                <td className="col-id">{h.rid.slice(0, 20)}…</td>
                <td>
                  <div className="row gap-3">
                    <div style={{width:28, height:28, borderRadius:'50%', background:'var(--primary-100)', color:'var(--primary-900)', display:'grid', placeItems:'center', fontSize:11, fontWeight:600}}>
                      {h.head !== "—" ? h.head.split(' ').map(w => w[0]).slice(0,2).join('') : "—"}
                    </div>
                    <div>
                      <div style={{fontWeight:500}}>{h.head}</div>
                      <div className="t-cap">{h.sex === 'F' ? 'Female' : h.sex === 'M' ? 'Male' : '—'}-headed</div>
                    </div>
                  </div>
                </td>
                <td className="t-num">{h.hh}</td>
                <td>
                  <div>{h.parish || "—"} · {h.district || "—"}</div>
                  <div className="t-cap">{h.subreg || "—"} · {h.village || "—"}</div>
                </td>
                <td>
                  {h.band
                    ? <Chip size="sm" tone="eligibility">{h.band}</Chip>
                    : <span className="muted t-cap">—</span>}
                  <div className="t-cap t-mono mt-1" style={{marginTop:2}}>
                    {h.pmt != null ? `score ${h.pmt.toFixed(2)}` : "no score"}
                  </div>
                </td>
                <td className="t-bodysm">{h.source || "—"}</td>
                <td className="t-cap" style={{whiteSpace:'nowrap'}}>{h.lastUpdate || "—"}</td>
                <td><Chip size="sm">{h.status}</Chip></td>
                <td>
                  {h.programmes.length === 0
                    ? <span className="muted t-cap">—</span>
                    : <div className="row-wrap">{h.programmes.map(p => <Chip key={p} size="sm" tone="programme">{p}</Chip>)}</div>}
                </td>
                <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination */}
        <div className="row gap-2" style={{padding:'12px 16px', borderTop:'1px solid var(--neutral-200)', justifyContent:'space-between'}}>
          <span className="t-cap">
            {liveCount === 0
              ? "0 results"
              : `Showing ${page*pageSize + 1}–${Math.min((page+1)*pageSize, liveCount)} of ${liveCount.toLocaleString()}`}
          </span>
          <div className="row gap-2">
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(0)}><Icon name="chevronsLeft" size={14}/></button>
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}><Icon name="chevronLeft" size={14}/></button>
            <span className="t-bodysm" style={{padding:'0 8px'}}>{page+1} / {totalPages}</span>
            <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}><Icon name="chevronRight" size={14}/></button>
            <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)}><Icon name="chevronsRight" size={14}/></button>
          </div>
        </div>
      </div>
      </>)}
    </div>
  );
};

/* ============================================================
   HOUSEHOLD DETAIL — 12 tabs
   ============================================================ */
const HH_DETAIL = {
  rid: "01KRPPW6WRGRJZY0N4XN8R1YC2",
  head: "Nsubuga Ruth",
  status: "Registered",
  hh: 7,
  subreg: "Buganda South", district: "Lyantonde", parish: "Kibalinga", village: "Okello Village", code: "114.01.01.04",
  gps: { lat: 0.266500, lng: 33.396584, acc: 10 },
  pmt: { score: 0.39, band: "Poorest 40%", model: "v2.4", computedAt: "22 Apr 2026" },
  phone: "+256 772 558 219",
  email: "—",
  capturedAt: "08 Mar 2026 · 11:22 EAT",
  capturedBy: "Mukasa Robert (PCH-2210) — Parish Chief",
  source: "DIH",
  programmes: [{ name: "OPM-PDM", since: "10 Apr 2026", status: "Active" }],
  members: [
    { line:1, name:"Nsubuga Ruth",       rel:"Head",      sex:"F", age:42, nin:"CM84050213ABCD", dob:"13 May 1983", literacy:"Reads + writes", everSchool:"Yes", highestGrade:19, currentlyAttending:"—", neverReason:"—" },
    { line:2, name:"Tumusiime Samuel",   rel:"Spouse",    sex:"M", age:46, nin:"CM80020412EFGH", dob:"12 Apr 1979", literacy:"—",             everSchool:"No",  highestGrade:"—", currentlyAttending:"—", neverReason:"96" },
    { line:3, name:"Okello James",       rel:"Son",       sex:"M", age:14, nin:"—",              dob:"04 Sep 2011", literacy:"Neither",       everSchool:"Yes", highestGrade:8,   currentlyAttending:"—", neverReason:"—" },
    { line:4, name:"Achen James",        rel:"Son",       sex:"M", age:18, nin:"—",              dob:"02 Feb 2008", literacy:"Neither",       everSchool:"Yes", highestGrade:12,  currentlyAttending:"—", neverReason:"—" },
    { line:5, name:"Byaruhanga James",   rel:"Son",       sex:"M", age:18, nin:"—",              dob:"15 Jul 2008", literacy:"Neither",       everSchool:"Yes", highestGrade:12,  currentlyAttending:"—", neverReason:"—" },
    { line:6, name:"Achen Rebecca",      rel:"Daughter",  sex:"F", age:6,  nin:"—",              dob:"22 Nov 2019", literacy:"—",             everSchool:"No",  highestGrade:"—", currentlyAttending:"—", neverReason:"98" },
    { line:7, name:"Mugisha Samuel",     rel:"Son",       sex:"M", age:11, nin:"—",              dob:"08 Aug 2014", literacy:"Neither",       everSchool:"Yes", highestGrade:8,   currentlyAttending:"Yes", neverReason:"—" },
  ],
};

const TABS = [
  { id: "over",  label: "Overview" },
  { id: "rost",  label: "Roster" },
  { id: "hd",    label: "Health & Disability" },
  { id: "ed",    label: "Education" },
  { id: "emp",   label: "Employment" },
  { id: "hous",  label: "Housing & Assets" },
  { id: "food",  label: "Food & Shocks" },
  { id: "hist",  label: "Updates history", count: 6 },
  { id: "grm",   label: "Grievances", count: 1 },
  { id: "prog",  label: "Programmes", count: 1 },
  { id: "cons",  label: "Consent" },
  { id: "aud",   label: "Audit" },
];

const CR_TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "openOnLoad": true,
  "addUx": "composer",
  "showQuickAdd": true,
  "showAccent": true
}/*EDITMODE-END*/;

const HouseholdScreen = ({ onBack }) => {
  const [tab, setTab] = useStateReg("ed"); // start on Education to match user's screenshot
  const h = HH_DETAIL;
  const [t, setTweak] = (typeof useTweaks === 'function' ? useTweaks(CR_TWEAK_DEFAULTS) : [CR_TWEAK_DEFAULTS, () => {}]);
  const [crOpen, setCrOpen] = useStateReg(t.openOnLoad);
  const [crToast, setCrToast] = useStateReg("");

  const handleCrSubmit = (payload) => {
    setCrOpen(false);
    setCrToast(`Change request created · ${payload.rows.length} ${payload.rows.length === 1 ? 'change' : 'changes'} · routed to ${payload.changeType} reviewer`);
  };

  return (
    <div className="page">
      {/* Eyebrow + title */}
      <PageHeader
        eyebrow={<>HOUSEHOLD DETAIL · <span className="t-mono">{h.rid}</span></>}
        title={<>{h.head} <span className="t-bodysm" style={{fontWeight:400, color:'var(--accent-data)', marginLeft:8}}>(live)</span></>}
        sub={<>{h.village} · {h.code} · {h.parish}, {h.district} · {h.subreg}</>}
        right={<>
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to Registry</button>
        </>}
      />

      {/* Header summary card */}
      <div className="card" style={{padding:0, marginBottom:16}}>
        <div style={{padding:'18px 20px', display:'grid', gridTemplateColumns:'1.4fr 2fr 1.4fr 1fr 1fr', gap:24, alignItems:'flex-start'}}>
          <Fact label="Head of household" big={h.head} sub={`HH size ${h.hh} · ${h.members.filter(m => m.sex === 'F').length}F / ${h.members.filter(m => m.sex === 'M').length}M`}/>
          <Fact label="Location" big={`${h.village}, ${h.code}, ${h.parish}, ${h.district}`} sub={`${h.subreg} / Central`}/>
          <Fact label="GPS" big={<span className="t-mono" style={{fontSize:14}}>{h.gps.lat.toFixed(6)}, {h.gps.lng.toFixed(6)}</span>} sub={`${h.gps.acc.toFixed(2)}m accuracy`}/>
          <div>
            <div className="t-cap">PMT</div>
            <div className="row gap-2" style={{marginTop:2}}>
              <span className="muted t-bodysm">poverty</span>
              <span style={{fontSize:22, fontWeight:700}}>{Math.round(h.pmt.score * 100)}</span>
            </div>
            <div className="row gap-2 mt-1"><Chip size="sm" tone="eligibility">{h.pmt.band}</Chip></div>
          </div>
          <div>
            <div className="t-cap">Source</div>
            <div className="row gap-2 mt-1"><Chip size="sm" tone="data">{h.source.toLowerCase()}</Chip></div>
            <div className="t-cap mt-2">Captured {h.capturedAt}</div>
          </div>
        </div>

        <div style={{borderTop:'1px solid var(--neutral-200)', padding:'12px 20px', display:'flex', alignItems:'center', gap:12, background:'var(--neutral-50)'}}>
          <Chip>{h.status}</Chip>
          <span className="t-bodysm muted">Status confirmed · last verified 22 Apr 2026</span>
          <div style={{flex:1}}/>
          <button className="btn btn-primary" onClick={() => setCrOpen(true)}><Icon name="edit" size={14}/> Open change request</button>
          <button className="btn"><Icon name="message" size={14}/> Open grievance</button>
          <button className="btn btn-ghost"><Icon name="moreH" size={14}/></button>
        </div>
      </div>

      {/* Tabs */}
      <div role="tablist" style={{display:'flex', gap:0, borderBottom:'1px solid var(--neutral-300)', marginBottom:0, flexWrap:'wrap'}}>
        {TABS.map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} role="tab" onClick={() => setTab(t.id)} style={{
              display:'inline-flex', alignItems:'center', gap:6,
              padding:'10px 16px', border:0, borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
              background:'transparent', cursor:'pointer',
              color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
              fontWeight: active ? 600 : 500, fontSize:13.5, marginBottom:-1,
            }}>
              {t.label}
              {t.count !== undefined && (
                <span style={{display:'inline-grid', placeItems:'center', minWidth:18, height:18, padding:'0 5px', borderRadius:9, background: active ? 'var(--primary-100)' : 'var(--neutral-100)', color: active ? 'var(--primary-900)' : 'var(--neutral-700)', fontSize:11, fontWeight:600}}>{t.count}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="card" style={{borderTopLeftRadius:0, borderTopRightRadius:0, padding:0, marginTop:0}}>
        {tab === "over"  && <TabOverview h={h}/>}
        {tab === "rost"  && <TabRoster h={h}/>}
        {tab === "hd"    && <TabHealth h={h}/>}
        {tab === "ed"    && <TabEducation h={h}/>}
        {tab === "emp"   && <TabEmployment h={h}/>}
        {tab === "hous"  && <TabHousing h={h}/>}
        {tab === "food"  && <TabFood h={h}/>}
        {tab === "hist"  && <TabHistory h={h}/>}
        {tab === "grm"   && <TabGrievances h={h}/>}
        {tab === "prog"  && <TabProgrammes h={h}/>}
        {tab === "cons"  && <TabConsent h={h}/>}
        {tab === "aud"   && <TabAudit h={h}/>}
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read-only registry view (AC-UPD-VERSION). All edits open a UPD ChangeRequest. Audit chain available under the Audit tab.
      </div>

      {/* CHANGE REQUEST MODAL */}
      <ChangeRequestModal
        open={crOpen}
        onClose={() => setCrOpen(false)}
        onSubmit={handleCrSubmit}
        householdId={h.rid}
        head={h.head}
        addUx={t.addUx}
        showQuickAdd={t.showQuickAdd}
        showAccent={t.showAccent}
      />
      <Toast message={crToast} onDone={() => setCrToast("")}/>

      {/* TWEAKS */}
      {typeof TweaksPanel === 'function' && (
        <TweaksPanel title="Tweaks · Change request">
          <TweakSection label="Demo"/>
          <TweakToggle label="Open on load" value={t.openOnLoad} onChange={v => { setTweak('openOnLoad', v); setCrOpen(v); }}/>
          <TweakButton label="Re-open modal" onClick={() => setCrOpen(true)}/>
          <TweakSection label="Add-field UX"/>
          <TweakRadio label="Style" value={t.addUx}
            options={[{value:'composer',label:'Composer'},{value:'picker',label:'Search'},{value:'tree',label:'Tree'}]}
            onChange={v => setTweak('addUx', v)}/>
          <TweakSection label="Appearance"/>
          <TweakToggle label="Quick-add chips" value={t.showQuickAdd} onChange={v => setTweak('showQuickAdd', v)}/>
          <TweakToggle label="Category accent bars" value={t.showAccent} onChange={v => setTweak('showAccent', v)}/>
        </TweaksPanel>
      )}
    </div>
  );
};

const Fact = ({ label, big, sub }) => (
  <div style={{minWidth:0}}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm" style={{fontWeight:600, fontSize:15, marginTop:2, color:'var(--neutral-900)', overflowWrap:'anywhere'}}>{big}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

const TabHeader = ({ title, sub, action }) => (
  <div style={{padding:'16px 20px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', gap:12}}>
    <div>
      <h3 className="t-h3" style={{margin:0}}>{title}</h3>
      {sub && <div className="t-cap mt-1">{sub}</div>}
    </div>
    {action}
  </div>
);

/* ============================================================
   TAB BODIES
   ============================================================ */

const TabOverview = ({ h }) => (
  <div>
    <TabHeader title="Overview" sub="Snapshot of the most-referenced fields. Open any tab below for the full record."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <KVCard title="Household composition" rows={[
        ["Members", h.hh],
        ["Female / male", `${h.members.filter(m=>m.sex==='F').length} / ${h.members.filter(m=>m.sex==='M').length}`],
        ["Children < 5",  h.members.filter(m=>m.age<5).length],
        ["Children 5–17", h.members.filter(m=>m.age>=5 && m.age<18).length],
        ["Adults 18–59",  h.members.filter(m=>m.age>=18 && m.age<60).length],
        ["Elderly 60+",   h.members.filter(m=>m.age>=60).length],
      ]}/>
      <KVCard title="Identification" rows={[
        ["Registry ID", <span className="t-mono">{h.rid}</span>],
        ["Head NIN",    <span className="t-mono">{h.members[0].nin}</span>],
        ["Phone",       <span className="t-mono">{h.phone}</span>],
        ["Source",      <Chip size="sm" tone="data">{h.source.toLowerCase()}</Chip>],
        ["Captured by", h.capturedBy],
        ["Captured at", h.capturedAt],
      ]}/>
      <KVCard title="Location" tint="data" rows={[
        ["Village",     `${h.village} (${h.code})`],
        ["Parish",      h.parish],
        ["Sub-county",  "Mityana"],
        ["District",    h.district],
        ["Sub-region",  h.subreg],
        ["GPS",         <span className="t-mono">{h.gps.lat.toFixed(6)}, {h.gps.lng.toFixed(6)}</span>],
      ]}/>
      <KVCard title="Welfare snapshot" tint="eligibility" rows={[
        ["PMT score",   <span className="t-mono">{h.pmt.score.toFixed(3)}</span>],
        ["PMT band",    <Chip size="sm" tone="eligibility">{h.pmt.band}</Chip>],
        ["PMT model",   h.pmt.model],
        ["Computed",    h.pmt.computedAt],
        ["Roof",        "Iron sheets"],
        ["Water source","Borehole (< 1 km)"],
      ]}/>
    </div>
  </div>
);

const TabRoster = ({ h }) => (
  <div>
    <TabHeader title={`Roster — ${h.members.length} members`} sub="Per-individual record. Click a line to open the member detail (IDV module)."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Propose new member</button>}/>
    <div style={{padding:0}}>
      <table className="tbl">
        <thead><tr>
          <th style={{width:40}}>Line</th>
          <th>Name</th>
          <th>Relation</th>
          <th>Sex</th>
          <th>Age</th>
          <th>DoB</th>
          <th>NIN</th>
          <th className="col-actions"></th>
        </tr></thead>
        <tbody>
          {h.members.map(m => (
            <tr key={m.line} style={{cursor:'pointer'}}>
              <td>
                <span style={{display:'inline-grid', placeItems:'center', width:24, height:24, borderRadius:'50%', background: m.line === 1 ? 'var(--accent-identity-bg)' : 'var(--neutral-100)', color: m.line === 1 ? 'var(--accent-identity)' : 'var(--neutral-700)', fontSize:11, fontWeight:600}}>{m.line}</span>
              </td>
              <td>
                <div style={{fontWeight: m.line === 1 ? 600 : 500}}>{m.name}{m.line === 1 && <span className="t-cap" style={{marginLeft:8, color:'var(--accent-identity)'}}>head</span>}</div>
              </td>
              <td className="t-bodysm">{m.rel}</td>
              <td><Chip size="sm">{m.sex}</Chip></td>
              <td className="t-num">{m.age}</td>
              <td className="t-cap">{m.dob}</td>
              <td className="col-id">{m.nin}</td>
              <td className="col-actions"><Icon name="chevronRight" size={14} color="var(--neutral-500)"/></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const TabHealth = ({ h }) => (
  <div>
    <TabHeader title="Health & Disability" sub="Per-member health attributes. Combine with WSC indicators for vulnerability scoring."/>
    <div style={{padding:20}}>
      <div className="row-wrap" style={{marginBottom:16}}>
        <Stat label="Members with disability"     value="0" tint="data"/>
        <Stat label="Chronic conditions reported" value="0" tint="data"/>
        <Stat label="Pregnant / lactating"        value="1" tint="quality"/>
        <Stat label="WSC indicator"               value="None active" tint="data"/>
        <Stat label="Health insurance"            value="0 of 7" tint="quality"/>
      </div>
      <table className="tbl">
        <thead><tr><th>Line</th><th>Name</th><th>Disability</th><th>Chronic</th><th>Pregnant</th><th>Insurance</th><th>Last clinic visit</th></tr></thead>
        <tbody>
          {h.members.map(m => (
            <tr key={m.line}>
              <td>{m.line}</td>
              <td>{m.name}</td>
              <td className="muted">—</td>
              <td className="muted">—</td>
              <td>{m.line === 1 ? "Yes (3rd trimester)" : "—"}</td>
              <td className="muted">No</td>
              <td className="t-cap">{m.line === 6 ? "12 Apr 2026 (Mityana HC III)" : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const TabEducation = ({ h }) => (
  <div>
    <TabHeader title="Education — per member" sub="Literacy, ever-school, highest grade, current attendance, and reason for never attending (if applicable)."
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>}/>
    <div style={{padding:0}}>
      <table className="tbl">
        <thead><tr>
          <th style={{width:40}}>Line</th>
          <th>Name</th>
          <th>Literacy</th>
          <th>Ever school</th>
          <th>Highest grade</th>
          <th>Currently attending</th>
          <th>Never-school reason</th>
        </tr></thead>
        <tbody>
          {h.members.map(m => (
            <tr key={m.line}>
              <td>{m.line}</td>
              <td style={{fontWeight: m.line === 1 ? 600 : 400}}>{m.name}</td>
              <td>
                {m.literacy === "Reads + writes"
                  ? <Chip size="sm" tone="data">Reads + writes</Chip>
                  : m.literacy === "Neither" ? <Chip size="sm" tone="quality">Neither</Chip>
                  : <span className="muted">—</span>}
              </td>
              <td>{m.everSchool === "Yes" ? <Chip size="sm" tone="data">Yes</Chip> : m.everSchool === "No" ? <Chip size="sm" tone="danger">No</Chip> : "—"}</td>
              <td className="t-num">{m.highestGrade !== "—" ? String(m.highestGrade).padStart(2, '0') : <span className="muted">—</span>}</td>
              <td>{m.currentlyAttending === "Yes" ? <Chip size="sm" tone="data">Yes</Chip> : <span className="muted">{m.currentlyAttending}</span>}</td>
              <td>{m.neverReason !== "—" ? <span className="t-mono" style={{color:'var(--neutral-700)'}}>code {m.neverReason}</span> : <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="t-cap" style={{padding:'10px 20px', borderTop:'1px solid var(--neutral-200)', background:'var(--neutral-50)'}}>
        Code 96 = "Worked instead" · 98 = "Too young" · code list reference: REF-EDU-NEVER-SCHOOL v2024.1
      </div>
    </div>
  </div>
);

const TabEmployment = ({ h }) => (
  <div>
    <TabHeader title="Employment" sub="Activity status and primary occupation for members 14+."/>
    <div style={{padding:20}}>
      <div className="row-wrap" style={{marginBottom:16}}>
        <Stat label="Members aged 14+" value="5" tint="data"/>
        <Stat label="Subsistence farming" value="2" tint="programme"/>
        <Stat label="Casual wage labour" value="1" tint="quality"/>
        <Stat label="Unemployed (seeking)" value="1" tint="danger"/>
      </div>
      <table className="tbl">
        <thead><tr><th>Line</th><th>Name</th><th>Activity</th><th>Occupation</th><th>Employer</th><th>Hours / week</th></tr></thead>
        <tbody>
          {[
            [1, "Nsubuga Ruth",     "Self-employed", "Subsistence farming", "Own plot", 40],
            [2, "Tumusiime Samuel", "Casual wage",   "Construction labour", "Various", 24],
            [3, "Okello James",     "Student",       "—",                   "—",       0],
            [4, "Achen James",      "Unemployed",    "—",                   "—",       0],
            [5, "Byaruhanga James", "Self-employed", "Boda-boda rider",     "Own",     56],
          ].map(([line, name, act, occ, emp, hrs]) => (
            <tr key={line}>
              <td>{line}</td>
              <td>{name}</td>
              <td>
                {act === "Self-employed" && <Chip size="sm" tone="programme">{act}</Chip>}
                {act === "Casual wage"    && <Chip size="sm" tone="quality">{act}</Chip>}
                {act === "Student"        && <Chip size="sm" tone="update">{act}</Chip>}
                {act === "Unemployed"     && <Chip size="sm" tone="danger">{act}</Chip>}
              </td>
              <td className="t-bodysm">{occ}</td>
              <td className="t-bodysm muted">{emp}</td>
              <td className="t-num">{hrs}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const TabHousing = ({ h }) => (
  <div>
    <TabHeader title="Housing & Assets"/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <KVCard title="Dwelling" tint="eligibility" rows={[
        ["Tenure",    "Owner-occupied"],
        ["Roof",      "Iron sheets"],
        ["Walls",     "Brick (burnt)"],
        ["Floor",     "Cement"],
        ["Rooms",     "3 (1 sleeping)"],
        ["Lighting",  "Solar"],
      ]}/>
      <KVCard title="Water, sanitation & energy" tint="eligibility" rows={[
        ["Drinking water", "Borehole, < 1 km"],
        ["Toilet",         "Pit latrine (covered)"],
        ["Handwashing",    "Yes, near toilet"],
        ["Cooking fuel",   "Firewood"],
        ["Cooking place",  "Separate kitchen building"],
        ["Electricity",    "No grid; solar lantern"],
      ]}/>
      <KVCard title="Productive assets" tint="programme" rows={[
        ["Land owned",         "1.2 acres (cultivated)"],
        ["Livestock — cattle", "2"],
        ["Livestock — goats",  "4"],
        ["Livestock — poultry","11"],
        ["Bicycle",            "1"],
        ["Mobile phone",       "2 (basic)"],
      ]}/>
      <KVCard title="Financial inclusion" tint="programme" rows={[
        ["Bank account",    "No"],
        ["Mobile money",    "Yes (head)"],
        ["VSLA member",     "Yes (head — Kibalinga VSLA 7)"],
        ["Savings",         "Reported: low"],
        ["Outstanding loan","UGX 240,000 (SACCO)"],
        ["Insurance",       "No"],
      ]}/>
    </div>
  </div>
);

const TabFood = ({ h }) => (
  <div>
    <TabHeader title="Food security & Shocks" sub="Last 12 months · FIES + shock module"/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <div className="card" style={{padding:16, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <h4 className="t-h3" style={{margin:'0 0 12px'}}>Food Insecurity Experience Scale (FIES)</h4>
        <div className="t-cap mb-2">Score 6 of 8 · moderate-to-severe</div>
        <div style={{height:8, background:'var(--neutral-100)', borderRadius:4, overflow:'hidden', marginBottom:14}}>
          <div style={{width:'75%', height:'100%', background:'var(--accent-quality)'}}/>
        </div>
        {[
          ["Worried about food", true],
          ["Unable to eat healthy", true],
          ["Ate few kinds of food", true],
          ["Skipped meals", true],
          ["Ate less than thought", true],
          ["Ran out of food", true],
          ["Hungry but did not eat", false],
          ["Went without eating a day", false],
        ].map(([q, yes]) => (
          <div key={q} className="row gap-3" style={{padding:'6px 0', borderBottom:'1px dashed var(--neutral-200)'}}>
            <Icon name={yes ? "checkCircle" : "xCircle"} size={14} color={yes ? "var(--accent-quality)" : "var(--neutral-300)"}/>
            <span className="t-bodysm" style={{flex:1}}>{q}</span>
            <span className={yes ? "t-bodysm" : "muted t-bodysm"} style={{color: yes ? 'var(--accent-quality)' : 'var(--neutral-500)'}}>{yes ? "Yes" : "No"}</span>
          </div>
        ))}
      </div>
      <div className="card" style={{padding:16, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <h4 className="t-h3" style={{margin:'0 0 12px'}}>Shocks reported (last 12 months)</h4>
        {[
          ["Drought", "Severe", "Feb 2026", "danger"],
          ["Crop pests / disease", "Moderate", "Oct 2025", "quality"],
          ["Death in household", "—", "—", "neutral"],
          ["Loss of employment", "Moderate", "Jan 2026", "quality"],
          ["Sickness of breadwinner", "—", "—", "neutral"],
        ].map(([shock, sev, when, tone]) => (
          <div key={shock} className="row gap-3" style={{padding:'10px 0', borderBottom:'1px solid var(--neutral-200)'}}>
            <div style={{flex:1}}>
              <div style={{fontWeight:500}}>{shock}</div>
              <div className="t-cap">{when}</div>
            </div>
            {sev === "—"
              ? <span className="muted t-bodysm">Not reported</span>
              : <Chip size="sm" tone={tone}>{sev}</Chip>}
          </div>
        ))}
        <div className="tint-quality mt-3" style={{padding:12, borderRadius:4, borderLeft:'3px solid var(--accent-quality)'}}>
          <div className="row gap-2" style={{marginBottom:4}}><Icon name="alert" size={14} color="var(--accent-quality)"/><strong className="t-bodysm">Coping strategy</strong></div>
          <div className="t-bodysm muted">Reduced meals · sold one goat · borrowed from VSLA (Apr 2026).</div>
        </div>
      </div>
    </div>
  </div>
);

const TabHistory = ({ h }) => (
  <div>
    <TabHeader title="Updates history" sub="All ChangeRequests since registration. Each event opens the original UPD diff."
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export history</button>}/>
    <div style={{padding:0}}>
      <table className="tbl">
        <thead><tr><th>UPD ID</th><th>Type</th><th>Submitted by</th><th>Reviewer</th><th>Submitted</th><th>Decided</th><th>PMT impact</th><th>Status</th></tr></thead>
        <tbody>
          {[
            ["UPD-2026-04-22-00188", "Roster: edit member age", "Mukasa R.", "Adong F.", "20 Apr 2026", "22 Apr 2026", "cosmetic", "Approved"],
            ["UPD-2026-04-04-00112", "Housing: roof material",  "Mukasa R.", "Adong F.", "01 Apr 2026", "04 Apr 2026", "pmt_relevant", "Approved"],
            ["UPD-2026-03-17-00067", "Phone: update primary",   "Citizen USSD","Adong F.", "16 Mar 2026", "17 Mar 2026", "cosmetic", "Approved"],
            ["UPD-2026-03-09-00041", "Employment: head occupation", "Mukasa R.", "Adong F.", "08 Mar 2026", "09 Mar 2026", "cosmetic", "Approved"],
            ["UPD-2026-03-08-00001", "Initial registration",   "Mukasa R.", "Akello P.", "08 Mar 2026", "08 Mar 2026", "—",        "Committed"],
            ["UPD-2026-04-30-00204", "Programme: enrol OPM-PDM","System REF","Adong F.", "29 Apr 2026", "—",          "—",         "Pending Approval"],
          ].map(([id, t, sub, rev, s, d, imp, stat]) => (
            <tr key={id} style={{cursor:'pointer'}}>
              <td className="col-id">{id}</td>
              <td>{t}</td>
              <td className="t-bodysm">{sub}</td>
              <td className="t-bodysm">{rev}</td>
              <td className="t-cap">{s}</td>
              <td className="t-cap">{d}</td>
              <td>{imp === "pmt_relevant" ? <Chip size="sm" tone="eligibility">pmt_relevant</Chip> : imp === "—" ? <span className="muted">—</span> : <Chip size="sm" tone="neutral">{imp}</Chip>}</td>
              <td><Chip size="sm">{stat}</Chip></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const TabGrievances = ({ h }) => (
  <div>
    <TabHeader title="Grievances" sub="GRM cases filed against or referencing this household."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> File grievance</button>}/>
    <div style={{padding:20}}>
      <GrmCard
        id="GRV-2026-04-18-00081"
        title="Disputed exclusion from OPM-PDM Q1 disbursement"
        opener="Citizen Walk-in" date="18 Apr 2026"
        level="L2"
        status="Resolved"
        summary="Citizen reported missing from the April disbursement list. Root cause: programme list staleness. Resolution: re-enrolled by NSR Coordinator on 24 Apr; back-payment scheduled."
        timeline={[
          ["Opened at parish (L1)", "18 Apr 2026"],
          ["Escalated to CDO (L2)", "20 Apr 2026"],
          ["Action taken — re-enrolled", "24 Apr 2026"],
          ["Citizen confirmed resolution", "29 Apr 2026"],
        ]}
      />
    </div>
  </div>
);

const TabProgrammes = ({ h }) => (
  <div>
    <TabHeader title="Programmes" sub="Active enrolments, exits, and payment events from partner programmes."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Add referral</button>}/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <div className="card" style={{padding:0, border:'1px solid var(--neutral-200)', boxShadow:'none'}}>
        <div style={{padding:'12px 16px', display:'flex', alignItems:'center', justifyContent:'space-between', borderBottom:'1px solid var(--neutral-200)', background:'var(--accent-programme-bg)'}}>
          <div>
            <div className="t-cap" style={{color:'var(--accent-programme)'}}>ACTIVE ENROLMENT</div>
            <strong>Operation Wealth Creation — Parish Development Model (OPM-PDM)</strong>
          </div>
          <Chip tone="data">Active</Chip>
        </div>
        <div style={{padding:16, display:'grid', gridTemplateColumns:'140px 1fr', rowGap:6, fontSize:13}}>
          <div className="muted">Enrolled since</div><div>10 Apr 2026</div>
          <div className="muted">Tranche</div><div>2026 Q2</div>
          <div className="muted">Amount per cycle</div><div>UGX 1,000,000 (≈ USD 270)</div>
          <div className="muted">Last payment</div><div>15 May 2026 · UGX 250,000</div>
          <div className="muted">Next payment</div><div>15 Aug 2026</div>
          <div className="muted">SACCO / agent</div><div>Kibalinga SACCO</div>
        </div>
      </div>
      <div className="card" style={{padding:0, border:'1px solid var(--neutral-200)', boxShadow:'none'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}>
          <strong>Recent payment events</strong>
          <div className="t-cap">3 payments · last 12 months</div>
        </div>
        <table className="tbl" style={{boxShadow:'none'}}>
          <thead><tr><th>Date</th><th>Programme</th><th>Tranche</th><th>Amount</th><th>Status</th></tr></thead>
          <tbody>
            {[
              ["15 May 2026", "OPM-PDM", "Q2-2", "UGX 250,000", "Disbursed"],
              ["15 Apr 2026", "OPM-PDM", "Q2-1", "UGX 250,000", "Disbursed"],
              ["10 Apr 2026", "OPM-PDM", "Enrolment", "—", "Acknowledged"],
            ].map(([d, p, t, a, s], i) => (
              <tr key={i}><td className="t-cap">{d}</td><td>{p}</td><td className="t-cap">{t}</td><td className="t-mono" style={{fontSize:12.5}}>{a}</td><td><Chip size="sm" tone="data">{s}</Chip></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  </div>
);

const TabConsent = ({ h }) => (
  <div>
    <TabHeader title="Consent" sub="Data Protection and Privacy Act 2019 (Uganda). Full text and signature evidence below."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:16}}>
      <div className="tint-update" style={{padding:18, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
        <div className="row gap-2" style={{marginBottom:8}}>
          <Icon name="shield" size={14} color="var(--accent-update)"/>
          <strong>Consent statement (read to the respondent)</strong>
        </div>
        <p style={{margin:0, fontSize:13.5, lineHeight:1.7}}>
          "I, the respondent, consent to the collection and processing of my household's data by the Ministry of Gender, Labour and Social Development (MGLSD) under the Data Protection and Privacy Act 2019 of Uganda. I understand my data may be shared with partner agencies under a signed Data Sharing Agreement. I understand I may request access, correction, or erasure at any time through the parish office."
        </p>
      </div>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}><strong>Evidence</strong></div>
        <div style={{padding:16, display:'grid', gridTemplateColumns:'120px 1fr', rowGap:8, fontSize:13}}>
          <div className="muted">Consent given</div><div><Chip size="sm" tone="data"><Icon name="check" size={11}/> Yes</Chip></div>
          <div className="muted">Date</div><div>08 Mar 2026 · 11:22 EAT</div>
          <div className="muted">Operator witness</div><div>Mukasa Robert (PCH-2210)</div>
          <div className="muted">Method</div><div>Verbal + thumbprint</div>
          <div className="muted">Evidence</div><div className="row-wrap"><Chip size="sm" tone="programme">Photo (thumbprint)</Chip><Chip size="sm" tone="programme">Audio (verbal)</Chip></div>
          <div className="muted">Erasure requests</div><div className="muted">None</div>
        </div>
      </div>
    </div>
  </div>
);

const TabAudit = ({ h }) => (
  <div>
    <TabHeader title="Audit chain" sub="Tamper-evident event chain · permanent · DPO-accessible."
      action={<>
        <select className="field-select btn-sm" style={{height:30, width:160}}><option>All actions</option><option>Create</option><option>Update</option><option>Approve</option><option>Reject</option><option>View</option></select>
        <button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>
      </>}/>
    <div style={{padding:0}}>
      {[
        { who:"Akello P.",  role:"NSR Unit Coordinator", action:"viewed household detail", detail:"Read · Overview tab · 3 min", time:"3m ago",  audit:"A-2026-05-16-09014", tone:"user" },
        { who:"System REF", role:"Reference data",       action:"enrolled in OPM-PDM",     detail:"Tranche 2026 Q2 · UGX 250,000 · cycle 2", time:"2d ago", audit:"A-2026-05-15-00041", tone:"system" },
        { who:"Adong F.",  role:"CDO Tapac",            action:"approved UPD-2026-04-22-00188", detail:"Roster: edit member age · cosmetic · reason: 'Field-confirmed'", time:"22 Apr 2026", audit:"A-2026-04-22-00188", tone:"user" },
        { who:"System DQA",role:"DQA engine",           action:"evaluated update payload", detail:"Ruleset v3.4 · 0 warnings · 0 blocking", time:"22 Apr 2026", audit:"A-2026-04-22-00187", tone:"system" },
        { who:"Mukasa R.", role:"Parish Chief",         action:"submitted UPD-2026-04-22-00188", detail:"Member 3 age 13 → 14", time:"20 Apr 2026", audit:"A-2026-04-20-00112", tone:"user" },
        { who:"Akello P.", role:"NSR Unit Coordinator", action:"promoted to Registered",   detail:"Same Registry ID retained · audit A-2026-03-08-00471", time:"08 Mar 2026", audit:"A-2026-03-08-00471", tone:"user" },
        { who:"System DIH",role:"Data ingestion hub",   action:"created provisional record", detail:"Channel CAPI · tablet PCH-2210 · Parish Office Kibalinga", time:"08 Mar 2026", audit:"A-2026-03-08-00091", tone:"system" },
      ].map((e, i) => (
        <div key={i} className="audit-row" style={{padding:'14px 20px'}}>
          <div className="audit-avatar" style={{background: e.tone === 'system' ? 'var(--neutral-200)' : 'var(--primary-100)', color: e.tone === 'system' ? 'var(--neutral-700)' : 'var(--primary-900)'}}>{e.who.split(' ').map(s => s[0]).slice(0,2).join('')}</div>
          <div>
            <div><strong>{e.who}</strong> <span className="t-cap">· {e.role}</span></div>
            <div className="audit-action mt-1" style={{fontWeight:400, color:'var(--neutral-700)'}}>{e.action}</div>
            <div className="audit-detail">{e.detail}</div>
            <div className="t-cap mt-1">Audit ID <span className="t-mono">{e.audit}</span></div>
          </div>
          <div className="audit-time">{e.time}</div>
        </div>
      ))}
    </div>
  </div>
);

/* ============================================================
   Helpers
   ============================================================ */
const KVCard = ({ title, rows, tint }) => (
  <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0, borderLeft: tint ? `3px solid var(--accent-${tint})` : '1px solid var(--neutral-200)'}}>
    <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', fontSize:14, fontWeight:600}}>{title}</div>
    <div style={{padding:14, display:'grid', gridTemplateColumns:'130px 1fr', rowGap:8, columnGap:12, fontSize:13}}>
      {rows.map(([k, v], i) => (
        <React.Fragment key={i}>
          <div className="muted">{k}</div>
          <div>{v}</div>
        </React.Fragment>
      ))}
    </div>
  </div>
);

const Stat = ({ label, value, tint = "data" }) => (
  <div style={{minWidth:140, padding:'10px 14px', border:'1px solid var(--neutral-200)', borderLeft:`3px solid var(--accent-${tint})`, borderRadius:4, background:'var(--neutral-0)'}}>
    <div className="t-cap">{label}</div>
    <div style={{fontSize:20, fontWeight:700, color: `var(--accent-${tint})`, letterSpacing:'-0.01em', marginTop:2}}>{value}</div>
  </div>
);

const GrmCard = ({ id, title, opener, date, level, status, summary, timeline }) => (
  <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
    <div style={{padding:'14px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:12}}>
      <div style={{flex:1}}>
        <div className="t-cap">CASE <span className="t-mono">{id}</span></div>
        <strong style={{fontSize:14.5}}>{title}</strong>
      </div>
      <Chip tone="grm">{level}</Chip>
      <Chip>{status}</Chip>
    </div>
    <div style={{padding:16}}>
      <div className="row gap-3 mb-2" style={{marginBottom:12}}>
        <span className="t-cap">Opened by <strong style={{color:'var(--neutral-900)'}}>{opener}</strong> on <strong style={{color:'var(--neutral-900)'}}>{date}</strong></span>
      </div>
      <p className="t-bodysm" style={{margin:0, color:'var(--neutral-700)'}}>{summary}</p>
      <div className="divider"/>
      <strong className="t-cap" style={{color:'var(--neutral-700)'}}>TIMELINE</strong>
      <div className="mt-2">
        {timeline.map(([what, when], i) => (
          <div key={i} className="row gap-3" style={{padding:'8px 0', borderBottom: i < timeline.length - 1 ? '1px dashed var(--neutral-200)' : 'none'}}>
            <span style={{width:18, height:18, borderRadius:'50%', background:'var(--accent-grm-bg)', color:'var(--accent-grm)', display:'grid', placeItems:'center', fontSize:11, fontWeight:600}}>{i+1}</span>
            <span className="t-bodysm" style={{flex:1}}>{what}</span>
            <span className="t-cap" style={{whiteSpace:'nowrap'}}>{when}</span>
          </div>
        ))}
      </div>
    </div>
  </div>
);

Object.assign(window, { RegistryScreen, HouseholdScreen });
