/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — 11.9 Household detail (US-005, US-090)
// AC-UPD-DIFF / AC-UPD-NO-SELF-APPROVE flow opens UPD ChangeRequest forms
// from this read-only page. No edit-in-place per UI-HH-3.

const { useState: useStateHH } = React;

const TABS = [
  "Overview", "Roster", "Health & Disability", "Education", "Employment",
  "Housing & Assets", "Food & Shocks", "Updates history", "Grievances",
  "Programmes", "Consent", "Audit",
];

const DEMO_HH = {
  registry_id: "01HXY7K3B2N9PVQE4M6FZRWS18",
  head_name: "Sarah Nakato",
  status: "Registered",
  village: "Bujumba Cell A",
  parish: "Bujumba",
  sub_county: "Bujumba",
  county: "Bujumba County",
  district: "Kalangala",
  sub_region: "Buganda South",
  region: "Central",
  gps: { lat: 0.234567, lng: 32.456789, acc_m: 4.5 },
  pmt: { score: 38.5, band: "POVERTY", model_version: 1, computed: "2026-05-14 09:11 EAT" },
  programme_enrolments: ["PDM", "NUSAF"],
  members: [
    { line: 1, surname: "Nakato", first_name: "Sarah", sex: "F", age: 38, role: "Head" },
    { line: 2, surname: "Mukasa", first_name: "James", sex: "M", age: 41, role: "Spouse" },
    { line: 3, surname: "Nakato", first_name: "Patience", sex: "F", age: 12, role: "Daughter" },
  ],
};

const HouseholdScreen = () => {
  const [tab, setTab] = useStateHH("Overview");
  return (
    <div className="page">
      <PageHeader
        title={`Household ${DEMO_HH.head_name}`}
        breadcrumb={["Operator console", "Households", DEMO_HH.head_name]}
        tone="data"
      >
        <Chip tone="registered" size="sm">{DEMO_HH.status}</Chip>
        <span className="t-mono ml-2">{DEMO_HH.registry_id}</span>
      </PageHeader>

      <div className="card mt-3">
        <div className="row gap-6" style={{flexWrap:'wrap', padding: '16px 20px'}}>
          <div>
            <div className="t-cap muted">Head of household</div>
            <div style={{fontWeight:500}}>{DEMO_HH.head_name}</div>
          </div>
          <div>
            <div className="t-cap muted">Location</div>
            <div>{DEMO_HH.village}, {DEMO_HH.parish}, {DEMO_HH.sub_county}, {DEMO_HH.district}</div>
            <div className="t-cap muted">{DEMO_HH.sub_region} / {DEMO_HH.region}</div>
          </div>
          <div>
            <div className="t-cap muted">GPS</div>
            <div className="t-mono">{DEMO_HH.gps.lat.toFixed(6)}, {DEMO_HH.gps.lng.toFixed(6)}</div>
            <div className="t-cap muted">{DEMO_HH.gps.acc_m}m accuracy</div>
          </div>
          <div>
            <div className="t-cap muted">PMT</div>
            <div><Chip tone="pmt" size="sm">{DEMO_HH.pmt.band}</Chip> <span style={{fontWeight:500}}>{DEMO_HH.pmt.score}</span></div>
            <div className="t-cap muted">v{DEMO_HH.pmt.model_version} · {DEMO_HH.pmt.computed}</div>
          </div>
          <div>
            <div className="t-cap muted">Programmes</div>
            <div className="row gap-1">
              {DEMO_HH.programme_enrolments.map(p => <Chip key={p} size="sm" tone="ref">{p}</Chip>)}
            </div>
          </div>
        </div>
        <div style={{display:'flex', justifyContent:'flex-end', gap: 8, padding: '8px 20px', borderTop:'1px solid var(--neutral-200)'}}>
          <button className="btn"><Icon name="filePlus" size={14}/> Open update</button>
          <button className="btn"><Icon name="alertTriangle" size={14}/> Open grievance</button>
          <button className="btn"><Icon name="moreH" size={14}/></button>
        </div>
      </div>

      <div className="tablist mt-4" role="tablist" aria-label="Household sections">
        {TABS.map(t => (
          <button key={t} role="tab" aria-selected={t === tab}
                  className={t === tab ? "tab tab--active" : "tab"}
                  onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      <div className="card mt-3" style={{minHeight: 280}}>
        {tab === "Overview" && <OverviewTab/>}
        {tab === "Roster" && <RosterTab/>}
        {tab === "Updates history" && <UpdatesTab/>}
        {tab === "Audit" && <AuditTab/>}
        {!["Overview", "Roster", "Updates history", "Audit"].includes(tab) && (
          <EmptyTab name={tab}/>
        )}
      </div>
    </div>
  );
};

const OverviewTab = () => (
  <div style={{padding:'16px 20px'}}>
    <div className="t-h3">Summary</div>
    <p>Registered 2026-04-22. 3 members. Head identified by NIN (verified by NIRA). Currently enrolled in PDM, NUSAF.</p>
    <div className="row gap-6 mt-3" style={{flexWrap:'wrap'}}>
      <KPI label="Members" value={DEMO_HH.members.length}/>
      <KPI label="PMT score" value={DEMO_HH.pmt.score}/>
      <KPI label="Programmes" value={DEMO_HH.programme_enrolments.length}/>
      <KPI label="Last UPD" value="14 May" tone="update"/>
    </div>
  </div>
);

const RosterTab = () => (
  <table className="data-table">
    <thead>
      <tr><th>Line</th><th>Name</th><th>Sex</th><th>Age</th><th>Role</th><th></th></tr>
    </thead>
    <tbody>
      {DEMO_HH.members.map(m => (
        <tr key={m.line}>
          <td>{m.line}</td>
          <td>{m.surname} {m.first_name}</td>
          <td>{m.sex}</td>
          <td className="num">{m.age}</td>
          <td>{m.role}</td>
          <td><button className="btn btn-ghost">Open update</button></td>
        </tr>
      ))}
    </tbody>
  </table>
);

const UpdatesTab = () => (
  <div style={{padding:'16px 20px'}}>
    <div className="t-h3">Updates history</div>
    <table className="data-table">
      <thead>
        <tr><th>When</th><th>Field</th><th>Old</th><th>New</th><th>By</th><th>Status</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>2026-05-14 09:11 EAT</td><td>telephone_1</td>
          <td className="t-mono">+256 700 000 001</td>
          <td className="t-mono">+256 700 000 002</td>
          <td>parish-chief-7</td>
          <td><Chip size="sm" tone="committed">committed</Chip></td>
        </tr>
        <tr>
          <td>2026-04-30 12:02 EAT</td><td>address_narrative</td>
          <td className="muted">—</td><td>Plot 7</td>
          <td>cdo-2</td>
          <td><Chip size="sm" tone="committed">committed</Chip></td>
        </tr>
        <tr>
          <td>2026-04-22 14:50 EAT</td><td>(initial intake)</td>
          <td colSpan={2} className="muted">household created via DIH promote</td>
          <td>system</td>
          <td><Chip size="sm" tone="committed">committed</Chip></td>
        </tr>
      </tbody>
    </table>
  </div>
);

const AuditTab = () => (
  <div style={{padding:'16px 20px'}}>
    <div className="t-h3">Audit chain</div>
    <p className="t-cap muted">Every read and write of personal data writes an
       AuditEvent. The hash chain renders here for support; tampering is
       detectable.</p>
    <table className="data-table">
      <thead>
        <tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Self hash (hex)</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>2026-05-14 09:11 EAT</td><td>parish-chief-7</td>
          <td>commit</td><td>change_request:01HXY…</td>
          <td className="t-mono">d2c4…fe09</td>
        </tr>
        <tr>
          <td>2026-04-22 14:50 EAT</td><td>system</td>
          <td>promote</td><td>household:01HXY…</td>
          <td className="t-mono">9b21…a045</td>
        </tr>
      </tbody>
    </table>
  </div>
);

const EmptyTab = ({ name }) => (
  <div className="empty-state" style={{padding:'24px 20px'}}>
    <div className="t-h3">{name}</div>
    <p className="muted">
      Module data renders here once the matching collector ships
      (questionnaire §6 maps each tab to a detail entity). Until then this is
      a placeholder so the screen layout is consistent across all 12 tabs.
    </p>
  </div>
);

Object.assign(window, { HouseholdScreen });
