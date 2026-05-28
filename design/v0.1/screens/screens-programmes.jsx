/* global React, Icon, Chip, PageHeader, KPI, useApi */
// NSR MIS — Programmes domain
//   • ProgrammesScreen        cross-partner list with filters, KPIs, status
//   • Programme detail lives in screens-programme-detail.jsx
//
// Live data (US-180 / US-182):
//   GET /api/v1/programmes/?partner=&kind=&status=&q=&page=&page_size=
//   GET /api/v1/programmes/aggregates/   — KPI strip
//   GET /api/v1/partners/?status=active  — partner filter dropdown
//
// The Programme model lives in apps.partners.models (not apps.referral —
// see the spec note in apps/partners/services/programme_lifecycle.py).
// Codes used: programme_kind (cash_transfer/service/in_kind/voucher/
// study/grant/subsidy); programme_status carries the lifecycle code
// (draft/pending_approval/active/suspended/pending_amendment/closing/
// closed).

const { useState: useStatePL } = React;

const _PROG_API_BASE = "/api/v1/programmes/";
const PROG_COLUMNS = [
  { id: "identity", label: "Code · Name" },
  { id: "partner", label: "Partner" },
  { id: "kind", label: "Kind" },
  { id: "unit", label: "Unit" },
  { id: "status", label: "Status" },
  { id: "enrolled", label: "Enrolled / target" },
  { id: "perCycle", label: "Per cycle" },
  { id: "dsa", label: "DSA" },
  { id: "actions", label: "" },
];
const _progDownloadCsv = (filename, rows) => {
  const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

const _progQS = (params) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v != null && v !== "") qs.set(k, String(v));
  }
  return qs.toString();
};

const _buildProgrammeListUrl = (filters, page, pageSize) => {
  const s = _progQS({ ...filters, page, page_size: pageSize });
  return s ? `${_PROG_API_BASE}?${s}` : _PROG_API_BASE;
};

const _buildProgrammeAggUrl = (filters) => {
  const s = _progQS(filters);
  return s
    ? `${_PROG_API_BASE}aggregates/?${s}`
    : `${_PROG_API_BASE}aggregates/`;
};

// Map the backend programme_status code → the human label the prototype's
// STATUS_TONE keys read off. Mirrors the migration 0010 seed.
const _STATUS_CODE_TO_LABEL = {
  draft:             "Draft",
  pending_approval:  "Pending approval",
  active:            "Active",
  suspended:         "Suspended",
  pending_amendment: "Pending amendment",
  closing:           "Closing",
  closed:            "Closed",
};

// Project a live Programme payload (ProgrammeSerializer shape) onto the
// row shape the existing table expects. Fields the backend doesn't yet
// expose (webhookHealth, lastSync, ytdUgx, grievances) default to safe
// values; the spec's follow-ups (Tranches / WebhookDelivery aggregation)
// will populate them later.
const _projectProgramme = (pr) => ({
  id: pr.id,
  code: pr.code || "",
  name: pr.name || "—",
  partner: pr.partner_code || "—",
  partnerName: pr.partner_name || "—",
  // ProgrammeKind codes — direct from the backend; KIND_TONE / KIND_LABEL
  // maps below tolerate both the new (cash_transfer) and prototype
  // (cash) keys via _normaliseKind.
  kind: _normaliseKind(pr.kind),
  kindLabel: pr.kind_label || _kindLabelFallback(pr.kind),
  unit: pr.unit_of_enrolment || "",
  unitLabel: pr.unit_of_enrolment_label || pr.unit_of_enrolment || "",
  status: _STATUS_CODE_TO_LABEL[pr.status] || pr.status_label || pr.status || "—",
  statusCode: pr.status || "",
  phase: pr.start_month || "",
  cohortTarget: pr.cohort_target || 0,
  enrolled: pr.beneficiary_estimate || 0,
  exited: 0,
  perCycleUgx: pr.amount_ugx || 0,
  ytdUgx: 0,
  geo: [],
  dsa: pr.dsa_reference || "",
  dsaExpiresIn: null,
  webhookHealth: pr.webhook_url ? "unset" : "unset",
  lastSync: "—",
  grievances: 0,
  grievancesOpen: 0,
  createdAt: (pr.created_at || "").slice(0, 10),
  lastEvent: (pr.updated_at || "").slice(0, 10),
});

// The Programme model's kind codes were renamed in US-S25-002
// (cash → cash_transfer, inkind → in_kind). Old-style codes still
// round-trip; this helper coerces both into the prototype's vocabulary
// for the colour/label maps below.
const _normaliseKind = (k) => {
  if (!k) return "";
  if (k === "cash_transfer") return "cash";
  if (k === "in_kind") return "inkind";
  return k;
};

const _kindLabelFallback = (k) => {
  const map = {
    cash_transfer: "Cash", service: "Service", in_kind: "In-kind",
    voucher: "Voucher", study: "Study", grant: "Grant", subsidy: "Subsidy",
  };
  return map[k] || k || "—";
};

// Kept as an empty fallback so any consumer that pulled PROGRAMMES
// off window still resolves to []. The screen no longer reads this.
const PROGRAMMES = [];

const _LEGACY_PROGRAMMES_UNUSED = [
  {
    code:"OPM-PDM", name:"Parish Development Model", partner:"OPM", partnerName:"Office of the Prime Minister",
    kind:"cash", unit:"household", cycle:"Quarterly",
    status:"Active", phase:"Q2 2026 disbursement",
    cohortTarget:1500000, enrolled:1487219, exited:11203,
    perCycleUgx:250000, ytdUgx:1086000000000,
    geo:["Karamoja","West Nile","Acholi","Teso","Lango","Bunyoro","Buganda South"],
    dsa:"DSA-OPM-PDM-2026-001", dsaExpiresIn:227,
    webhookHealth:"green", lastSync:"3 min ago",
    grievances:14, grievancesOpen:3,
    createdAt:"04 Jan 2026", lastEvent:"15 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"OPM-NUSAF4", name:"Northern Uganda SAF 4", partner:"OPM", partnerName:"Office of the Prime Minister",
    kind:"cash", unit:"group", cycle:"Semi-annual",
    status:"Active", phase:"Cohort 2 enrolment",
    cohortTarget:42000, enrolled:38491, exited:807,
    perCycleUgx:1200000, ytdUgx:38800000000,
    geo:["Acholi","West Nile","Karamoja","Lango"],
    dsa:"DSA-OPM-NUSAF4-2025-002", dsaExpiresIn:391,
    webhookHealth:"green", lastSync:"12 min ago",
    grievances:6, grievancesOpen:2,
    createdAt:"19 Mar 2025", lastEvent:"14 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"MGLSD-SCG", name:"Senior Citizens' Grant", partner:"MGLSD", partnerName:"Min. of Gender, Labour & Social Dev't",
    kind:"cash", unit:"member", cycle:"Monthly",
    status:"Active", phase:"May 2026 disbursement",
    cohortTarget:520000, enrolled:506744, exited:18992,
    perCycleUgx:25000, ytdUgx:63500000000,
    geo:["Karamoja","West Nile","Acholi","Teso","Lango","Bunyoro","Buganda South","Busoga","Tooro","Ankole","Kigezi","Buganda North","Bukedi","Sebei"],
    dsa:"DSA-MGLSD-SAGE-2025-002", dsaExpiresIn:158,
    webhookHealth:"amber", lastSync:"2 h ago",
    grievances:81, grievancesOpen:21,
    createdAt:"02 Feb 2023", lastEvent:"15 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"MGLSD-SAGE", name:"SAGE — close-out tranche", partner:"MGLSD", partnerName:"Min. of Gender, Labour & Social Dev't",
    kind:"cash", unit:"member", cycle:"Monthly",
    status:"Closing", phase:"Closure window · 4 of 8 districts done",
    cohortTarget:24000, enrolled:18441, exited:5559,
    perCycleUgx:25000, ytdUgx:2200000000,
    geo:["Karamoja","Acholi"],
    dsa:"DSA-MGLSD-SAGE-2025-002", dsaExpiresIn:158,
    webhookHealth:"green", lastSync:"55 min ago",
    grievances:4, grievancesOpen:0,
    createdAt:"14 Aug 2019", lastEvent:"08 May 2026",
    lifecycleStatus:"Closing",
  },
  {
    code:"WFP-KFS", name:"Karamoja Food Security", partner:"WFP", partnerName:"World Food Programme",
    kind:"inkind", unit:"household", cycle:"Monthly",
    status:"Active", phase:"April distribution",
    cohortTarget:85000, enrolled:81204, exited:1841,
    perCycleUgx:0, ytdUgx:0,
    geo:["Karamoja"],
    dsa:"DSA-WFP-KFS-2026-004", dsaExpiresIn:281,
    webhookHealth:"green", lastSync:"1 h ago",
    grievances:22, grievancesOpen:6,
    createdAt:"11 Sep 2025", lastEvent:"14 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"UNICEF-CGK", name:"Cash Grant — Karamoja", partner:"UNICEF", partnerName:"UNICEF Uganda",
    kind:"cash", unit:"household", cycle:"Quarterly",
    status:"Active", phase:"Cohort 4 enrolling",
    cohortTarget:60000, enrolled:51008, exited:1432,
    perCycleUgx:180000, ytdUgx:24400000000,
    geo:["Karamoja"],
    dsa:"DSA-UNICEF-CGK-2024-001", dsaExpiresIn:71,
    webhookHealth:"amber", lastSync:"5 h ago",
    grievances:18, grievancesOpen:4,
    createdAt:"22 Jan 2024", lastEvent:"13 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"MoH-eMTCT", name:"eMTCT Vouchers — pregnant mothers", partner:"MoH", partnerName:"Ministry of Health",
    kind:"voucher", unit:"member", cycle:"Monthly",
    status:"Active", phase:"Routine",
    cohortTarget:140000, enrolled:128091, exited:8302,
    perCycleUgx:18000, ytdUgx:11200000000,
    geo:["Karamoja","West Nile","Acholi","Teso","Lango","Bunyoro","Buganda South","Busoga","Tooro","Ankole","Kigezi","Buganda North","Bukedi","Sebei"],
    dsa:"DSA-MOH-MK-2025-003", dsaExpiresIn:198,
    webhookHealth:"green", lastSync:"7 min ago",
    grievances:38, grievancesOpen:11,
    createdAt:"05 May 2024", lastEvent:"15 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"MoES-UPE", name:"UPE attendance tracking", partner:"MoES", partnerName:"Ministry of Education & Sports",
    kind:"service", unit:"member", cycle:"Annual",
    status:"Active", phase:"AY 2026 term 1",
    cohortTarget:5200000, enrolled:5012003, exited:0,
    perCycleUgx:0, ytdUgx:0,
    geo:["Karamoja","West Nile","Acholi","Teso","Lango","Bunyoro","Buganda South","Busoga","Tooro","Ankole","Kigezi","Buganda North","Bukedi","Sebei"],
    dsa:"DSA-MOES-UPE-2025-001", dsaExpiresIn:312,
    webhookHealth:"green", lastSync:"22 min ago",
    grievances:2, grievancesOpen:0,
    createdAt:"01 Feb 2025", lastEvent:"15 May 2026",
    lifecycleStatus:"Active",
  },
  {
    code:"MGLSD-DVA", name:"Domestic Violence Aid", partner:"MGLSD", partnerName:"Min. of Gender, Labour & Social Dev't",
    kind:"grant", unit:"member", cycle:"One-off",
    status:"Draft", phase:"Awaiting MGLSD Data Steward sign-off",
    cohortTarget:8000, enrolled:0, exited:0,
    perCycleUgx:450000, ytdUgx:0,
    geo:["Karamoja","Acholi"],
    dsa:"DSA-MGLSD-SAGE-2025-002", dsaExpiresIn:158,
    webhookHealth:"unset", lastSync:"—",
    grievances:0, grievancesOpen:0,
    createdAt:"08 May 2026", lastEvent:"—",
    lifecycleStatus:"Draft",
  },
  {
    code:"OPM-DRDIP", name:"DRDIP — refugee-hosting districts", partner:"OPM", partnerName:"Office of the Prime Minister",
    kind:"inkind", unit:"household", cycle:"Quarterly",
    status:"Suspended", phase:"Suspended — DPO review of Q1 incident",
    cohortTarget:48000, enrolled:46201, exited:0,
    perCycleUgx:380000, ytdUgx:8800000000,
    geo:["West Nile","Acholi"],
    dsa:"DSA-OPM-DRDIP-2025-005", dsaExpiresIn:144,
    webhookHealth:"red", lastSync:"3 d ago",
    grievances:47, grievancesOpen:19,
    createdAt:"03 Apr 2025", lastEvent:"12 May 2026",
    lifecycleStatus:"Suspended",
  },
];

const KIND_TONE = { cash:"data", voucher:"update", inkind:"quality", service:"identity", grant:"programme", subsidy:"eligibility" };
const KIND_LABEL = { cash:"Cash", voucher:"Voucher", inkind:"In-kind", service:"Service", grant:"Grant", subsidy:"Subsidy" };
const UNIT_LABEL = { household:"Household", member:"Member", group:"Group" };
const STATUS_TONE = { Active:"data", Draft:"quality", Suspended:"danger", Closing:"update", Closed:"neutral" };

const ugx = (n) => {
  if (!n) return "—";
  if (n >= 1e9) return `UGX ${(n/1e9).toFixed(2)} B`;
  if (n >= 1e6) return `UGX ${(n/1e6).toFixed(1)} M`;
  if (n >= 1e3) return `UGX ${(n/1e3).toFixed(0)} k`;
  return `UGX ${n}`;
};
const num = (n) => n.toLocaleString();

/* ============================================================
   Webhook health pip
   ============================================================ */
const WebhookPip = ({ health, lastSync }) => {
  const map = {
    green: { color:"var(--accent-data)",     label:"Healthy" },
    amber: { color:"var(--accent-quality)",  label:"Lagging" },
    red:   { color:"var(--accent-danger)",   label:"Stalled" },
    unset: { color:"var(--neutral-400)",     label:"Not connected" },
  };
  const m = map[health] || map.unset;
  return (
    <div className="row gap-2" title={`Webhook ${m.label.toLowerCase()} · last sync ${lastSync}`}>
      <span style={{width:8, height:8, borderRadius:"50%", background:m.color}}/>
      <span className="t-cap">{m.label}</span>
    </div>
  );
};

/* ============================================================
   PROGRAMMES SCREEN
   ============================================================ */
const ProgrammesScreen = ({ onOpen, onRegister }) => {
  const [q, setQ] = useStatePL("");
  const [partnerId, setPartnerId] = useStatePL("");
  // Filter values use BACKEND codes (cash_transfer, household, draft)
  // so they round-trip through the API. Display labels stay localised
  // via the KIND_LABEL / UNIT_LABEL maps below.
  const [kindCode, setKindCode] = useStatePL("");
  const [unitCode, setUnitCode] = useStatePL("");
  const [statusCode, setStatusCode] = useStatePL("");
  const [sortBy, setSortBy] = useStatePL("lastEvent");
  const [page, setPage] = useStatePL(0);
  const [columnsOpen, setColumnsOpen] = useStatePL(false);
  const [hiddenColumns, setHiddenColumns] = useStatePL(() => {
    try { return new Set(JSON.parse(localStorage.getItem("nsr.programmes.columns.hidden") || "[]")); }
    catch (e) { return new Set(); }
  });
  const pageSize = 25;

  const _orderingMap = {
    lastEvent: "-updated_at",
    name: "name",
    enrolled: "-beneficiary_estimate",
    ytd: "-amount_ugx",
    dsaExp: "-created_at",  // proper DSA expiry sort needs a join — defer
  };

  const _filters = {
    q,
    partner: partnerId,
    kind: kindCode,
    status: statusCode,
  };
  const listUrl = _buildProgrammeListUrl(
    { ..._filters, ordering: _orderingMap[sortBy] || undefined },
    page + 1, pageSize,
  );
  const aggUrl = _buildProgrammeAggUrl(_filters);
  const partnersUrl = "/api/v1/partners/?status=active&page_size=200";

  const [listResp, listMeta] = useApi(listUrl);
  const [aggResp] = useApi(aggUrl);
  const [partnersResp] = useApi(partnersUrl);

  const rows = ((listResp && listResp.results) || []).map(_projectProgramme);
  // Client-side unit filter — the backend doesn't yet take ?unit_of_enrolment=
  // on the list endpoint (it's still a free CharField on the model).
  const filtered = unitCode ? rows.filter(r => r.unit === unitCode) : rows;

  const partners = ((partnersResp && partnersResp.results) || partnersResp || [])
    .map(p => ({ code: p.code, name: p.name }));

  const reset = () => {
    setQ(""); setPartnerId(""); setKindCode(""); setUnitCode("");
    setStatusCode(""); setPage(0);
  };

  // KPIs — aggregates endpoint returns total / by_status / by_kind.
  const total = aggResp?.total ?? 0;
  const byStatus = aggResp?.by_status || {};
  const active = byStatus.active || 0;
  const drafts = byStatus.draft || 0;
  const suspended = byStatus.suspended || 0;
  // YTD disbursement + DSA-expiry-soon need cross-table aggregation
  // (Disbursement + DSA.effective_to) — both deferred until those
  // sources land. Render dashes for now.
  const liveCount = (listResp && typeof listResp.count === "number")
    ? listResp.count
    : filtered.length;
  const showCol = (id) => !hiddenColumns.has(id);
  const visibleColSpan = PROG_COLUMNS.filter(c => showCol(c.id)).length;
  const toggleColumn = (id) => {
    const next = new Set(hiddenColumns);
    if (next.has(id)) next.delete(id); else next.add(id);
    if (["identity", "actions"].every(required => !next.has(required))) {
      setHiddenColumns(next);
      localStorage.setItem("nsr.programmes.columns.hidden", JSON.stringify([...next]));
    }
  };
  const exportCsv = () => {
    _progDownloadCsv("programmes.csv", [
      ["code", "name", "partner", "kind", "unit", "status", "enrolled", "target", "per_cycle_ugx", "dsa"],
      ...filtered.map(p => [p.code, p.name, p.partner, p.kindLabel || p.kind, p.unitLabel || p.unit, p.status, p.enrolled, p.cohortTarget, p.perCycleUgx, p.dsa]),
    ]);
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="PROGRAMMES · US-180 · REF module"
        title="Programmes"
        sub="Partner-run programmes registered against an active DSA. Each row is the source of truth for eligibility rules and lifecycle webhooks for that programme."
        right={<>
          <button className="btn" onClick={exportCsv}><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn btn-primary" onClick={onRegister}><Icon name="plus" size={14}/> Register programme</button>
        </>}
      />

      {/* KPIs */}
      <div className="grid grid-4">
        <KPI title="Programmes"
             value={total.toLocaleString()}
             foot={`${active} active · ${drafts} draft · ${suspended} suspended`}
             spark={[6,7,7,8,8,9,10,10]}/>
        <KPI title="Beneficiaries enrolled"
             value="—"
             foot="Sum across active programmes — lands when ProgrammeEnrolment aggregation ships."
             spark={[6.4,6.5,6.6,6.7,6.8,6.9,7.0,7.1]}/>
        <KPI title="YTD disbursement"
             value="—"
             foot="Needs the Disbursement table (HANDOFF §4.2)."
             spark={[40,55,72,90,110,140,170,200]}/>
        <KPI title="DSAs expiring < 6mo"
             value="—"
             foot="Needs the DSA join — see Partners · DSA tab for now."
             spark={[1,1,2,2,2,3,3,3]}/>
      </div>

      {/* Filters */}
      <div className="card mt-5" style={{padding:'14px 16px'}}>
        <div className="row gap-3" style={{flexWrap:'wrap'}}>
          <div className="search" style={{maxWidth:380, height:34, background:'var(--neutral-0)'}}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, code, partner, DSA…"/>
          </div>

          <select className="field-select" style={{height:34, width:'auto', minWidth:160}} value={partnerId} onChange={(e) => { setPartnerId(e.target.value); setPage(0); }}>
            <option value="">Any partner</option>
            {partners.map(p => <option key={p.code} value={p.code}>{p.name}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:140}} value={kindCode} onChange={(e) => { setKindCode(e.target.value); setPage(0); }}>
            <option value="">Any kind</option>
            <option value="cash_transfer">Cash</option>
            <option value="service">Service</option>
            <option value="in_kind">In-kind</option>
            <option value="voucher">Voucher</option>
            <option value="study">Study</option>
            <option value="grant">Grant</option>
            <option value="subsidy">Subsidy</option>
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:130}} value={unitCode} onChange={(e) => setUnitCode(e.target.value)}>
            <option value="">Any unit</option>
            <option value="household">Household</option>
            <option value="member">Member</option>
            <option value="group">Group</option>
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:170}} value={statusCode} onChange={(e) => { setStatusCode(e.target.value); setPage(0); }}>
            <option value="">Any status</option>
            <option value="draft">Draft</option>
            <option value="pending_approval">Pending approval</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="pending_amendment">Pending amendment</option>
            <option value="closing">Closing</option>
            <option value="closed">Closed</option>
          </select>

          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost" onClick={reset}><Icon name="x" size={13}/> Reset</button>
          <div style={{width:1, height:24, background:'var(--neutral-200)'}}/>
          <span className="t-cap">Sort:</span>
          <select className="field-select" style={{height:30, width:'auto'}} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="lastEvent">Most recent activity</option>
            <option value="name">Name (A→Z)</option>
            <option value="enrolled">Enrolled (high→low)</option>
            <option value="ytd">YTD disbursement</option>
            <option value="dsaExp">DSA expiry (soonest)</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="card mt-4">
        <div className="card-toolbar">
          <strong className="t-bodysm">{liveCount.toLocaleString()} programmes</strong>
          <span className="t-cap">
            {listMeta.loading ? "Loading…" : "click a row to open the programme record"}
          </span>
          <div style={{flex:1}}/>
          <div style={{ position: "relative" }}>
            <button className="btn btn-sm btn-ghost" onClick={() => setColumnsOpen(v => !v)}><Icon name="sliders" size={14}/> Columns</button>
            {columnsOpen && (
              <div className="card" style={{ position: "absolute", right: 0, top: 34, zIndex: 5, width: 220, padding: 10 }}>
                {PROG_COLUMNS.filter(c => c.label).map(c => (
                  <label key={c.id} className="t-bodysm" style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 4px" }}>
                    <input type="checkbox" checked={showCol(c.id)} disabled={c.id === "identity"} onChange={() => toggleColumn(c.id)}/>
                    {c.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
        {listMeta.error && (
          <div style={{padding:'12px 16px', color:'var(--accent-danger)'}} className="t-bodysm">
            Couldn’t load programmes: {listMeta.error}
          </div>
        )}
        <table className="tbl">
          <thead>
            <tr>
              {showCol("identity") && <th>Code · Name</th>}
              {showCol("partner") && <th>Partner</th>}
              {showCol("kind") && <th>Kind</th>}
              {showCol("unit") && <th>Unit</th>}
              {showCol("status") && <th>Status</th>}
              {showCol("enrolled") && <th>Enrolled / target</th>}
              {showCol("perCycle") && <th>Per cycle</th>}
              {showCol("dsa") && <th>DSA</th>}
              {showCol("actions") && <th className="col-actions"></th>}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !listMeta.loading && (
              <tr><td colSpan={visibleColSpan} style={{padding:'20px', textAlign:'center'}} className="muted t-bodysm">
                No programmes match the current filters.
              </td></tr>
            )}
            {filtered.map(p => {
              const pct = Math.round((p.enrolled / Math.max(p.cohortTarget, 1)) * 100);
              const tone = KIND_TONE[p.kind] || "data";
              return (
                <tr key={p.id} onClick={() => onOpen?.(p.id)} style={{cursor:'pointer'}}>
                  {showCol("identity") && <td>
                    <div className="row gap-3">
                      <div style={{
                        width:32, height:32, borderRadius:6,
                        background:`var(--accent-${tone}-bg, var(--neutral-100))`,
                        color:`var(--accent-${tone})`,
                        display:'grid', placeItems:'center', fontSize:11, fontWeight:700,
                      }}>{(p.code || p.name).split(/[-\s]/)[1]?.slice(0, 3)
                          || (p.code || p.name).slice(0, 3).toUpperCase()}</div>
                      <div style={{minWidth:0}}>
                        <div style={{fontWeight:600}}>{p.name}</div>
                        <div className="t-cap t-mono">{p.code || "—"}</div>
                      </div>
                    </div>
                  </td>}
                  {showCol("partner") && <td className="t-bodysm">{p.partner}</td>}
                  {showCol("kind") && <td><Chip size="sm" tone={tone}>{p.kindLabel || KIND_LABEL[p.kind] || "—"}</Chip></td>}
                  {showCol("unit") && <td>{p.unitLabel
                    ? <Chip size="sm">{p.unitLabel}</Chip>
                    : <span className="muted t-cap">—</span>}</td>}
                  {showCol("status") && <td><Chip size="sm" tone={STATUS_TONE[p.status] || "neutral"}>{p.status}</Chip></td>}
                  {showCol("enrolled") && <td>
                    {p.cohortTarget > 0 ? (
                      <>
                        <div className="t-num" style={{fontWeight:500}}>{num(p.enrolled)}</div>
                        <div style={{
                          height:4, width:120, background:'var(--neutral-100)',
                          borderRadius:2, overflow:'hidden', marginTop:3,
                        }}>
                          <div style={{
                            width:`${Math.min(pct, 100)}%`, height:'100%',
                            background: pct >= 90 ? 'var(--accent-data)'
                              : pct >= 50 ? 'var(--accent-update)' : 'var(--accent-quality)',
                          }}/>
                        </div>
                        <div className="t-cap mt-1">{pct}% of {num(p.cohortTarget)}</div>
                      </>
                    ) : <span className="muted t-cap">—</span>}
                  </td>}
                  {showCol("perCycle") && <td className="t-num t-bodysm">{p.perCycleUgx ? ugx(p.perCycleUgx) : <span className="muted">—</span>}</td>}
                  {showCol("dsa") && <td>
                    <div className="t-mono t-cap" style={{whiteSpace:'nowrap'}}>
                      {p.dsa ? `${p.dsa.slice(0, 18)}${p.dsa.length > 18 ? '…' : ''}` : <span className="muted">—</span>}
                    </div>
                  </td>}
                  {showCol("actions") && <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>}
                </tr>
              );
            })}
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
            <span className="t-bodysm" style={{padding:'0 8px'}}>
              {page+1} / {Math.max(1, Math.ceil(liveCount / pageSize))}
            </span>
            <button className="btn btn-sm" disabled={(page + 1) * pageSize >= liveCount} onClick={() => setPage(p => p + 1)}><Icon name="chevronRight" size={14}/></button>
            <button className="btn btn-sm" disabled={(page + 1) * pageSize >= liveCount} onClick={() => setPage(Math.max(0, Math.ceil(liveCount / pageSize) - 1))}><Icon name="chevronsRight" size={14}/></button>
          </div>
        </div>
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read-only programmes view. Use <strong>Register programme</strong> to draft a new one — sign-off chain shown on submission.
      </div>
    </div>
  );
};

Object.assign(window, { ProgrammesScreen, PROGRAMMES, KIND_TONE, KIND_LABEL, UNIT_LABEL, STATUS_TONE, WebhookPip, ugx, num });
