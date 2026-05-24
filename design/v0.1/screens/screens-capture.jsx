/* global React, Icon, Chip, KPI, PageHeader, Field, GeoTreePicker, Modal, ReasonModal, ActionBar,
   useChoiceList,
   RosterSection, HealthDisabilitySection, EducationSection, EmploymentSection,
   HousingSection, FoodShocksSection */
// NSR MIS — 11.1 Parish capture + 11.2 Receipt slip

const { useState: useStateCap } = React;

const SECTIONS = [
  { id: "id",    label: "Identification",     tint: "data",     icon: "mapPin" },
  { id: "rost",  label: "Roster",             tint: "identity", icon: "users" },
  { id: "hd",    label: "Health & Disability",tint: "danger",   icon: "shield" },
  { id: "ed",    label: "Education",          tint: "update",   icon: "book" },
  { id: "emp",   label: "Employment",         tint: "programme",icon: "users" },
  { id: "hous",  label: "Housing",            tint: "eligibility",icon:"home" },
  { id: "food",  label: "Food & Shocks",      tint: "grm",      icon: "alert" },
];
// Demo seed: Lokol Naume as head + spouse + 3 children. Operators
// start from an empty list in production; this seed makes the
// preview look populated.
const _DEMO_MEMBERS = [
  { line_number: 1, surname: "Lokol", first_name: "Naume", other_name: "",
    relationship_to_head: "01", sex: "2", date_of_birth: "1992-03-12",
    age_years: 33, marital_status: "1", nationality: "1", residency_status: "1",
    birth_certificate_status: "1", nin_status: "1", nin_last4: "1234",
    telephone_1: "+256 786 234567", telephone_2: "" },
  { line_number: 2, surname: "Lokol", first_name: "Akello", other_name: "",
    relationship_to_head: "03", sex: "2", date_of_birth: "1989-08-04",
    age_years: 36, marital_status: "1", nationality: "1", residency_status: "1",
    birth_certificate_status: "1", nin_status: "1", nin_last4: "5678",
    telephone_1: "", telephone_2: "" },
  { line_number: 3, surname: "Lokol", first_name: "Atim", other_name: "",
    relationship_to_head: "04", sex: "2", date_of_birth: "2014-05-22",
    age_years: 11, marital_status: "8", nationality: "1", residency_status: "1",
    birth_certificate_status: "1", nin_status: "8", nin_last4: "",
    telephone_1: "", telephone_2: "" },
  { line_number: 4, surname: "Lokol", first_name: "Okello", other_name: "",
    relationship_to_head: "04", sex: "1", date_of_birth: "2017-11-08",
    age_years: 8, marital_status: "8", nationality: "1", residency_status: "1",
    birth_certificate_status: "1", nin_status: "8", nin_last4: "",
    telephone_1: "", telephone_2: "" },
];

const CaptureScreen = ({ device = "desktop", onChangeDevice, onPromoted }) => {
  const [active, setActive] = useStateCap("id");
  const [geo, setGeo] = useStateCap({
    subregion: "Karamoja", district: "Moroto", subcounty: "Tapac",
    parish: "Nakiloro", village: "Lopuwapuwa A"
  });
  const [consent, setConsent] = useStateCap("yes");
  const [urbanRural, setUR] = useStateCap("2"); // "1"=Urban, "2"=Rural per rural_urban list
  const [submitOpen, setSubmitOpen] = useStateCap(false);
  const [showReceipt, setShowReceipt] = useStateCap(false);

  // ----- detail-entity state (per US-S22-DE models) -----
  const [members, setMembers] = useStateCap(_DEMO_MEMBERS);
  const [healthData, setHealthData] = useStateCap({});       // { line_number: { health: {...}, disability: {...} } }
  const [educationData, setEducationData] = useStateCap({}); // { line_number: { ... } }
  const [employmentData, setEmploymentData] = useStateCap({}); // { line_number: { ... } }
  const [housing, setHousing] = useStateCap({
    dwelling: {}, utilities: {}, livelihood: {},
    assets: [], crops: [], livestock: [],
  });
  const [foodShocks, setFoodShocks] = useStateCap({
    food_security: {}, food_consumption: {},
    shocks: [], coping: [],
  });

  // Derived per-section progress — used by the stepper + left rail.
  const SECTION_PROG = {
    id: (geo.village && consent === "yes") ? "done" : "active",
    rost: members.length > 0 ? "done" : "active",
    hd: Object.keys(healthData).length > 0 ? "done" : "todo",
    ed: Object.keys(educationData).length > 0 ? "done" : "todo",
    emp: Object.keys(employmentData).length > 0 ? "done" : "todo",
    hous: (housing.dwelling.tenure || housing.utilities.cooking_fuel) ? "done" : "todo",
    food: (foodShocks.food_security.worried_food || foodShocks.shocks.length) ? "done" : "todo",
  };
  const _doneCount = Object.values(SECTION_PROG).filter(s => s === "done").length;
  const _progPct = Math.round((_doneCount / 7) * 100);
  const _nextSectionId = (() => {
    const order = ["id", "rost", "hd", "ed", "emp", "hous", "food"];
    const idx = order.indexOf(active);
    return order[Math.min(idx + 1, order.length - 1)];
  })();
  const _nextSectionLabel = SECTIONS.find(s => s.id === _nextSectionId)?.label || "Done";

  if (device === "capi") {
    return <CapturePadCAPI onChangeDevice={onChangeDevice}/>;
  }

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow="CAPTURES · US-088, US-112"
        title="Household capture"
        sub="Parish Office, Nakiloro · Operator: Lokwang Peter (PCH-7411) · Draft saved 14:34 EAT"
        right={<>
          <div className="seg" role="tablist" aria-label="Device variant">
            <button className="on" onClick={() => onChangeDevice?.('desktop')}>Desktop</button>
            <button onClick={() => onChangeDevice?.('capi')}>CAPI tablet</button>
          </div>
          <button className="btn"><Icon name="history"/> Resume draft</button>
        </>}
      />

      {/* Progress stepper */}
      <div className="card" style={{padding:'14px 20px', display:'flex', alignItems:'center', gap:0, position:'sticky', top:56, zIndex:10}}>
        {SECTIONS.map((s, i) => {
          const state = SECTION_PROG[s.id];
          const isActive = s.id === active;
          const done = state === "done";
          return (
            <React.Fragment key={s.id}>
              <button onClick={() => setActive(s.id)} style={{
                display:'flex', alignItems:'center', gap:8,
                padding:'6px 10px', border:0, background:'transparent',
                color: isActive ? 'var(--accent-data)' : done ? 'var(--neutral-700)' : 'var(--neutral-500)',
                fontWeight: isActive ? 600 : 500, fontSize: 13,
              }}>
                <span style={{
                  width:22, height:22, borderRadius:'50%',
                  display:'grid', placeItems:'center',
                  background: isActive ? 'var(--accent-data)' : done ? 'var(--accent-data-bg)' : 'var(--neutral-100)',
                  color: isActive ? 'white' : done ? 'var(--accent-data)' : 'var(--neutral-500)',
                  fontSize:11, fontWeight:600,
                  border: isActive ? '0' : `1px solid ${done ? 'var(--accent-data)' : 'var(--neutral-300)'}`,
                }}>
                  {done ? <Icon name="check" size={12}/> : i+1}
                </span>
                <span className="stretchable">{s.label}</span>
              </button>
              {i < SECTIONS.length - 1 && <div style={{flex:1, height:1, background:'var(--neutral-300)', minWidth:14}}/>}
            </React.Fragment>
          );
        })}
      </div>

      {/* 3-column form layout */}
      <div style={{display:'grid', gridTemplateColumns:'220px 1fr 320px', gap:20, marginTop:20}}>
        {/* Left rail — section nav */}
        <div className="card" style={{padding:8, alignSelf:'start', position:'sticky', top: 140}}>
          {SECTIONS.map((s) => {
            const state = SECTION_PROG[s.id];
            const isActive = s.id === active;
            return (
              <button key={s.id} onClick={() => setActive(s.id)} style={{
                display:'flex', alignItems:'center', gap:10, width:'100%',
                padding:'10px 12px', border:0, background: isActive ? 'var(--accent-data-bg)' : 'transparent',
                borderLeft: isActive ? '3px solid var(--accent-data)' : '3px solid transparent',
                color: isActive ? 'var(--accent-data)' : 'var(--neutral-900)',
                textAlign:'left', borderRadius:4, cursor:'pointer',
                fontWeight: isActive ? 600 : 500, fontSize:13,
              }}>
                <Icon name={s.icon} size={16}/>
                <span style={{flex:1}} className="stretchable">{s.label}</span>
                {state === 'done' && <Icon name="check" size={14} color="var(--accent-data)"/>}
              </button>
            );
          })}
          <div className="divider"/>
          <div style={{padding:'8px 12px'}} className="t-cap">
            <div>Progress <strong style={{color:'var(--neutral-900)'}}>{_doneCount} of 7</strong></div>
            <div style={{height:4, background:'var(--neutral-200)', borderRadius:2, marginTop:6}}>
              <div style={{width:`${_progPct}%`, height:'100%', background:'var(--accent-data)', borderRadius:2}}/>
            </div>
          </div>
        </div>

        {/* Main form — switches body by active section */}
        <div className="card">
          {active === "id" && (
            <IdentificationSection
              geo={geo} setGeo={setGeo}
              urbanRural={urbanRural} setUR={setUR}
              consent={consent} setConsent={setConsent}
            />
          )}
          {active === "rost" && (
            <RosterSection members={members} setMembers={setMembers}/>
          )}
          {active === "hd" && (
            <HealthDisabilitySection
              members={members}
              healthData={healthData} setHealthData={setHealthData}
            />
          )}
          {active === "ed" && (
            <EducationSection
              members={members}
              educationData={educationData} setEducationData={setEducationData}
            />
          )}
          {active === "emp" && (
            <EmploymentSection
              members={members}
              employmentData={employmentData} setEmploymentData={setEmploymentData}
            />
          )}
          {active === "hous" && (
            <HousingSection housing={housing} setHousing={setHousing}/>
          )}
          {active === "food" && (
            <FoodShocksSection foodShocks={foodShocks} setFoodShocks={setFoodShocks}/>
          )}
        </div>

        {/* Right rail — helper */}
        <div className="col gap-4" style={{alignSelf:'start', position:'sticky', top:140}}>
          {/* DQA live preview */}
          <div className="card">
            <div className="card-header" style={{padding:'12px 16px'}}>
              <h3 className="t-h3" style={{margin:0}}>Live DQA preview</h3>
              <span className="t-cap">refreshed 0:03</span>
            </div>
            <div style={{padding:16}}>
              <div className="row gap-3" style={{marginBottom:10}}>
                <div className="row gap-2"><div style={{width:8,height:8,borderRadius:'50%',background:'var(--accent-quality)'}}/><strong>3</strong> <span className="muted">warnings</span></div>
                <div className="row gap-2"><div style={{width:8,height:8,borderRadius:'50%',background:'var(--accent-danger)'}}/><strong>0</strong> <span className="muted">blocking</span></div>
              </div>
              <DQARow tone="quality" rule="AC-DQA-PHONE-LENGTH" detail="Phone ends in 7-digit subscriber section; AT&T-style; accept on review."/>
              <DQARow tone="quality" rule="AC-DQA-GPS-DRIFT" detail="GPS varied 4m across two readings; within tolerance."/>
              <DQARow tone="quality" rule="AC-DQA-AGE-HEAD" detail="Head of household age 27 — flag for review (median 35–45)."/>
            </div>
          </div>

          {/* Photo evidence */}
          <div className="card">
            <div className="card-header" style={{padding:'12px 16px'}}>
              <h3 className="t-h3" style={{margin:0}}>Evidence photos</h3>
              <button className="btn btn-sm btn-ghost"><Icon name="camera" size={14}/> Add</button>
            </div>
            <div style={{padding:16, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:8}}>
              {[
                ["Dwelling exterior","var(--accent-eligibility-bg)"],
                ["NIRA card (head)","var(--accent-identity-bg)"],
                ["Household roster","var(--accent-update-bg)"],
                ["Add photo","var(--neutral-100)"],
              ].map(([label, bg], i) => (
                <div key={i} style={{aspectRatio:'1', background:bg, borderRadius:4, border:'1px dashed var(--neutral-300)', display:'grid', placeItems:'center', textAlign:'center', padding:6, fontSize:11, color:'var(--neutral-700)'}}>
                  {i === 3 ? <Icon name="plus" size={20} color="var(--neutral-500)"/> : <Icon name="camera" size={20} color="var(--neutral-500)"/>}
                  <div style={{marginTop:4}} className="stretchable">{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Skip-logic hint */}
          <div className="card" style={{borderLeft:'3px solid var(--accent-update)'}}>
            <div style={{padding:16}}>
              <div className="row gap-2" style={{marginBottom:8}}>
                <Icon name="info" size={16} color="var(--accent-update)"/>
                <strong className="t-bodysm">Skip-logic hint</strong>
              </div>
              <p className="t-bodysm" style={{margin:0, color:'var(--neutral-700)'}}>
                If you select <strong>Urban</strong> for this household, the <strong>Food & Shocks</strong> section will reduce by 4 questions (rule SKIP-FS-URBAN).
              </p>
            </div>
          </div>

          {/* Offline indicator (informational) */}
          <div className="row gap-2 t-cap" style={{padding:'0 4px'}}>
            <div style={{width:8,height:8,borderRadius:'50%',background:'var(--accent-data)'}}/>
            Online · last sync 14:31 EAT · 0 queued
          </div>
        </div>
      </div>

      {/* Action bar */}
      <div style={{margin:'20px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
        <ActionBar left={<>Section {SECTIONS.findIndex(s => s.id === active) + 1} of 7 · {_progPct}% complete · <span className="stretchable">Auto-saved 14:34 EAT</span></>}>
          <button className="btn"><Icon name="save" size={14}/> Save draft</button>
          <button className="btn" onClick={() => setActive(_nextSectionId)}>
            <Icon name="arrowRight" size={14}/> Next: {_nextSectionLabel}
          </button>
          <button className="btn btn-primary" onClick={() => setSubmitOpen(true)}>
            <Icon name="check" size={14}/> Submit for promotion
          </button>
        </ActionBar>
      </div>

      {/* Submit modal */}
      <Modal open={submitOpen} onClose={() => setSubmitOpen(false)} title="Submit for promotion?"
        footer={<>
          <button className="btn" onClick={() => setSubmitOpen(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => { setSubmitOpen(false); setShowReceipt(true); }}>
            <Icon name="check" size={14}/> Confirm submission
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>This household will be assigned a <strong>provisional Registry ID</strong> and queued for NSR Unit promotion (AC-DIH-PROMOTE).</p>
          <div className="tint-quality" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-quality)'}}>
            <div className="row gap-2" style={{marginBottom:6}}><Icon name="alert" size={14} color="var(--accent-quality)"/><strong className="t-bodysm">3 warnings will be carried forward</strong></div>
            <ul className="t-bodysm" style={{margin:0, paddingLeft:20, color:'var(--neutral-700)'}}>
              <li>AC-DQA-PHONE-LENGTH · subscriber section</li>
              <li>AC-DQA-GPS-DRIFT · 4m variance between readings</li>
              <li>AC-DQA-AGE-HEAD · head age below 28</li>
            </ul>
          </div>
          <div className="t-cap">Audit entry will be written. SMS will be sent to +256 786 234567.</div>
        </div>
      </Modal>

      {/* Receipt overlay */}
      {showReceipt && <ReceiptOverlay onClose={() => setShowReceipt(false)}/>}
    </div>
  );
};

/* ============================================================
   Section 1 — Identification (extracted for the conditional shell)
   ============================================================ */
const IdentificationSection = ({ geo, setGeo, urbanRural, setUR, consent, setConsent }) => {
  const [urOpts] = (typeof useChoiceList === "function")
    ? useChoiceList("rural_urban")
    : [[]];
  return (
    <>
      <div className="card-header">
        <div>
          <div className="t-cap">SECTION 1 OF 7 · ACTIVE</div>
          <h3 className="t-h2" style={{ margin: 0 }}>Identification</h3>
        </div>
        <Chip>Draft</Chip>
      </div>
      <div style={{ padding: 20 }}>
        <h4 className="t-h3" style={{ margin: '0 0 16px' }}>Location</h4>
        <GeoTreePicker value={geo} onChange={setGeo}/>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Household identifiers</h4>
        <div className="field-row-3">
          <Field label="Household number" required hint="Auto-generated on first save">
            <input className="field-input" defaultValue="HH-7411-002-0148" readOnly/>
          </Field>
          <Field label="Urban / Rural" required>
            <div className="seg">
              {(urOpts.length ? urOpts : [{ code: "1", label: "Urban" }, { code: "2", label: "Rural" }]).map(o => (
                <button key={o.code}
                  className={urbanRural === o.code ? 'on' : ''}
                  onClick={() => setUR(o.code)}>
                  {o.label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Date captured">
            <div className="row gap-2"><Icon name="clock" size={14} color="var(--neutral-500)"/><span className="t-bodysm">14 May 2026 · 14:34 EAT</span></div>
          </Field>
        </div>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>GPS reading</h4>
        <div className="field-row-3">
          <Field label="Latitude" required>
            <input className="field-input t-mono" defaultValue="2.49423"/>
          </Field>
          <Field label="Longitude" required>
            <input className="field-input t-mono" defaultValue="34.65103"/>
          </Field>
          <Field label="Accuracy" required hint="Must be ≤ 10m (AC-GPS-ACCURACY)" error="6 m — within limit">
            <div className="input-affix" style={{ borderColor: 'var(--accent-data)' }}>
              <input defaultValue="6" className="t-mono"/>
              <span className="affix">m</span>
            </div>
          </Field>
        </div>
        <div className="t-cap mt-2" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon name="mapPin" size={12} color="var(--accent-data)"/> Position captured 14:31 EAT · accuracy 6 m · device tablet-PCH-7411
        </div>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Respondent</h4>
        <div className="field-row-3">
          <Field label="Respondent name" required>
            <input className="field-input" defaultValue="Lokol Naume"/>
          </Field>
          <Field label="Phone (E.164)" required hint="Format: +256 XXX XXXXXX">
            <input className="field-input" defaultValue="+256 786 234567"/>
          </Field>
          <Field label="Head of household" hint="Auto-filled from Roster Person 01">
            <input className="field-input" defaultValue="Lokol Naume" readOnly style={{ background: 'var(--neutral-50)', color: 'var(--neutral-700)' }}/>
          </Field>
        </div>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Consent <span style={{ color: 'var(--accent-danger)' }}>*</span></h4>
        <div className="tint-update" style={{ padding: 16, borderRadius: 6, borderLeft: '3px solid var(--accent-update)' }}>
          <p style={{ margin: '0 0 12px', fontSize: 13, lineHeight: 1.6 }}>
            "I, the respondent, consent to the collection and processing of my household's data by the Ministry of Gender, Labour and Social Development (MGLSD) under the Data Protection and Privacy Act 2019 of Uganda. I understand my data may be shared with partner agencies under a signed Data Sharing Agreement."
          </p>
          <div className="seg">
            <button className={consent === 'yes' ? 'on' : ''} onClick={() => setConsent('yes')}><Icon name="check" size={12}/> Yes — consented</button>
            <button className={consent === 'no' ? 'on' : ''} onClick={() => setConsent('no')}>No</button>
          </div>
        </div>
      </div>
    </>
  );
};

const DQARow = ({ tone, rule, detail }) => (
  <div style={{padding:'8px 10px', borderLeft:`3px solid var(--accent-${tone})`, background:`var(--accent-${tone}-bg)`, borderRadius:4, marginBottom:8}}>
    <div className="row gap-2" style={{justifyContent:'space-between', marginBottom:2}}>
      <span className="t-mono" style={{fontSize:11, color:`var(--accent-${tone})`, fontWeight:600}}>{rule}</span>
      <Chip tone={tone} size="sm">{tone === 'quality' ? 'Warning' : tone === 'danger' ? 'Blocking' : 'Info'}</Chip>
    </div>
    <div className="t-bodysm" style={{color:'var(--neutral-700)'}}>{detail}</div>
  </div>
);

/* ============================================================
   CAPI tablet variant — single question per screen
   ============================================================ */
const CapturePadCAPI = ({ onChangeDevice }) => {
  return (
    <div className="page" style={{display:'grid', placeItems:'center', minHeight:'80vh'}}>
      <div className="row gap-3" style={{marginBottom:16}}>
        <span className="t-cap">CAPI variant · 720×540 landscape · offline-first runtime</span>
        <div className="seg">
          <button onClick={() => onChangeDevice?.('desktop')}>Desktop</button>
          <button className="on">CAPI tablet</button>
        </div>
      </div>

      <div style={{width:720, height:540, background:'var(--neutral-0)', borderRadius:24, overflow:'hidden', boxShadow:'0 24px 60px rgba(0,0,0,0.18), 0 0 0 8px #1A1A1A, 0 0 0 10px #2A2A2A', display:'grid', gridTemplateRows:'auto 1fr auto'}}>
        {/* CAPI status bar */}
        <div style={{padding:'10px 16px', background:'var(--primary-900)', color:'white', display:'flex', alignItems:'center', justifyContent:'space-between', fontSize:12}}>
          <div className="row gap-3">
            <strong>NSR CAPI</strong>
            <span style={{opacity:0.7}}>HH-7411-002-0148 · Section 1/7</span>
          </div>
          <div className="row gap-3">
            <span style={{opacity:0.8}}><Icon name="mapPin" size={12}/> GPS 6m</span>
            <span style={{display:'inline-flex', alignItems:'center', gap:4, opacity:0.8}}>
              <span style={{width:6,height:6,borderRadius:'50%',background:'#FFB300'}}/> Offline · 3 queued
            </span>
            <span style={{opacity:0.8}}>92%</span>
            <span>14:35</span>
          </div>
        </div>

        {/* Progress */}
        <div style={{padding:'24px 32px', display:'grid', gridTemplateRows:'auto auto 1fr', gap:16}}>
          <div>
            <div className="t-cap">Section 1 · Identification · Q 4 of 9</div>
            <div style={{height:6, background:'var(--neutral-200)', borderRadius:3, marginTop:6}}>
              <div style={{width:'14%', height:'100%', background:'var(--accent-data)', borderRadius:3}}/>
            </div>
          </div>

          <h2 className="t-h1" style={{margin:0, fontSize:22, lineHeight:'30px'}}>What is the respondent's primary phone number?</h2>
          <div className="t-bodysm muted" style={{margin:'-8px 0 0'}}>Used for SMS receipt and status notifications. Format: +256 XXX XXXXXX.</div>

          <div className="col gap-4">
            <div className="input-affix" style={{height:56, fontSize:18}}>
              <span className="affix" style={{fontSize:16, padding:'0 14px'}}>+256</span>
              <input className="t-mono" style={{fontSize:18}} defaultValue="786 234567"/>
            </div>
            <div className="row gap-2"><Icon name="info" size={14} color="var(--neutral-500)"/><span className="t-bodysm muted">SMS will be sent at submission · operator hours 06:00 — 22:00 EAT</span></div>
          </div>
        </div>

        {/* CAPI bottom bar */}
        <div style={{padding:'12px 16px', borderTop:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', background:'var(--neutral-50)'}}>
          <button className="btn btn-lg"><Icon name="chevronLeft"/> Back</button>
          <button className="btn btn-lg btn-ghost"><Icon name="save"/> Save & exit</button>
          <button className="btn btn-lg btn-primary">Next <Icon name="chevronRight"/></button>
        </div>
      </div>
      <div className="t-cap mt-3" style={{maxWidth:640, textAlign:'center'}}>
        Touch target ≥ 48 dp · Talkback enabled · large-text mode toggle in profile · drafts persist for 14 days
      </div>
    </div>
  );
};

/* ============================================================
   11.2 Receipt slip overlay
   ============================================================ */
const ReceiptOverlay = ({ onClose }) => {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{maxWidth:980, display:'grid', gridTemplateColumns:'1fr 1fr', gap:0, padding:0}} onClick={(e) => e.stopPropagation()}>
        {/* Left — A6 slip */}
        <div style={{padding:24, borderRight:'1px solid var(--neutral-200)', background:'var(--neutral-100)'}}>
          <div className="t-cap" style={{marginBottom:8}}>A6 PRINT · 105 × 148 mm · THERMAL-FRIENDLY</div>
          <ReceiptSlipA6/>
        </div>
        {/* Right — SMS + actions */}
        <div style={{padding:24}}>
          <div className="row gap-2" style={{marginBottom:6}}>
            <Chip>Provisional</Chip>
            <span className="t-cap">Generated 14:35 EAT</span>
          </div>
          <h2 className="t-h2" style={{margin:'4px 0 8px'}}>Provisional Registry ID issued</h2>
          <p className="t-body" style={{color:'var(--neutral-700)', marginTop:0}}>Hand the printed slip to the respondent. An SMS has been queued to <span className="t-mono">+256 786 234567</span>.</p>

          <div className="card" style={{padding:14, marginTop:12}}>
            <div className="t-cap" style={{marginBottom:6}}>SMS PREVIEW · 160 char</div>
            <div className="t-mono" style={{fontSize:12.5, lineHeight:1.55, padding:10, background:'var(--neutral-50)', borderRadius:4, color:'var(--neutral-900)'}}>
              MGLSD NSR: Your provisional Registry ID is 01HXY7K3B2N9PVQE4M6FZRWS18. Pending approval. Track via parish office or SMS HELP to 8800.
            </div>
            <div className="t-cap mt-2">158 / 160 characters · UTF-8 safe</div>
          </div>

          <div className="card mt-4" style={{padding:14}}>
            <div className="t-cap" style={{marginBottom:6}}>NEXT IN THE PIPELINE</div>
            <div className="col gap-2">
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--accent-data-bg)',color:'var(--accent-data)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>1</span><span className="t-bodysm">Captured at parish · <strong>now</strong></span></div>
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--accent-update-bg)',color:'var(--accent-update)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>2</span><span className="t-bodysm">DIH staging · DQA + IDV checks · ~10 min</span></div>
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--accent-quality-bg)',color:'var(--accent-quality)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>3</span><span className="t-bodysm">NSR Unit review · within 24 hours (walk-in SLA)</span></div>
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--neutral-100)',color:'var(--neutral-500)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>4</span><span className="t-bodysm muted">Promoted to <strong>Registered</strong> · same ID, no re-issue</span></div>
            </div>
          </div>

          <div className="row gap-3 mt-4">
            <button className="btn"><Icon name="print"/> Print A6</button>
            <button className="btn"><Icon name="phone"/> Resend SMS</button>
            <button className="btn"><Icon name="download"/> Save PDF</button>
            <div style={{flex:1}}/>
            <button className="btn btn-primary" onClick={onClose}>Done</button>
          </div>
        </div>
      </div>
    </div>
  );
};

const ReceiptSlipA6 = () => (
  <div style={{
    width: 380, height: 540,
    background:'white', boxShadow:'0 8px 24px rgba(0,0,0,0.12)',
    padding:'18px 22px', fontFamily:'Calibri, "Segoe UI", sans-serif',
    fontSize:11, lineHeight:1.5, color:'#111',
    display:'flex', flexDirection:'column', gap:8,
    border:'1px solid var(--neutral-300)',
  }}>
    <div className="row" style={{gap:8, borderBottom:'1px solid #111', paddingBottom:8}}>
      <div style={{width:28, height:28, background:'#111', color:'white', display:'grid', placeItems:'center', fontSize:9, fontWeight:700, letterSpacing:'.04em'}}>MGLSD</div>
      <div style={{flex:1}}>
        <div style={{fontWeight:700, fontSize:11, letterSpacing:'.02em'}}>MGLSD — NATIONAL SOCIAL REGISTRY</div>
        <div style={{fontSize:9, color:'#444'}}>Ministry of Gender, Labour and Social Development · Republic of Uganda</div>
      </div>
    </div>

    <div>
      <div style={{fontSize:9, color:'#444', letterSpacing:'.06em', textTransform:'uppercase'}}>Provisional Registry ID</div>
      <div style={{fontFamily:'"JetBrains Mono", ui-monospace, monospace', fontSize:12.5, letterSpacing:'.02em', wordBreak:'break-all', fontWeight:700, marginTop:2}}>
        01HXY7K3B2N9PVQE4M6FZRWS18
      </div>
    </div>

    <div style={{display:'grid', gridTemplateColumns:'88px 1fr', rowGap:3, columnGap:6, marginTop:2}}>
      <div style={{color:'#666'}}>Captured at:</div><div>Parish Office, Nakiloro · Moroto</div>
      <div style={{color:'#666'}}>Date:</div><div>14 May 2026 · 14:35 EAT</div>
      <div style={{color:'#666'}}>Operator:</div><div>Lokwang Peter (PCH-7411)</div>
      <div style={{color:'#666'}}>Status:</div><div style={{fontWeight:700}}>Pending NSR Unit approval</div>
    </div>

    <div style={{borderTop:'1px solid #ccc', paddingTop:8, marginTop:4}}>
      <div style={{fontWeight:700, fontSize:10, marginBottom:4, letterSpacing:'.02em', textTransform:'uppercase'}}>Track your status</div>
      <ul style={{margin:0, paddingLeft:14, fontSize:10, lineHeight:1.55}}>
        <li>Quote your Provisional Registry ID at any parish office.</li>
        <li>SMS HELP to 8800 for status (operator hours).</li>
        <li>You will receive an SMS within 24 hours confirming Registered status, or a reason if the application is held.</li>
      </ul>
    </div>

    <div style={{fontSize:9.5, color:'#222', borderTop:'1px solid #ccc', paddingTop:8, marginTop:'auto'}}>
      Your Provisional Registry ID <strong>becomes</strong> your confirmed Registry ID on approval. Same number, no re-issue.
    </div>

    <div className="row" style={{justifyContent:'space-between', gap:12, borderTop:'1px solid #111', paddingTop:8, alignItems:'flex-end'}}>
      <div style={{fontSize:8.5, color:'#444', flex:1}}>
        Collected and processed under the Data Protection and Privacy Act 2019 (Uganda). Controller: MGLSD-NSR. Data subject rights: see mglsd.go.ug/nsr/privacy.
      </div>
      {/* QR placeholder */}
      <div style={{width:56, height:56, background:'repeating-linear-gradient(45deg, #111 0 4px, #fff 4px 8px)', border:'1px solid #111'}}/>
    </div>
  </div>
);

const ReceiptScreen = () => (
  <div className="page">
    <PageHeader
      eyebrow="CAPTURES · US-112"
      title="Provisional Registry ID receipt"
      sub="A6 printable slip and matching SMS for the citizen."
      right={<>
        <button className="btn"><Icon name="phone"/> Resend SMS</button>
        <button className="btn"><Icon name="print"/> Print A6</button>
        <button className="btn btn-primary"><Icon name="download"/> Save as PDF</button>
      </>}
    />
    <div style={{display:'grid', gridTemplateColumns:'420px 1fr', gap:24}}>
      <div className="col gap-3">
        <div className="t-cap">A6 PRINT PREVIEW · 105 × 148 mm</div>
        <ReceiptSlipA6/>
      </div>
      <div className="col gap-4">
        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>SMS template</h3><span className="t-cap">160 char limit</span></div>
          <div style={{padding:16}}>
            <div className="t-mono" style={{padding:12, background:'var(--neutral-50)', borderRadius:4, fontSize:13, lineHeight:1.55, border:'1px solid var(--neutral-200)'}}>
              MGLSD NSR: Your provisional Registry ID is 01HXY7K3B2N9PVQE4M6FZRWS18. Pending approval. Track via parish office or SMS HELP to 8800.
            </div>
            <div className="t-cap mt-2">158 / 160 characters · UTF-8 safe</div>
          </div>
        </div>

        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}>
            <h3 className="t-h3" style={{margin:0}}>Content blocks (Section 11.2)</h3>
            <Chip>Approved</Chip>
          </div>
          <div style={{padding:16}}>
            {[
              "MGLSD wordmark and full programme name",
              "Provisional Registry ID (ULID, monospace)",
              "Captured at — Parish name, District",
              "Date and time (East Africa Time)",
              "Operator name and code",
              "Status: Pending NSR Unit approval",
              "Track your status — three numbered actions",
              "Provisional → confirmed clarification (same number)",
              "Data Protection and Privacy Act 2019 footer",
            ].map((line, i) => (
              <div key={i} className="row gap-3" style={{padding:'6px 0', borderBottom: i < 8 ? '1px solid var(--neutral-200)' : 'none'}}>
                <span style={{width:22, height:22, borderRadius:'50%', background:'var(--accent-data-bg)', color:'var(--accent-data)', display:'grid', placeItems:'center', fontSize:11, fontWeight:600}}>{i+1}</span>
                <span className="t-bodysm">{line}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{borderLeft:'3px solid var(--accent-update)'}}>
          <div style={{padding:16}}>
            <div className="row gap-2" style={{marginBottom:8}}>
              <Icon name="info" size={16} color="var(--accent-update)"/>
              <strong className="t-bodysm">Lifecycle reminder</strong>
            </div>
            <p className="t-bodysm" style={{margin:0, color:'var(--neutral-700)'}}>
              The provisional Registry ID is real. On approval it is promoted to <strong>Registered</strong> without re-issue. On rejection, the ID is voided and the citizen receives an SMS with a reason.
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
);

Object.assign(window, { CaptureScreen, ReceiptScreen, ReceiptOverlay, ReceiptSlipA6 });
