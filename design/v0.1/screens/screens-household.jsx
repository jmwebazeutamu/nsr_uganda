/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — 11.9 Household detail (US-005, US-090)
// US-S11-017: wired to /api/v1/data-management/households/{id}/ when
// a householdId prop is provided. Falls back to DEMO_HH for the
// design-preview mode (no backend / unauthenticated / no id).
// AC-UPD-DIFF / AC-UPD-NO-SELF-APPROVE flow opens UPD ChangeRequest forms
// from this read-only page. No edit-in-place per UI-HH-3.

const { useState: useStateHH, useEffect: useEffectHH, useMemo: useMemoHH } = React;

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
  };
};


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
        eyebrow={<>HOUSEHOLD DETAIL · <span className="t-mono">{hh.registry_id}</span></>}
        title={<>
          {hh.head_name}{" "}
          <Chip tone="data" size="sm">{hh.status}</Chip>
          {dataSource === "live" && <Chip tone="eligibility" size="sm">live</Chip>}
          {dataSource === "mock" && <Chip tone="quality" size="sm">mock</Chip>}
        </>}
        sub={<>{hh.village}, {hh.parish}, {hh.sub_county}, {hh.district} &middot; {hh.sub_region} / {hh.region}</>}
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
        {tab === "Overview" && <OverviewTab hh={hh} live={dataSource === "live"}/>}
        {tab === "Roster" && <RosterTab hh={hh} live={dataSource === "live"}/>}
        {tab === "Updates history" && <UpdatesTab live={dataSource === "live"}/>}
        {tab === "Audit" && <AuditTab live={dataSource === "live"}/>}
        {!["Overview", "Roster", "Updates history", "Audit"].includes(tab) && (
          <EmptyTab name={tab}/>
        )}
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
