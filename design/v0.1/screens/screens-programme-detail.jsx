/* global React, Icon, Chip, PageHeader, Modal, Field, Toast,
   KIND_TONE, KIND_LABEL, UNIT_LABEL, STATUS_TONE, WebhookPip, ugx, num,
   useApi, useChoiceList, nsrApi */
// NSR MIS — Programme detail (US-180 sibling)
// ============================================
// 9-tab programme record. Mirrors HouseholdScreen / MemberDetailScreen
// shape: PageHeader → summary card → action bar → tabs → tab bodies.
//
// Live data:
//   GET /api/v1/programmes/{id}/         — ProgrammeSerializer payload
//   GET /api/v1/programmes/{id}/signoffs/ — 4-step sign-off chain rows
//
// Six of the nine tabs (Overview, Eligibility, Geography, Integration,
// Sign-off & audit + the summary card) render off live data. Three —
// Schedule & disbursement, Enrolment, Lifecycle events, Grievances —
// have no backend source yet (Tranche / WebhookDelivery / GRM.Case
// joins). Those render bounded empty-state stubs naming the missing
// data source.

const { useState: useStatePD } = React;

// Same status-code → label translation as the list view.
const _PD_STATUS_LABEL = {
  draft:             "Draft",
  pending_approval:  "Pending approval",
  active:            "Active",
  suspended:         "Suspended",
  pending_amendment: "Pending amendment",
  closing:           "Closing",
  closed:            "Closed",
};

// Empty fallback so tab bodies that read .events / .recent /etc.
// don't need null-guards while the fetch is in flight.
const _PROG_FALLBACK = {
  id: "",
  code: "—",
  name: "Loading…",
  partner: "—", partnerName: "—", partnerLead: "—",
  kind: "", kindLabel: "—",
  unit: "", cycle: "—",
  status: "—", statusCode: "", phase: "—",
  summary: "",
  startDate: "—", endDate: "—",
  cohortTarget: 0, enrolled: 0, exited: 0,
  perCycleUgx: 0, ytdUgx: 0, currency: "UGX",
  geo: [],
  dsa: "—", dsaExpiresIn: null, dsaCeiling: "",
  webhookUrl: "", webhookSecret: "wh_••••••••",
  webhookHealth: "unset", lastSync: "—", successRate24h: null,
  webhookEvents: [],
  eligibility: {
    pmtBands: [], sex: "", ageBand: "",
    disability: "", requirePmtRecency: "",
    requireConsent: false, excludeProgrammes: [],
    additionalRules: [],
  },
  schedule: { nextCycleStart: "", cyclesThisYear: 0, cyclesCompleted: 0,
    completedTranches: [], plannedTranches: [] },
  enrolment: { recentEnrolled: [], recentExits: [] },
  grievances: { total: 0, open: 0, breakdown: [], recent: [] },
  audit: [],
  signoff: [],
  amendments: [],
};

const _normaliseKindD = (k) => {
  if (!k) return "";
  if (k === "cash_transfer") return "cash";
  if (k === "in_kind") return "inkind";
  return k;
};

// Project the live ProgrammeSerializer payload + signoff chain
// response onto the `m` shape the existing tab bodies render off.
const _projectProgrammeDetail = (programme, signoffs) => {
  if (!programme) return _PROG_FALLBACK;
  const m = JSON.parse(JSON.stringify(_PROG_FALLBACK));
  m.id = programme.id;
  m.code = programme.code || "—";
  m.name = programme.name || "—";
  m.partner = programme.partner_code || "—";
  m.partnerName = programme.partner_name || "—";
  m.kind = _normaliseKindD(programme.kind);
  m.kindLabel = programme.kind_label || programme.kind || "—";
  m.unit = programme.unit_of_enrolment || "";
  m.cycle = programme.disbursement_cycle_label
    || programme.disbursement_cycle || "—";
  m.status = _PD_STATUS_LABEL[programme.status]
    || programme.status_label || programme.status || "—";
  m.statusCode = programme.status || "";
  m.phase = programme.start_month || "";
  m.summary = programme.summary || "";
  m.startDate = programme.start_date || programme.start_month || "—";
  m.endDate = programme.end_date
    || (programme.duration_months ? `${programme.duration_months}mo from start` : "—");
  m.cohortTarget = programme.cohort_target || 0;
  m.enrolled = programme.beneficiary_estimate || 0;
  m.perCycleUgx = programme.amount_ugx || 0;
  m.dsa = programme.dsa_reference || "—";
  m.webhookUrl = programme.webhook_url || "";
  m.webhookSecret = programme.webhook_url
    ? "wh_•••••••••••• (rotate via /webhook/rotate-secret/)"
    : "—";
  m.eligibility = {
    pmtBands: programme.pmt_bands || [],
    sex: programme.sex_filter_label || programme.sex_filter || "any",
    ageBand: (programme.age_min != null && programme.age_max != null)
      ? `${programme.age_min}–${programme.age_max}`
      : "—",
    disability: "—",
    requirePmtRecency: "—",
    requireConsent: false,
    excludeProgrammes: [],
    additionalRules: [],
  };

  m.signoff = (signoffs || []).map((s) => ({
    step: s.step,
    role: _ROLE_LABEL[s.expected_role] || s.expected_role,
    who: s.actual_email || s.expected_email || "—",
    at: s.decided_at ? s.decided_at.slice(0, 16).replace("T", " ") : "—",
    status: s.status,
  }));

  return m;
};

// Map ProgrammeSignOff.expected_role codes to display labels.
const _ROLE_LABEL = {
  nsr_unit_coordinator: "NSR Unit Coordinator",
  partner_data_steward: "Partner Data Steward",
  dpo: "Data Protection Officer (DPO)",
  nsr_director: "Director · NSR Programme",
};

const _LEGACY_PROG_DETAIL_UNUSED = {
  code:"OPM-PDM",
  name:"Parish Development Model",
  partner:"OPM", partnerName:"Office of the Prime Minister",
  partnerLead:"Bahati Esther · OPM Data Steward",
  kind:"cash", unit:"household", cycle:"Quarterly",
  status:"Active", phase:"Q2 2026 disbursement",
  summary:"Quarterly cash transfer to Parish Development Model SACCO members in the seven targeted sub-regions. Tranches funded centrally, disbursed via SACCO agents, lifecycle pushed back through the partner MIS webhook.",
  startDate:"04 Jan 2026",
  endDate:"31 Dec 2026 (renewable)",
  cohortTarget:1500000, enrolled:1487219, exited:11203,
  perCycleUgx:250000, ytdUgx:1086000000000, currency:"UGX",
  geo:["Karamoja","West Nile","Acholi","Teso","Lango","Bunyoro","Buganda South"],
  dsa:"DSA-OPM-PDM-2026-001", dsaExpiresIn:227, dsaCeiling:"Households · Karamoja+6, P40 cap",
  webhookUrl:"https://opm.go.ug/pdm/nsr/webhook",
  webhookSecret:"wh_••••••••••••••••••••",
  webhookHealth:"green", lastSync:"3 min ago", successRate24h:99.4,
  webhookEvents:[
    { time:"15 May 2026 · 14:02", evt:"payment.disbursed", count:"487,210 records · 1 batch", status:"ok" },
    { time:"15 May 2026 · 13:55", evt:"enrolment.activated", count:"412 records",            status:"ok" },
    { time:"15 May 2026 · 09:18", evt:"member.exited",     count:"38 records",                status:"ok" },
    { time:"14 May 2026 · 22:01", evt:"payment.disbursed", count:"312,008 records · 1 batch", status:"ok" },
    { time:"13 May 2026 · 08:14", evt:"enrolment.activated", count:"611 records",            status:"ok" },
    { time:"12 May 2026 · 04:22", evt:"webhook.retry",     count:"1 batch · 503 from partner",status:"warn" },
  ],
  eligibility: {
    pmtBands:["Poorest 20%","Poorest 40%"],
    sex:"any",
    ageBand:"18+",
    disability:"any",
    requirePmtRecency:"≤ 24 months",
    requireConsent:true,
    excludeProgrammes:["MGLSD-SCG"],
    additionalRules:[
      "Head of household must be enrolled in a Parish SACCO",
      "Household must have completed the PDM orientation module",
    ],
  },
  schedule:{
    nextCycleStart:"15 Aug 2026",
    cyclesThisYear:4,
    cyclesCompleted:2,
    completedTranches:[
      { id:"2026Q1", window:"15 Feb–15 Mar 2026", disbursed: 372500000000, count: 1490000, status:"Disbursed" },
      { id:"2026Q2", window:"15 May–15 Jun 2026", disbursed: 371000000000, count: 1484000, status:"Disbursing" },
    ],
    plannedTranches:[
      { id:"2026Q3", window:"15 Aug–15 Sep 2026", planned:  371250000000, count: 1485000, status:"Planned"   },
      { id:"2026Q4", window:"15 Nov–15 Dec 2026", planned:  371250000000, count: 1485000, status:"Planned"   },
    ],
  },
  enrolment: {
    recentEnrolled:[
      { id:"01HXP02CN4QFB7K6FZRWS00111", head:"Mukasa Patrick",     subreg:"West Nile",      district:"Arua",      enrolledAt:"15 Feb 2026" },
      { id:"01KRPPW6WRGRJZY0N4XN8R1YC2", head:"Nsubuga Ruth",       subreg:"Buganda South",  district:"Lyantonde", enrolledAt:"10 Apr 2026" },
      { id:"01HY09KRS1P9MN6FB7K6FZRWS84", head:"Lopuwa John",       subreg:"Karamoja",       district:"Moroto",    enrolledAt:"08 Apr 2026" },
      { id:"01HX91KPNRMQ0F2B7K6FZRWS44", head:"Namutebi Sarah",     subreg:"Buganda South",  district:"Lyantonde", enrolledAt:"22 Dec 2025" },
      { id:"01HX91KPNRMQ0F2B7K6FZRWS10", head:"Byaruhanga Charles", subreg:"Buganda South",  district:"Lyantonde", enrolledAt:"22 Dec 2025" },
    ],
    recentExits:[
      { id:"01HX91KPNRMQ0F2B7K6FZRWS66", head:"Apio Joyce",     reason:"50 — Re-targeted out", exitedAt:"04 May 2026" },
      { id:"01HY0AMNT8P2N6FB7K6FZRWS92", head:"Acheng Rose",    reason:"20 — Transferred to SCG", exitedAt:"02 May 2026" },
      { id:"01HXZBVK6QN8M2PFB7K6FZRWS41", head:"Nakato Sarah",  reason:"60 — Withdrew consent", exitedAt:"24 Apr 2026" },
    ],
  },
  grievances: {
    total:14, open:3, breakdown:[
      { level:"L1 · Parish",    count:5 },
      { level:"L2 · CDO",       count:6 },
      { level:"L3 · NSR Unit",  count:2 },
      { level:"L4 · DPO",       count:1 },
    ],
    recent:[
      { id:"GRV-2026-04-18-00081", title:"Disputed exclusion from Q1 disbursement",      level:"L2", status:"Resolved" },
      { id:"GRV-2026-04-29-00112", title:"Wrong agent assigned · Kakingol",              level:"L1", status:"In progress" },
      { id:"GRV-2026-05-04-00127", title:"SACCO membership lapsed before disbursement",  level:"L1", status:"Resolved" },
    ],
  },
  audit:[
    { who:"Akello P.",  role:"NSR Unit Coordinator", action:"viewed programme record",   detail:"Read · Overview · 4 min",          time:"6m ago",        audit:"A-2026-05-22-09028", tone:"user" },
    { who:"System REF", role:"Reference data",       action:"enrolment.activated",       detail:"412 records · batch wh-2026-05-15-088", time:"15 May 2026", audit:"A-2026-05-15-00088", tone:"system" },
    { who:"Adong F.",   role:"NSR Coordinator",      action:"approved amendment AM-04",  detail:"DSA scope expanded to Buganda South · audit AM-2026-04-22-04", time:"22 Apr 2026", audit:"A-2026-04-22-00044", tone:"user" },
    { who:"Bahati E.",  role:"OPM Data Steward",     action:"signed programme",          detail:"Sign-off chain step 2/4",          time:"04 Jan 2026",  audit:"A-2026-01-04-00012", tone:"user" },
    { who:"System DPO", role:"Data Protection Office", action:"approved DSA",            detail:"DSA-OPM-PDM-2026-001 · ceiling 1.5M HH", time:"02 Jan 2026", audit:"A-2026-01-02-00004", tone:"system" },
  ],
  signoff:[
    { step:1, role:"NSR Unit Coordinator",          who:"Akello P.",   at:"04 Jan 2026 · 09:14", status:"signed" },
    { step:2, role:"OPM Data Steward",              who:"Bahati E.",   at:"04 Jan 2026 · 11:02", status:"signed" },
    { step:3, role:"Data Protection Officer (DPO)", who:"Otieno J.",   at:"04 Jan 2026 · 15:48", status:"signed" },
    { step:4, role:"Director · NSR Programme",      who:"Mutebi R.",   at:"05 Jan 2026 · 08:30", status:"signed" },
  ],
  amendments:[
    { id:"AM-2026-04-22-04", title:"Extend DSA scope to Buganda South",      requestedBy:"Bahati E.",   decidedAt:"22 Apr 2026", status:"Approved" },
    { id:"AM-2026-03-14-03", title:"Tighten PMT cap to P40",                 requestedBy:"Mukasa P.",   decidedAt:"15 Mar 2026", status:"Approved" },
    { id:"AM-2026-02-08-02", title:"Add 'PDM orientation completed' rule",   requestedBy:"Bahati E.",   decidedAt:"10 Feb 2026", status:"Approved" },
    { id:"AM-2026-01-30-01", title:"Initial programme record",               requestedBy:"Akello P.",   decidedAt:"04 Jan 2026", status:"Committed" },
  ],
};

const PD_TABS = [
  { id:"over",  label:"Overview" },
  { id:"elig",  label:"Eligibility" },
  { id:"sched", label:"Schedule & disbursement" },
  { id:"geo",   label:"Geography & DSA scope" },
  // Tab counts for Enrolment / Lifecycle events / Grievances need
  // join targets (ProgrammeEnrolment / WebhookDelivery / GRM.Case)
  // that aren't yet wired into the detail response. Counts are
  // computed inline in the render below when those endpoints land.
  { id:"enr",   label:"Enrolment" },
  { id:"life",  label:"Lifecycle events" },
  { id:"intg",  label:"Integration" },
  { id:"grm",   label:"Grievances" },
  { id:"aud",   label:"Sign-off & audit" },
];

/* ============================================================
   Locally-scoped helpers
   ============================================================ */
const PD_Fact = ({ label, big, sub }) => (
  <div style={{minWidth:0}}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm" style={{fontWeight:600, fontSize:15, marginTop:2, color:'var(--neutral-900)', overflowWrap:'anywhere'}}>{big}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

const PD_TabHeader = ({ title, sub, action }) => (
  <div style={{padding:'16px 20px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', gap:12}}>
    <div>
      <h3 className="t-h3" style={{margin:0}}>{title}</h3>
      {sub && <div className="t-cap mt-1">{sub}</div>}
    </div>
    {action}
  </div>
);

const PD_KVCard = ({ title, rows, tint }) => (
  <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0, borderLeft: tint ? `3px solid var(--accent-${tint})` : '1px solid var(--neutral-200)'}}>
    <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', fontSize:14, fontWeight:600}}>{title}</div>
    <div style={{padding:'12px 16px', display:'grid', gridTemplateColumns:'160px 1fr', rowGap:6, columnGap:12, fontSize:13}}>
      {rows.map(([k, v], i) => (
        <React.Fragment key={i}>
          <div className="muted">{k}</div>
          <div>{v}</div>
        </React.Fragment>
      ))}
    </div>
  </div>
);

const PD_Stat = ({ label, value, tint = "data", sub }) => (
  <div style={{minWidth:160, padding:'10px 14px', border:'1px solid var(--neutral-200)', borderLeft:`3px solid var(--accent-${tint})`, borderRadius:4, background:'var(--neutral-0)'}}>
    <div className="t-cap">{label}</div>
    <div style={{fontSize:17, fontWeight:600, marginTop:2}}>{value}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

/* ============================================================
   ProgrammeDetailScreen
   ============================================================ */
const ProgrammeDetailScreen = ({ programmeId, onBack, onOpenPartner, onOpenHousehold }) => {
  const [tab, setTab] = useStatePD("over");
  // US-S11-037 — CRUD affordances on the Programme detail. Edit is
  // a PATCH on focused fields (lifecycle status NOT exposed here —
  // status transitions go through close/suspend lifecycle actions).
  // Close uses the existing /close/ action because Programme rows
  // carry audit lineage that hard-delete would orphan; Delete is
  // allowed only for status=draft (no commitments yet).
  const [toast, setToast] = useStatePD("");
  const [editOpen, setEditOpen] = useStatePD(false);
  const [closeOpen, setCloseOpen] = useStatePD(false);
  const [deleteOpen, setDeleteOpen] = useStatePD(false);

  const [progResp, progMeta] = useApi(
    programmeId ? `/api/v1/programmes/${programmeId}/` : null,
  );
  const [signoffResp] = useApi(
    programmeId ? `/api/v1/programmes/${programmeId}/signoffs/` : null,
  );
  const p = _projectProgrammeDetail(
    progResp,
    (signoffResp && signoffResp.items) || [],
  );
  const pct = Math.round((p.enrolled / Math.max(p.cohortTarget, 1)) * 100);

  if (!programmeId) {
    return (
      <div className="page">
        <PageHeader eyebrow="PROGRAMME" title="No programme selected"/>
        <div className="card" style={{padding: 20}} className="muted">
          Open a programme from the Programmes list to see its detail view.
        </div>
      </div>
    );
  }
  if (progMeta.loading && !progResp) {
    return (
      <div className="page">
        <PageHeader eyebrow="PROGRAMME" title="Loading…"/>
      </div>
    );
  }
  if (progMeta.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="PROGRAMME" title="Could not load programme" sub={progMeta.error}/>
        <div style={{padding:20}}>
          <button className="btn" onClick={onBack}>
            <Icon name="chevronLeft" size={14}/> Back to Programmes
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow={<>PROGRAMME · <span className="t-mono">{p.code}</span> · {p.partner}</>}
        title={<>{p.name} <span className="t-bodysm" style={{fontWeight:400, color:'var(--accent-data)', marginLeft:8}}>· {p.phase}</span></>}
        sub={<>{KIND_LABEL[p.kind]} · {UNIT_LABEL[p.unit]} · {p.cycle} · DSA <span className="t-mono">{p.dsa}</span></>}
        right={<>
          <button className="btn" onClick={() => onOpenPartner?.(p.partner)}><Icon name="users" size={14}/> Open partner</button>
          <button className="btn" onClick={() => setEditOpen(true)}
                  title="Edit name, summary, disbursement, webhook (PATCH /api/v1/programmes/{id}/)">
            <Icon name="edit" size={14}/> Edit
          </button>
          {p.statusCode !== "draft" && p.statusCode !== "closed" && (
            <button className="btn"
                    style={{color:"var(--accent-quality)"}}
                    onClick={() => setCloseOpen(true)}
                    title="Lifecycle close — POST /api/v1/programmes/{id}/close/">
              <Icon name="archive" size={14}/> Close
            </button>
          )}
          {p.statusCode === "draft" && (
            <button className="btn"
                    style={{color:"var(--accent-danger)"}}
                    onClick={() => setDeleteOpen(true)}
                    title="Hard-delete the draft (DELETE /api/v1/programmes/{id}/)">
              <Icon name="trash" size={14}/> Delete draft
            </button>
          )}
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to Programmes</button>
        </>}
      />

      {/* Summary card */}
      <div className="card" style={{padding:0, marginBottom:16}}>
        <div style={{padding:'18px 20px', display:'grid', gridTemplateColumns:'72px 1.2fr 1.2fr 1.2fr 1.4fr 1fr', gap:24, alignItems:'flex-start'}}>
          <div style={{
            width:72, height:72, borderRadius:8,
            background:`var(--accent-${KIND_TONE[p.kind]}-bg, var(--neutral-100))`,
            color:`var(--accent-${KIND_TONE[p.kind]})`,
            display:'grid', placeItems:'center', fontSize:18, fontWeight:700,
          }}>{p.code.split('-')[1]?.slice(0, 3) || p.code.slice(0, 3)}</div>

          <PD_Fact label="Partner"
            big={p.partnerName}
            sub={p.partnerLead}/>

          <PD_Fact label="Status"
            big={<Chip tone={STATUS_TONE[p.status]}>{p.status}</Chip>}
            sub={p.phase}/>

          <PD_Fact label="Enrolment"
            big={`${num(p.enrolled)} / ${num(p.cohortTarget)}`}
            sub={`${pct}% of cohort target · ${num(p.exited)} exits`}/>

          <PD_Fact label="Disbursement"
            big={ugx(p.perCycleUgx)}
            sub={<>per cycle · YTD {ugx(p.ytdUgx)}</>}/>

          <div>
            <div className="t-cap">Webhook</div>
            <div className="row gap-2 mt-1"><WebhookPip health={p.webhookHealth} lastSync={p.lastSync}/></div>
            <div className="t-cap mt-2">{p.successRate24h}% 24h success</div>
          </div>
        </div>

        {/* Enrolment progress bar */}
        <div style={{padding:'0 20px 14px'}}>
          <div style={{
            height:6, background:'var(--neutral-100)', borderRadius:3, overflow:'hidden',
          }}>
            <div style={{
              width:`${Math.min(pct, 100)}%`, height:'100%',
              background: pct >= 90 ? 'var(--accent-data)'
                : pct >= 50 ? 'var(--accent-update)' : 'var(--accent-quality)',
            }}/>
          </div>
        </div>

        <div style={{borderTop:'1px solid var(--neutral-200)', padding:'12px 20px', display:'flex', alignItems:'center', gap:12, background:'var(--neutral-50)'}}>
          <Chip size="sm" tone={KIND_TONE[p.kind]}>{KIND_LABEL[p.kind]}</Chip>
          <Chip size="sm">{UNIT_LABEL[p.unit]}</Chip>
          <Chip size="sm">{p.cycle}</Chip>
          <span className="t-bodysm muted">DSA expires in {p.dsaExpiresIn} days · ceiling {p.dsaCeiling}</span>
          <div style={{flex:1}}/>
          <button className="btn btn-primary"><Icon name="edit" size={14}/> Propose amendment</button>
          <button className="btn"><Icon name="pause" size={14}/> Suspend</button>
          <button className="btn btn-ghost"><Icon name="moreH" size={14}/></button>
        </div>
      </div>

      {/* Tabs */}
      <div role="tablist" style={{display:'flex', gap:0, borderBottom:'1px solid var(--neutral-300)', marginBottom:0, flexWrap:'wrap'}}>
        {PD_TABS.map(t => {
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

      <div className="card" style={{borderTopLeftRadius:0, borderTopRightRadius:0, padding:0, marginTop:0}}>
        {tab === "over"  && <PdOverview p={p}/>}
        {tab === "elig"  && <PdEligibility p={p}/>}
        {tab === "sched" && <PdSchedule p={p}/>}
        {tab === "geo"   && <PdGeography p={p}/>}
        {tab === "enr"   && <PdEnrolment p={p} onOpenHousehold={onOpenHousehold}/>}
        {tab === "life"  && <PdLifecycle p={p}/>}
        {tab === "intg"  && <PdIntegration p={p}/>}
        {tab === "grm"   && <PdGrievances p={p}/>}
        {tab === "aud"   && <PdAudit p={p}/>}
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read-only programme record. All edits open an Amendment ChangeRequest. Sign-off chain visible under the Sign-off & audit tab.
      </div>

      <Toast message={toast} onDone={() => setToast("")}/>

      <EditProgrammeModal
        open={editOpen}
        programme={progResp}
        onClose={() => setEditOpen(false)}
        onSaved={(updated) => {
          setEditOpen(false);
          setToast(`Updated ${updated?.code || "programme"}.`);
          progMeta.refresh && progMeta.refresh();
        }}
        onError={(msg) => setToast(`Edit failed: ${msg}`)}/>

      <CloseProgrammeConfirm
        open={closeOpen}
        programme={progResp}
        onClose={() => setCloseOpen(false)}
        onClosed={() => {
          setCloseOpen(false);
          setToast(`Closed ${p.code} — lifecycle event written to audit chain.`);
          progMeta.refresh && progMeta.refresh();
        }}
        onError={(msg) => setToast(`Close failed: ${msg}`)}/>

      <DeleteProgrammeConfirm
        open={deleteOpen}
        programme={progResp}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => {
          setDeleteOpen(false);
          setToast(`Deleted ${p.code}.`);
          if (onBack) onBack();
        }}
        onError={(msg) => setToast(`Delete failed: ${msg}`)}/>
    </div>
  );
};


// ── EditProgrammeModal (US-S11-037) ───────────────────────────────────
// PATCHes the most-commonly-changed fields. Status is intentionally
// NOT here — lifecycle transitions go through close/suspend actions
// so the sign-off + audit chain stays intact.
const EditProgrammeModal = ({ open, programme, onClose, onSaved, onError }) => {
  const [name, setName] = useStatePD("");
  const [summary, setSummary] = useStatePD("");
  const [durationMonths, setDurationMonths] = useStatePD("");
  const [channel, setChannel] = useStatePD("");
  const [amountUgx, setAmountUgx] = useStatePD("");
  const [cohortTarget, setCohortTarget] = useStatePD("");
  const [webhookUrl, setWebhookUrl] = useStatePD("");
  const [submitting, setSubmitting] = useStatePD(false);

  React.useEffect(() => {
    if (!open || !programme) return;
    setName(programme.name || "");
    setSummary(programme.summary || "");
    setDurationMonths(programme.duration_months ?? "");
    setChannel(programme.channel || "");
    setAmountUgx(programme.amount_ugx ?? "");
    setCohortTarget(programme.cohort_target ?? "");
    setWebhookUrl(programme.webhook_url || "");
  }, [open, programme]);

  if (!open || !programme) return null;
  const canSave = !submitting && name.trim();

  const save = async () => {
    if (!canSave) return;
    setSubmitting(true);
    try {
      const payload = {
        name: name.trim(),
        summary: summary.trim(),
        channel: channel.trim(),
        webhook_url: webhookUrl.trim(),
      };
      // Numeric fields — only include when non-empty, and coerce. The
      // serializer rejects "" for these IntegerFields.
      if (durationMonths !== "") payload.duration_months = parseInt(durationMonths, 10);
      if (amountUgx !== "")      payload.amount_ugx = parseInt(amountUgx, 10);
      if (cohortTarget !== "")   payload.cohort_target = parseInt(cohortTarget, 10);
      const updated = await nsrApi.patch(
        `/api/v1/programmes/${programme.id}/`, payload,
      );
      setSubmitting(false);
      onSaved(updated);
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || Object.values(err.body).flat().join(" · "))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Edit ${programme.code || "programme"}`} size="md">
      <p className="t-bodysm muted" style={{marginTop:0, marginBottom:16}}>
        Patches descriptive + disbursement fields. Status transitions go
        through the Close button (lifecycle service); scope amendments
        through the Amendment ChangeRequest path.
      </p>

      <Field label="Name">
        <input value={name} onChange={e => setName(e.target.value)} disabled={submitting}/>
      </Field>
      <Field label="Summary">
        <textarea value={summary} onChange={e => setSummary(e.target.value)} rows={2} disabled={submitting}/>
      </Field>

      <div className="grid grid-3" style={{gap:12}}>
        <Field label="Duration (months)">
          <input type="number" min={0} value={durationMonths}
                 onChange={e => setDurationMonths(e.target.value)} disabled={submitting}/>
        </Field>
        <Field label="Amount (UGX)">
          <input type="number" min={0} value={amountUgx}
                 onChange={e => setAmountUgx(e.target.value)} disabled={submitting}/>
        </Field>
        <Field label="Cohort target">
          <input type="number" min={0} value={cohortTarget}
                 onChange={e => setCohortTarget(e.target.value)} disabled={submitting}/>
        </Field>
      </div>

      <Field label="Channel">
        <input value={channel} onChange={e => setChannel(e.target.value)} disabled={submitting}
               placeholder="e.g. mobile-money, bank-transfer"/>
      </Field>
      <Field label="Webhook URL">
        <input type="url" value={webhookUrl} onChange={e => setWebhookUrl(e.target.value)}
               disabled={submitting} placeholder="https://…/nsr-webhook"/>
      </Field>

      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!canSave}>
          {submitting ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
};


// ── CloseProgrammeConfirm (US-S11-037) ────────────────────────────────
// Posts to the existing /close/ lifecycle action. Preserves the
// programme row + audit chain — the only state change is status →
// closed and a lifecycle event row written server-side.
const CloseProgrammeConfirm = ({ open, programme, onClose, onClosed, onError }) => {
  const [reason, setReason] = useStatePD("");
  const [submitting, setSubmitting] = useStatePD(false);
  React.useEffect(() => { if (open) setReason(""); }, [open]);
  if (!open || !programme) return null;

  const fire = async () => {
    setSubmitting(true);
    try {
      await nsrApi.post(`/api/v1/programmes/${programme.id}/close/`, {
        reason: reason.trim(),
      });
      setSubmitting(false);
      onClosed();
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || JSON.stringify(err.body))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Close ${programme.code}?`} size="sm">
      <p className="t-bodysm" style={{margin:"4px 0 12px"}}>
        Marks the programme as closed and writes a ProgrammeLifecycleEvent
        row. Existing enrolments + sign-offs are preserved. The programme
        cannot be re-opened — use a new Programme draft if the partner
        wants to resume.
      </p>
      <Field label="Reason (recorded on the lifecycle event)">
        <textarea value={reason} onChange={e => setReason(e.target.value)}
                  rows={2} disabled={submitting}
                  placeholder="e.g. cohort complete, partner withdrawing scope"/>
      </Field>
      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button
          className="btn"
          style={{background:"var(--accent-quality)", color:"white", borderColor:"var(--accent-quality)"}}
          onClick={fire} disabled={submitting || !reason.trim()}
        >
          {submitting ? "Closing…" : "Close programme"}
        </button>
      </div>
    </Modal>
  );
};


// ── DeleteProgrammeConfirm (US-S11-037) ───────────────────────────────
// Hard-delete — only offered when status=draft. The Edit modal won't
// show a Delete button for any other state, but we still surface the
// status here so a stale prop doesn't slip a destructive call through.
const DeleteProgrammeConfirm = ({ open, programme, onClose, onDeleted, onError }) => {
  const [reason, setReason] = useStatePD("");
  const [submitting, setSubmitting] = useStatePD(false);
  React.useEffect(() => { if (open) setReason(""); }, [open]);
  if (!open || !programme) return null;
  const isDraft = programme.status === "draft";

  const fire = async () => {
    setSubmitting(true);
    try {
      await nsrApi.delete(`/api/v1/programmes/${programme.id}/`);
      setSubmitting(false);
      onDeleted();
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || JSON.stringify(err.body))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Delete draft ${programme.code}?`} size="sm">
      {!isDraft && (
        <div className="callout" style={{
          background:"var(--accent-danger-bg)", color:"var(--accent-danger)",
          padding:"10px 12px", borderRadius:4, marginBottom:12, fontSize:13,
        }}>
          <strong>Programme is not in draft.</strong> Hard-delete is
          disabled — use Close instead so the lifecycle + audit chain
          survives.
        </div>
      )}
      <p className="t-bodysm" style={{margin:"4px 0 12px"}}>
        Hard-deletes the draft. No enrolments or sign-offs exist for a
        draft, so the cascade is clean.
      </p>
      <Field label="Reason (audit only)">
        <textarea value={reason} onChange={e => setReason(e.target.value)}
                  rows={2} disabled={submitting}
                  placeholder="e.g. draft created in error, replaced by US-180 partner."/>
      </Field>
      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button
          className="btn"
          style={{background:"var(--accent-danger)", color:"white", borderColor:"var(--accent-danger)"}}
          onClick={fire} disabled={!isDraft || submitting || !reason.trim()}
        >
          {submitting ? "Deleting…" : "Delete draft"}
        </button>
      </div>
    </Modal>
  );
};


/* ============================================================
   Tab bodies
   ============================================================ */
const PdOverview = ({ p }) => (
  <div>
    <PD_TabHeader title="Overview" sub="Snapshot of programme configuration. Open any tab below for the full record."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <PD_KVCard title="Programme" rows={[
        ["Code",       <span className="t-mono">{p.code}</span>],
        ["Kind",       <Chip size="sm" tone={KIND_TONE[p.kind]}>{KIND_LABEL[p.kind]}</Chip>],
        ["Unit",       UNIT_LABEL[p.unit]],
        ["Cycle",      p.cycle],
        ["Start",      p.startDate],
        ["End",        p.endDate],
      ]}/>
      <PD_KVCard title="Partner" tint="programme" rows={[
        ["Partner",    p.partnerName],
        ["Partner code", <span className="t-mono">{p.partner}</span>],
        ["Lead",       p.partnerLead],
        ["DSA",        <span className="t-mono">{p.dsa}</span>],
        ["DSA expiry", `${p.dsaExpiresIn} days`],
        ["DSA ceiling", p.dsaCeiling],
      ]}/>
      <PD_KVCard title="Cohort & money" tint="data" rows={[
        ["Cohort target",  num(p.cohortTarget)],
        ["Currently enrolled", num(p.enrolled)],
        ["Exited",         num(p.exited)],
        ["Per cycle",      ugx(p.perCycleUgx)],
        ["YTD disbursement", ugx(p.ytdUgx)],
        ["Cycles 2026",    `${p.schedule.cyclesCompleted} of ${p.schedule.cyclesThisYear} complete`],
      ]}/>
      <PD_KVCard title="Description" rows={[
        ["Summary",        <span className="t-bodysm">{p.summary}</span>],
      ]}/>
    </div>
  </div>
);

const PdEligibility = ({ p }) => (
  <div>
    <PD_TabHeader title="Eligibility rules" sub="The targeting expression compiled into the partner MIS query. Edits open an amendment that re-runs the cohort estimate."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:16}}>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}>
          <strong>Targeting filters</strong>
          <div className="t-cap">Expression evaluated against the live registry on every cycle.</div>
        </div>
        <div style={{padding:16, display:'grid', gridTemplateColumns:'160px 1fr', rowGap:10, fontSize:13}}>
          <div className="muted">PMT bands</div>
          <div className="row-wrap">{p.eligibility.pmtBands.map(b => <Chip key={b} size="sm" tone="eligibility">{b}</Chip>)}</div>

          <div className="muted">Sex</div>
          <div>{p.eligibility.sex === "any" ? <Chip size="sm">Any</Chip> : <Chip size="sm">{p.eligibility.sex}</Chip>}</div>

          <div className="muted">Age band</div>
          <div><Chip size="sm">{p.eligibility.ageBand}</Chip></div>

          <div className="muted">Disability</div>
          <div>{p.eligibility.disability === "any" ? <Chip size="sm">Any</Chip> : <Chip size="sm">{p.eligibility.disability}</Chip>}</div>

          <div className="muted">PMT recency</div>
          <div><Chip size="sm" tone="data">{p.eligibility.requirePmtRecency}</Chip></div>

          <div className="muted">Consent required</div>
          <div>{p.eligibility.requireConsent
            ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> Yes</Chip>
            : <Chip size="sm" tone="danger">No</Chip>}</div>

          <div className="muted">Excludes programme</div>
          <div className="row-wrap">{p.eligibility.excludeProgrammes.map(c => <Chip key={c} size="sm" tone="quality">{c}</Chip>)}</div>
        </div>
        <div style={{borderTop:'1px solid var(--neutral-200)', padding:16}}>
          <strong className="t-bodysm">Additional rules</strong>
          <ul style={{margin:'8px 0 0 18px', padding:0, fontSize:13, color:'var(--neutral-700)'}}>
            {p.eligibility.additionalRules.map((r, i) => <li key={i} style={{marginBottom:4}}>{r}</li>)}
          </ul>
        </div>
      </div>
      <div className="tint-update" style={{padding:14, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
        <div className="row gap-2" style={{marginBottom:6}}>
          <Icon name="shield" size={14} color="var(--accent-update)"/>
          <strong className="t-bodysm">Amendment lifecycle</strong>
        </div>
        <p className="t-bodysm muted" style={{margin:0, lineHeight:1.55}}>
          Changing any rule opens an Amendment ChangeRequest. The amendment shows the projected
          cohort impact (estimated new size, planned-in / planned-out members), and is gated by
          the same 4-step sign-off chain as the original programme.
        </p>
      </div>
    </div>
  </div>
);

const PdSchedule = ({ p }) => (
  <div>
    <PD_TabHeader title="Schedule & disbursement"
      sub={`${p.cycle} cycle · ${p.schedule.cyclesCompleted} of ${p.schedule.cyclesThisYear} cycles complete this calendar year.`}
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export tranches</button>}/>
    <div style={{padding:20}}>
      <div className="row-wrap" style={{marginBottom:16}}>
        <PD_Stat label="Next cycle"        value={p.schedule.nextCycleStart} tint="update" sub={`${p.cycle.toLowerCase()} cadence`}/>
        <PD_Stat label="Per cycle"         value={ugx(p.perCycleUgx)}        tint="data"   sub="per household"/>
        <PD_Stat label="YTD disbursement"  value={ugx(p.ytdUgx)}             tint="programme"/>
        <PD_Stat label="Cycles 2026"       value={`${p.schedule.cyclesCompleted} / ${p.schedule.cyclesThisYear}`} tint="eligibility" sub="completed / planned"/>
      </div>

      <table className="tbl">
        <thead><tr><th>Tranche</th><th>Window</th><th>Households</th><th>Amount</th><th>Status</th></tr></thead>
        <tbody>
          {[...p.schedule.completedTranches, ...p.schedule.plannedTranches].map(t => (
            <tr key={t.id}>
              <td className="t-mono">{t.id}</td>
              <td className="t-cap">{t.window}</td>
              <td className="t-num">{num(t.count)}</td>
              <td className="t-bodysm">{ugx(t.disbursed || t.planned)}</td>
              <td>
                {t.status === "Disbursed" && <Chip size="sm" tone="data"><Icon name="check" size={10}/> {t.status}</Chip>}
                {t.status === "Disbursing" && <Chip size="sm" tone="update">{t.status}</Chip>}
                {t.status === "Planned" && <Chip size="sm">{t.status}</Chip>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const PdGeography = ({ p }) => {
  const allSubregions = ["Karamoja","West Nile","Acholi","Teso","Lango","Bunyoro","Buganda South","Busoga","Tooro","Ankole","Kigezi","Buganda North","Bukedi","Sebei"];
  return (
    <div>
      <PD_TabHeader title="Geography & DSA scope"
        sub={`Programme operates in ${p.geo.length} of 14 sub-regions. DSA-bounded — adding a new sub-region requires a DSA amendment.`}/>
      <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
        <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
          <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}>
            <strong>In-scope sub-regions</strong>
            <div className="t-cap">{p.geo.length} of 14</div>
          </div>
          <div style={{padding:16, display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
            {allSubregions.map(s => {
              const inScope = p.geo.includes(s);
              return (
                <div key={s} style={{
                  display:'flex', alignItems:'center', gap:8,
                  padding:'8px 10px', borderRadius:4,
                  background: inScope ? 'var(--accent-data-bg, var(--neutral-50))' : 'transparent',
                  border:'1px solid',
                  borderColor: inScope ? 'var(--accent-data)' : 'var(--neutral-200)',
                }}>
                  <Icon name={inScope ? "check" : "x"} size={12} color={inScope ? "var(--accent-data)" : "var(--neutral-400)"}/>
                  <span className="t-bodysm" style={{
                    color: inScope ? 'var(--neutral-900)' : 'var(--neutral-500)',
                    fontWeight: inScope ? 500 : 400,
                  }}>{s}</span>
                </div>
              );
            })}
          </div>
        </div>
        <PD_KVCard title="DSA ceiling" tint="programme" rows={[
          ["DSA reference",  <span className="t-mono">{p.dsa}</span>],
          ["Ceiling",        p.dsaCeiling],
          ["Sub-regions allowed", `${p.geo.length} of 14`],
          ["Entity",         UNIT_LABEL[p.unit]],
          ["Expires in",     `${p.dsaExpiresIn} days`],
          ["Renewal owner",  p.partnerLead],
        ]}/>
      </div>
    </div>
  );
};

const PdEnrolment = ({ p, onOpenHousehold }) => (
  <div>
    <PD_TabHeader title="Enrolment"
      sub={`${num(p.enrolled)} currently active · ${num(p.exited)} exits to date. Click any row to open the household record.`}
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export full roster</button>}/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
          <strong>Recent enrolments</strong>
          <span className="t-cap">latest 5</span>
        </div>
        <table className="tbl" style={{boxShadow:'none'}}>
          <thead><tr><th>Household</th><th>Head</th><th>Sub-region</th><th>Enrolled</th></tr></thead>
          <tbody>
            {p.enrolment.recentEnrolled.map(r => (
              <tr key={r.id} style={{cursor:'pointer'}} onClick={() => onOpenHousehold?.(r.id)}>
                <td className="col-id">{r.id.slice(0, 16)}…</td>
                <td>{r.head}</td>
                <td className="t-bodysm">{r.subreg} · {r.district}</td>
                <td className="t-cap" style={{whiteSpace:'nowrap'}}>{r.enrolledAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
          <strong>Recent exits</strong>
          <span className="t-cap">latest 3</span>
        </div>
        <table className="tbl" style={{boxShadow:'none'}}>
          <thead><tr><th>Household</th><th>Head</th><th>Reason</th><th>Exited</th></tr></thead>
          <tbody>
            {p.enrolment.recentExits.map(r => (
              <tr key={r.id} style={{cursor:'pointer'}} onClick={() => onOpenHousehold?.(r.id)}>
                <td className="col-id">{r.id.slice(0, 16)}…</td>
                <td>{r.head}</td>
                <td className="t-bodysm">{r.reason}</td>
                <td className="t-cap" style={{whiteSpace:'nowrap'}}>{r.exitedAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  </div>
);

const PdLifecycle = ({ p }) => (
  <div>
    <PD_TabHeader title="Lifecycle events" sub="Recent webhook events received from the partner MIS. Programme-scoped slice of the global event stream."
      action={<button className="btn btn-sm"><Icon name="refresh" size={13}/> Refresh</button>}/>
    <div style={{padding:0}}>
      <table className="tbl">
        <thead><tr><th>When</th><th>Event</th><th>Volume</th><th>Status</th></tr></thead>
        <tbody>
          {p.webhookEvents.map((e, i) => (
            <tr key={i}>
              <td className="t-cap" style={{whiteSpace:'nowrap'}}>{e.time}</td>
              <td className="t-mono" style={{fontSize:12.5}}>{e.evt}</td>
              <td className="t-bodysm">{e.count}</td>
              <td>
                {e.status === "ok"   && <Chip size="sm" tone="data"><Icon name="check" size={10}/> ok</Chip>}
                {e.status === "warn" && <Chip size="sm" tone="quality"><Icon name="alert" size={10}/> retry</Chip>}
                {e.status === "err"  && <Chip size="sm" tone="danger">error</Chip>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="t-cap" style={{padding:'10px 20px', borderTop:'1px solid var(--neutral-200)', background:'var(--neutral-50)'}}>
        Event types: <span className="t-mono">enrolment.activated</span>, <span className="t-mono">enrolment.suspended</span>, <span className="t-mono">payment.disbursed</span>, <span className="t-mono">member.exited</span>, <span className="t-mono">webhook.retry</span>. Full schema: <span className="t-mono">/api/v1/webhooks/programme.events</span>.
      </div>
    </div>
  </div>
);

const PdIntegration = ({ p }) => (
  <div>
    <PD_TabHeader title="Integration"
      sub="Partner-MIS webhook receiver and credentials. Rotate the secret if it leaks."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:16}}>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
          <div>
            <strong>Webhook receiver</strong>
            <div className="t-cap">Inbound events from partner MIS</div>
          </div>
          <WebhookPip health={p.webhookHealth} lastSync={p.lastSync}/>
        </div>
        <div style={{padding:16, display:'grid', gridTemplateColumns:'160px 1fr', rowGap:10, fontSize:13}}>
          <div className="muted">URL</div>
          <div className="t-mono" style={{wordBreak:'break-all'}}>{p.webhookUrl}</div>
          <div className="muted">Secret</div>
          <div className="row gap-2">
            <span className="t-mono">{p.webhookSecret}</span>
            <button className="btn btn-sm btn-ghost"><Icon name="refresh" size={11}/> Rotate</button>
          </div>
          <div className="muted">Method</div>
          <div className="t-mono">POST · HMAC-SHA256 signed</div>
          <div className="muted">Timeout</div>
          <div>30 s · 3 retries with exponential backoff</div>
          <div className="muted">24h success rate</div>
          <div><Chip size="sm" tone={p.successRate24h >= 99 ? "data" : p.successRate24h >= 95 ? "update" : "quality"}>{p.successRate24h}%</Chip></div>
          <div className="muted">Last sync</div>
          <div>{p.lastSync}</div>
        </div>
        <div style={{borderTop:'1px solid var(--neutral-200)', padding:16, display:'flex', gap:10}}>
          <button className="btn"><Icon name="play" size={13}/> Test connection</button>
          <button className="btn"><Icon name="download" size={13}/> Download spec</button>
        </div>
      </div>
      <div className="tint-update" style={{padding:14, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
        <div className="row gap-2" style={{marginBottom:6}}>
          <Icon name="shield" size={14} color="var(--accent-update)"/>
          <strong className="t-bodysm">Security note</strong>
        </div>
        <p className="t-bodysm muted" style={{margin:0, lineHeight:1.55}}>
          All inbound webhook payloads must be HMAC-signed with the secret above and include a
          timestamp within ±5 minutes of NSR clock. Replays are rejected. Secret rotation
          requires partner notification — schedule a rotation window first.
        </p>
      </div>
    </div>
  </div>
);

const PdGrievances = ({ p }) => (
  <div>
    <PD_TabHeader title="Grievances" sub={`${p.grievances.open} open · ${p.grievances.total - p.grievances.open} resolved / closed`}
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> File grievance</button>}/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1.4fr', gap:16}}>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}>
          <strong>By escalation level</strong>
        </div>
        <div style={{padding:'8px 0'}}>
          {p.grievances.breakdown.map(b => {
            const max = Math.max(...p.grievances.breakdown.map(x => x.count));
            return (
              <div key={b.level} style={{padding:'8px 16px', display:'grid', gridTemplateColumns:'140px 1fr 40px', gap:12, alignItems:'center'}}>
                <span className="t-bodysm">{b.level}</span>
                <div style={{height:6, background:'var(--neutral-100)', borderRadius:3, overflow:'hidden'}}>
                  <div style={{width:`${(b.count/max)*100}%`, height:'100%', background:'var(--accent-quality)'}}/>
                </div>
                <span className="t-num t-bodysm" style={{textAlign:'right', fontWeight:600}}>{b.count}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}>
          <strong>Recent cases</strong>
        </div>
        <table className="tbl" style={{boxShadow:'none'}}>
          <thead><tr><th>Case</th><th>Title</th><th>Level</th><th>Status</th></tr></thead>
          <tbody>
            {p.grievances.recent.map(g => (
              <tr key={g.id} style={{cursor:'pointer'}}>
                <td className="col-id">{g.id}</td>
                <td className="t-bodysm">{g.title}</td>
                <td><Chip size="sm">{g.level}</Chip></td>
                <td>
                  {g.status === "Resolved" && <Chip size="sm" tone="data">{g.status}</Chip>}
                  {g.status === "In progress" && <Chip size="sm" tone="update">{g.status}</Chip>}
                  {g.status === "Open" && <Chip size="sm" tone="quality">{g.status}</Chip>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  </div>
);

const PdAudit = ({ p }) => (
  <div>
    <PD_TabHeader title="Sign-off & audit chain" sub="Tamper-evident programme record — sign-off chain, amendments, and the full audit event stream."/>
    {/* Sign-off chain */}
    <div style={{padding:20, borderBottom:'1px solid var(--neutral-200)'}}>
      <h4 className="t-h3" style={{margin:'0 0 12px'}}>Sign-off chain</h4>
      <div className="row gap-3" style={{flexWrap:'wrap'}}>
        {p.signoff.map(s => (
          <div key={s.step} style={{
            flex:'1 1 220px', minWidth:200,
            padding:14, borderRadius:6,
            border:'1px solid var(--neutral-200)',
            borderLeft:'3px solid var(--accent-data)',
            background:'var(--neutral-0)',
          }}>
            <div className="row gap-2" style={{marginBottom:6}}>
              <div style={{
                width:22, height:22, borderRadius:'50%',
                background:'var(--accent-data-bg, var(--neutral-100))',
                color:'var(--accent-data)',
                display:'grid', placeItems:'center', fontSize:11, fontWeight:600,
              }}>{s.step}</div>
              <Chip size="sm" tone="data"><Icon name="check" size={10}/> signed</Chip>
            </div>
            <div className="t-bodysm" style={{fontWeight:600}}>{s.role}</div>
            <div className="t-cap mt-1">{s.who}</div>
            <div className="t-cap mt-1">{s.at}</div>
          </div>
        ))}
      </div>
    </div>

    {/* Amendments */}
    <div style={{padding:20, borderBottom:'1px solid var(--neutral-200)'}}>
      <h4 className="t-h3" style={{margin:'0 0 12px'}}>Amendments</h4>
      <table className="tbl" style={{boxShadow:'none'}}>
        <thead><tr><th>ID</th><th>Title</th><th>Requested by</th><th>Decided</th><th>Status</th></tr></thead>
        <tbody>
          {p.amendments.map(a => (
            <tr key={a.id}>
              <td className="col-id">{a.id}</td>
              <td className="t-bodysm">{a.title}</td>
              <td className="t-bodysm">{a.requestedBy}</td>
              <td className="t-cap">{a.decidedAt}</td>
              <td><Chip size="sm">{a.status}</Chip></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>

    {/* Audit events */}
    <div>
      <div style={{padding:'16px 20px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:12}}>
        <h4 className="t-h3" style={{margin:0}}>Audit events</h4>
        <div style={{flex:1}}/>
        <select className="field-select btn-sm" style={{height:30, width:160}}><option>All actions</option><option>Sign</option><option>Amend</option><option>View</option></select>
        <button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>
      </div>
      {p.audit.map((e, i) => (
        <div key={i} style={{padding:'14px 20px', display:'flex', gap:14, alignItems:'flex-start', borderBottom:'1px solid var(--neutral-200)'}}>
          <div style={{
            width:32, height:32, borderRadius:'50%',
            background: e.tone === 'system' ? 'var(--neutral-200)' : 'var(--primary-100)',
            color: e.tone === 'system' ? 'var(--neutral-700)' : 'var(--primary-900)',
            display:'grid', placeItems:'center', fontSize:11, fontWeight:600, flex:'0 0 auto',
          }}>{e.who.split(' ').map(w => w[0]).slice(0, 2).join('')}</div>
          <div style={{flex:1, minWidth:0}}>
            <div style={{display:'flex', alignItems:'baseline', gap:8, flexWrap:'wrap'}}>
              <strong>{e.who}</strong>
              <span className="t-cap">{e.role}</span>
              <span className="t-cap">·</span>
              <span className="t-bodysm">{e.action}</span>
            </div>
            <div className="t-cap mt-1" style={{color:'var(--neutral-600)'}}>{e.detail}</div>
            <div className="t-cap mt-1 t-mono" style={{color:'var(--neutral-500)'}}>{e.audit}</div>
          </div>
          <div className="t-cap" style={{flex:'0 0 auto', whiteSpace:'nowrap'}}>{e.time}</div>
        </div>
      ))}
    </div>
  </div>
);

Object.assign(window, { ProgrammeDetailScreen });
