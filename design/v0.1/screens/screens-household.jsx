/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — 11.9 Household detail (US-005, US-090)
// US-S11-017: wired to /api/v1/data-management/households/{id}/ when
// a householdId prop is provided. Falls back to DEMO_HH for the
// design-preview mode (no backend / unauthenticated / no id).
// AC-UPD-DIFF / AC-UPD-NO-SELF-APPROVE flow opens UPD ChangeRequest forms
// from this read-only page. No edit-in-place per UI-HH-3.


// Lightweight error boundary — when a child render throws, render the
// message + component stack inline instead of crashing the whole
// tree to a blank screen. Particularly useful while iterating on the
// live wiring; production would replace with a more polished
// component-stack reporter.
class HouseholdErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null, info: null };
  }
  static getDerivedStateFromError(err) {
    return { err };
  }
  componentDidCatch(err, info) {
    this.setState({ err, info });
    // eslint-disable-next-line no-console
    console.error("[HouseholdScreen render error]", err, info);
  }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="page">
        <div className="card mt-3" style={{padding:24, borderLeft:"3px solid var(--accent-danger)"}}>
          <div className="t-h3">Household screen crashed</div>
          <p className="muted">
            React threw while rendering this household. The detail is below — copy it here and we'll trace the exact field.
          </p>
          <pre style={{
            background:"var(--neutral-50)", padding:12, borderRadius:6,
            overflow:"auto", fontSize:12, maxHeight:300,
          }}>{String(this.state.err && this.state.err.message)}{"\n\n"}{this.state.info && this.state.info.componentStack}</pre>
        </div>
      </div>
    );
  }
}

const { useState: useStateHH, useEffect: useEffectHH, useMemo: useMemoHH } = React;

const HH_TABS = [
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


// Project the API HouseholdSerializer payload (with nested members
// + flat *_name geo fields, per S11-017 backend change) into the
// shape the existing render code expects. Keeps the JSX agnostic to
// whether it was mounted with mock data or live data.
const _hhApiToView = (h) => {
  const members = (h.members || []).slice().sort(
    (a, b) => (a.line_number || 0) - (b.line_number || 0),
  );
  const head = members.find(m => m.id === h.head_member) || members[0] || {};
  const headName = [head.surname, head.first_name].filter(Boolean).join(" ") || "(no head)";
  // Loose status mapping: backend has no Status enum on Household
  // today; we infer Registered from the existence of the row.
  return {
    registry_id: h.id,
    head_name: headName,
    status: "Registered",
    village: h.village_name || h.village || "—",
    parish: h.parish_name || h.parish || "—",
    sub_county: h.sub_county_name || h.sub_county || "—",
    county: h.county_name || h.county || "—",
    district: h.district_name || h.district || "—",
    sub_region: h.sub_region_name || h.sub_region || "—",
    region: h.region_name || h.region || "—",
    address_narrative: h.address_narrative || "",
    urban_rural: h.urban_rural || "",
    gps: (h.gps_lat != null && h.gps_lng != null)
      ? { lat: Number(h.gps_lat), lng: Number(h.gps_lng), acc_m: h.gps_accuracy_m }
      : null,
    pmt: h.current_pmt_score != null
      ? {
          score: Number(h.current_pmt_score),
          band: h.current_vulnerability_band || "—",
          model_version: null,
          computed: null,
        }
      : null,
    programme_enrolments: [],
    source: h.current_intake_source || "—",
    enumeration_area: h.enumeration_area || "",
    household_number: h.household_number || "",
    created_at: h.created_at,
    updated_at: h.updated_at,
    members: members.map(m => ({
      id: m.id,
      line: m.line_number,
      surname: m.surname || "",
      first_name: m.first_name || "",
      sex: m.sex || "—",
      age: m.age_years != null ? m.age_years : "—",
      role: (m.id === h.head_member) ? "Head" : (m.relationship_to_head || "—"),
      nin_last4: m.nin_last4 || "",
      nin_status: m.nin_status || "",
      telephone_1: m.telephone_1 || "",
    })),
    // source_payload (US-S11-020) carries the canonical_payload of
    // the upstream StageRecord — surfaces questionnaire blocks
    // (housing, education, food security, etc.) that aren't on the
    // Household model itself. Members in source_payload still carry
    // their per-member detail blocks (health, education, employment).
    source: h.source_payload || null,
  };
};


// Resolve a code from the questionnaire to a label. Forms encode
// answers as numeric strings ("01", "11", "16"); the React side
// renders them with light human labels for the most operationally-
// relevant fields. Codes not in the dictionary fall back to "code X".
const KOBO_LABELS = {
  c4_sex:           { "1": "Male", "2": "Female" },
  // Roof / wall / floor / cooking fuel / lighting / water / toilet
  // labels follow the UBOS questionnaire codes. Operators will
  // recognize them; full lookup tables ship with REF-DATA later.
  d1_chronic:       { "1": "Yes", "2": "No", "8": "Don't know" },
  d_disability:     { "01": "No difficulty", "02": "Some difficulty",
                      "03": "A lot of difficulty", "04": "Cannot do at all" },
  e_literacy:       { "1": "Reads + writes", "2": "Reads only", "3": "Neither" },
  e_attendance:     { "1": "Yes", "2": "No" },
  yes_no:           { "1": "Yes", "2": "No" },
  shock_affected:   { "1": "Yes", "2": "No" },
  coping_level:     { "1": "Always", "2": "Often", "3": "Sometimes", "4": "Never" },
};
const _lbl = (dict, code) => (dict[String(code)] || (code ? `code ${code}` : "—"));


const HouseholdScreen = ({ householdId, onNavigate } = {}) => {
  const [tab, setTab] = useStateHH("Overview");
  // Live-data state. Starts null when a householdId is given (loading
  // spinner); falls back to DEMO_HH when no id (design preview).
  const [liveHh, setLiveHh] = useStateHH(null);
  const [loadError, setLoadError] = useStateHH(null);
  const [dataSource, setDataSource] = useStateHH(householdId ? "loading" : "mock");

  useEffectHH(() => {
    if (!householdId) return undefined;
    let cancelled = false;
    setDataSource("loading");
    fetch(`/api/v1/data-management/households/${householdId}/`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(data => {
        if (cancelled) return;
        setLiveHh(_hhApiToView(data));
        setDataSource("live");
      })
      .catch(err => {
        if (cancelled) return;
        setLoadError(String(err.message || err));
        setDataSource("error");
      });
    return () => { cancelled = true; };
  }, [householdId]);

  // Memoised view model — live wins if loaded; mock for design preview.
  const hh = useMemoHH(() => {
    if (liveHh) return liveHh;
    if (!householdId) return DEMO_HH;
    return null;
  }, [liveHh, householdId]);

  if (dataSource === "loading") {
    return (
      <div className="page">
        <div className="card mt-3" style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
          <Icon name="clock" size={32} color="var(--neutral-300)"/>
          <div className="t-bodysm mt-2">Loading household <span className="t-mono">{(householdId || "").slice(0, 12)}…</span></div>
        </div>
      </div>
    );
  }
  if (dataSource === "error") {
    return (
      <div className="page">
        <div className="card mt-3" style={{padding:32, borderLeft:"3px solid var(--accent-danger)"}}>
          <div className="t-h3">Couldn't load household</div>
          <p className="muted">Request to <code>/api/v1/data-management/households/{householdId}/</code> failed: <strong>{loadError}</strong></p>
          <p className="muted">Make sure you're logged into <a href="/admin/" target="_blank" rel="noreferrer">Django admin</a> first — session-cookie auth carries through to the API.</p>
        </div>
      </div>
    );
  }
  if (!hh) return null;

  return (
    <div className="page">
      <PageHeader
        eyebrow={`HOUSEHOLD DETAIL · ${hh.registry_id}`}
        title={hh.head_name + (dataSource === "live" ? "  (live)" : dataSource === "mock" ? "  (mock)" : "")}
        sub={`${hh.village}, ${hh.parish}, ${hh.sub_county}, ${hh.district} · ${hh.sub_region} / ${hh.region}`}
        right={onNavigate ? (
          <button className="btn" onClick={() => onNavigate("registry")}>
            <Icon name="chevronLeft" size={14}/> Back to Registry
          </button>
        ) : null}
      />

      <div className="card mt-3">
        <div className="row gap-6" style={{flexWrap:'wrap', padding: '16px 20px'}}>
          <div>
            <div className="t-cap muted">Head of household</div>
            <div style={{fontWeight:500}}>{hh.head_name}</div>
          </div>
          <div>
            <div className="t-cap muted">Location</div>
            <div>{hh.village}, {hh.parish}, {hh.sub_county}, {hh.district}</div>
            <div className="t-cap muted">{hh.sub_region} / {hh.region}</div>
          </div>
          <div>
            <div className="t-cap muted">GPS</div>
            {hh.gps
              ? <>
                  <div className="t-mono">{hh.gps.lat.toFixed(6)}, {hh.gps.lng.toFixed(6)}</div>
                  <div className="t-cap muted">{hh.gps.acc_m ?? "?"}m accuracy</div>
                </>
              : <div className="t-bodysm muted">—</div>}
          </div>
          <div>
            <div className="t-cap muted">PMT</div>
            {hh.pmt
              ? <>
                  <div><Chip tone="pmt" size="sm">{hh.pmt.band}</Chip> <span style={{fontWeight:500}}>{hh.pmt.score}</span></div>
                  {hh.pmt.computed && <div className="t-cap muted">v{hh.pmt.model_version} · {hh.pmt.computed}</div>}
                </>
              : <div className="t-bodysm muted">not scored</div>}
          </div>
          <div>
            <div className="t-cap muted">{dataSource === "live" ? "Source" : "Programmes"}</div>
            {dataSource === "live"
              ? <Chip size="sm" tone="data">{hh.source}</Chip>
              : <div className="row gap-1">
                  {hh.programme_enrolments.map(p => <Chip key={p} size="sm" tone="ref">{p}</Chip>)}
                </div>}
          </div>
        </div>
        <div style={{display:'flex', justifyContent:'flex-end', gap: 8, padding: '8px 20px', borderTop:'1px solid var(--neutral-200)'}}>
          <button className="btn"><Icon name="edit" size={14}/> Open update</button>
          <button className="btn"><Icon name="message" size={14}/> Open grievance</button>
          <button className="btn"><Icon name="moreH" size={14}/></button>
        </div>
      </div>

      <div className="tablist mt-4" role="tablist" aria-label="Household sections">
        {HH_TABS.map(t => (
          <button key={t} role="tab" aria-selected={t === tab}
                  className={t === tab ? "tab tab--active" : "tab"}
                  onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      <div className="card mt-3" style={{minHeight: 280}}>
        {tab === "Overview" && <OverviewTab hh={hh} live={dataSource === "live"}/>}
        {tab === "Roster" && <RosterTab hh={hh} live={dataSource === "live"}/>}
        {tab === "Health & Disability" && <HealthTab hh={hh}/>}
        {tab === "Education" && <EducationTab hh={hh}/>}
        {tab === "Employment" && <EmploymentTab hh={hh}/>}
        {tab === "Housing & Assets" && <HousingTab hh={hh}/>}
        {tab === "Food & Shocks" && <FoodShocksTab hh={hh}/>}
        {tab === "Programmes" && <ProgrammesTab hh={hh}/>}
        {tab === "Consent" && <ConsentTab hh={hh}/>}
        {tab === "Updates history" && <UpdatesTab live={dataSource === "live"}/>}
        {tab === "Audit" && <AuditTab live={dataSource === "live"}/>}
        {tab === "Grievances" && <EmptyTab name={tab}/>}
      </div>
    </div>
  );
};

const OverviewTab = ({ hh, live }) => (
  <div style={{padding:'16px 20px'}}>
    <div className="t-h3">Summary</div>
    <p>
      {live
        ? <>Registered {hh.created_at?.slice(0, 10) || "—"}. {hh.members.length} members. Source: <strong>{hh.source}</strong>.{hh.household_number ? <> Form HH#: <span className="t-mono">{hh.household_number}</span>.</> : null}</>
        : <>Registered 2026-04-22. 3 members. Head identified by NIN (verified by NIRA). Currently enrolled in PDM, NUSAF.</>}
    </p>
    <div className="row gap-6 mt-3" style={{flexWrap:'wrap'}}>
      <KPI title="Members" value={hh.members.length}/>
      <KPI title="PMT score" value={hh.pmt ? hh.pmt.score : "—"}/>
      <KPI title={live ? "Source" : "Programmes"}
           value={live ? hh.source : (hh.programme_enrolments?.length || 0)}/>
      {!live && <KPI title="Last UPD" value="14 May"/>}
    </div>
  </div>
);

const RosterTab = ({ hh, live }) => (
  <table className="data-table">
    <thead>
      <tr><th>Line</th><th>Name</th><th>Sex</th><th>Age</th><th>Role</th>
        {live && <th>NIN</th>}
        {live && <th>Phone</th>}
        <th></th></tr>
    </thead>
    <tbody>
      {hh.members.map(m => (
        <tr key={m.line}>
          <td>{m.line}</td>
          <td>{m.surname} {m.first_name}</td>
          <td>{m.sex}</td>
          <td className="num">{m.age}</td>
          <td>{m.role}</td>
          {live && <td className="t-mono">{m.nin_last4 ? `…${m.nin_last4}` : "—"}</td>}
          {live && <td className="t-mono">{m.telephone_1 || "—"}</td>}
          <td><button className="btn btn-ghost">Open update</button></td>
        </tr>
      ))}
    </tbody>
  </table>
);

const UpdatesTab = ({ live }) => (
  <div style={{padding:'16px 20px'}}>
    <div className="t-h3">Updates history</div>
    {live ? (
      <p className="muted t-bodysm">
        Wiring to <code>/api/v1/upd/change-requests/?household_id={"{id}"}</code> deferred —
        see UPD reviewer (<a href="#">screens-upd.jsx</a>) for the per-change-request detail.
      </p>
    ) : (
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
    )}
  </div>
);

const AuditTab = ({ live }) => (
  <div style={{padding:'16px 20px'}}>
    <div className="t-h3">Audit chain</div>
    <p className="t-cap muted">Every read and write of personal data writes an
       AuditEvent. The hash chain renders here for support; tampering is
       detectable.</p>
    {live ? (
      <p className="muted t-bodysm">
        Wiring to <code>/api/v1/security/audit-events/?entity_id={"{id}"}</code>
        deferred — Django admin at <code>/admin/security/auditevent/</code> shows
        the live chain today.
      </p>
    ) : (
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
    )}
  </div>
);

// ──────────────────────────────────────────────────────────────────
// Tab renderers backed by source_payload (US-S11-020). Each one
// gracefully degrades to a placeholder if the questionnaire block
// is missing (e.g., the household came in via walk-in CAPI not Kobo).
// ──────────────────────────────────────────────────────────────────

const _SourceMissing = ({ section }) => (
  <div className="empty-state" style={{padding:"24px 20px"}}>
    <div className="t-h3">{section}</div>
    <p className="muted">
      No questionnaire payload attached to this household — likely a
      walk-in CAPI record. The {section.toLowerCase()} section ships
      when the matching collector lands.
    </p>
  </div>
);

const _DataTable = ({ rows }) => (
  <table className="data-table">
    <thead><tr><th>Field</th><th>Value</th></tr></thead>
    <tbody>
      {rows.map(([k, v], i) => (
        <tr key={i}>
          <td className="muted">{k}</td>
          <td>{(v === "" || v == null) ? <span className="muted">—</span> : v}</td>
        </tr>
      ))}
    </tbody>
  </table>
);

const HealthTab = ({ hh }) => {
  if (!hh.source) return <_SourceMissing section="Health & Disability"/>;
  const members = (hh.source.members || []).filter(m => m.health);
  if (members.length === 0) return <_SourceMissing section="Health & Disability"/>;
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Health &amp; Disability — per member</div>
      <table className="data-table">
        <thead>
          <tr><th>Line</th><th>Name</th><th>Chronic illness</th>
            <th>Seeing</th><th>Hearing</th><th>Walking</th>
            <th>Remembering</th><th>Self-care</th><th>Communicating</th></tr>
        </thead>
        <tbody>
          {members.map((m, i) => (
            <tr key={i}>
              <td>{m.line_number}</td>
              <td>{[m.surname, m.first_name].filter(Boolean).join(" ")}</td>
              <td>{_lbl(KOBO_LABELS.d1_chronic, m.health.chronic_illness)}</td>
              <td>{_lbl(KOBO_LABELS.d_disability, m.health.seeing)}</td>
              <td>{_lbl(KOBO_LABELS.d_disability, m.health.hearing)}</td>
              <td>{_lbl(KOBO_LABELS.d_disability, m.health.walking)}</td>
              <td>{_lbl(KOBO_LABELS.d_disability, m.health.remembering)}</td>
              <td>{_lbl(KOBO_LABELS.d_disability, m.health.self_care)}</td>
              <td>{_lbl(KOBO_LABELS.d_disability, m.health.communicating)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const EducationTab = ({ hh }) => {
  if (!hh.source) return <_SourceMissing section="Education"/>;
  const members = (hh.source.members || []).filter(m => m.education);
  if (members.length === 0) return <_SourceMissing section="Education"/>;
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Education — per member</div>
      <table className="data-table">
        <thead>
          <tr><th>Line</th><th>Name</th><th>Literacy</th>
            <th>Ever school</th><th>Highest grade</th>
            <th>Currently attending</th><th>Never-school reason</th></tr>
        </thead>
        <tbody>
          {members.map((m, i) => (
            <tr key={i}>
              <td>{m.line_number}</td>
              <td>{[m.surname, m.first_name].filter(Boolean).join(" ")}</td>
              <td>{_lbl(KOBO_LABELS.e_literacy, m.education.literacy)}</td>
              <td>{_lbl(KOBO_LABELS.yes_no, m.education.ever_school)}</td>
              <td>{m.education.highest_grade || <span className="muted">—</span>}</td>
              <td>{_lbl(KOBO_LABELS.e_attendance, m.education.currently_attending)}</td>
              <td>{m.education.never_school_reason || <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const EmploymentTab = ({ hh }) => {
  if (!hh.source) return <_SourceMissing section="Employment"/>;
  const members = (hh.source.members || []).filter(m => m.employment);
  if (members.length === 0) return <_SourceMissing section="Employment"/>;
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Employment &amp; livelihoods — per member</div>
      <table className="data-table">
        <thead>
          <tr><th>Line</th><th>Name</th><th>Main job</th>
            <th>Sector</th><th>Freq</th><th>Status</th>
            <th>Programmes</th><th>Savings</th></tr>
        </thead>
        <tbody>
          {members.map((m, i) => (
            <tr key={i}>
              <td>{m.line_number}</td>
              <td>{[m.surname, m.first_name].filter(Boolean).join(" ")}</td>
              <td>{m.employment.main_job || <span className="muted">—</span>}</td>
              <td>{m.employment.work_sector || <span className="muted">—</span>}</td>
              <td>{m.employment.work_frequency || <span className="muted">—</span>}</td>
              <td>{m.employment.work_status || <span className="muted">—</span>}</td>
              <td>{m.employment.programmes || <span className="muted">—</span>}</td>
              <td>{_lbl(KOBO_LABELS.yes_no, m.employment.made_savings)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const HousingTab = ({ hh }) => {
  if (!hh.source?.housing) return <_SourceMissing section="Housing & Assets"/>;
  const h = hh.source.housing;
  const assets = (h.assets_owned || "").split(/\s+/).filter(Boolean);
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Housing &amp; Assets</div>
      <div className="row gap-6" style={{flexWrap:"wrap", marginTop:8}}>
        <div style={{minWidth:280, flex:1}}>
          <_DataTable rows={[
            ["Tenure", h.tenure],
            ["Dwelling type", h.dwelling_type],
            ["Rooms (total)", h.rooms_total],
            ["Rooms (sleeping)", h.rooms_sleeping],
            ["Roof material", h.roof_material],
            ["Wall material", h.wall_material],
            ["Floor material", h.floor_material],
            ["Cooking fuel", h.cooking_fuel],
            ["Lighting source", h.lighting_source],
          ]}/>
        </div>
        <div style={{minWidth:280, flex:1}}>
          <_DataTable rows={[
            ["Water source", h.water_source],
            ["Toilet type", h.toilet_type],
            ["Share toilet", _lbl(KOBO_LABELS.yes_no, h.share_toilet)],
            ["Share-toilet HHs", h.share_toilet_households],
            ["Waste disposal", h.waste_disposal],
            ["Livelihood source", h.livelihood_source],
          ]}/>
        </div>
      </div>
      <div style={{marginTop:16}}>
        <div className="t-cap" style={{fontWeight:600, marginBottom:6}}>ASSETS OWNED</div>
        {assets.length === 0
          ? <span className="muted">—</span>
          : <div className="row-wrap" style={{display:"flex", flexWrap:"wrap", gap:6}}>
              {assets.map(a => (
                <Chip key={a} size="sm" tone="data">
                  {a}{h.asset_counts[a] != null ? ` ×${h.asset_counts[a]}` : ""}
                </Chip>
              ))}
            </div>}
      </div>
    </div>
  );
};

const FoodShocksTab = ({ hh }) => {
  if (!hh.source?.food_security && !hh.source?.shocks_coping) {
    return <_SourceMissing section="Food & Shocks"/>;
  }
  const fs = hh.source.food_security || {};
  const sc = hh.source.shocks_coping || {};
  const groups = fs.food_groups || {};
  const fiesKeys = Object.keys(fs.fies || {});
  const fiesYes = fiesKeys.filter(k => String(fs.fies[k]) === "1").length;
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Food security &amp; shocks</div>

      <div className="t-cap" style={{fontWeight:600, marginTop:12, marginBottom:6}}>
        FOOD INSECURITY EXPERIENCE SCALE (FIES) · {fiesYes}/{fiesKeys.length} yes
      </div>
      <_DataTable rows={fiesKeys.map(k => [k.toUpperCase(),
        _lbl(KOBO_LABELS.yes_no, fs.fies[k])])}/>

      <div className="t-cap" style={{fontWeight:600, marginTop:16, marginBottom:6}}>7-DAY FOOD CONSUMPTION</div>
      <table className="data-table">
        <thead><tr><th>Group</th><th>Days</th><th>Primary source</th><th>Secondary</th></tr></thead>
        <tbody>
          {Object.entries(groups).map(([label, g]) => (
            <tr key={label}>
              <td style={{textTransform:"capitalize"}}>{label.replace(/_/g, " ")}</td>
              <td className="num">{g.days != null ? g.days : "—"}</td>
              <td>{g.source_primary || <span className="muted">—</span>}</td>
              <td>{g.source_secondary || <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="t-cap" style={{fontWeight:600, marginTop:16, marginBottom:6}}>SHOCKS &amp; COPING</div>
      <div className="row gap-2" style={{marginBottom:8}}>
        <Chip size="sm" tone="data">Affected: {_lbl(KOBO_LABELS.shock_affected, sc.shock_affected)}</Chip>
      </div>
      <_DataTable rows={Object.entries(sc.coping || {}).map(([k, v]) => [
        k.replace(/^l0[12][a-z]_/, ""),
        _lbl(KOBO_LABELS.coping_level, v),
      ])}/>
    </div>
  );
};

const ProgrammesTab = ({ hh }) => {
  if (!hh.source) return <_SourceMissing section="Programmes"/>;
  // Aggregate programme participation across members.
  const beneficiaries = (hh.source.members || []).filter(
    m => m.employment?.gov_program_beneficiary === "1",
  );
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Government programme participation</div>
      {beneficiaries.length === 0
        ? <p className="muted">No member reported as a government programme beneficiary.</p>
        : (
          <table className="data-table">
            <thead><tr><th>Line</th><th>Name</th><th>Programmes</th><th>Currently benefiting</th></tr></thead>
            <tbody>
              {beneficiaries.map((m, i) => (
                <tr key={i}>
                  <td>{m.line_number}</td>
                  <td>{[m.surname, m.first_name].filter(Boolean).join(" ")}</td>
                  <td>{m.employment.programmes || <span className="muted">—</span>}</td>
                  <td>{_lbl(KOBO_LABELS.yes_no, m.employment.currently_benefiting)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  );
};

const ConsentTab = ({ hh }) => {
  const iv = hh.source?.interview;
  if (!iv) return <_SourceMissing section="Consent"/>;
  return (
    <div style={{padding:"16px 20px"}}>
      <div className="t-h3">Consent &amp; interview metadata</div>
      <_DataTable rows={[
        ["Consent recorded", _lbl(KOBO_LABELS.yes_no, iv.consent)],
        ["Interview result", iv.interview_result],
        ["Respondent name", iv.respondent_name],
        ["Respondent phone", iv.respondent_phone],
        ["Head name (form)", iv.head_name],
        ["Household size declared", iv.hh_size],
        ["Interviewer", iv.interviewer],
        ["Supervisor", iv.supervisor],
        ["Device ID", iv.deviceid],
        ["Interview start", iv.start],
        ["Interview end", iv.end],
      ]}/>
    </div>
  );
};


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

// Public-facing component wraps the inner one in the error boundary
// so a render crash surfaces as a visible message instead of a blank
// page. App shell imports `HouseholdScreen` so the wrap is transparent.
const _HouseholdScreenInner = HouseholdScreen;
const HouseholdScreenWithBoundary = (props) => (
  <HouseholdErrorBoundary>
    <_HouseholdScreenInner {...props}/>
  </HouseholdErrorBoundary>
);

Object.assign(window, { HouseholdScreen: HouseholdScreenWithBoundary });
