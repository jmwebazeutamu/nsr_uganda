/* global React, Icon, Chip, PageHeader, useApi */
// NSR MIS — Registry · Member detail (US-005 sibling)
// =========================================================
// Per-individual detail screen. Sister to HouseholdScreen — same
// chrome (header, summary, tab bar, tab bodies) but member-shaped.
// Lifecycle/audit events stay anchored to the parent household;
// this view just lenses into the slice that belongs to one person.
//
// Live data:
//   GET /api/v1/data-management/members/{memberId}/
//   GET /api/v1/data-management/households/{member.household}/
//
// The four tabs that need source models we haven't wired yet — Vital
// events (no VitalEvent model), Updates history (apps.update_workflow
// ChangeRequest filtered by entity_id), Programmes (no MemberEnrolment
// — only Household-level ProgrammeEnrolment), and Audit (
// AuditEvent.subject_member_id) — render empty-state stubs noting
// where the data will land.

const { useState: useStateMD } = React;

// Empty fallback so render code paths that read .events / .upds /
// .programmes / .audit don't have to guard against null when the
// fetch is still in flight or the member id is missing.
const _MEMBER_FALLBACK = {
  mid: "", line: "", name: "Loading…", rel: "", relCode: "",
  status: "",
  hh: "", head: "—", hhSize: 0,
  subreg: "", district: "", parish: "", village: "",
  nin: { status: "", value: "", verifiedAt: "", verifiedBy: "", last4: "" },
  dob: "", age: null, ageBand: "", sex: "",
  marital: "", ethnicity: "", language: "",
  photoRef: "", birthCert: false,
  wg: { seeing: "", hearing: "", walking: "", cognition: "", selfcare: "", communication: "", flag: false },
  chronic: [], insurance: "", lastVisit: "",
  literacy: "", everSchool: false, highestGrade: "", currentlyAttending: false,
  activity: "", occupation: "", industry: "", hoursPerWeek: null,
  employerType: "", earningsBand: "",
  programmes: [],
  upds: [],
  events: [],
  audit: [],
};

// Translate Disability.<domain> ChoiceList code (01..04) to a
// human-friendly answer string. Lines up with WgRow's tone ladder so
// the Health & Disability tab keeps its colour grammar.
const _WG_CODE = {
  "01": "No difficulty",
  "02": "Some difficulty",
  "03": "A lot of difficulty",
  "04": "Cannot do at all",
};
const _wgAnswer = (code) => _WG_CODE[code] || (code || "—");

const _MD_ageBand = (years) => {
  if (years == null) return "";
  if (years < 5)  return "<5";
  if (years < 10) return "5-9";
  if (years < 15) return "10-14";
  if (years < 20) return "15-19";
  if (years < 30) return "20-29";
  if (years < 40) return "30-39";
  if (years < 50) return "40-49";
  if (years < 60) return "50-59";
  return "60+";
};

// Project a live Member API payload (MemberSerializer shape) plus an
// optional Household payload onto the existing prototype `m` shape.
// Every tab body reads off this projection, so live wiring is a
// matter of producing a faithful mapping — the JSX below stays
// unchanged.
const _projectMemberDetail = (member, household) => {
  if (!member) return _MEMBER_FALLBACK;

  const m = JSON.parse(JSON.stringify(_MEMBER_FALLBACK));

  m.mid = member.id || "";
  m.line = member.line_number;
  m.name = `${member.surname || ""} ${member.first_name || ""}`.trim()
    || _MEMBER_FALLBACK.name;
  m.rel = member.relationship_to_head_label || member.relationship_to_head || "—";
  m.relCode = member.relationship_to_head || "";
  m.status = "Confirmed";

  m.hh = member.household || "";
  m.head = "—";
  m.hhSize = 0;
  if (household) {
    const members = household.members || [];
    m.hhSize = members.length;
    const head = members.find(x => x.relationship_to_head === "01")
      || members.find(x => x.line_number === 1)
      || members[0]
      || null;
    if (head) {
      m.head = `${head.surname || ""} ${head.first_name || ""}`.trim() || "—";
    }
    m.subreg = household.sub_region_name || "";
    m.district = household.district_name || "";
    m.parish = household.parish_name || "";
    m.village = household.village_name || "";
  } else {
    m.subreg = member.household_sub_region_name || "";
    m.district = member.household_district_name || "";
    m.parish = member.household_parish_name || "";
    m.village = member.household_village_name || "";
  }

  m.nin = {
    status: member.nin_status || "",
    statusLabel: member.nin_status_label || member.nin_status || "—",
    last4: member.nin_last4 || "",
    // List + detail surfaces never receive the full NIN value
    // (HANDOFF §4 sensitive layer). Reveal goes through the
    // post-MVP audit-emitting endpoint (`nin_reveal` action,
    // follow-up).
    value: member.nin_last4 ? `••••${member.nin_last4}` : "—",
    verifiedAt: "",
    verifiedBy: "",
  };
  m.dob = member.date_of_birth || "";
  m.age = member.age_years;
  m.ageBand = _MD_ageBand(member.age_years);
  // ChoiceList sex code: 1=Male, 2=Female.
  m.sex = member.sex === "1" ? "M" : member.sex === "2" ? "F" : (member.sex_label || "—");
  m.marital = member.marital_status_label || member.marital_status || "—";
  // Member model doesn't carry ethnicity / preferred_language; surface
  // dashes until a follow-up adds them to the demographics tail.
  m.ethnicity = "—";
  m.language = "—";
  m.birthCert = (member.birth_certificate_status || "") === "1";

  const disab = member.disability || {};
  m.wg = {
    seeing:        _wgAnswer(disab.seeing),
    hearing:       _wgAnswer(disab.hearing),
    walking:       _wgAnswer(disab.walking),
    cognition:     _wgAnswer(disab.memory),
    selfcare:      _wgAnswer(disab.selfcare),
    communication: _wgAnswer(disab.communication),
    flag:          !!disab.wg_disability_flag,
  };
  const health = member.health || {};
  m.chronic = (health.chronic_illness_flag === "1") ? ["Chronic illness flagged"] : [];
  m.insurance = "—";
  m.lastVisit = "—";

  const ed = member.education || {};
  m.literacy = ed.literacy_status_label || ed.literacy_status || "—";
  m.everSchool = (ed.ever_attended || "") === "1";
  m.highestGrade = ed.highest_grade_label || ed.highest_grade || "—";
  m.currentlyAttending = (ed.currently_attending || "") === "1";

  const emp = member.employment || {};
  m.activity = emp.main_activity_last_30d_label || emp.main_activity_last_30d || "—";
  m.occupation = emp.sector_label || emp.sector || "—";
  m.industry = "—";
  m.hoursPerWeek = null;
  m.employerType = emp.employment_status_label || emp.employment_status || "—";
  m.earningsBand = "—";

  // Programmes / UPDs / Vital events / Audit — none wired yet.
  // Empty arrays keep the tabs rendering their empty-state.
  m.programmes = [];
  m.upds = [];
  m.events = [];
  m.audit = [];

  return m;
};

// Tab counts are read off the live `m` projection at render time
// (see the MemberDetailScreen body); the constant array keeps the
// stepper's iteration order.
const MD_TABS = [
  { id:"over", label:"Overview" },
  { id:"idn",  label:"Identity" },
  { id:"demo", label:"Demographics" },
  { id:"hd",   label:"Health & Disability" },
  { id:"ed",   label:"Education" },
  { id:"emp",  label:"Employment" },
  { id:"vit",  label:"Vital events" },
  { id:"hist", label:"Updates history" },
  { id:"prog", label:"Programmes" },
  { id:"aud",  label:"Audit" },
];

/* ----------------------------------------------------------------
   Locally-scoped helpers (mirror screens-registry.jsx)
   ---------------------------------------------------------------- */
const MD_Fact = ({ label, big, sub }) => (
  <div style={{minWidth:0}}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm" style={{fontWeight:600, fontSize:15, marginTop:2, color:'var(--neutral-900)', overflowWrap:'anywhere'}}>{big}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

const MD_TabHeader = ({ title, sub, action }) => (
  <div style={{padding:'16px 20px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', gap:12}}>
    <div>
      <h3 className="t-h3" style={{margin:0}}>{title}</h3>
      {sub && <div className="t-cap mt-1">{sub}</div>}
    </div>
    {action}
  </div>
);

const MD_KVCard = ({ title, rows, tint }) => (
  <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0, borderLeft: tint ? `3px solid var(--accent-${tint})` : '1px solid var(--neutral-200)'}}>
    <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', fontSize:14, fontWeight:600}}>{title}</div>
    <div style={{padding:'12px 16px', display:'grid', gridTemplateColumns:'140px 1fr', rowGap:6, columnGap:12, fontSize:13}}>
      {rows.map(([k, v], i) => (
        <React.Fragment key={i}>
          <div className="muted">{k}</div>
          <div>{v}</div>
        </React.Fragment>
      ))}
    </div>
  </div>
);

const MD_Stat = ({ label, value, tint = "data" }) => (
  <div style={{minWidth:140, padding:'10px 14px', border:'1px solid var(--neutral-200)', borderLeft:`3px solid var(--accent-${tint})`, borderRadius:4, background:'var(--neutral-0)'}}>
    <div className="t-cap">{label}</div>
    <div style={{fontSize:17, fontWeight:600, marginTop:2}}>{value}</div>
  </div>
);

const WgRow = ({ q, answer }) => {
  const sev = (answer || "").toLowerCase();
  const tone = sev.includes("a lot") || sev.includes("cannot") ? "danger"
    : sev.includes("some") ? "quality"
    : "data";
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr auto', alignItems:'center', gap:12, padding:'10px 0', borderBottom:'1px dashed var(--neutral-200)'}}>
      <span className="t-bodysm">{q}</span>
      <Chip size="sm" tone={tone}>{answer}</Chip>
    </div>
  );
};

/* ----------------------------------------------------------------
   MEMBER DETAIL — top-level
   ---------------------------------------------------------------- */
const MemberDetailScreen = ({ memberId, onBack, onOpenHousehold }) => {
  const [tab, setTab] = useStateMD("over");

  // Live fetch — main payload first, then the parent household so
  // the summary card has head name + size. The household call is
  // gated until we have the household id.
  const [memberResp, memberMeta] = useApi(
    memberId ? `/api/v1/data-management/members/${memberId}/` : null,
  );
  const householdId = memberResp ? memberResp.household : null;
  const [householdResp] = useApi(
    householdId ? `/api/v1/data-management/households/${householdId}/` : null,
  );
  const m = _projectMemberDetail(memberResp, householdResp);

  // No member id at all → render an empty shell with a back button.
  if (!memberId) {
    return (
      <div className="page">
        <PageHeader eyebrow="MEMBER" title="No member selected"/>
        <div className="card" style={{padding:20}} className="muted">
          Open a member from the Members list to see their record.
        </div>
      </div>
    );
  }
  if (memberMeta.loading && !memberResp) {
    return (
      <div className="page">
        <PageHeader eyebrow="MEMBER" title="Loading…"/>
      </div>
    );
  }
  if (memberMeta.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="MEMBER" title="Could not load member" sub={memberMeta.error}/>
        <div style={{padding:20}}>
          <button className="btn" onClick={onBack}>
            <Icon name="chevronLeft" size={14}/> Back to Members
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        back={{ label: "Members", onClick: onBack }}
        eyebrow={<>MEMBER · <span className="t-mono">{(m.mid || "").slice(0, 20)}{m.mid && m.mid.length > 20 ? "…" : ""}</span></>}
        title={<>{m.name} {m.rel && m.rel !== "—" && <span className="t-bodysm" style={{fontWeight:400, color:'var(--accent-data)', marginLeft:8}}>({String(m.rel).toLowerCase()})</span>}</>}
        sub={<>Line {m.line || "—"} of HH <span className="t-mono">{m.hh ? `${m.hh.slice(0, 16)}…` : "—"}</span> · {m.village || "—"} · {m.parish || "—"}, {m.district || "—"} · {m.subreg || "—"}</>}
        right={<>
          <button className="btn" onClick={() => onOpenHousehold?.(m.hh)}><Icon name="home" size={14}/> Open household</button>
        </>}
      />

      {/* Summary card */}
      <div className="card" style={{padding:0, marginBottom:16}}>
        <div style={{padding:'18px 20px', display:'grid', gridTemplateColumns:'72px 1.4fr 1.2fr 1.2fr 1fr', gap:24, alignItems:'flex-start'}}>
          <div style={{
            width:72, height:72, borderRadius:'50%',
            background:'var(--primary-100)', color:'var(--primary-900)',
            display:'grid', placeItems:'center',
            fontSize:24, fontWeight:600,
          }}>{m.name.split(' ').map(w => w[0]).slice(0,2).join('')}</div>

          <MD_Fact label="Identity"
            big={<>{m.name} <Chip size="sm">{m.sex}</Chip></>}
            sub={<>{m.age != null ? `${m.age} yrs` : "—"} ({m.ageBand || "—"}) · {m.marital}</>}/>

          <MD_Fact label="Household linkage"
            big={<><span className="t-mono" style={{fontSize:13}}>{m.hh ? `${m.hh.slice(0,16)}…` : "—"}</span></>}
            sub={<>{m.rel} of <strong>{m.head}</strong> · HH size {m.hhSize || "—"}</>}/>

          <MD_Fact label="NIN"
            big={m.nin.status === "1"
              ? <span className="t-mono" style={{fontSize:14}}>{m.nin.value}</span>
              : "—"}
            sub={m.nin.status === "1"
              ? <>verified · last 4 only</>
              : <>{m.nin.statusLabel}</>}/>

          <div>
            <div className="t-cap">Disability (WG-SS)</div>
            <div className="row gap-2 mt-1">
              {m.wg.flag
                ? <Chip size="sm" tone="quality"><Icon name="shield" size={11}/> Flagged</Chip>
                : <Chip size="sm" tone="data">Not flagged</Chip>}
            </div>
            <div className="t-cap mt-2">
              {Object.entries(m.wg).filter(([k,v]) => k !== "flag" && /some|lot|cannot/i.test(v)).map(([k]) => k).join(", ") || "no difficulty across 6 domains"}
            </div>
          </div>
        </div>

        <div style={{borderTop:'1px solid var(--neutral-200)', padding:'12px 20px', display:'flex', alignItems:'center', gap:12, background:'var(--neutral-50)'}}>
          <Chip>{m.status}</Chip>
          <span className="t-bodysm muted">Member record · linked to household above · last verified 22 Apr 2026</span>
          {m.programmes.length > 0 && (
            <div className="row-wrap" style={{gap:6}}>
              {m.programmes.map(p => <Chip key={p.code} size="sm" tone="programme">{p.code}</Chip>)}
            </div>
          )}
          <div style={{flex:1}}/>
          <button className="btn btn-primary"><Icon name="edit" size={14}/> Open change request</button>
          <button className="btn"><Icon name="message" size={14}/> Open grievance</button>
          <button className="btn btn-ghost"><Icon name="moreH" size={14}/></button>
        </div>
      </div>

      {/* Tabs */}
      <div role="tablist" style={{display:'flex', gap:0, borderBottom:'1px solid var(--neutral-300)', marginBottom:0, flexWrap:'wrap'}}>
        {MD_TABS.map(t => {
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
        {tab === "over"  && <MdOverview m={m}/>}
        {tab === "idn"   && <MdIdentity m={m}/>}
        {tab === "demo"  && <MdDemographics m={m}/>}
        {tab === "hd"    && <MdHealth m={m}/>}
        {tab === "ed"    && <MdEducation m={m}/>}
        {tab === "emp"   && <MdEmployment m={m}/>}
        {tab === "vit"   && <MdEvents m={m}/>}
        {tab === "hist"  && <MdHistory m={m}/>}
        {tab === "prog"  && <MdProgrammes m={m}/>}
        {tab === "aud"   && <MdAudit m={m}/>}
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read-only registry view (AC-UPD-VERSION). All edits open a UPD ChangeRequest against the
        parent household. Full audit chain available under the household's Audit tab.
      </div>
    </div>
  );
};

/* ----------------------------------------------------------------
   Tab bodies
   ---------------------------------------------------------------- */
const MdOverview = ({ m }) => (
  <div>
    <MD_TabHeader title="Overview" sub="Snapshot of the most-referenced member fields. Open any tab below for the full record."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <MD_KVCard title="Identity" tint="identity" rows={[
        ["Full name",   m.name],
        ["Sex / Age",   `${m.sex} · ${m.age} (${m.ageBand})`],
        ["DoB",         m.dob],
        ["NIN",         m.nin.status === "verified"
                          ? <><span className="t-mono">{m.nin.value}</span> <Chip size="sm" tone="data">verified</Chip></>
                          : <Chip size="sm" tone="quality">{m.nin.status}</Chip>],
        ["Marital",     m.marital],
        ["Relation",    m.rel],
      ]}/>
      <MD_KVCard title="Household linkage" tint="data" rows={[
        ["Registry ID", <span className="t-mono">{m.hh}</span>],
        ["Head",        m.head],
        ["HH size",     m.hhSize],
        ["Sub-region",  m.subreg],
        ["District",    m.district],
        ["Village",     `${m.village} · ${m.parish}`],
      ]}/>
      <MD_KVCard title="Health & Disability snapshot" tint="quality" rows={[
        ["WG-SS flag",       m.wg.flag ? <Chip size="sm" tone="quality">Yes</Chip> : <Chip size="sm" tone="data">No</Chip>],
        ["Walking",          m.wg.walking],
        ["Seeing",           m.wg.seeing],
        ["Chronic",          m.chronic.length ? m.chronic.join(", ") : <span className="muted">None reported</span>],
        ["Insurance",        m.insurance],
        ["Last clinic",      m.lastVisit],
      ]}/>
      <MD_KVCard title="Education & Employment" tint="programme" rows={[
        ["Literacy",         m.literacy],
        ["Highest grade",    m.highestGrade],
        ["Currently attending", m.currentlyAttending ? "Yes" : "No"],
        ["Activity",         <Chip size="sm" tone="quality">{m.activity}</Chip>],
        ["Occupation",       m.occupation],
        ["Hours / week",     m.hoursPerWeek],
      ]}/>
    </div>
  </div>
);

const MdIdentity = ({ m }) => (
  <div>
    <MD_TabHeader title="Identity" sub="Personal identifiers and verification evidence. PII — access logged."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:16}}>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
          <strong>NIN verification</strong>
          {m.nin.status === "1"
            ? <Chip size="sm" tone="data"><Icon name="check" size={11}/> verified</Chip>
            : <Chip size="sm" tone="quality">{m.nin.statusLabel || m.nin.status || "—"}</Chip>}
        </div>
        <div style={{padding:16, display:'grid', gridTemplateColumns:'160px 1fr', rowGap:8, fontSize:13}}>
          <div className="muted">NIN (last 4)</div>
          <div className="t-mono">{m.nin.last4 ? `••••${m.nin.last4}` : "—"}</div>
          <div className="muted">Status</div><div>{m.nin.statusLabel || "—"}</div>
          <div className="muted">DoB</div><div>{m.dob || "—"}</div>
          <div className="muted">Birth certificate</div>
          <div>{m.birthCert
            ? <Chip size="sm" tone="data">Registered (URSB)</Chip>
            : <Chip size="sm" tone="quality">Not on file</Chip>}
          </div>
        </div>
        <div className="tint-update" style={{margin:16, padding:12, borderRadius:4, borderLeft:'3px solid var(--accent-update)'}}>
          <div className="row gap-2" style={{marginBottom:4}}>
            <Icon name="shield" size={14} color="var(--accent-update)"/>
            <strong className="t-bodysm">Full NIN reveal requires audit</strong>
          </div>
          <div className="t-bodysm muted">
            The registry surface returns only the last-4 of the NIN by
            default. Full reveal is gated by the upcoming nin_reveal
            endpoint, which writes an AuditEvent before returning the
            stored value (HANDOFF §4).
          </div>
        </div>
      </div>
      <div className="card" style={{padding:0, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)'}}>
          <strong>Photo</strong>
          <div className="t-cap">Masked placeholder — photo asset fetch lands with the object-storage signed-URL flow.</div>
        </div>
        <div style={{padding:16}}>
          <div style={{
            aspectRatio:'3/4', borderRadius:6,
            background:'repeating-linear-gradient(45deg, var(--neutral-100), var(--neutral-100) 8px, var(--neutral-50) 8px, var(--neutral-50) 16px)',
            border:'1px solid var(--neutral-200)',
            display:'grid', placeItems:'center',
          }}>
            <div style={{textAlign:'center', color:'var(--neutral-500)'}}>
              <Icon name="user" size={36} color="var(--neutral-300)"/>
              <div className="t-cap mt-1">photo ref</div>
              <div className="t-cap">click reveal · access logged (follow-up)</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
);

const MdDemographics = ({ m }) => (
  <div>
    <MD_TabHeader title="Demographics"/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <MD_KVCard title="Person" rows={[
        ["Sex",          <Chip size="sm">{m.sex}</Chip>],
        ["Age",          m.age != null ? `${m.age} (${m.ageBand})` : "—"],
        ["Date of birth", m.dob || "—"],
        ["Marital",      m.marital],
        ["Relationship", m.rel],
      ]}/>
      <MD_KVCard title="Language & culture" rows={[
        ["Ethnicity",          m.ethnicity],
        ["Preferred language", m.language],
        ["Religion",           <span className="muted">Not on Member model · follow-up</span>],
        ["Place of birth",     <span className="muted">Not on Member model · follow-up</span>],
      ]}/>
    </div>
  </div>
);

const MdHealth = ({ m }) => (
  <div>
    <MD_TabHeader title="Health & Disability" sub="Washington Group Short Set (WG-SS) — six domains. A flag is set when any domain reports ‘A lot of difficulty’ or worse."/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:16}}>
      <div className="card" style={{padding:16, boxShadow:'none', border:'1px solid var(--neutral-200)'}}>
        <div className="row gap-2" style={{marginBottom:8}}>
          <h4 className="t-h3" style={{margin:0}}>WG-SS responses</h4>
          <div style={{flex:1}}/>
          {m.wg.flag
            ? <Chip size="sm" tone="quality">Composite flag · Yes</Chip>
            : <Chip size="sm" tone="data">Composite flag · No</Chip>}
        </div>
        <WgRow q="Difficulty seeing, even if wearing glasses?"        answer={m.wg.seeing}/>
        <WgRow q="Difficulty hearing, even if using a hearing aid?"   answer={m.wg.hearing}/>
        <WgRow q="Difficulty walking or climbing stairs?"             answer={m.wg.walking}/>
        <WgRow q="Difficulty remembering or concentrating?"           answer={m.wg.cognition}/>
        <WgRow q="Difficulty with self-care (washing / dressing)?"    answer={m.wg.selfcare}/>
        <WgRow q="Difficulty communicating in usual language?"        answer={m.wg.communication}/>
      </div>
      <div style={{display:'flex', flexDirection:'column', gap:12}}>
        <MD_KVCard title="Chronic conditions" tint="quality" rows={[
          ["Reported",        m.chronic.length ? m.chronic.join(", ") : <span className="muted">None reported</span>],
          ["On medication",   m.chronic.length ? "Yes (informal)" : "—"],
          ["Notes",           m.chronic.length ? "Self-reported · no clinic record attached" : "—"],
        ]}/>
        <MD_KVCard title="Care access" rows={[
          ["Health insurance", m.insurance],
          ["Last clinic visit", m.lastVisit],
          ["Nearest facility", <span className="muted">Not on Health detail · follow-up</span>],
          ["Pregnant / lactating", m.sex === "F" ? <span className="muted">Not on Health detail · follow-up</span> : "—"],
        ]}/>
      </div>
    </div>
  </div>
);

const MdEducation = ({ m }) => (
  <div>
    <MD_TabHeader title="Education"/>
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      <MD_KVCard title="Attainment" tint="programme" rows={[
        ["Literacy",            <Chip size="sm" tone="data">{m.literacy}</Chip>],
        ["Ever attended school", m.everSchool ? <Chip size="sm" tone="data">Yes</Chip> : <Chip size="sm" tone="danger">No</Chip>],
        ["Highest grade",        m.highestGrade],
        ["Currently attending",  m.currentlyAttending ? <Chip size="sm" tone="data">Yes</Chip> : "No"],
        ["Never-school reason",  <span className="muted">—</span>],
      ]}/>
      <MD_KVCard title="School history" rows={[
        ["Last school",      <span className="muted">Not on Education detail · follow-up</span>],
        ["Last year present",<span className="muted">—</span>],
        ["Reason for leaving",<span className="muted">—</span>],
        ["Vocational training",<span className="muted">—</span>],
      ]}/>
    </div>
  </div>
);

const MdEmployment = ({ m }) => (
  <div>
    <MD_TabHeader title="Employment" sub="Activity status and primary occupation."/>
    <div style={{padding:20}}>
      <div className="row-wrap" style={{marginBottom:16}}>
        <MD_Stat label="Activity"        value={m.activity}                   tint="quality"/>
        <MD_Stat label="Hours / week"    value={m.hoursPerWeek != null ? m.hoursPerWeek : "—"} tint="data"/>
        <MD_Stat label="Earnings band"   value={m.earningsBand}               tint="eligibility"/>
        <MD_Stat label="Employer"        value={m.employerType}               tint="programme"/>
      </div>
      <MD_KVCard title="Detail" rows={[
        ["Occupation (ISCO-08)", m.occupation],
        ["Industry (ISIC rev. 4)", m.industry],
        ["Employer",                       <span className="muted">Not on Employment detail · follow-up</span>],
        ["Multiple jobs",                  <span className="muted">—</span>],
        ["Looking for additional work",    <span className="muted">—</span>],
        ["Member of cooperative / SACCO",  <span className="muted">—</span>],
      ]}/>
    </div>
  </div>
);

const MdEvents = ({ m }) => (
  <div>
    <MD_TabHeader title="Vital events" sub="Birth · death · marriage · divorce · NIN-issued events. URSB + NIRA feed nightly."/>
    <div style={{padding:0}}>
      {m.events.length === 0 ? (
        <div style={{padding:'40px 20px', textAlign:'center'}} className="muted t-bodysm">
          Vital events not yet wired — a VitalEvent model + nightly URSB/NIRA
          feed land in a follow-up (HANDOFF §3.3).
        </div>
      ) : (
        <table className="tbl">
          <thead><tr><th>Event</th><th>Date</th><th>Note</th><th>Evidence</th></tr></thead>
          <tbody>
            {m.events.map((e, i) => (
              <tr key={i}>
                <td><Chip size="sm" tone="programme">{e.kind}</Chip></td>
                <td className="t-cap">{e.date}</td>
                <td className="t-bodysm">{e.note}</td>
                <td className="t-bodysm muted">{e.evidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  </div>
);

const MdHistory = ({ m }) => (
  <div>
    <MD_TabHeader title="Updates history" sub="ChangeRequests where this member is the subject."/>
    <div style={{padding:0}}>
      {m.upds.length === 0 ? (
        <div style={{padding:'40px 20px', textAlign:'center'}} className="muted t-bodysm">
          Updates-history join not yet wired — needs a filter on
          ChangeRequest.entity_type="member" + entity_id={m.mid} from
          apps.update_workflow (HANDOFF §3.3).
        </div>
      ) : (
        <table className="tbl">
          <thead><tr><th>UPD ID</th><th>Type</th><th>PMT impact</th><th>Decided</th><th>Status</th></tr></thead>
          <tbody>
            {m.upds.map(u => (
              <tr key={u.id} style={{cursor:'pointer'}}>
                <td className="col-id">{u.id}</td>
                <td>{u.type}</td>
                <td>{u.impact === "pmt_relevant"
                    ? <Chip size="sm" tone="eligibility">pmt_relevant</Chip>
                    : u.impact === "—" ? <span className="muted">—</span>
                    : <Chip size="sm" tone="neutral">{u.impact}</Chip>}</td>
                <td className="t-cap">{u.decidedAt}</td>
                <td><Chip size="sm">{u.status}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  </div>
);

const MdProgrammes = ({ m }) => (
  <div>
    <MD_TabHeader title="Programmes" sub="Member-level enrolments. Programmes that target individuals (e.g. SCG, child grants) attach here; household-level programmes attach to the household."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Add referral</button>}/>
    <div style={{padding:20}}>
      {m.programmes.length === 0 && (
        <div className="t-cap muted" style={{padding:'40px 0', textAlign:'center'}}>
          No member-level enrolments. Household-level programmes are listed under the household.
        </div>
      )}
      {m.programmes.map(p => (
        <div key={p.code} className="card" style={{padding:0, border:'1px solid var(--neutral-200)', boxShadow:'none', marginBottom:12}}>
          <div style={{padding:'12px 16px', display:'flex', alignItems:'center', justifyContent:'space-between', borderBottom:'1px solid var(--neutral-200)', background:'var(--accent-programme-bg)'}}>
            <div>
              <div className="t-cap" style={{color:'var(--accent-programme)'}}>{p.role.toUpperCase()}</div>
              <strong>{p.code}</strong>
            </div>
            <Chip tone="data">{p.status}</Chip>
          </div>
          <div style={{padding:16, display:'grid', gridTemplateColumns:'160px 1fr', rowGap:6, fontSize:13}}>
            <div className="muted">Enrolled since</div><div>{p.enrolledAt}</div>
            <div className="muted">Role</div><div>{p.role}</div>
            <div className="muted">Notes</div><div className="t-bodysm muted">Enrolment inherited through head of household's tranche; member is a co-beneficiary, not a primary recipient.</div>
          </div>
        </div>
      ))}
    </div>
  </div>
);

const MdAudit = ({ m }) => (
  <div>
    <MD_TabHeader title="Audit chain" sub="Tamper-evident events scoped to this member · permanent · DPO-accessible."/>
    <div style={{padding:0}}>
      {m.audit.length === 0 ? (
        <div style={{padding:'40px 20px', textAlign:'center'}} className="muted t-bodysm">
          Audit-chain join not yet wired — needs an AuditEvent filter on
          subject_member_id={m.mid} from apps.security (HANDOFF §3.3).
        </div>
      ) : (
        m.audit.map((e, i) => (
          <div key={i} style={{padding:'14px 20px', display:'flex', gap:14, alignItems:'flex-start', borderBottom:'1px solid var(--neutral-200)'}}>
            <div style={{
              width:32, height:32, borderRadius:'50%',
              background: e.tone === 'system' ? 'var(--neutral-200)' : 'var(--primary-100)',
              color: e.tone === 'system' ? 'var(--neutral-700)' : 'var(--primary-900)',
              display:'grid', placeItems:'center', fontSize:11, fontWeight:600, flex:'0 0 auto',
            }}>{(e.who || "").split(' ').map(w => w[0]).slice(0,2).join('')}</div>
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
        ))
      )}
    </div>
  </div>
);

Object.assign(window, { MemberDetailScreen, _projectMemberDetail });
