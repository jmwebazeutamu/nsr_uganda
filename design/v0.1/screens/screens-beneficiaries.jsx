/* global React, Icon, Chip, PageHeader, KPI, Toast, TweaksPanel, TweakSection, TweakToggle, TweakRadio, useTweaks, useChoiceList, useApi */
// NSR MIS — Beneficiary registry (US-180 / US-S25-007 / US-S26-007)
//
// Distinct from the household registry:
//   • Household Registry  → universe of households surveyed in NSR (PMT + identity).
//   • Beneficiary Registry → subset *enrolled in a programme* with its own
//                            active / suspended / pending / exited lifecycle,
//                            cohort, payment ledger, and exit reasons.
//
// One row = one (entity, programme) enrolment record. The same household may
// appear in two programmes; exits are recorded per-programme.
//
// Wiring:
//   • Status segmented tabs read from `programme_enrolment_status` ChoiceList
//   • Programme rollup cards read /api/v1/programmes/?status=active
//   • Unit filter reads `programme_unit_of_enrolment` ChoiceList
//   • Exit-reason chart reads `programme_exit_reason` ChoiceList
//   • Sub-region filter reads /api/v1/reference-data/geographic-units/
//     (level=sub_region)
//   • **Beneficiary rows feed from /api/v1/beneficiaries/ (US-S26-006)** —
//     ABAC-scoped server-side; the apiClient hook fires one request
//     with page_size=500 so the table, KPIs, and per-programme rollup
//     all derive from the same response. A dedicated aggregate endpoint
//     replaces this approach at production scale (OI-S26-5).

const { useState: useStateBen, useMemo: useMemoBen } = React;

/* ============================================================
   UI tone maps — presentation only, NOT code lists.
   The codes themselves come from the ChoiceLists; these maps
   just paint the chip the right colour. Add a new status to
   the ChoiceList and add one line here.
   ============================================================ */
// UI-only mappings from enrolment-status codes (sourced from the
// programme_enrolment_status ChoiceList) to chip tone, icon glyph,
// and one-line sub-text. Add a new status to the ChoiceList and
// add one line to each of these maps.
const ENROL_STATUS_TONE = {
  active:    "data",
  suspended: "quality",
  pending:   "update",
  exited:    "neutral",
};
const ENROL_STATUS_ICON = {
  active:    "checkCircle",
  suspended: "alert",
  pending:   "clock",
  exited:    "arrowRight",
};
const ENROL_STATUS_SUB = {
  active:    "currently receiving",
  suspended: "compliance hold",
  pending:   "awaiting first pay",
  exited:    "left the programme",
};

const EXIT_TONE = {
  "10": "data",        // graduated
  "20": "update",      // transferred
  "30": "neutral",     // deceased
  "40": "quality",     // migrated lost
  "50": "eligibility", // re-targeted out
  "60": "identity",    // withdrew consent
  "70": "neutral",     // programme closed
  "80": "danger",      // non-compliance
  "99": "neutral",     // other
};

// Per-partners.Programme.kind tone (used until partners.Programme
// gains an explicit `tone` choice list). Codes match the canonical
// programme_kind ChoiceList.
const KIND_TONE = {
  cash_transfer: "data",
  service:       "identity",
  in_kind:       "quality",
  voucher:       "update",
  study:         "programme",
  grant:         "programme",
  subsidy:       "eligibility",
};

/* ============================================================
   API → render-shape mapper.
   The endpoint at /api/v1/beneficiaries/ (US-S26-006) returns
   snake_case rows; the screen body still references the legacy
   camelCase shape so we normalise here at the boundary instead
   of touching every td. Update this mapper if either side moves.
   ============================================================ */
const _mapApiRow = (r) => ({
  id:            r.id,
  rid:           r.household_id,
  entity:        r.household_head_name || "—",
  unit:          r.unit_of_enrolment || "household",
  hh:            r.household_size || 0,
  sex:           r.household_sex || "",
  district:      r.district || "",
  parish:        r.parish || "",
  subreg:        r.sub_region_name || "",
  progCode:      r.programme_code || r.programme_id || "—",
  cohort:        r.cohort || "",
  status:        r.status,
  enrolledAt:    r.enrolled_at || "",
  monthsIn:      r.months_in || 0,
  lastPayAt:     r.last_pay_at || "—",
  lastPayAmt:    r.last_pay_amt || 0,
  totalPaid:     r.total_paid || 0,
  nextPayAt:     r.next_pay_at || "",
  channel:       r.channel || "",
  exitedAt:      r.exited_at || "",
  exitCode:      r.exit_code || "",
  exitNote:      r.exit_note || "",
  suspendReason: r.suspend_reason || "",
  suspendAt:     r.suspend_at || "",
  pmt:           r.pmt_score,
  note:          r.note || "",
});

/* ============================================================
   helpers
   ============================================================ */
const fmtUGX = (n) => {
  if (n === 0 || n == null) return "—";
  if (n >= 1000000) return "UGX " + (n/1000000).toFixed(1) + "M";
  if (n >= 1000)    return "UGX " + (n/1000).toFixed(0) + "k";
  return "UGX " + n;
};

const BEN_TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "showProgrammeStrip": true,
  "showExitChart": true,
  "showPaymentSpark": true,
  "groupByProg": false
}/*EDITMODE-END*/;

const labelOf = (opts, code, fallback = "—") => {
  const o = opts.find(x => x.code === code);
  return o ? o.label : fallback;
};

/* ============================================================
   BENEFICIARIES SCREEN
   ============================================================ */
const BeneficiariesScreen = ({ onOpenHousehold, onNewProgramme }) => {
  /* ---- ChoiceLists (every coded selector reads from the DB) ---- */
  const [, { allLists: cl }] = useChoiceList([
    "programme_enrolment_status",
    "programme_unit_of_enrolment",
    "programme_exit_reason",
  ]);
  const statusOpts = cl.programme_enrolment_status   || [];
  const unitOpts   = cl.programme_unit_of_enrolment  || [];
  const exitOpts   = cl.programme_exit_reason        || [];

  /* ---- Live data ---- */
  const [partnerProgrammesResp] = useApi("/api/v1/programmes/?status=active");
  const livePartnerProgrammes = (partnerProgrammesResp && partnerProgrammesResp.results) || [];

  const [geoResp] = useApi("/api/v1/reference-data/geographic-units/");
  const subRegions = useMemoBen(
    () => ((geoResp && geoResp.results) || [])
      .filter(g => g.level === "sub_region")
      .map(g => g.name)
      .sort(),
    [geoResp],
  );

  /* ---- Local state ---- */
  // Default the status tab to the first ChoiceList entry; the
  // initialiser falls back to "active" until the bundle arrives.
  const [statusTab, setStatusTab] = useStateBen("active");
  const [q, setQ]                 = useStateBen("");
  const [progCode, setProgCode]   = useStateBen("");
  const [subreg, setSubreg]       = useStateBen("");
  const [unit, setUnit]           = useStateBen("");
  const [exitCode, setExitCode]   = useStateBen("");
  const [cohort, setCohort]       = useStateBen("");
  const [sortBy, setSortBy]       = useStateBen("recent");
  const [page, setPage]           = useStateBen(0);
  const [toast, setToast]         = useStateBen("");
  const pageSize = 10;

  const [t, setTweak] = (typeof useTweaks === 'function' ? useTweaks(BEN_TWEAK_DEFAULTS) : [BEN_TWEAK_DEFAULTS, () => {}]);

  /* ---- Live beneficiaries feed ----
     Single fetch with page_size large enough to serve both the
     filterable table and the per-programme rollup tallies. The
     endpoint is ABAC-scoped server-side (US-S26-006); we still
     apply UI filters client-side so the table reflects the chips
     without re-fetching every keystroke. A dedicated aggregate
     endpoint replaces this approach at production scale. */
  const [beneficiariesResp, beneficiariesMeta] = useApi(
    "/api/v1/beneficiaries/?page_size=500",
  );
  const allRows = useMemoBen(
    () => ((beneficiariesResp && beneficiariesResp.results) || []).map(_mapApiRow),
    [beneficiariesResp],
  );

  /* ---- Compose programme list ----
     One card per live partners.Programme (US-S25-001 catalogue) +
     a fallback card per programme code that appears in beneficiary
     rows but isn't in the partners table yet (covers legacy
     GoU-LEGACY attributions from US-S26-004). */
  const programmesForRollup = useMemoBen(() => {
    const livePartial = livePartnerProgrammes.map(p => ({
      code: p.code || p.id.slice(0, 8),
      name: p.name,
      unit_label: labelOf(unitOpts, p.unit_of_enrolment, "—"),
      modality_label: p.kind_label || p.kind,
      tone: KIND_TONE[p.kind] || "programme",
      isLive: true,
    }));
    const codesInRows = Array.from(new Set(allRows.map(b => b.progCode)));
    const orphanCodes = codesInRows
      .filter(c => c && !livePartial.some(p => p.code === c))
      .map(c => {
        const sample = allRows.find(b => b.progCode === c);
        return {
          code: c, name: c, isLive: false,
          unit_label: labelOf(unitOpts, sample ? sample.unit : "", "—"),
          modality_label: "—",
          tone: "neutral",
        };
      });
    return [...livePartial, ...orphanCodes];
  }, [livePartnerProgrammes, unitOpts, allRows]);

  const PROG_BY_CODE = useMemoBen(
    () => Object.fromEntries(programmesForRollup.map(p => [p.code, p])),
    [programmesForRollup],
  );

  // Status counts — derived from the live feed.
  const counts = useMemoBen(() => {
    const c = {};
    statusOpts.forEach(s => { c[s.code] = 0; });
    allRows.forEach(b => { c[b.status] = (c[b.status] || 0) + 1; });
    return c;
  }, [allRows, statusOpts]);

  // Per-programme rollup — same source, client-side tally.
  const progRollup = useMemoBen(() => programmesForRollup.map(p => {
    const recs = allRows.filter(b => b.progCode === p.code);
    const tally = { active: 0, suspended: 0, pending: 0, exited: 0 };
    for (const r of recs) tally[r.status] = (tally[r.status] || 0) + 1;
    const paid = recs.reduce((acc, r) => acc + (r.totalPaid || 0), 0);
    return { ...p, ...tally, total: recs.length, paid };
  }), [programmesForRollup, allRows]);

  const rows = useMemoBen(() => {
    let r = allRows.filter(b => {
      if (statusTab && b.status !== statusTab) return false;
      if (q) {
        const hay = `${b.entity} ${b.rid} ${b.parish} ${b.district} ${b.id}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      if (progCode && b.progCode !== progCode) return false;
      if (subreg && b.subreg !== subreg) return false;
      if (unit && b.unit !== unit) return false;
      if (cohort && b.cohort !== cohort) return false;
      if (exitCode && b.exitCode !== exitCode) return false;
      return true;
    });
    if (sortBy === "recent")    r = [...r].sort((a,b) => (b.lastPayAt||b.enrolledAt).localeCompare(a.lastPayAt||a.enrolledAt));
    if (sortBy === "name")      r = [...r].sort((a,b) => a.entity.localeCompare(b.entity));
    if (sortBy === "paid")      r = [...r].sort((a,b) => (b.totalPaid||0) - (a.totalPaid||0));
    if (sortBy === "enrolled")  r = [...r].sort((a,b) => a.enrolledAt.localeCompare(b.enrolledAt));
    if (sortBy === "monthsIn")  r = [...r].sort((a,b) => (b.monthsIn||0) - (a.monthsIn||0));
    return r;
  }, [allRows, statusTab, q, progCode, subreg, unit, cohort, exitCode, sortBy]);

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const visible = rows.slice(page * pageSize, page * pageSize + pageSize);

  const reset = () => { setQ(""); setProgCode(""); setSubreg(""); setUnit(""); setCohort(""); setExitCode(""); setPage(0); };

  const cohorts = useMemoBen(
    () => [...new Set(allRows.filter(b => !progCode || b.progCode === progCode).map(b => b.cohort).filter(Boolean))].sort(),
    [allRows, progCode],
  );

  // KPIs
  const totalActive = counts.active || 0;
  const totalExited = counts.exited || 0;
  const exitRate    = totalExited / (totalActive + totalExited) || 0;
  const ytdPaid     = allRows.reduce((acc, r) => acc + (r.totalPaid || 0), 0);
  const pendingPay  = (counts.pending || 0) + (counts.suspended || 0);

  return (
    <div className="page">
      <PageHeader
        eyebrow="BENEFICIARY REGISTRY · REF module · SAD §5.1"
        title="Beneficiaries"
        sub={<>Per-programme enrolment ledger — one row = one <span className="t-mono">ProgrammeEnrolment</span>. Status reads <span className="t-mono">programme_enrolment_status</span>; pending shows in-flight <span className="t-mono">Referrals</span>.</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
          <button className="btn"><Icon name="arrowUp" size={14}/> Import enrolment list</button>
          <button className="btn" onClick={onNewProgramme}><Icon name="book" size={14}/> Add programme</button>
          <button className="btn btn-primary" onClick={() => setToast("Enrolment endpoint lands with OI-S25-4 (Sprint 26).")}><Icon name="plus" size={14}/> Enrol household</button>
        </>}
      />

      {/* Status banner — render only while the first fetch is in flight
          or when the server reported an error. Once data is back this
          slot collapses to nothing. */}
      {(beneficiariesMeta.loading || beneficiariesMeta.error) && (
        <div className="mt-3" style={{padding:"10px 14px", background: beneficiariesMeta.error ? "var(--accent-danger-bg)" : "var(--accent-update-bg)", borderLeft:`3px solid var(${beneficiariesMeta.error ? "--accent-danger" : "--accent-update"})`, borderRadius:4, display:"flex", alignItems:"center", gap:10}}>
          <Icon name={beneficiariesMeta.error ? "alert" : "clock"} size={14} color={`var(${beneficiariesMeta.error ? "--accent-danger" : "--accent-update"})`}/>
          <span className="t-bodysm" style={{color:"var(--neutral-900)"}}>
            {beneficiariesMeta.error
              ? <>Failed to load beneficiaries: <span className="t-mono">{beneficiariesMeta.error}</span></>
              : <>Loading beneficiaries from <span className="t-mono">/api/v1/beneficiaries/</span>…</>}
          </span>
        </div>
      )}

      {/* KPI grid */}
      <div className="grid grid-4 mt-4">
        <KPI title="Active enrolments"     value={totalActive.toLocaleString()}   foot={`${programmesForRollup.length} programmes tracked`} trend="up" trendValue="+34 this wk" spark={[3,4,5,5,6,6,7,8]}/>
        <KPI title="Exited (cum.)"         value={totalExited.toLocaleString()}   foot={`exit rate ${(exitRate*100).toFixed(1)}%`} spark={[1,1,2,2,3,4,5,6]}/>
        <KPI title="Disbursed · all-time"  value={"UGX " + (ytdPaid/1000000).toFixed(1) + "M"}   foot="Cash + vouchers" trend="up" trendValue="+UGX 1.2M wk" spark={[4,5,6,7,8,8,9,10]}/>
        <KPI title="Suspended / pending"   value={pendingPay.toLocaleString()}    foot="Awaiting action" trend="flat" spark={[2,2,2,3,3,3,3,3]}/>
      </div>

      {/* STATUS SEGMENTED TABS — driven by programme_enrolment_status */}
      <div className="card mt-5" style={{padding:0, overflow:'hidden'}}>
        <div style={{display:'grid', gridTemplateColumns:`repeat(${Math.max(statusOpts.length, 1)}, 1fr)`}}>
          {statusOpts.map((s, i) => {
            const active = s.code === statusTab;
            const tone = ENROL_STATUS_TONE[s.code] || "primary";
            const icon = ENROL_STATUS_ICON[s.code] || "circle";
            const sub = ENROL_STATUS_SUB[s.code] || "";
            const n = counts[s.code] || 0;
            return (
              <button key={s.code}
                onClick={() => { setStatusTab(s.code); setPage(0); setExitCode(""); }}
                style={{
                  textAlign:'left', cursor:'pointer',
                  padding:'16px 20px',
                  background: active ? `var(--accent-${tone}-bg, var(--primary-100))` : 'var(--neutral-0)',
                  border:0, borderRight: i < statusOpts.length - 1 ? '1px solid var(--neutral-200)' : 0,
                  borderBottom: active ? `3px solid var(--accent-${tone}, var(--primary-700))` : '3px solid transparent',
                  borderTop: '3px solid transparent',
                  display:'flex', flexDirection:'column', gap:6,
                }}>
                <div className="row gap-2">
                  <Icon name={icon} size={15} color={`var(--accent-${tone}, var(--neutral-700))`}/>
                  <span className="t-cap" style={{textTransform:'uppercase', letterSpacing:'0.08em', color: active ? `var(--accent-${tone})` : 'var(--neutral-500)', fontWeight:600}}>{s.label}</span>
                </div>
                <div style={{fontSize:28, fontWeight:700, letterSpacing:'-0.01em', color: active ? `var(--accent-${tone})` : 'var(--neutral-900)', fontVariantNumeric:'tabular-nums'}}>
                  {n.toLocaleString()}
                </div>
                <div className="t-cap">{sub}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* PROGRAMME ROLLUP STRIP */}
      {t.showProgrammeStrip && (
        <div className="mt-5">
          <div className="row gap-2" style={{marginBottom:8, alignItems:'baseline'}}>
            <strong className="t-h3">By programme</strong>
            <span className="t-cap">click a card to filter · {programmesForRollup.filter(p => p.isLive).length} live</span>
          </div>
          <div className="grid" style={{gridTemplateColumns:`repeat(auto-fill, minmax(180px, 1fr))`, gap:12}}>
            {progRollup.map(p => {
              const selected = progCode === p.code;
              return (
                <button key={p.code}
                  onClick={() => { setProgCode(selected ? "" : p.code); setPage(0); }}
                  style={{
                    textAlign:'left', cursor:'pointer', background:'var(--neutral-0)',
                    border:'1px solid var(--neutral-300)',
                    borderRadius:'var(--radius-card)',
                    borderLeft: `3px solid var(--accent-${p.tone})`,
                    boxShadow: selected ? '0 0 0 2px var(--primary-700)' : 'var(--card-shadow)',
                    padding:'12px 14px',
                    display:'flex', flexDirection:'column', gap:6, minHeight:0,
                    opacity: p.isLive ? 1 : 0.85,
                  }}>
                  <div className="row gap-2" style={{justifyContent:'space-between'}}>
                    <strong className="t-mono" style={{fontSize:11.5, color:`var(--accent-${p.tone})`, letterSpacing:'0.04em'}}>{p.code}</strong>
                    <span className="t-cap" style={{whiteSpace:'nowrap'}}>{p.unit_label}</span>
                  </div>
                  <div style={{fontWeight:600, fontSize:12.5, lineHeight:1.3, color:'var(--neutral-900)', overflow:'hidden', display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical'}}>{p.name}</div>
                  <StatusStackBar active={p.active} susp={p.suspended} pend={p.pending} exited={p.exited}/>
                  <div className="row gap-2" style={{justifyContent:'space-between', marginTop:2}}>
                    <span className="t-cap"><span style={{color:'var(--accent-data)', fontWeight:600}}>{p.active}</span> act · {p.exited} ex</span>
                    <span className="t-cap t-mono" style={{fontSize:11.5}}>{p.total} total</span>
                  </div>
                  {!p.isLive && <span className="t-cap" style={{fontSize:10, color:'var(--neutral-500)'}}>preview · not yet in partners.Programme</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* EXIT REASON CHART — only when on Exited tab */}
      {statusTab === "exited" && t.showExitChart && (
        <ExitReasonRollup
          rows={DEMO_BENEFICIARIES.filter(b => b.status === "exited" && (!progCode || b.progCode === progCode))}
          exitOpts={exitOpts}
          selected={exitCode}
          onSelect={(c) => { setExitCode(exitCode === c ? "" : c); setPage(0); }}
        />
      )}

      {/* FILTER BAR */}
      <div className="card mt-4" style={{padding:'12px 14px'}}>
        <div className="row gap-3" style={{flexWrap:'wrap'}}>
          <div className="search" style={{maxWidth:340, height:34, background:'var(--neutral-0)'}}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Search beneficiary, Registry ID, parish…"/>
          </div>
          <select className="field-select" style={{height:34, width:'auto', minWidth:170}} value={progCode} onChange={(e) => { setProgCode(e.target.value); setCohort(""); setPage(0); }}>
            <option value="">Any programme</option>
            {programmesForRollup.map(p => <option key={p.code} value={p.code}>{p.code} — {p.name}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:130}} value={unit} onChange={(e) => { setUnit(e.target.value); setPage(0); }}>
            <option value="">Any unit</option>
            {unitOpts.map(u => <option key={u.code} value={u.code}>{u.label}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:160}} value={subreg} onChange={(e) => { setSubreg(e.target.value); setPage(0); }}>
            <option value="">Any sub-region</option>
            {subRegions.map(s => <option key={s}>{s}</option>)}
          </select>
          {progCode && (
            <select className="field-select" style={{height:34, width:'auto', minWidth:150}} value={cohort} onChange={(e) => { setCohort(e.target.value); setPage(0); }}>
              <option value="">Any cohort</option>
              {cohorts.map(c => <option key={c}>{c}</option>)}
            </select>
          )}
          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost" onClick={reset}><Icon name="x" size={13}/> Reset</button>
          <div style={{width:1, height:24, background:'var(--neutral-200)'}}/>
          <span className="t-cap">Sort:</span>
          <select className="field-select" style={{height:30, width:'auto'}} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="recent">Most recent activity</option>
            <option value="enrolled">Enrolled (oldest first)</option>
            <option value="name">Name (A→Z)</option>
            <option value="paid">Total disbursed (high→low)</option>
            <option value="monthsIn">Months in programme</option>
          </select>
        </div>
        {(q || progCode || subreg || unit || cohort || exitCode) && (
          <div className="row gap-2 mt-3" style={{flexWrap:'wrap'}}>
            <span className="t-cap">Active filters:</span>
            {q && <Chip size="sm">"{q}" <button onClick={() => setQ("")} style={{marginLeft:4, border:0, background:'transparent', cursor:'pointer'}}>×</button></Chip>}
            {progCode && <Chip size="sm" tone={PROG_BY_CODE[progCode]?.tone || 'programme'}>{progCode} <button onClick={() => setProgCode("")} style={{marginLeft:4, border:0, background:'transparent', cursor:'pointer'}}>×</button></Chip>}
            {unit && <Chip size="sm">unit · {labelOf(unitOpts, unit, unit)}</Chip>}
            {subreg && <Chip size="sm">{subreg}</Chip>}
            {cohort && <Chip size="sm">{cohort}</Chip>}
            {exitCode && <Chip size="sm" tone={EXIT_TONE[exitCode] || 'neutral'}>{labelOf(exitOpts, exitCode, exitCode)}</Chip>}
          </div>
        )}
      </div>

      {/* RESULTS TABLE */}
      <div className="card mt-4">
        <div className="card-toolbar">
          <strong className="t-bodysm">{rows.length.toLocaleString()} {labelOf(statusOpts, statusTab, statusTab).toLowerCase()} enrolment{rows.length === 1 ? '' : 's'}</strong>
          <span className="t-cap">Page {page+1} of {totalPages} · click any row to open the household</span>
          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost"><Icon name="sliders" size={14}/> Columns</button>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Enrolment</th>
              <th>Beneficiary</th>
              <th>Programme · Cohort</th>
              <th>Location</th>
              {statusTab === "active"    && <><th>Months in</th><th style={{textAlign:'right'}}>Last paid</th><th>Next pay</th></>}
              {statusTab === "suspended" && <><th>Suspended on</th><th>Hold reason</th><th>Months in</th></>}
              {statusTab === "pending"   && <><th>Awaiting</th><th>Channel / blocker</th><th>Enrolled</th></>}
              {statusTab === "exited"    && <><th>Exited on</th><th>Reason</th><th style={{textAlign:'right'}}>Total paid</th></>}
              <th>Status</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr><td colSpan="9">
                <div className="center" style={{padding:48, flexDirection:'column', gap:8, color:'var(--neutral-500)'}}>
                  <Icon name="inbox" size={28} color="var(--neutral-300)"/>
                  <strong className="t-body">No {labelOf(statusOpts, statusTab, statusTab).toLowerCase()} enrolments match these filters.</strong>
                  <button className="btn btn-sm" onClick={reset}>Reset filters</button>
                </div>
              </td></tr>
            )}
            {visible.map(b => {
              const progMeta = PROG_BY_CODE[b.progCode];
              const exitLabel = labelOf(exitOpts, b.exitCode, b.exitCode);
              const exitTone = EXIT_TONE[b.exitCode] || "neutral";
              return (
                <tr key={b.id} onClick={() => onOpenHousehold?.(b.rid)} style={{cursor:'pointer'}}>
                  <td>
                    <div className="col-id">{b.id}</div>
                    <div className="t-cap t-mono" style={{fontSize:11}}>{b.rid.slice(0,16)}…</div>
                  </td>
                  <td>
                    <div className="row gap-3">
                      <div style={{width:28, height:28, borderRadius:'50%', background:'var(--primary-100)', color:'var(--primary-900)', display:'grid', placeItems:'center', fontSize:11, fontWeight:600}}>
                        {b.entity.split(' ').filter(w => /^[A-Za-z]/.test(w)).slice(0,2).map(w => w[0]).join('')}
                      </div>
                      <div style={{minWidth:0}}>
                        <div style={{fontWeight:500}}>{b.entity}</div>
                        <div className="t-cap">{labelOf(unitOpts, b.unit, b.unit)} · HH {b.hh}{b.sex ? ` · ${b.sex}` : ''}{b.age != null ? ` · age ${b.age}` : ''}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="row gap-2">
                      <Chip size="sm" tone={progMeta?.tone || 'programme'}>{b.progCode}</Chip>
                    </div>
                    <div className="t-cap mt-1" style={{marginTop:2}}>{b.cohort}</div>
                  </td>
                  <td>
                    <div className="t-bodysm">{b.parish} · {b.district}</div>
                    <div className="t-cap">{b.subreg}</div>
                  </td>

                  {/* status-specific columns */}
                  {statusTab === "active" && (
                    <>
                      <td className="t-num"><MonthsBar months={b.monthsIn}/></td>
                      <td style={{textAlign:'right'}}>
                        <div className="t-mono" style={{fontSize:12.5}}>{fmtUGX(b.lastPayAmt)}</div>
                        <div className="t-cap">{b.lastPayAt}</div>
                      </td>
                      <td>
                        <div className="t-bodysm">{b.nextPayAt}</div>
                        <div className="t-cap" style={{maxWidth:180, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{b.channel}</div>
                      </td>
                    </>
                  )}
                  {statusTab === "suspended" && (
                    <>
                      <td className="t-cap">{b.suspendAt}</td>
                      <td style={{maxWidth:320}}>
                        <div className="t-bodysm" style={{lineHeight:1.4, color:'var(--neutral-900)'}}>{b.suspendReason}</div>
                      </td>
                      <td className="t-num"><MonthsBar months={b.monthsIn}/></td>
                    </>
                  )}
                  {statusTab === "pending" && (
                    <>
                      <td><Chip size="sm" tone="update">first pay {b.nextPayAt}</Chip></td>
                      <td style={{maxWidth:320}}><div className="t-bodysm">{b.channel}</div>{b.note && <div className="t-cap mt-1">{b.note}</div>}</td>
                      <td className="t-cap">{b.enrolledAt}</td>
                    </>
                  )}
                  {statusTab === "exited" && (
                    <>
                      <td>
                        <div className="t-bodysm">{b.exitedAt}</div>
                        <div className="t-cap">enrolled {b.enrolledAt}</div>
                      </td>
                      <td style={{maxWidth:360}}>
                        <div className="row gap-2" style={{marginBottom:2}}>
                          <Chip size="sm" tone={exitTone}>{(b.exitCode || "").padStart(2,'0')} · {exitLabel}</Chip>
                        </div>
                        <div className="t-cap" style={{lineHeight:1.4}}>{b.exitNote}</div>
                      </td>
                      <td style={{textAlign:'right'}}>
                        <div className="t-mono" style={{fontSize:12.5, fontWeight:600}}>{fmtUGX(b.totalPaid)}</div>
                        <div className="t-cap">{b.monthsIn} months</div>
                      </td>
                    </>
                  )}

                  <td>
                    <StatusChip code={b.status} statusOpts={statusOpts}/>
                  </td>
                  <td className="col-actions">
                    <Icon name="chevronRight" size={16} color="var(--neutral-500)"/>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {/* Pagination */}
        <div className="row gap-2" style={{padding:'12px 16px', borderTop:'1px solid var(--neutral-200)', justifyContent:'space-between'}}>
          <span className="t-cap">Showing {rows.length === 0 ? 0 : page*pageSize + 1}–{Math.min((page+1)*pageSize, rows.length)} of {rows.length.toLocaleString()}</span>
          <div className="row gap-2">
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(0)}><Icon name="chevronsLeft" size={14}/></button>
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}><Icon name="chevronLeft" size={14}/></button>
            <span className="t-bodysm" style={{padding:'0 8px'}}>{page+1} / {totalPages}</span>
            <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}><Icon name="chevronRight" size={14}/></button>
            <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)}><Icon name="chevronsRight" size={14}/></button>
          </div>
        </div>
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read-only ledger (AC-PROG-LEDGER). Enrolment, suspension, and exit events are written via the Programmes API and audited per AC-AUDIT-EVENT.
      </div>

      <Toast message={toast} onDone={() => setToast("")}/>

      {/* TWEAKS */}
      {typeof TweaksPanel === 'function' && (
        <TweaksPanel title="Tweaks · Beneficiaries">
          <TweakSection label="Layout"/>
          <TweakToggle label="Show programme rollup strip" value={t.showProgrammeStrip} onChange={v => setTweak('showProgrammeStrip', v)}/>
          <TweakToggle label="Show exit-reason chart (Exited tab)" value={t.showExitChart} onChange={v => setTweak('showExitChart', v)}/>
          <TweakToggle label="Show payment activity sparkline" value={t.showPaymentSpark} onChange={v => setTweak('showPaymentSpark', v)}/>
          <TweakSection label="Status tab"/>
          <TweakRadio label="Jump to" value={statusTab}
            options={statusOpts.map(s => ({ value: s.code, label: s.label }))}
            onChange={v => { setStatusTab(v); setPage(0); setExitCode(""); }}/>
        </TweaksPanel>
      )}
    </div>
  );
};

/* ============================================================
   Sub-components
   ============================================================ */

/* horizontal stacked bar — active / pend / susp / exited */
const StatusStackBar = ({ active, susp, pend, exited }) => {
  const total = (active||0) + (susp||0) + (pend||0) + (exited||0);
  if (total === 0) {
    return <div style={{height:6, borderRadius:3, background:'var(--neutral-200)'}}/>;
  }
  const pctA = (active||0)/total*100;
  const pctP = (pend||0)/total*100;
  const pctS = (susp||0)/total*100;
  const pctE = (exited||0)/total*100;
  return (
    <div style={{display:'flex', height:6, borderRadius:3, overflow:'hidden', background:'var(--neutral-200)'}}>
      {pctA > 0 && <div title={`${active} active`} style={{width:pctA+'%', background:'var(--accent-data)'}}/>}
      {pctP > 0 && <div title={`${pend} pending`} style={{width:pctP+'%', background:'var(--accent-update)'}}/>}
      {pctS > 0 && <div title={`${susp} suspended`} style={{width:pctS+'%', background:'var(--accent-quality)'}}/>}
      {pctE > 0 && <div title={`${exited} exited`} style={{width:pctE+'%', background:'var(--neutral-500)'}}/>}
    </div>
  );
};

/* Months-in indicator: filled bar capped at 24 + text */
const MonthsBar = ({ months }) => {
  const pct = Math.min(100, (months / 24) * 100);
  return (
    <div style={{minWidth:90}}>
      <div className="row gap-2" style={{justifyContent:'space-between', marginBottom:2}}>
        <span style={{fontVariantNumeric:'tabular-nums', fontSize:13, fontWeight:500}}>{months}<span className="muted" style={{fontWeight:400}}> mo</span></span>
      </div>
      <div style={{height:4, background:'var(--neutral-100)', borderRadius:2, overflow:'hidden'}}>
        <div style={{width:pct + '%', height:'100%', background: months >= 24 ? 'var(--accent-data)' : 'var(--primary-700)'}}/>
      </div>
    </div>
  );
};

const StatusChip = ({ code, statusOpts }) => {
  const opt = statusOpts.find(s => s.code === code);
  const tone = ENROL_STATUS_TONE[code] || "neutral";
  const icon = ENROL_STATUS_ICON[code] || null;
  return <Chip size="sm" tone={tone} icon={icon}>{opt ? opt.label : code}</Chip>;
};

/* ============================================================
   Exit reason rollup — bar chart with click-to-filter
   ============================================================ */
const ExitReasonRollup = ({ rows, exitOpts, selected, onSelect }) => {
  const tally = {};
  rows.forEach(r => {
    const c = String(r.exitCode);
    tally[c] = (tally[c] || 0) + 1;
  });
  const items = Object.entries(tally)
    .map(([code, n]) => {
      const opt = exitOpts.find(o => o.code === code);
      return {
        code, n,
        label: opt ? opt.label : code,
        tone: EXIT_TONE[code] || "neutral",
      };
    })
    .sort((a,b) => b.n - a.n);
  const max = Math.max(...items.map(i => i.n), 1);
  const total = rows.length;
  return (
    <div className="card mt-5" style={{padding:0}}>
      <div style={{padding:'14px 18px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'baseline', justifyContent:'space-between', gap:12}}>
        <div>
          <strong className="t-h3" style={{display:'block'}}>Why are people exiting?</strong>
          <span className="t-cap">{total.toLocaleString()} exits · click a reason to filter the list</span>
        </div>
        <div className="t-cap">Codes per <span className="t-mono">programme_exit_reason</span> v1</div>
      </div>
      <div style={{padding:'12px 18px 16px'}}>
        <div style={{display:'grid', gridTemplateColumns:'180px 1fr 60px 60px', gap:10, alignItems:'center'}}>
          {items.map(it => {
            const isSel = selected === it.code;
            const pct = (it.n / max) * 100;
            const pctOfTotal = (it.n / total) * 100;
            return (
              <React.Fragment key={it.code}>
                <button onClick={() => onSelect(it.code)} style={{textAlign:'left', background:'transparent', border:0, cursor:'pointer', padding:0, display:'flex', alignItems:'center', gap:8}}>
                  <span style={{width:8, height:8, borderRadius:'50%', background:`var(--accent-${it.tone})`, display:'inline-block', flexShrink:0}}/>
                  <span className="t-mono" style={{fontSize:11.5, color:'var(--neutral-500)'}}>{String(it.code).padStart(2,'0')}</span>
                  <span style={{fontSize:13, fontWeight: isSel ? 700 : 500, color: isSel ? `var(--accent-${it.tone})` : 'var(--neutral-900)'}}>{it.label}</span>
                </button>
                <button onClick={() => onSelect(it.code)} style={{background:'transparent', border:0, cursor:'pointer', padding:0}}>
                  <div style={{height:22, background:'var(--neutral-100)', borderRadius:3, overflow:'hidden', position:'relative', border: isSel ? `1px solid var(--accent-${it.tone})` : '1px solid transparent'}}>
                    <div style={{width: pct + '%', height:'100%', background:`var(--accent-${it.tone})`, opacity: isSel ? 1 : 0.85}}/>
                  </div>
                </button>
                <div className="t-num" style={{textAlign:'right', fontSize:13, fontWeight:600}}>{it.n}</div>
                <div className="t-cap" style={{textAlign:'right'}}>{pctOfTotal.toFixed(0)}%</div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
};

/* expose to window so app.jsx can pick it up */
Object.assign(window, { BeneficiariesScreen });
