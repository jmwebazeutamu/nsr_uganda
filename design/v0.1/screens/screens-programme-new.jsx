/* global React, Icon, Chip, PageHeader, Modal, Field, Toast, useChoiceList, useApi, nsrApi */
// NSR MIS — Programme registration wizard (US-181 / US-S25-004 · REF + Partners)
//
//   ProgrammeRegistrationScreen — 5-step wizard to create a new Programme
//   under an existing partner + DSA. Per the project-wide rule, every
//   coded selector reads from /api/v1/reference-data/choice-list-bundle/
//   via useChoiceList. Partner picker reads /api/v1/partners/. Geographic
//   scope reads /api/v1/reference-data/geographic-units/. Submit POSTs
//   to /api/v1/programmes/.
//
//   Steps:
//     1) Basics              code, name, partner, kind, summary
//     2) Cohort & targeting  unit, eligibility rules (PMT / sex / age /
//                            composition), cohort target, live reach est.
//     3) Disbursement        amount, cycle, duration, channel, calendar
//     4) Geographic scope    sub-regions constrained by partner's DSA
//     5) Lifecycle & API     exit reasons, auto-exit triggers, webhook
//
// Domain references:
//   apps.partners.models.Programme           (US-S25-002 extended columns)
//   apps.partners.models.DataSharingAgreement (geo + entity scope cap)
//   apps.reference_data ChoiceList            (every coded selector here)

const { useState: useStateProg, useMemo: useMemoProg, useEffect: useEffectProg } = React;

/* ============================================================
   Small UI maps (NOT code lists — pure presentation layer)
   ============================================================ */

// Icon glyph per unit-of-enrolment code. Codes come from the DB; the
// icon mapping is a UI-side decoration that doesn't change the data
// surface. Falls back to a default glyph for unknown codes.
const UNIT_ICON = { household: "home", member: "users", group: "users" };
const UNIT_HINT = {
  household: "12.1M targeted",
  member:    "48.1M individuals",
  group:     "VSLAs, co-ops, women's groups",
};

// Tone for exit-reason chip. We map by code only because the chip
// component needs a colour; the reason catalogue itself lives in
// the programme_exit_reason ChoiceList.
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

// PMT-band rough fraction of total HHs (for the wizard's live reach
// estimate only; the actual eligibility is server-side and depends
// on the household PMT score).
const PMT_BAND_META = {
  extreme_poverty: { label: "Extreme poverty", fraction: 0.10, note: "≤ 2.812 · 10%" },
  poverty:         { label: "Poverty",         fraction: 0.10, note: "≤ 3.245 · 20%" },
  vulnerable:      { label: "Vulnerable",      fraction: 0.10, note: "≤ 3.582 · 30%" },
  not_poor:        { label: "Not poor",        fraction: 0.00, note: "≤ 7.219 · default excludes" },
  poorest_20:      { label: "Extreme poverty", fraction: 0.10, note: "legacy code" },
  poorest_40:      { label: "Poverty",         fraction: 0.10, note: "legacy code" },
  middle_40:       { label: "Vulnerable",      fraction: 0.10, note: "legacy code" },
  top_20:          { label: "Not poor",        fraction: 0.00, note: "legacy code" },
};
const PMT_BAND_ALIASES = {
  extreme_poverty: "poorest_20",
  "extreme poverty": "poorest_20",
  "poorest 20%": "poorest_20",
  poorest_20: "poorest_20",
  poverty: "poorest_40",
  "poorest 40%": "poorest_40",
  poorest_40: "poorest_40",
  vulnerable: "middle_40",
  "middle 40%": "middle_40",
  middle_40: "middle_40",
  not_poor: "top_20",
  "not poor": "top_20",
  "top 20%": "top_20",
  top_20: "top_20",
};
const normalizePmtBandCode = (value) => {
  const raw = (value ?? "").toString().trim().toLowerCase();
  return PMT_BAND_ALIASES[raw] || raw;
};
const pmtDisplayLabel = (code, fallback = code) => {
  const normalized = normalizePmtBandCode(code);
  return PMT_BAND_META[normalized]?.label || fallback;
};
const pmtFraction = (code) => Number(PMT_BAND_META[normalizePmtBandCode(code)]?.fraction || 0);

// Composition flag → narrowing factor for the live reach estimate.
const COMP_FACTOR = {
  female_headed: 0.35, under_five: 0.55, elderly: 0.18,
  pregnant: 0.06, disabled: 0.12, orphan: 0.08,
};

// Disbursement cycle code → cycles-per-month factor.
const CYCLE_FACTOR = {
  monthly: 1, quarterly: 1/3, semi_annual: 1/6, annual: 1/12, one_off: 0,
};
const CYCLE_NOUN = {
  monthly: "month", quarterly: "quarter", semi_annual: "half",
  annual: "year", one_off: "one-off",
};
const CYCLE_BAR_LABEL = {
  monthly: "m", quarterly: "Q", semi_annual: "H", annual: "Y", one_off: "—",
};

/* ============================================================
   Step list — local UI ordering, not a ChoiceList (it's the
   form's own navigation state).
   ============================================================ */
const PROG_STEPS = [
  { id: "basics",       label: "Basics",            icon: "book"     },
  { id: "cohort",       label: "Cohort & targeting", icon: "users"    },
  { id: "disbursement", label: "Disbursement",      icon: "download" },
  { id: "scope",        label: "Geographic scope",  icon: "mapPin"   },
  { id: "lifecycle",    label: "Lifecycle & API",   icon: "refresh"  },
];

/* ============================================================
   MAIN SCREEN
   ============================================================ */
const ProgrammeRegistrationScreen = ({ onBack }) => {
  /* ---- ChoiceLists (every coded selector reads from the DB) ---- */
  const [, { allLists: cl }] = useChoiceList([
    "programme_kind",
    "programme_unit_of_enrolment",
    "programme_disbursement_cycle",
    "programme_pmt_band",
    "programme_exit_reason",
    "programme_composition_flag",
    "programme_auto_exit_trigger",
    "programme_webhook_event",
    "programme_sex_filter",
  ]);
  const kindOpts    = cl.programme_kind                || [];
  const unitOpts    = cl.programme_unit_of_enrolment   || [];
  const cycleOpts   = cl.programme_disbursement_cycle  || [];
  const pmtOpts     = cl.programme_pmt_band            || [];
  const exitOpts    = cl.programme_exit_reason         || [];
  const compOpts    = cl.programme_composition_flag    || [];
  const autoOpts    = cl.programme_auto_exit_trigger   || [];
  const webhookOpts = cl.programme_webhook_event       || [];
  const sexOpts     = cl.programme_sex_filter          || [];

  /* ---- Live data ---- */
  const [partnersResp] = useApi("/api/v1/partners/?status=active");
  const partners = (partnersResp && partnersResp.results) || [];

  const [geoResp] = useApi("/api/v1/reference-data/geographic-units/");
  const allGeoUnits = useMemoProg(
    () => ((geoResp && geoResp.results) || []).filter(g => g.level === "sub_region"),
    [geoResp],
  );

  /* ---- Local state ---- */
  const [step, setStep] = useStateProg("basics");
  const [submitOpen, setSubmitOpen] = useStateProg(false);
  const [toast, setToast] = useStateProg("");
  const [submitting, setSubmitting] = useStateProg(false);
  const [submitError, setSubmitError] = useStateProg("");
  const [data, setData] = useStateProg({
    // Step 1
    code:    "",
    name:    "",
    partner_id: "",
    kind:    "",
    summary: "",
    // Step 2
    unit_of_enrolment: "",
    pmt_bands:         [],
    age_min:           0,
    age_max:           99,
    sex_filter:        "any",
    composition_flags: [],
    cohort_target:     0,
    // Step 3
    amount_ugx:           0,
    disbursement_cycle:   "",
    duration_months:      12,
    channel:              "",
    start_month:          "",
    // Step 4 — geo holds GeographicUnit IDs (canonical), not names
    geo_unit_ids: [],
    // Step 5
    exit_codes_allowed:  [],
    auto_exit_triggers:  [],
    suspend_on_grievance: true,
    webhook_url:          "",
  });

  /* ---- Defaults once code lists arrive ---- */
  useEffectProg(() => {
    setData(d => ({
      ...d,
      kind:               d.kind               || (kindOpts[0]?.code || ""),
      unit_of_enrolment:  d.unit_of_enrolment  || (unitOpts[0]?.code || ""),
      disbursement_cycle: d.disbursement_cycle || (cycleOpts[0]?.code || ""),
      sex_filter:         d.sex_filter         || (sexOpts[0]?.code || "any"),
      // Pre-select graduate/transferred/deceased/etc. (all but punitive)
      exit_codes_allowed: d.exit_codes_allowed.length
        ? d.exit_codes_allowed
        : exitOpts.filter(o => o.code !== "80" && o.code !== "99").map(o => o.code),
    }));
  }, [kindOpts.length, unitOpts.length, cycleOpts.length, sexOpts.length, exitOpts.length]);

  /* ---- Pre-select the first partner when the list arrives ---- */
  useEffectProg(() => {
    if (!data.partner_id && partners.length) {
      setData(d => ({ ...d, partner_id: partners[0].id }));
    }
  }, [partners.length]);

  const stepIdx = PROG_STEPS.findIndex(s => s.id === step);
  const next = () => setStep(PROG_STEPS[Math.min(stepIdx+1, PROG_STEPS.length-1)].id);
  const prev = () => setStep(PROG_STEPS[Math.max(stepIdx-1, 0)].id);
  const setD = (k, v) => setData(d => ({ ...d, [k]: v }));
  const toggleInArr = (k, v) => setData(d => ({
    ...d, [k]: d[k].includes(v) ? d[k].filter(x => x !== v) : [...d[k], v],
  }));

  /* ---- Derived ---- */
  const partner = partners.find(p => p.id === data.partner_id) || null;
  const kindMeta = kindOpts.find(k => k.code === data.kind) || null;

  // The selected partner's active DSA — the geo cap comes from this.
  const [dsaResp] = useApi(
    data.partner_id
      ? `/api/v1/dsas/?partner=${data.partner_id}&status=active`
      : null,
    { skip: !data.partner_id },
  );
  const activeDsa = ((dsaResp && dsaResp.results) || [])[0] || null;

  // Sub-region IDs the DSA permits. Empty array = no allowlist yet.
  const dsaGeoIds = useMemoProg(() => {
    if (!activeDsa) return [];
    // geographic_scope is a list of GeographicUnit IDs per the
    // canonical DsaSerializer (ADR-0013 / Sprint 24).
    return activeDsa.geographic_scope || [];
  }, [activeDsa]);

  // Out-of-scope geo: anything the user picked that isn't in the DSA.
  const outOfScopeGeo = data.geo_unit_ids.filter(g => !dsaGeoIds.includes(g));

  /* ---- Budget projection ---- */
  const cycle = data.disbursement_cycle;
  const monthlyCycles = CYCLE_FACTOR[cycle] || 0;
  const cyclesInPeriod = cycle === "one_off"
    ? 1
    : Math.max(1, Math.round((data.duration_months || 0) * monthlyCycles));
  const totalPerBenef = (data.amount_ugx || 0) * cyclesInPeriod;
  const totalBudget   = totalPerBenef * (data.cohort_target || 0);

  /* ---- Estimated reach — wizard preview only ---- */
  const estReach = useMemoProg(() => {
    let base = 12100000;
    if (data.pmt_bands.length) {
      base *= data.pmt_bands.reduce((s, c) => s + pmtFraction(c), 0);
    }
    const geoFrac = allGeoUnits.length === 0
      ? 0
      : Math.min(1, data.geo_unit_ids.length / allGeoUnits.length);
    base *= geoFrac;
    if (data.unit_of_enrolment === "member") base *= 4;
    for (const c of data.composition_flags) base *= (COMP_FACTOR[c] || 1);
    if (
      data.unit_of_enrolment === "member"
      && (data.age_max - data.age_min) < 80
    ) {
      base *= (data.age_max - data.age_min + 1) / 100;
    }
    return Math.max(0, Math.round(base));
  }, [data, allGeoUnits.length]);

  /* ---- Submit ---- */
  const submit = async () => {
    setSubmitting(true);
    setSubmitError("");
    try {
      const payload = {
        partner:           data.partner_id,
        code:              data.code,
        name:              data.name,
        summary:           data.summary,
        kind:              data.kind,
        status:            "draft",
        dsa:               activeDsa ? activeDsa.id : null,
        unit_of_enrolment: data.unit_of_enrolment,
        cohort_target:     data.cohort_target,
        sex_filter:        data.sex_filter,
        age_min:           data.age_min,
        age_max:           data.age_max,
        pmt_bands:         data.pmt_bands.map(normalizePmtBandCode),
        composition_flags: data.composition_flags,
        amount_ugx:        data.amount_ugx,
        disbursement_cycle: data.disbursement_cycle,
        duration_months:   data.duration_months,
        channel:           data.channel,
        start_month:       data.start_month,
        geographic_units:  data.geo_unit_ids,
        exit_codes_allowed: data.exit_codes_allowed,
        auto_exit_triggers: data.auto_exit_triggers,
        suspend_on_grievance: data.suspend_on_grievance,
        webhook_url:       data.webhook_url,
      };
      const r = await nsrApi.post("/api/v1/programmes/", payload);
      setSubmitOpen(false);
      const secretNotice = r.webhook_secret_cleartext
        ? ` · webhook secret displayed once: ${r.webhook_secret_cleartext.slice(0, 8)}…`
        : "";
      setToast(
        `Programme ${r.code || r.name} created · draft pending ${partner ? partner.code : "partner"} Data Steward sign-off${secretNotice}`,
      );
    } catch (err) {
      setSubmitError(
        (err.body && (err.body.detail || JSON.stringify(err.body)))
        || err.message || "Submit failed",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page" style={{paddingBottom:0}}>

      <PageHeader
        back={{ label: "Partners", onClick: onBack }}
        eyebrow={<>PROGRAMMES · NEW · REF module · SAD §5.1</>}
        title="Register programme"
        sub={<>Define a new partner-run programme — its eligibility rules, disbursement schedule, and the lifecycle events the partner MIS will push back to NSR. Saved as a <strong>draft</strong> until signed off by the partner's Data Steward.</>}
        right={<>
          <button className="btn" onClick={() => setToast("Draft saved · resume from Programmes tab any time")}><Icon name="save" size={14}/> Save draft</button>
          <button className="btn btn-ghost" onClick={onBack}><Icon name="x" size={14}/> Discard</button>
        </>}
      />

      {/* STEPPER */}
      <div className="card" style={{padding:"14px 20px", marginBottom:16, display:"flex", alignItems:"center", gap:0}}>
        {PROG_STEPS.map((s, i) => {
          const done = i < stepIdx;
          const active = i === stepIdx;
          return (
            <React.Fragment key={s.id}>
              <button onClick={() => setStep(s.id)} style={{
                display:"flex", alignItems:"center", gap:8,
                padding:"4px 12px", border:0, background:"transparent", cursor:"pointer",
                color: active ? "var(--primary-900)" : done ? "var(--neutral-700)" : "var(--neutral-500)",
                fontWeight: active ? 600 : 500, fontSize:13.5,
              }}>
                <span style={{
                  width:24, height:24, borderRadius:"50%", display:"grid", placeItems:"center",
                  background: active ? "var(--primary-900)" : done ? "var(--primary-100)" : "var(--neutral-100)",
                  color: active ? "white" : done ? "var(--primary-900)" : "var(--neutral-500)",
                  fontSize:12, fontWeight:600,
                  border: active ? 0 : `1px solid ${done ? "var(--primary-700)" : "var(--neutral-300)"}`,
                }}>{done ? <Icon name="check" size={12}/> : i+1}</span>
                {s.label}
              </button>
              {i < PROG_STEPS.length - 1 && <div style={{flex:1, height:1, background: i < stepIdx ? "var(--primary-700)" : "var(--neutral-300)", minWidth:14}}/>}
            </React.Fragment>
          );
        })}
      </div>

      {/* CONTENT + PREVIEW RAIL */}
      <div style={{display:"grid", gridTemplateColumns:"1fr 340px", gap:16}}>
        <div className="col gap-4">
          {step === "basics"       && <StepBasics       data={data} setD={setD} partners={partners} partner={partner} activeDsa={activeDsa} kindOpts={kindOpts}/>}
          {step === "cohort"       && <StepCohort       data={data} setD={setD} toggleInArr={toggleInArr} unitOpts={unitOpts} pmtOpts={pmtOpts} sexOpts={sexOpts} compOpts={compOpts} estReach={estReach}/>}
          {step === "disbursement" && <StepDisbursement data={data} setD={setD} cycleOpts={cycleOpts} cyclesInPeriod={cyclesInPeriod} totalPerBenef={totalPerBenef} totalBudget={totalBudget}/>}
          {step === "scope"        && <StepScopeGeo    data={data} setD={setD} toggleInArr={toggleInArr} allGeoUnits={allGeoUnits} dsaGeoIds={dsaGeoIds} outOfScopeGeo={outOfScopeGeo} activeDsa={activeDsa}/>}
          {step === "lifecycle"    && <StepLifecycle   data={data} setD={setD} toggleInArr={toggleInArr} exitOpts={exitOpts} autoOpts={autoOpts} webhookOpts={webhookOpts}/>}
        </div>

        <ProgPreview data={data} partner={partner} activeDsa={activeDsa} kindMeta={kindMeta} estReach={estReach} totalPerBenef={totalPerBenef} totalBudget={totalBudget} cyclesInPeriod={cyclesInPeriod} outOfScopeGeo={outOfScopeGeo} cycleOpts={cycleOpts} unitOpts={unitOpts} sexOpts={sexOpts} pmtOpts={pmtOpts} compOpts={compOpts} exitOpts={exitOpts} allGeoUnits={allGeoUnits}/>
      </div>

      {/* ACTION BAR */}
      {(() => {
        // The "Create programme" button at the wizard's last step needs
        // partner + name + kind to be set. When the user clicked
        // through and one of these is empty (e.g. the programme_kind
        // ChoiceList never loaded because of a session expiry, or the
        // user skipped the Kind card), the button used to disable
        // silently — looked like a dead click. List which fields are
        // missing inline + as a tooltip so the user knows what to fix.
        const missing = [];
        if (!data.partner_id) missing.push("partner");
        if (!data.name)       missing.push("name");
        if (!data.kind)       missing.push("programme kind");
        const submitBlocked = missing.length > 0;
        const tip = submitBlocked
          ? `Missing: ${missing.join(", ")}. Go back to Step 1 (Basics) to set ${missing.length === 1 ? "it" : "them"}.`
          : "";
        const isLast = stepIdx === PROG_STEPS.length - 1;
        return (
          <div style={{margin:"16px -24px 0", position:"sticky", bottom:0, zIndex:20, background:"var(--neutral-0)", borderTop:"1px solid var(--neutral-300)", padding:"12px 20px", display:"flex", gap:12, alignItems:"center", boxShadow:"0 -2px 8px rgba(0,0,0,0.04)"}}>
            <span className="t-bodysm muted">Step {stepIdx+1} of {PROG_STEPS.length} · <strong style={{color:"var(--neutral-900)"}}>{PROG_STEPS[stepIdx].label}</strong></span>
            {outOfScopeGeo.length > 0 && step !== "scope" && (
              <span className="row gap-2" style={{color:"var(--accent-quality)", fontSize:13}}>
                <Icon name="alert" size={14} color="var(--accent-quality)"/> {outOfScopeGeo.length} region{outOfScopeGeo.length===1?'':'s'} outside DSA scope
              </span>
            )}
            {isLast && submitBlocked && (
              <span className="row gap-2" style={{color:"var(--accent-danger)", fontSize:13}}>
                <Icon name="alert" size={14} color="var(--accent-danger)"/>
                Missing on Basics step: <strong>{missing.join(", ")}</strong>
              </span>
            )}
            <div style={{flex:1}}/>
            <button className="btn" onClick={prev} disabled={stepIdx === 0}><Icon name="chevronLeft" size={14}/> Back</button>
            {!isLast
              ? <button className="btn btn-primary" onClick={next}>Continue <Icon name="chevronRight" size={14}/></button>
              : <button className="btn btn-primary"
                       onClick={() => setSubmitOpen(true)}
                       disabled={submitBlocked}
                       title={tip}
                       aria-disabled={submitBlocked}>
                  <Icon name="check" size={14}/> Create programme
                </button>
            }
          </div>
        );
      })()}

      {/* SUBMIT MODAL */}
      <Modal open={submitOpen} onClose={() => !submitting && setSubmitOpen(false)} title="Create programme · save as draft" width={540}
        footer={<>
          <button className="btn" onClick={() => setSubmitOpen(false)} disabled={submitting}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={submitting}>
            <Icon name="check" size={14}/> {submitting ? "Creating..." : "Create programme"}
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>
            Programme <strong>{data.name || "—"}</strong> {data.code ? <>(<span className="t-mono">{data.code}</span>)</> : null} will be created as a draft under partner <strong>{partner ? partner.name : "—"}</strong>.
          </p>
          {submitError && (
            <div style={{padding:10, background:"var(--accent-danger-bg)", borderLeft:"3px solid var(--accent-danger)", borderRadius:4, fontSize:13, color:"var(--accent-danger)"}}>
              {submitError}
            </div>
          )}
          <div style={{padding:12, background:"var(--accent-programme-bg)", borderLeft:"3px solid var(--accent-programme)", borderRadius:4}}>
            <div className="row gap-2"><Icon name="shield" size={14} color="var(--accent-programme)"/><strong className="t-bodysm">Sign-off chain</strong></div>
            <ol style={{margin:"6px 0 0 18px", padding:0, fontSize:13, color:"var(--neutral-700)"}}>
              <li>NSR Unit Coordinator · auto-signed on submission</li>
              <li>{partner ? partner.code : "Partner"} Data Steward · sign in partner console · 2 working days</li>
              <li>NSR DPO · scope sanity check · 1 working day</li>
            </ol>
          </div>
          <div className="row gap-3 t-cap" style={{borderTop:"1px dashed var(--neutral-300)", paddingTop:10}}>
            <span><strong style={{color:"var(--neutral-900)"}}>{estReach.toLocaleString()}</strong> est. reach</span>
            <span>·</span>
            <span><strong style={{color:"var(--neutral-900)"}}>UGX {Math.round(totalBudget/1000000).toLocaleString()}M</strong> {data.duration_months}-mo budget</span>
            <span>·</span>
            <span><strong style={{color:"var(--neutral-900)"}}>{data.geo_unit_ids.length}</strong> sub-regions</span>
          </div>
        </div>
      </Modal>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

/* ============================================================
   STEP 1 — Basics
   ============================================================ */
const StepBasics = ({ data, setD, partners, partner, activeDsa, kindOpts }) => (
  <div className="col gap-4">
    {/* Identity */}
    <div className="card">
      <div className="card-header">
        <h3 className="t-h3" style={{margin:0}}>Identity</h3>
        <span className="t-cap">The short code becomes the chip on every beneficiary row and the suffix on every DRS request.</span>
      </div>
      <div style={{padding:20}}>
        <div className="field-row">
          <Field label="Short code" hint="3–24 uppercase letters · used as the programme mark">
            <input className="field-input t-mono" value={data.code}
              onChange={(e) => setD("code", e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, "").slice(0, 24))}
              style={{textTransform:"uppercase"}}/>
          </Field>
          <Field label="Display name" required>
            <input className="field-input" value={data.name} onChange={(e) => setD("name", e.target.value)}/>
          </Field>
        </div>
        <Field label="Short summary" hint="One-sentence description shown in the partner programmes tab" >
          <textarea className="field-textarea" rows={2} value={data.summary} onChange={(e) => setD("summary", e.target.value)}/>
        </Field>
      </div>
    </div>

    {/* Partner / DSA */}
    <div className="card">
      <div className="card-header">
        <h3 className="t-h3" style={{margin:0}}>Run by partner</h3>
        <span className="t-cap">Locks the DSA scope cap (geo + entity + field-group allowlist)</span>
      </div>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(200px, 1fr))", gap:10}}>
        {partners.length === 0
          ? <span className="muted t-bodysm">No active partners — register one first.</span>
          : partners.map(p => {
            const on = data.partner_id === p.id;
            return (
              <button key={p.id} onClick={() => setD("partner_id", p.id)} style={{
                textAlign:"left", padding:"12px 14px", borderRadius:6,
                border: `2px solid ${on ? "var(--primary-900)" : "var(--neutral-300)"}`,
                background: on ? "var(--primary-100)" : "var(--neutral-0)",
                cursor:"pointer", minWidth:0,
              }}>
                <div className="row gap-2" style={{justifyContent:"space-between"}}>
                  <strong className="t-mono" style={{fontSize:12, color:`var(--accent-${p.tone || "primary"}, var(--primary-900))`, letterSpacing:"0.04em"}}>{p.code}</strong>
                  {on && <Icon name="check" size={13} color="var(--primary-900)"/>}
                </div>
                <div className="t-bodysm" style={{marginTop:4, fontWeight:500, color:"var(--neutral-900)", lineHeight:1.3, overflow:"hidden", display:"-webkit-box", WebkitLineClamp:2, WebkitBoxOrient:"vertical"}}>{p.name}</div>
                <div className="t-cap mt-1">{p.sector_label || p.sector || "—"}</div>
              </button>
            );
          })}
      </div>
      <div className="divider" style={{margin:0}}/>
      <div style={{padding:"14px 20px", background:"var(--neutral-50)"}}>
        <div className="row gap-3" style={{alignItems:"baseline"}}>
          <span className="t-cap">Linked DSA</span>
          {activeDsa ? (
            <>
              <strong className="t-mono" style={{fontSize:13}}>{activeDsa.reference}</strong>
              <Chip size="sm" tone="data" icon="check">{activeDsa.status_label || activeDsa.status}</Chip>
            </>
          ) : (
            <span className="muted t-bodysm">
              {partner ? `No active DSA on ${partner.code}` : "Pick a partner to see their DSA"}
            </span>
          )}
          <div style={{flex:1}}/>
          {activeDsa && <a className="t-bodysm" href={`#dsa-${activeDsa.id}`}>View DSA scope →</a>}
        </div>
      </div>
    </div>

    {/* Kind */}
    <div className="card">
      <div className="card-header">
        <h3 className="t-h3" style={{margin:0}}>Programme kind</h3>
        <span className="t-cap">Drives the modality choices in step 3 and the default exit-reason codes</span>
      </div>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(220px, 1fr))", gap:10}}>
        {kindOpts.length === 0 ? (
          <span className="muted t-bodysm">
            Programme kinds didn’t load. Check that you’re signed in
            (the choice-list endpoint returns 403 anonymously) and
            refresh — without a kind set, the “Create programme”
            button at Step 5 stays disabled.
          </span>
        ) : kindOpts.map(k => {
          const on = data.kind === k.code;
          const tone = "programme";
          return (
            <button key={k.code} onClick={() => setD("kind", k.code)} style={{
              textAlign:"left", padding:"14px 16px", borderRadius:6,
              border: `2px solid ${on ? `var(--accent-${tone})` : "var(--neutral-300)"}`,
              background: on ? `var(--accent-${tone}-bg)` : "var(--neutral-0)",
              cursor:"pointer", display:"flex", flexDirection:"column", gap:6,
            }}>
              <div className="row gap-2"><strong className="t-bodysm" style={{color: on ? `var(--accent-${tone})` : 'var(--neutral-900)'}}>{k.label}</strong>{on && <Icon name="check" size={13} color={`var(--accent-${tone})`}/>}</div>
              <div className="t-cap" style={{color: on ? `var(--accent-${tone})` : 'var(--neutral-500)', opacity:0.85}}>{k.code}</div>
            </button>
          );
        })}
      </div>
    </div>
  </div>
);

/* ============================================================
   STEP 2 — Cohort & targeting
   ============================================================ */
const StepCohort = ({ data, setD, toggleInArr, unitOpts, pmtOpts, sexOpts, compOpts, estReach }) => (
  <div className="col gap-4">

    {/* Unit of enrolment */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Unit of enrolment</h3>
        <span className="t-cap">Who is the beneficiary? Drives the enrolment row shape and the disbursement target.</span>
      </div>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(220px, 1fr))", gap:10}}>
        {unitOpts.map(u => {
          const on = data.unit_of_enrolment === u.code;
          return (
            <button key={u.code} onClick={() => setD("unit_of_enrolment", u.code)} style={{
              textAlign:"left", padding:"14px 16px", borderRadius:6,
              border:`2px solid ${on ? "var(--primary-900)" : "var(--neutral-300)"}`,
              background: on ? "var(--primary-100)" : "var(--neutral-0)",
              cursor:"pointer", display:"flex", flexDirection:"column", gap:4,
            }}>
              <div className="row gap-2"><Icon name={UNIT_ICON[u.code] || "users"} size={14} color={on ? "var(--primary-900)" : "var(--neutral-700)"}/><strong className="t-bodysm">{u.label}</strong>{on && <Icon name="check" size={13} color="var(--primary-900)" style={{marginLeft:"auto"}}/>}</div>
              <div className="t-cap">{UNIT_HINT[u.code] || ""}</div>
            </button>
          );
        })}
      </div>
    </div>

    {/* Eligibility rules */}
    <div className="card">
      <div className="card-header">
        <h3 className="t-h3" style={{margin:0}}>Eligibility rules</h3>
        <span className="t-cap">Stacked filters · all rules must match · evaluated against current NSR snapshot</span>
      </div>

      {/* PMT band */}
      <div style={{padding:"18px 20px", borderBottom:"1px solid var(--neutral-200)"}}>
        <div className="row gap-2" style={{marginBottom:10}}>
          <Icon name="barchart" size={14} color="var(--accent-eligibility)"/>
          <strong className="t-bodysm">PMT band</strong>
          <span className="t-cap" style={{marginLeft:"auto"}}>at least one</span>
        </div>
        <div className="row-wrap">
          {pmtOpts.map(b => {
            const on = data.pmt_bands.includes(b.code);
            const meta = PMT_BAND_META[b.code] || {};
            return (
              <button key={b.code} onClick={() => toggleInArr("pmt_bands", b.code)} style={{
                border:`1px solid ${on ? "var(--accent-eligibility)" : "var(--neutral-300)"}`,
                background: on ? "var(--accent-eligibility-bg)" : "var(--neutral-0)",
                color: on ? "var(--accent-eligibility)" : "var(--neutral-700)",
                padding:"7px 13px", borderRadius:16, fontSize:13, fontWeight: on ? 600 : 500,
                cursor:"pointer",
              }} title={meta.note || b.label}>
                {on && <Icon name="check" size={11} style={{marginRight:5, verticalAlign:"-1px"}}/>}
                {pmtDisplayLabel(b.code, b.label)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Age + sex */}
      <div style={{padding:"18px 20px", borderBottom:"1px solid var(--neutral-200)"}}>
        <div className="row gap-2" style={{marginBottom:10}}>
          <Icon name="users" size={14} color="var(--accent-identity)"/>
          <strong className="t-bodysm">{data.unit_of_enrolment === "member" ? "Age & sex" : "Head age & sex"}</strong>
          <span className="t-cap" style={{marginLeft:"auto"}}>{data.unit_of_enrolment === "member" ? "filters at member level" : "filters at household-head level"}</span>
        </div>
        <div style={{display:"grid", gridTemplateColumns:"1fr 240px", gap:18, alignItems:"center"}}>
          <RangeBar min={0} max={99} valMin={data.age_min} valMax={data.age_max}
            onChange={(min, max) => { setD("age_min", min); setD("age_max", max); }}/>
          <div className="seg">
            {sexOpts.map(o => (
              <button key={o.code} className={data.sex_filter === o.code ? "on" : ""} onClick={() => setD("sex_filter", o.code)}>{o.label}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Composition flags */}
      <div style={{padding:"18px 20px"}}>
        <div className="row gap-2" style={{marginBottom:10}}>
          <Icon name="home" size={14} color="var(--accent-data)"/>
          <strong className="t-bodysm">Household composition / vulnerability</strong>
          <span className="t-cap" style={{marginLeft:"auto"}}>all selected must hold (AND)</span>
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gap:8}}>
          {compOpts.map(c => {
            const on = data.composition_flags.includes(c.code);
            return (
              <button key={c.code} onClick={() => toggleInArr("composition_flags", c.code)} style={{
                textAlign:"left", padding:"10px 12px", borderRadius:4,
                border:`1px solid ${on ? "var(--accent-data)" : "var(--neutral-200)"}`,
                background: on ? "var(--accent-data-bg)" : "var(--neutral-0)",
                cursor:"pointer",
                display:"flex", alignItems:"flex-start", gap:8,
              }}>
                <span style={{
                  width:16, height:16, borderRadius:3, display:"grid", placeItems:"center", flexShrink:0,
                  background: on ? "var(--accent-data)" : "var(--neutral-0)",
                  border: on ? 0 : "1px solid var(--neutral-300)",
                  marginTop:1,
                }}>{on && <Icon name="check" size={11} color="white"/>}</span>
                <div style={{minWidth:0}}>
                  <div className="t-bodysm" style={{fontWeight: on ? 600 : 500, color: on ? "var(--accent-data)" : "var(--neutral-900)"}}>{c.label}</div>
                  <div className="t-cap" style={{marginTop:1}}>{c.code}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>

    {/* Estimated reach + cohort target */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Cohort target</h3>
        <span className="t-cap">How many beneficiaries do you aim to enrol?</span>
      </div>
      <div style={{padding:"18px 20px"}}>
        <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:18, alignItems:"center"}}>
          <div style={{padding:14, background:"var(--accent-eligibility-bg)", borderLeft:"3px solid var(--accent-eligibility)", borderRadius:4}}>
            <div className="t-cap" style={{color:"var(--accent-eligibility)", fontWeight:600, letterSpacing:"0.06em"}}>NSR ELIGIBLE · LIVE ESTIMATE</div>
            <div style={{fontSize:30, fontWeight:700, color:"var(--accent-eligibility)", marginTop:2, letterSpacing:"-0.01em", fontVariantNumeric:"tabular-nums"}}>{estReach.toLocaleString()}</div>
            <div className="t-cap mt-1">{data.unit_of_enrolment === "member" ? "members" : data.unit_of_enrolment === "group" ? "potential groups" : "households"} match all filters</div>
          </div>
          <Field label="Target enrolment for this cohort" required hint="Caps the size of the first programme batch · doesn't have to equal NSR eligible">
            <div className="input-affix">
              <input type="number" value={data.cohort_target} min={1}
                onChange={(e) => setD("cohort_target", Math.max(0, +e.target.value))}/>
              <span className="affix" style={{borderRight:0, borderLeft:"1px solid var(--neutral-200)"}}>{data.unit_of_enrolment === "household" ? "HH" : data.unit_of_enrolment === "member" ? "indiv" : "groups"}</span>
            </div>
          </Field>
        </div>
        <CoverageBar target={data.cohort_target} pool={estReach}/>
      </div>
    </div>
  </div>
);

/* ============================================================
   STEP 3 — Disbursement
   ============================================================ */
const StepDisbursement = ({ data, setD, cycleOpts, cyclesInPeriod, totalPerBenef, totalBudget }) => (
  <div className="col gap-4">
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Schedule & amount</h3>
        <span className="t-cap">Drives the auto-generated payment events on every active enrolment</span>
      </div>
      <div style={{padding:"18px 20px"}}>
        <div className="field-row-3">
          <Field label={`Amount per ${CYCLE_NOUN[data.disbursement_cycle] || "cycle"}`} required>
            <div className="input-affix">
              <span className="affix">UGX</span>
              <input type="number" value={data.amount_ugx} min={0} onChange={(e) => setD("amount_ugx", Math.max(0, +e.target.value))}/>
            </div>
          </Field>
          <Field label="Cycle" required>
            <div className="seg" style={{width:"100%"}}>
              {cycleOpts.map(c => (
                <button key={c.code} className={data.disbursement_cycle === c.code ? "on" : ""} onClick={() => setD("disbursement_cycle", c.code)} style={{flex:1}}>{c.label}</button>
              ))}
            </div>
          </Field>
          <Field label="Duration" required>
            <div className="input-affix">
              <input type="number" value={data.duration_months} min={1} max={120} onChange={(e) => setD("duration_months", Math.max(1, +e.target.value))}/>
              <span className="affix" style={{borderRight:0, borderLeft:"1px solid var(--neutral-200)"}}>months</span>
            </div>
          </Field>
        </div>
        <div className="field-row mt-4">
          <Field label="Start month" required>
            <input className="field-input" placeholder="Aug 2026" value={data.start_month} onChange={(e) => setD("start_month", e.target.value)}/>
          </Field>
          <Field label="Channel / cash rail" required>
            <input className="field-input" value={data.channel} onChange={(e) => setD("channel", e.target.value)}/>
          </Field>
        </div>
      </div>
    </div>

    {/* Budget projection */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Budget projection</h3>
        <span className="t-cap">{cyclesInPeriod} cycle{cyclesInPeriod===1?'':'s'} × {(data.cohort_target||0).toLocaleString()} {data.unit_of_enrolment === "household" ? "HH" : data.unit_of_enrolment === "member" ? "indiv" : "groups"}</span>
      </div>
      <div style={{padding:"18px 20px"}}>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gap:14, marginBottom:14}}>
          <BudgetCell label="Per beneficiary"      value={`UGX ${(totalPerBenef/1000).toLocaleString()}k`}        sub={`${cyclesInPeriod} cycle${cyclesInPeriod===1?'':'s'} × ${((data.amount_ugx||0)/1000).toLocaleString()}k`}    tone="data"/>
          <BudgetCell label={`${data.duration_months||0}-mo total`} value={`UGX ${(totalBudget/1000000).toFixed(1)}M`}                sub={`${(data.cohort_target||0).toLocaleString()} beneficiaries`}                                            tone="programme"/>
          <BudgetCell label="Annualised cost"      value={`UGX ${((data.duration_months||1) > 0 ? (totalBudget/(data.duration_months||1)*12/1000000) : 0).toFixed(1)}M`}      sub="straight-line annualisation"                                                                       tone="eligibility"/>
        </div>
        <PaymentTimeline cycles={cyclesInPeriod} cycleCode={data.disbursement_cycle} amount={data.amount_ugx} duration={data.duration_months}/>
      </div>
    </div>
  </div>
);

/* ============================================================
   STEP 4 — Geographic scope
   ============================================================ */
const StepScopeGeo = ({ data, toggleInArr, allGeoUnits, dsaGeoIds, outOfScopeGeo, activeDsa }) => {
  const idToUnit = useMemoProg(() => {
    const m = {};
    for (const g of allGeoUnits) m[g.id] = g;
    return m;
  }, [allGeoUnits]);

  const dsaUnits = dsaGeoIds.map(id => idToUnit[id]).filter(Boolean);

  return (
  <div className="col gap-4">
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Geographic scope</h3>
        <span className="t-cap">Constrained by the partner DSA — out-of-scope regions need a DSA amendment</span>
      </div>

      {/* DSA constraint banner */}
      <div style={{padding:"12px 20px", background:"var(--neutral-50)", borderBottom:"1px solid var(--neutral-200)"}}>
        <div className="row gap-2" style={{alignItems:"baseline", flexWrap:"wrap"}}>
          <Icon name="shield" size={13} color="var(--accent-update)"/>
          <span className="t-bodysm">
            <span className="muted">DSA cap · </span>
            {activeDsa
              ? <><strong className="t-mono">{activeDsa.reference}</strong> allows <strong>{dsaUnits.length}</strong> sub-region{dsaUnits.length===1?'':'s'}:</>
              : <span className="muted">No active DSA — pick a partner with an active DSA first.</span>}
          </span>
          <div className="row-wrap">
            {dsaUnits.map(g => <Chip key={g.id} size="sm" tone="update">{g.name}</Chip>)}
          </div>
        </div>
      </div>

      <div style={{padding:"18px 20px"}}>
        <div className="row-wrap">
          {allGeoUnits.map(g => {
            const on = data.geo_unit_ids.includes(g.id);
            const inDsa = dsaGeoIds.includes(g.id);
            const tone = !inDsa && on ? "danger" : on ? "data" : "neutral";
            return (
              <button key={g.id} onClick={() => toggleInArr("geo_unit_ids", g.id)} disabled={!inDsa && !on} style={{
                border:`1px solid ${tone === "danger" ? "var(--accent-danger)" : on ? "var(--accent-data)" : "var(--neutral-300)"}`,
                background: tone === "danger" ? "var(--accent-danger-bg)" : on ? "var(--accent-data-bg)" : !inDsa ? "var(--neutral-50)" : "var(--neutral-0)",
                color: tone === "danger" ? "var(--accent-danger)" : on ? "var(--accent-data)" : !inDsa ? "var(--neutral-300)" : "var(--neutral-700)",
                padding:"8px 14px", borderRadius:18, fontSize:13, fontWeight: on ? 600 : 500,
                cursor: !inDsa && !on ? "not-allowed" : "pointer",
                opacity: !inDsa && !on ? 0.55 : 1,
              }}>
                {on && <Icon name="check" size={11} style={{marginRight:5, verticalAlign:"-1px"}}/>}
                {!inDsa && on && <Icon name="alert" size={11} style={{marginRight:5, verticalAlign:"-1px"}}/>}
                {g.name}
                {!inDsa && <span className="t-cap" style={{marginLeft:6, fontSize:10, color:"inherit"}}>not in DSA</span>}
              </button>
            );
          })}
        </div>

        {outOfScopeGeo.length > 0 && (
          <div className="mt-4" style={{padding:"12px 14px", background:"var(--accent-danger-bg)", borderLeft:"3px solid var(--accent-danger)", borderRadius:4}}>
            <div className="row gap-2" style={{marginBottom:4}}><Icon name="alert" size={14} color="var(--accent-danger)"/><strong className="t-bodysm" style={{color:"var(--accent-danger)"}}>{outOfScopeGeo.length} region{outOfScopeGeo.length===1?'':'s'} outside the DSA scope</strong></div>
            <div className="t-bodysm" style={{color:"var(--neutral-700)"}}>You cannot save the programme until either (a) these regions are removed from scope, or (b) the partner's DSA is amended to include them. Submit a DSA amendment from the partner detail page.</div>
          </div>
        )}
      </div>
    </div>

    {/* Sub-county / district nudge */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>District / sub-county refinement</h3>
        <span className="t-cap">Optional · default is all districts within the selected sub-regions</span>
      </div>
      <div style={{padding:"18px 20px"}}>
        <div className="row gap-2"><Chip size="sm" tone="programme">all districts</Chip><span className="muted t-bodysm">in {data.geo_unit_ids.length || 0} sub-region{data.geo_unit_ids.length===1?'':'s'}</span></div>
        <div className="mt-3"><button className="btn btn-sm"><Icon name="mapPin" size={13}/> Refine by district</button> <span className="muted t-bodysm" style={{marginLeft:6}}>open the geographic tree picker</span></div>
      </div>
    </div>
  </div>
  );
};

/* ============================================================
   STEP 5 — Lifecycle & API
   ============================================================ */
const StepLifecycle = ({ data, setD, toggleInArr, exitOpts, autoOpts, webhookOpts }) => (
  <div className="col gap-4">

    {/* Exit reasons */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Allowed exit reasons</h3>
        <span className="t-cap">Codes the partner MIS may push when ending an enrolment · programme_exit_reason</span>
      </div>
      <div>
        {exitOpts.map(r => {
          const on = data.exit_codes_allowed.includes(r.code);
          const tone = EXIT_TONE[r.code] || "neutral";
          return (
            <div key={r.code} onClick={() => toggleInArr("exit_codes_allowed", r.code)} style={{
              padding:"12px 20px", borderBottom:"1px solid var(--neutral-200)",
              display:"grid", gridTemplateColumns:"24px 80px 200px 1fr 80px", gap:12, alignItems:"center",
              background: on ? `var(--accent-${tone}-bg)` : "transparent", opacity: on ? 1 : 0.7,
              cursor:"pointer",
            }}>
              <span style={{
                width:16, height:16, borderRadius:3, display:"grid", placeItems:"center",
                background: on ? `var(--accent-${tone})` : "var(--neutral-0)",
                border: on ? 0 : "1px solid var(--neutral-300)",
              }}>{on && <Icon name="check" size={11} color="white"/>}</span>
              <span className="t-mono" style={{fontSize:12, color:"var(--neutral-500)"}}>code {r.code}</span>
              <strong className="t-bodysm" style={{color: on ? `var(--accent-${tone})` : 'var(--neutral-900)'}}>{r.label}</strong>
              <span className="t-bodysm muted">&nbsp;</span>
              <span className="t-cap" style={{textAlign:"right"}}>{r.code === "80" || r.code === "60" ? "audit-only" : "auto-OK"}</span>
            </div>
          );
        })}
      </div>
    </div>

    {/* Auto-exit triggers + suspension */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Automatic exits & suspensions</h3>
        <span className="t-cap">Triggers the NSR runs nightly · partner is notified via webhook</span>
      </div>
      <div style={{padding:"6px 20px"}}>
        {autoOpts.map(t => {
          const on = data.auto_exit_triggers.includes(t.code);
          return (
            <label key={t.code} style={{display:"grid", gridTemplateColumns:"40px 1fr 80px", gap:12, alignItems:"center", padding:"12px 0", borderBottom:"1px solid var(--neutral-200)", cursor:"pointer"}}>
              <Toggle on={on} onChange={() => toggleInArr("auto_exit_triggers", t.code)}/>
              <div>
                <strong className="t-bodysm">{t.label}</strong>
                <div className="t-cap" style={{marginTop:2}}>{t.code}</div>
              </div>
              <Chip size="sm" tone="data">{on ? "on" : "off"}</Chip>
            </label>
          );
        })}
      </div>
      <div className="divider" style={{margin:0}}/>
      <div style={{padding:"14px 20px", background:"var(--neutral-50)", display:"flex", alignItems:"center", gap:12}}>
        <Toggle on={data.suspend_on_grievance} onChange={() => setD("suspend_on_grievance", !data.suspend_on_grievance)}/>
        <div style={{flex:1}}>
          <strong className="t-bodysm">Suspend on open grievance</strong>
          <div className="t-cap" style={{marginTop:2}}>Enrolment moves to <Chip size="sm" tone="quality">Suspended</Chip> while any L2+ grievance is open against this household · payments held</div>
        </div>
      </div>
    </div>

    {/* Webhook */}
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Programme MIS callback</h3>
        <span className="t-cap">Where the NSR pushes referral and enrolment events. HMAC-SHA256 signed.</span>
      </div>
      <div style={{padding:"18px 20px"}}>
        <Field label="Webhook URL" hint="Must be HTTPS · TLS 1.2+">
          <input className="field-input t-mono" placeholder="https://partner.example.go.ug/nsr/webhook" value={data.webhook_url} onChange={(e) => setD("webhook_url", e.target.value)}/>
        </Field>
        <div className="mt-4" style={{padding:"10px 12px", background:"var(--neutral-50)", border:"1px dashed var(--neutral-300)", borderRadius:4}}>
          <div className="t-cap" style={{marginBottom:4}}>Event types delivered</div>
          <div className="row-wrap">
            {webhookOpts.map(w => <Chip key={w.code} size="sm" tone="programme">{w.label}</Chip>)}
          </div>
        </div>
        <div className="t-cap mt-3">
          A webhook secret will be generated when you create the programme. It is displayed once — the partner IT/Sec contact must capture it then.
        </div>
      </div>
    </div>
  </div>
);

/* ============================================================
   PREVIEW RAIL
   ============================================================ */
const ProgPreview = ({ data, partner, activeDsa, kindMeta, estReach, totalPerBenef, totalBudget, cyclesInPeriod, outOfScopeGeo, cycleOpts, unitOpts, sexOpts, pmtOpts, compOpts, exitOpts, allGeoUnits }) => {
  const label = (opts, code, fallback = "—") => (opts.find(o => o.code === code) || { label: fallback }).label;
  const cycleLabel = label(cycleOpts, data.disbursement_cycle);
  const unitLabel  = label(unitOpts, data.unit_of_enrolment);
  const sexLabel   = label(sexOpts, data.sex_filter, "Any");
  const geoNames   = data.geo_unit_ids.map(id => {
    const g = allGeoUnits.find(u => u.id === id); return g ? g.name : id;
  });

  return (
  <aside style={{position:"sticky", top:72, alignSelf:"start"}}>
    <div className="card" style={{padding:0}}>
      <div style={{padding:"14px 16px", borderBottom:"1px solid var(--neutral-200)", background:"var(--accent-programme-bg)", borderTopLeftRadius:"var(--radius-card)", borderTopRightRadius:"var(--radius-card)"}}>
        <div className="t-cap" style={{color:"var(--accent-programme)", fontWeight:600, letterSpacing:"0.06em"}}>LIVE PREVIEW</div>
        <div className="row gap-2" style={{marginTop:6}}>
          <span style={{
            width:34, height:34, borderRadius:6, background:"var(--accent-programme)",
            color:"white", display:"grid", placeItems:"center",
            fontFamily:"'JetBrains Mono', monospace", fontSize:10, fontWeight:700, letterSpacing:"0.04em",
            flexShrink:0,
          }}>{(data.code || "—").slice(0,7)}</span>
          <div style={{minWidth:0, flex:1}}>
            <div style={{fontWeight:600, fontSize:14, lineHeight:1.3, color:"var(--neutral-900)", overflow:"hidden", display:"-webkit-box", WebkitLineClamp:2, WebkitBoxOrient:"vertical"}}>{data.name || "Untitled programme"}</div>
            <div className="t-cap mt-1">{kindMeta ? <Chip size="sm" tone="programme">{kindMeta.label}</Chip> : <span className="muted">no kind</span>}</div>
          </div>
        </div>
      </div>

      <div style={{padding:"14px 16px", display:"grid", gridTemplateColumns:"1fr 1fr", gap:12}}>
        <PreviewCell label="Run by"     value={partner ? partner.code : "—"} sub={partner ? partner.name : "—"}/>
        <PreviewCell label="DSA"        value={activeDsa ? <span className="t-mono" style={{fontSize:11.5}}>{activeDsa.reference.split("-").slice(0,3).join("-")}</span> : "—"} sub={activeDsa ? (activeDsa.status_label || activeDsa.status) : "none"}/>
        <PreviewCell label="Unit"       value={unitLabel} sub={data.unit_of_enrolment === "member" && data.sex_filter !== "any" ? `${sexLabel} · age ${data.age_min}-${data.age_max}` : "all"}/>
        <PreviewCell label="Cycle"      value={cycleLabel} sub={`${data.duration_months} months`}/>
        <PreviewCell label="Eligible"   value={estReach.toLocaleString()} sub="match all filters"/>
        <PreviewCell label="Cohort tgt" value={(data.cohort_target||0).toLocaleString()} sub={`${(data.cohort_target||0) > 0 && estReach > 0 ? Math.round(data.cohort_target/estReach*100) : 0}% of eligible`}/>
        <PreviewCell label="Per benef." value={`UGX ${(totalPerBenef/1000).toLocaleString()}k`} sub={`${cyclesInPeriod} × ${((data.amount_ugx||0)/1000).toLocaleString()}k`}/>
        <PreviewCell label="Total budget" value={`UGX ${(totalBudget/1000000).toFixed(1)}M`} sub={`${data.duration_months}-mo`}/>
      </div>

      {/* PMT bands */}
      <div style={{padding:"4px 16px 12px"}}>
        <div className="t-cap" style={{marginBottom:4}}>PMT BANDS</div>
        <div className="row-wrap">
          {data.pmt_bands.length === 0
            ? <span className="muted t-bodysm">none selected</span>
            : data.pmt_bands.map(c => <Chip key={c} size="sm" tone="eligibility">{pmtDisplayLabel(c, label(pmtOpts, c, c))}</Chip>)}
        </div>
      </div>

      {/* Geo */}
      <div style={{padding:"4px 16px 14px"}}>
        <div className="row gap-2" style={{marginBottom:4}}>
          <span className="t-cap">GEO · {data.geo_unit_ids.length} REGION{data.geo_unit_ids.length===1?'':'S'}</span>
          {outOfScopeGeo.length > 0 && <Chip size="sm" tone="danger" icon="alert">{outOfScopeGeo.length} OOS</Chip>}
        </div>
        <div className="row-wrap">
          {geoNames.length === 0
            ? <span className="muted t-bodysm">none</span>
            : geoNames.map((n, i) => <Chip key={i} size="sm" tone={outOfScopeGeo.includes(data.geo_unit_ids[i]) ? "danger" : "data"}>{n}</Chip>)}
        </div>
      </div>

      {/* Composition flags */}
      <div style={{padding:"4px 16px 14px"}}>
        <div className="t-cap" style={{marginBottom:4}}>COMPOSITION FLAGS</div>
        <div className="row-wrap">
          {data.composition_flags.length === 0
            ? <span className="muted t-bodysm">none</span>
            : data.composition_flags.map(c => <Chip key={c} size="sm" tone="data">{label(compOpts, c, c)}</Chip>)}
        </div>
      </div>

      {/* Exit codes */}
      <div style={{padding:"4px 16px 16px"}}>
        <div className="t-cap" style={{marginBottom:4}}>EXIT CODES ALLOWED</div>
        <div className="row-wrap">
          {data.exit_codes_allowed.length === 0
            ? <span className="muted t-bodysm">none</span>
            : data.exit_codes_allowed.map(c => {
              const opt = exitOpts.find(x => x.code === c);
              const tone = EXIT_TONE[c] || "neutral";
              return <span key={c} title={opt ? opt.label : c} style={{
                width:24, height:24, borderRadius:4, background:`var(--accent-${tone})`, color:"white",
                fontFamily:"'JetBrains Mono', monospace", fontSize:11, fontWeight:600,
                display:"grid", placeItems:"center",
              }}>{c}</span>;
            })}
        </div>
      </div>
    </div>

    <div className="t-cap mt-3" style={{padding:"0 4px", textAlign:"center"}}>
      Saved as a draft until the {partner ? partner.code : "partner"} Data Steward signs off · AC-AUDIT-EVENT
    </div>
  </aside>
  );
};

const PreviewCell = ({ label, value, sub }) => (
  <div style={{minWidth:0}}>
    <div className="t-cap" style={{textTransform:"uppercase", letterSpacing:"0.04em", fontSize:11}}>{label}</div>
    <div className="t-bodysm" style={{fontWeight:600, color:"var(--neutral-900)", marginTop:2, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{value || "—"}</div>
    {sub && <div className="t-cap" style={{marginTop:1, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{sub}</div>}
  </div>
);

/* ============================================================
   Tiny widgets
   ============================================================ */

const Toggle = ({ on, onChange }) => (
  <button onClick={onChange} type="button" style={{
    width:34, height:20, borderRadius:10, border:0, position:"relative",
    background: on ? "var(--primary-700)" : "var(--neutral-300)",
    cursor:"pointer", padding:0,
    transition:"background 0.15s ease",
  }}>
    <span style={{
      position:"absolute", top:2, left: on ? 16 : 2,
      width:16, height:16, borderRadius:"50%", background:"white",
      transition:"left 0.15s ease",
      boxShadow:"0 1px 2px rgba(0,0,0,0.2)",
    }}/>
  </button>
);

/* Dual-handle range bar */
const RangeBar = ({ min, max, valMin, valMax, onChange }) => {
  const span = max - min;
  const pctMin = ((valMin - min) / span) * 100;
  const pctMax = ((valMax - min) / span) * 100;
  return (
    <div>
      <div className="row gap-2" style={{justifyContent:"space-between", marginBottom:8}}>
        <div className="t-bodysm"><span className="muted">from </span><strong>{valMin}</strong></div>
        <div className="t-bodysm"><span className="muted">to </span><strong>{valMax}</strong> <span className="muted">years</span></div>
      </div>
      <div style={{position:"relative", height:32, padding:"12px 0"}}>
        <div style={{position:"absolute", top:14, left:0, right:0, height:4, background:"var(--neutral-200)", borderRadius:2}}/>
        <div style={{position:"absolute", top:14, left:pctMin+"%", width:(pctMax-pctMin)+"%", height:4, background:"var(--primary-700)", borderRadius:2}}/>
        <input type="range" min={min} max={max} value={valMin} onChange={(e) => onChange(Math.min(+e.target.value, valMax), valMax)} style={rangeStyle}/>
        <input type="range" min={min} max={max} value={valMax} onChange={(e) => onChange(valMin, Math.max(+e.target.value, valMin))} style={rangeStyle}/>
      </div>
    </div>
  );
};
const rangeStyle = {
  position:"absolute", top:8, left:0, width:"100%", height:16, background:"transparent",
  pointerEvents:"none", WebkitAppearance:"none", appearance:"none",
};

const CoverageBar = ({ target, pool }) => {
  if (pool <= 0) return <div className="t-cap mt-3">No eligible pool yet — adjust the filters above.</div>;
  const pct = Math.min(100, (target / pool) * 100);
  const over = target > pool;
  return (
    <div className="mt-4">
      <div className="row gap-2" style={{justifyContent:"space-between", marginBottom:4}}>
        <span className="t-cap">target coverage</span>
        <span className="t-bodysm" style={{fontWeight:600, color: over ? "var(--accent-danger)" : "var(--accent-data)"}}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{height:8, borderRadius:4, background:"var(--neutral-200)", overflow:"hidden"}}>
        <div style={{height:"100%", width:pct+"%", background: over ? "var(--accent-danger)" : "var(--accent-data)"}}/>
      </div>
      {over && <div className="t-cap mt-2" style={{color:"var(--accent-danger)"}}>Cohort target exceeds the eligible pool — broaden filters or lower the target.</div>}
    </div>
  );
};

const BudgetCell = ({ label, value, sub, tone }) => (
  <div style={{padding:14, borderRadius:6, border:`1px solid var(--neutral-200)`, borderLeft:`3px solid var(--accent-${tone})`, background:"var(--neutral-0)"}}>
    <div className="t-cap" style={{textTransform:"uppercase", letterSpacing:"0.06em"}}>{label}</div>
    <div style={{fontSize:22, fontWeight:700, marginTop:2, color:"var(--neutral-900)", letterSpacing:"-0.01em", fontVariantNumeric:"tabular-nums"}}>{value}</div>
    <div className="t-cap mt-1">{sub}</div>
  </div>
);

const PaymentTimeline = ({ cycles, cycleCode, amount, duration }) => {
  if (cycles === 0) return null;
  const maxBars = Math.min(cycles, 24);
  const prefix = CYCLE_BAR_LABEL[cycleCode] || "c";
  const labels = cycleCode === "one_off"
    ? ["one-off"]
    : Array.from({length: maxBars}, (_, i) => `${prefix}${i+1}`);
  return (
    <div style={{borderTop:"1px solid var(--neutral-200)", paddingTop:14}}>
      <div className="t-cap" style={{marginBottom:8}}>PAYMENT CALENDAR · {cycles} cycle{cycles===1?'':'s'} over {duration} months</div>
      <div style={{display:"flex", alignItems:"flex-end", gap:3, height:60}}>
        {labels.map((l, i) => (
          <div key={i} style={{flex:1, display:"flex", flexDirection:"column", alignItems:"center", gap:4, minWidth:0}}>
            <div title={`${l} · UGX ${((amount||0)/1000).toLocaleString()}k`} style={{width:"100%", height: 36+(i%4)*4, background:"var(--accent-programme)", borderRadius:"2px 2px 0 0", opacity: 0.65 + (i%3)*0.1}}/>
            <span className="t-cap" style={{fontSize:10, fontVariantNumeric:"tabular-nums"}}>{l}</span>
          </div>
        ))}
        {cycles > maxBars && <div style={{padding:"0 8px"}} className="t-cap">+{cycles-maxBars} more</div>}
      </div>
    </div>
  );
};

/* expose to window so app.jsx can pick it up */
Object.assign(window, { ProgrammeRegistrationScreen });
