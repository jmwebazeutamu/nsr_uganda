/* global React, Icon, Chip, PageHeader, KPI, useApi, MembersListView */
// NSR MIS — Registry browse (US-005 / US-090 read-only registry view).
//
// This file owns the two-headed RegistryScreen (Households + Members
// tabs). The Household Detail screen lives in screens-household.jsx —
// it loaded first into the harness and registers HouseholdScreen on
// `window` before this file runs. We deliberately do NOT export a
// HouseholdScreen here; an earlier prototype version in this file
// used to override the live one (regressed the detail view into a
// mocked Change Request form), and the export is removed for good.

const { useState: useStateReg } = React;

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

// HouseholdScreen is deliberately NOT exported here — the canonical
// live-wired implementation lives in screens-household.jsx and is
// registered on window before this file loads. An earlier prototype
// in this file used to override that and regressed the detail view
// into a mocked Change Request form; the prototype block (HH_DETAIL +
// HouseholdScreen + 12 tab bodies + CR_TWEAK_DEFAULTS + helpers) has
// been removed.
Object.assign(window, { RegistryScreen });
