/* global React, Icon, Chip, PageHeader, Modal, Field, Toast */
// NSR MIS — 11.7 DRS Query Builder + Field Selector

const { useState: useStateDRS } = React;

const STEPS = [
  { id: "scope",    label: "Scope",          icon: "target" },
  { id: "build",    label: "Build",          icon: "filter" },
  { id: "fields",   label: "Field Selector", icon: "sliders" },
  { id: "preview",  label: "Preview",        icon: "eye" },
  { id: "delivery", label: "Delivery",       icon: "download" },
  { id: "submit",   label: "Submit",         icon: "check" },
];

const FIELDS = [
  // group, name, sensitivity, disabled?, reason
  ["Identifiers", "registry_id",        "Public",    false],
  ["Identifiers", "household_number",   "Public",    false],
  ["Identifiers", "captured_date",      "Public",    false],
  ["Identifiers", "captured_parish",    "Internal",  false],
  ["Geography",   "subregion",          "Public",    false],
  ["Geography",   "district",           "Public",    false],
  ["Geography",   "subcounty",          "Public",    false],
  ["Geography",   "parish",             "Internal",  false],
  ["Geography",   "village",            "Internal",  false],
  ["Geography",   "gps_lat",            "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["Geography",   "gps_lng",            "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["Household",   "household_size",     "Public",    false],
  ["Household",   "head_sex",           "Public",    false],
  ["Household",   "head_age_band",      "Public",    false],
  ["Household",   "head_education",     "Internal",  false],
  ["Identity",    "nin_value",          "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["Identity",    "head_name",          "Personal",  false],
  ["Identity",    "phone",              "Personal",  false],
  ["Identity",    "photo_ref",          "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["PMT",         "pmt_score",          "Internal",  false],
  ["PMT",         "pmt_band",           "Internal",  false],
  ["Housing",     "roof_material",      "Internal",  false],
  ["Housing",     "walls_material",     "Internal",  false],
  ["Housing",     "toilet_type",        "Internal",  false],
  ["Housing",     "water_source",       "Internal",  false],
  ["Wealth",      "household_savings_amount", "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
];

const PREVIEW_ROWS = [
  { rid: "01HXY7K3B2N9PVQE4M6FZRWS18", hh: "HH-7411-002-0148", parish: "Nakiloro", subreg: "Karamoja", size: 6, sex: "F", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••4567" },
  { rid: "01HXZ9MR4N8P2QFB7K6FZRWS33", hh: "HH-3122-005-0091", parish: "Pageya",  subreg: "Acholi",   size: 5, sex: "F", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••2119" },
  { rid: "01HY09KRS1P9MN6FB7K6FZRWS84", hh: "HH-7411-002-0103", parish: "Kakingol",subreg: "Karamoja", size: 7, sex: "M", age: "40-49", band: "Poorest 20%", roof: "Iron sheets", phone: "+256 ••• ••8221" },
  { rid: "01HY02FNQ9P8MN6FB7K6FZRWS67", hh: "HH-7531-001-0048", parish: "Lorengedwat", subreg: "Karamoja", size: 6, sex: "F", age: "20-29", band: "Poorest 20%", roof: "Thatch",      phone: "+256 ••• ••5582" },
  { rid: "01HY04MQR0N8P2FB7K6FZRWS73", hh: "HH-7531-002-0017", parish: "Apeitolim", subreg: "Karamoja", size: 8, sex: "F", age: "40-49", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••6620" },
  { rid: "01HXP02CN4QFB7K6FZRWS00111", hh: "HH-2110-008-0021", parish: "Anyiribu", subreg: "West Nile", size: 4, sex: "M", age: "50-59", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••0044" },
  { rid: "01HXP02CN4QFB7K6FZRWS00118", hh: "HH-2110-008-0033", parish: "Logiri",   subreg: "West Nile", size: 7, sex: "M", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••9912" },
  { rid: "01HXP02CN4QFB7K6FZRWS00124", hh: "HH-3122-009-0019", parish: "Bobi",     subreg: "Acholi",    size: 5, sex: "F", age: "20-29", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••3322" },
  { rid: "01HXP02CN4QFB7K6FZRWS00135", hh: "HH-2110-008-0040", parish: "Kuluba",   subreg: "West Nile", size: 4, sex: "F", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••7711" },
  { rid: "01HXP02CN4QFB7K6FZRWS00148", hh: "HH-7411-002-0211", parish: "Tapac",    subreg: "Karamoja",  size: 6, sex: "F", age: "40-49", band: "Poorest 20%", roof: "Iron sheets", phone: "+256 ••• ••1188" },
];

const DRSScreen = () => {
  const [step, setStep] = useStateDRS("build");
  const [selectedFields, setSel] = useStateDRS(new Set(["registry_id","subregion","district","parish","household_size","pmt_band","roof_material"]));
  const [submitOpen, setSubmitOpen] = useStateDRS(false);
  const [toast, setToast] = useStateDRS("");
  const stepIdx = STEPS.findIndex(s => s.id === step);

  const next = () => setStep(STEPS[Math.min(stepIdx + 1, STEPS.length - 1)].id);
  const prev = () => setStep(STEPS[Math.max(stepIdx - 1, 0)].id);

  const toggleField = (name, disabled, reason) => {
    if (disabled) return;
    const next = new Set(selectedFields);
    if (next.has(name)) next.delete(name); else next.add(name);
    setSel(next);
  };

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow="DATA REQUESTS · US-097, US-098"
        title="DRS query builder"
        sub={<>Requester: OPM Data Office · Active DSA <span className="t-mono">DSA-OPM-PDM-2026</span> · valid 01 Jan 2026 — 31 Dec 2026</>}
        right={<>
          <button className="btn"><Icon name="save" size={14}/> Save as template</button>
          <button className="btn btn-ghost"><Icon name="x" size={14}/> Discard</button>
        </>}
      />

      {/* Step indicator */}
      <div className="card" style={{padding:'14px 20px', marginBottom:16, display:'flex', alignItems:'center', gap:0}}>
        {STEPS.map((s, i) => {
          const done = i < stepIdx;
          const active = i === stepIdx;
          return (
            <React.Fragment key={s.id}>
              <button onClick={() => setStep(s.id)} style={{
                display:'flex', alignItems:'center', gap:8,
                padding:'4px 12px', border:0, background:'transparent', cursor:'pointer',
                color: active ? 'var(--accent-system)' : done ? 'var(--neutral-700)' : 'var(--neutral-500)',
                fontWeight: active ? 600 : 500, fontSize:13.5,
              }}>
                <span style={{
                  width:24, height:24, borderRadius:'50%', display:'grid', placeItems:'center',
                  background: active ? 'var(--accent-system)' : done ? 'var(--accent-system-bg)' : 'var(--neutral-100)',
                  color: active ? 'white' : done ? 'var(--accent-system)' : 'var(--neutral-500)',
                  fontSize:12, fontWeight:600,
                  border: active ? 0 : `1px solid ${done ? 'var(--accent-system)' : 'var(--neutral-300)'}`,
                }}>{done ? <Icon name="check" size={12}/> : i+1}</span>
                {s.label}
              </button>
              {i < STEPS.length - 1 && <div style={{flex:1, height:1, background: i < stepIdx ? 'var(--accent-system)' : 'var(--neutral-300)', minWidth:14}}/>}
            </React.Fragment>
          );
        })}
      </div>

      {step === 'scope' && <ScopeStep/>}
      {step === 'build' && <BuildStep/>}
      {step === 'fields' && <FieldStep selected={selectedFields} onToggle={toggleField}/>}
      {step === 'preview' && <PreviewStep selected={selectedFields}/>}
      {step === 'delivery' && <DeliveryStep/>}
      {step === 'submit' && <SubmitStep onSubmit={() => setSubmitOpen(true)} selected={selectedFields}/>}

      {/* Action bar */}
      <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20, background:'var(--neutral-0)', borderTop:'1px solid var(--neutral-300)', padding:'12px 20px', display:'flex', gap:12, alignItems:'center', boxShadow:'0 -2px 8px rgba(0,0,0,0.04)'}}>
        <span className="t-bodysm muted">Step {stepIdx + 1} of {STEPS.length} · <strong style={{color:'var(--neutral-900)'}}>{STEPS[stepIdx].label}</strong></span>
        <div style={{flex:1}}/>
        <button className="btn" onClick={prev} disabled={stepIdx === 0}><Icon name="chevronLeft" size={14}/> Back</button>
        {stepIdx < STEPS.length - 1
          ? <button className="btn btn-primary" onClick={next}>Continue <Icon name="chevronRight" size={14}/></button>
          : <button className="btn btn-primary" onClick={() => setSubmitOpen(true)}><Icon name="check" size={14}/> Submit for approval</button>
        }
      </div>

      <Modal open={submitOpen} onClose={() => setSubmitOpen(false)} title="Submit data request" width={520}
        footer={<>
          <button className="btn" onClick={() => setSubmitOpen(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => { setSubmitOpen(false); setToast("Data request submitted. DRS Reviewer will approve within 2 working days."); }}><Icon name="check" size={14}/> Submit</button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>Request <span className="t-mono">DRS-2026-05-14-00088</span> will be sent to <strong>NSR Unit DRS Reviewer</strong> and the <strong>DPO</strong> for approval.</p>
          <div style={{display:'grid', gridTemplateColumns:'130px 1fr', rowGap:6, fontSize:13}}>
            <div className="muted">Entity</div><div>Household</div>
            <div className="muted">Filters</div><div>3 rows (AND) · Karamoja + West Nile · Poorest 40% · updated since 1 Apr</div>
            <div className="muted">Fields</div><div>{selectedFields.size} of {FIELDS.length} (8 sensitive disabled)</div>
            <div className="muted">Match estimate</div><div>~47,233 rows</div>
            <div className="muted">DSA budget</div><div>1.8M / 2.5M rows for May 2026</div>
            <div className="muted">Delivery</div><div>Excel · password-protected · 7-day TTL</div>
          </div>
          <div className="tint-update" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
            <div className="row gap-2"><Icon name="shield" size={14} color="var(--accent-update)"/><strong className="t-bodysm">DPIA + DPO review required</strong></div>
            <p className="t-bodysm" style={{margin:'4px 0 0', color:'var(--neutral-700)'}}>The DPO is notified automatically. Query hash and field selection are logged for the cumulative-volume console (US-103).</p>
          </div>
        </div>
      </Modal>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

/* ============================================================
   Step 1 — Scope
   ============================================================ */
const ScopeStep = () => (
  <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Choose entity</h3><span className="t-cap">Only entities allowed by your active DSA</span></div>
      <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:12}}>
        {[
          ["Household","12.1M records · primary entity", true, true],
          ["Member","48.1M records · per-individual",   true, false],
          ["Referral summary","Programme referrals · aggregated", true, false],
          ["Grievance summary","Case-level summary",   false, false],
        ].map(([name, sub, allowed, selected]) => (
          <button key={name} disabled={!allowed} style={{
            textAlign:'left', padding:16, borderRadius:6,
            border: `2px solid ${selected ? 'var(--accent-system)' : 'var(--neutral-300)'}`,
            background: selected ? 'var(--accent-system-bg)' : !allowed ? 'var(--neutral-100)' : 'var(--neutral-0)',
            opacity: allowed ? 1 : 0.5, cursor: allowed ? 'pointer' : 'not-allowed',
          }}>
            <div className="row gap-2"><strong>{name}</strong>{selected && <Icon name="check" size={14} color="var(--accent-system)"/>}</div>
            <div className="t-cap mt-1">{sub}</div>
            {!allowed && <div className="t-cap mt-2" style={{color:'var(--accent-danger)'}}><Icon name="lock" size={11}/> Not in DSA scope</div>}
          </button>
        ))}
      </div>
    </div>
    <DSACard/>
  </div>
);

/* ============================================================
   Step 2 — Build
   ============================================================ */
const BuildStep = () => (
  <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
    <div className="card">
      <div className="card-header">
        <div>
          <h3 className="t-h3" style={{margin:0}}>Filter expression</h3>
          <div className="t-cap">Group: AND · type-aware operators</div>
        </div>
        <button className="btn btn-sm"><Icon name="plus" size={14}/> Add filter</button>
      </div>
      <div style={{padding:16, position:'relative'}}>
        <div style={{position:'absolute', left:36, top:32, bottom:32, width:2, background:'var(--neutral-200)', borderRadius:1}}/>

        <FilterRow op="AND" first field="Sub-region" cmp="IN" value={["Karamoja","West Nile"]}/>
        <FilterRow op="AND" field="PMT band" cmp="IN" value={["Poorest 40%","Poorest 20%"]}/>
        <FilterRow op="AND" field="Updated at" cmp="BETWEEN" value={["1 Apr 2026","14 May 2026"]}/>

        <div style={{paddingLeft:64, marginTop:8}}>
          <button className="btn btn-sm btn-ghost"><Icon name="plus" size={13}/> Add condition</button>
          <button className="btn btn-sm btn-ghost" style={{marginLeft:6}}><Icon name="git" size={13}/> Add nested group</button>
        </div>

        <div className="divider"/>

        <div className="t-cap mb-2" style={{marginBottom:6}}>EXPRESSION PREVIEW</div>
        <div className="t-mono" style={{padding:12, background:'var(--neutral-50)', borderRadius:4, fontSize:12, lineHeight:1.6, color:'var(--neutral-900)', whiteSpace:'pre-wrap', border:'1px solid var(--neutral-200)'}}>
{`AND (
  subregion IN ('Karamoja', 'West Nile'),
  pmt_band IN ('Poorest 40%', 'Poorest 20%'),
  updated_at BETWEEN '2026-04-01' AND '2026-05-14'
)`}
        </div>
      </div>
    </div>

    <div className="col gap-3">
      <DSACard/>
      <div className="card">
        <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>Geographic tree picker</h3><span className="t-cap">UBOS 2024 frame</span></div>
        <div style={{padding:14}}>
          <GeoTree/>
        </div>
      </div>
    </div>
  </div>
);

const FilterRow = ({ op, field, cmp, value, first }) => (
  <div style={{display:'flex', gap:10, marginBottom:8, alignItems:'center'}}>
    <div style={{width:56, textAlign:'right'}}>
      {first ? <span className="t-cap">WHERE</span>
        : <Chip size="sm" tone="system">{op}</Chip>}
    </div>
    <div style={{flex:1, display:'grid', gridTemplateColumns:'180px 130px 1fr auto', gap:8, padding:'8px 10px', background:'var(--neutral-0)', border:'1px solid var(--neutral-300)', borderRadius:4}}>
      <select className="field-select" style={{height:28, fontSize:12.5}}><option>{field}</option></select>
      <select className="field-select" style={{height:28, fontSize:12.5}}><option>{cmp}</option></select>
      <div className="row-wrap" style={{padding:'4px 8px', background:'var(--neutral-50)', borderRadius:3, border:'1px solid var(--neutral-200)'}}>
        {value.map((v, i) => <Chip key={i} size="sm">{v}</Chip>)}
        <span className="t-cap">+ add value</span>
      </div>
      <button className="btn btn-sm btn-ghost"><Icon name="x" size={14}/></button>
    </div>
  </div>
);

const GeoTree = () => (
  <div className="t-bodysm">
    {[
      ["Karamoja", true, "selected · 4 districts"],
      ["West Nile", true, "selected · 5 districts"],
      ["Acholi", false, ""],
      ["Lango", false, ""],
      ["Teso", false, ""],
    ].map(([name, on, sub]) => (
      <div key={name} style={{padding:'6px 8px', borderRadius:3, background: on ? 'var(--accent-system-bg)' : 'transparent', display:'flex', alignItems:'center', gap:8, marginBottom:2}}>
        <input type="checkbox" checked={on} readOnly/>
        <div style={{flex:1}}>
          <div style={{fontWeight: on ? 600 : 400}}>{name}</div>
          {sub && <div className="t-cap">{sub}</div>}
        </div>
        <Icon name="chevronRight" size={14} color="var(--neutral-500)"/>
      </div>
    ))}
  </div>
);

/* ============================================================
   DSA card (shared)
   ============================================================ */
const DSACard = () => (
  <div className="card" style={{borderTop:'3px solid var(--accent-system)'}}>
    <div className="card-header" style={{padding:'12px 16px'}}>
      <div>
        <div className="t-cap" style={{color:'var(--accent-system)'}}>ACTIVE DSA</div>
        <h3 className="t-h3" style={{margin:'2px 0 0'}}>DSA-OPM-PDM-2026</h3>
      </div>
      <Chip tone="data">Active</Chip>
    </div>
    <div style={{padding:16}}>
      <div style={{display:'grid', gridTemplateColumns:'110px 1fr', rowGap:6, fontSize:13}}>
        <div className="muted">Partner</div><div>Office of the Prime Minister</div>
        <div className="muted">Programme</div><div>OPM-PDM 2026</div>
        <div className="muted">Valid from</div><div>1 Jan 2026</div>
        <div className="muted">Valid to</div><div>31 Dec 2026 <Chip size="sm" tone="data">8 months left</Chip></div>
        <div className="muted">Row budget</div><div>2,500,000 / month</div>
        <div className="muted">Used this month</div><div>1,824,317 (73%)</div>
      </div>
      <div style={{height:6, background:'var(--neutral-200)', borderRadius:3, marginTop:10, overflow:'hidden'}}>
        <div style={{width:'73%', height:'100%', background:'var(--accent-system)'}}/>
      </div>
      <div className="t-cap mt-3">Sensitive fields: <strong>4 disabled</strong> by clause 4.2.b.</div>
      <button className="btn btn-sm mt-3" style={{width:'100%'}}><Icon name="file" size={13}/> Open DSA document</button>
    </div>
  </div>
);

/* ============================================================
   Step 3 — Field Selector
   ============================================================ */
const FieldStep = ({ selected, onToggle }) => {
  const groups = FIELDS.reduce((acc, f) => { (acc[f[0]] = acc[f[0]] || []).push(f); return acc; }, {});
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 320px', gap:16}}>
      <div className="card">
        <div className="card-header">
          <div>
            <h3 className="t-h3" style={{margin:0}}>Field selector</h3>
            <div className="t-cap">{selected.size} selected · {FIELDS.filter(f => f[3]).length} sensitive fields disabled</div>
          </div>
          <div className="row gap-2">
            <button className="btn btn-sm">Select all available</button>
            <button className="btn btn-sm btn-ghost"><Icon name="save" size={14}/> Save selection</button>
          </div>
        </div>
        <div>
          {Object.entries(groups).map(([group, fields]) => (
            <React.Fragment key={group}>
              <div style={{padding:'10px 20px', background:'var(--neutral-100)', borderBottom:'1px solid var(--neutral-200)', fontSize:12, fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--neutral-700)'}}>
                {group}
              </div>
              {fields.map(([, name, sens, disabled, reason]) => (
                <div key={name} title={reason || ""} onClick={() => onToggle(name, disabled, reason)} style={{
                  padding:'10px 20px', borderBottom:'1px solid var(--neutral-200)',
                  display:'grid', gridTemplateColumns:'24px 1fr 120px 200px', alignItems:'center', gap:12,
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  background: selected.has(name) ? 'var(--accent-system-bg)' : disabled ? 'var(--neutral-50)' : 'transparent',
                  opacity: disabled ? 0.7 : 1,
                }}>
                  <input type="checkbox" checked={selected.has(name)} disabled={disabled} readOnly/>
                  <div className="t-mono" style={{fontSize:13, color: disabled ? 'var(--neutral-500)' : 'var(--neutral-900)'}}>{name}</div>
                  <Chip>{sens}</Chip>
                  <div className="t-cap" style={{color: disabled ? 'var(--accent-danger)' : 'var(--neutral-500)'}}>
                    {disabled ? <><Icon name="lock" size={11}/> DSA clause 4.2.b</> : "Available under DSA"}
                  </div>
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </div>

      <div className="col gap-3">
        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>Sensitivity legend</h3></div>
          <div style={{padding:14, display:'flex', flexDirection:'column', gap:10}}>
            {[["Public", "Geography rolled up; aggregate counts"],
              ["Internal", "Programme-level reporting"],
              ["Personal", "Identifies a person; PII"],
              ["Sensitive", "Identifies + categorical risk; requires expansion"]].map(([s, desc]) => (
              <div key={s} className="row gap-3">
                <Chip>{s}</Chip>
                <span className="t-bodysm muted">{desc}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{borderLeft:'3px solid var(--accent-danger)'}}>
          <div style={{padding:14}}>
            <div className="row gap-2" style={{marginBottom:4}}>
              <Icon name="lock" size={14} color="var(--accent-danger)"/>
              <strong className="t-bodysm">DSA-clause guard</strong>
            </div>
            <div className="t-bodysm muted">
              Fields marked <Chip size="sm">Sensitive</Chip> are blocked by clause 4.2.b of your active DSA. To enable, request a scope expansion via your data steward.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ============================================================
   Step 4 — Preview
   ============================================================ */
const PreviewStep = ({ selected }) => {
  const cols = [
    ["Registry ID", "rid", "mono"],
    ["Household number", "hh", "mono"],
    ["Sub-region", "subreg"],
    ["Parish", "parish"],
    ["HH size", "size"],
    ["Sex (head)", "sex"],
    ["Age band (head)", "age"],
    ["PMT band", "band"],
    ["Roof", "roof"],
    ["Phone (masked)", "phone", "mono"],
  ];
  return (
    <div className="col gap-4">
      <div className="card" style={{padding:16, display:'flex', alignItems:'center', gap:24}}>
        <div>
          <div className="t-cap">MATCHED</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>47,233</div>
          <div className="t-cap">of 12,089,442 households (0.39%)</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">PREVIEW SHOWN</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>10</div>
          <div className="t-cap">server-side masked sample</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">QUERY HASH</div>
          <div className="t-mono" style={{fontSize:13.5, fontWeight:600}}>a4e9d2f1…b7c3</div>
          <div className="t-cap">written to DPO console</div>
        </div>
        <div style={{flex:1}}/>
        <button className="btn"><Icon name="refresh" size={14}/> Refresh preview</button>
      </div>

      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">Preview rows (masked)</strong>
          <span className="t-cap">Phone last 4 digits revealed only · IDs always full · sensitive fields excluded</span>
        </div>
        <div style={{overflowX:'auto'}}>
          <table className="tbl">
            <thead><tr>{cols.map(c => <th key={c[1]}>{c[0]}</th>)}</tr></thead>
            <tbody>
              {PREVIEW_ROWS.map((r, i) => (
                <tr key={i}>
                  {cols.map(c => (
                    <td key={c[1]} className={c[2] === 'mono' ? 'col-id' : ''}>
                      {c[1] === 'rid' ? r.rid.slice(0, 22) + '…' : r[c[1]]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

/* ============================================================
   Step 5 — Delivery
   ============================================================ */
const DeliveryStep = () => {
  const [choice, setChoice] = useStateDRS("excel");
  const opts = [
    { id: "excel", title: "Excel · password-protected",      sub: "Single .xlsx · sent to recipient list · ~18 MB · 7d TTL", icon: "file" },
    { id: "csv",   title: "CSV · 7z password-protected",     sub: "UTF-8 CSV inside 7-zip archive · ~5 MB · 7d TTL", icon: "file" },
    { id: "api",   title: "Paginated API · token endpoint",  sub: "Pull pages of 1,000 · 30d token · throttled 60 req/min", icon: "database" },
  ];
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
      <div className="card">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Delivery channel</h3></div>
        <div style={{padding:16, display:'flex', flexDirection:'column', gap:10}}>
          {opts.map(o => (
            <button key={o.id} onClick={() => setChoice(o.id)} style={{
              textAlign:'left', padding:16, borderRadius:6,
              border:`2px solid ${choice === o.id ? 'var(--accent-system)' : 'var(--neutral-300)'}`,
              background: choice === o.id ? 'var(--accent-system-bg)' : 'var(--neutral-0)',
              display:'flex', alignItems:'center', gap:14, cursor:'pointer',
            }}>
              <div style={{width:36, height:36, borderRadius:6, background:'var(--neutral-100)', display:'grid', placeItems:'center'}}><Icon name={o.icon} size={18}/></div>
              <div style={{flex:1}}>
                <div className="row gap-2"><strong>{o.title}</strong>{choice === o.id && <Icon name="check" size={14} color="var(--accent-system)"/>}</div>
                <div className="t-cap">{o.sub}</div>
              </div>
            </button>
          ))}

          <div className="divider"/>

          <Field label="Recipient list (must match DSA)" required>
            <input className="field-input" defaultValue="data@opm.go.ug; steward.opm@pdm.go.ug"/>
          </Field>
          <Field label="Password (sent via separate channel)" required>
            <input className="field-input t-mono" type="password" defaultValue="P5!nKLqV2x"/>
          </Field>
        </div>
      </div>
      <DSACard/>
    </div>
  );
};

/* ============================================================
   Step 6 — Submit
   ============================================================ */
const SubmitStep = ({ onSubmit, selected }) => (
  <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Purpose, retention, recipients</h3></div>
      <div style={{padding:16}}>
        <Field label="Purpose of use" required hint="Will be reviewed by DPO under US-101.">
          <textarea className="field-textarea" rows={3} defaultValue="Identify candidate households in Karamoja and West Nile for the OPM-PDM Q2 2026 supplementary disbursement, restricted to the Poorest 40% PMT band updated in the last 6 weeks."/>
        </Field>
        <div className="field-row mt-4">
          <Field label="Retention pledge" required>
            <select className="field-select"><option>Retain 90 days, then destroy</option><option>Retain 180 days</option><option>Retain 12 months</option></select>
          </Field>
          <Field label="Aggregation level" required>
            <select className="field-select"><option>Row-level (PII masked)</option><option>Parish aggregate</option><option>District aggregate</option></select>
          </Field>
        </div>
        <Field label="Recipient list (DSA-linked)" required>
          <input className="field-input" defaultValue="data@opm.go.ug; steward.opm@pdm.go.ug; nsr-unit@mglsd.go.ug"/>
        </Field>
      </div>
    </div>
    <div className="col gap-3">
      <div className="card">
        <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>Summary</h3></div>
        <div style={{padding:16, display:'grid', gridTemplateColumns:'130px 1fr', rowGap:6, fontSize:13}}>
          <div className="muted">Entity</div><div>Household</div>
          <div className="muted">Filters</div><div>3 (AND group)</div>
          <div className="muted">Fields</div><div>{selected.size}</div>
          <div className="muted">Match estimate</div><div>~47,233</div>
          <div className="muted">Delivery</div><div>Excel · 7d TTL</div>
          <div className="muted">Query hash</div><div className="t-mono">a4e9d2f1…b7c3</div>
        </div>
      </div>
      <DSACard/>
    </div>
  </div>
);

Object.assign(window, { DRSScreen });
