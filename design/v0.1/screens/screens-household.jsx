/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — Household detail (US-005, US-090)
//
// Visual design from the claude.ai/design redesign deposited at
// design/v0.1/html/Household_detail.html and stashed for reference
// at design/v0.1/screens/_redesign_reference.jsx.
//
// Data layer:
// - Household + members + canonical_payload come from
//   /api/v1/data-management/households/{id}/ (US-S11-017 wiring;
//   canonical_payload added in US-S11-020).
// - Audit chain tab calls /api/v1/security/audit-events/?entity_id=
//   (US-S12-002).
// - Updates history tab calls /api/v1/upd/change-requests/?entity_id=
//   (US-S12-003).
// - Tabs that don't have a backend source yet (Programmes,
//   Grievances, Consent's evidence block) render the redesign's
//   sample content with a clear "design-preview content" hint so an
//   operator doesn't mistake it for live data.

const {
  useState: useStateHH,
  useEffect: useEffectHH,
  useMemo: useMemoHH,
} = React;


// ────────────────────────────────────────────────────────────────
// Error boundary — render crashes inline rather than blanking the
// screen. Stays from S11-017's debug pass.
// ────────────────────────────────────────────────────────────────
class HouseholdErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null, info: null };
  }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { this.setState({ err, info }); }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="page">
        <div className="card mt-3" style={{padding:24, borderLeft:"3px solid var(--accent-danger)"}}>
          <div className="t-h3">Household screen crashed</div>
          <p className="muted">React threw while rendering this household.</p>
          <pre style={{background:"var(--neutral-50)", padding:12, borderRadius:6,
                       overflow:"auto", fontSize:12, maxHeight:300}}>
            {String(this.state.err?.message)}{"\n\n"}{this.state.info?.componentStack}
          </pre>
        </div>
      </div>
    );
  }
}


// Mock fallback — kept lean so the design preview still tells the
// visual story. The live projection produces the same shape.
const DEMO_HH = {
  rid: "01HXY7K3B2N9PVQE4M6FZRWS18",
  head: "Sarah Nakato",
  status: "Registered",
  hh: 3,
  subreg: "Buganda South", district: "Lyantonde", parish: "Kibalinga",
  village: "Okello Village", code: "—",
  gps: { lat: 0.266500, lng: 33.396584, acc: 10 },
  pmt: { score: 0.39, band: "Poorest 40%", model: "v2.4", computedAt: "—" },
  phone: "+256 772 558 219",
  capturedAt: "—",
  capturedBy: "—",
  source: "DIH",
  programmes: [],
  members: [
    { line:1, name:"Sarah Nakato", rel:"Head", sex:"F", age:38, nin:"…ABCD",
      dob:"—", literacy:"—", everSchool:"Yes", highestGrade:"—",
      currentlyAttending:"—", neverReason:"—",
      health:null, education:null, employment:null },
  ],
  questionnaire: null,
};


// Project the API HouseholdSerializer payload into the view-model
// the redesign's render tree consumes.
const _hhApiToView = (h) => {
  const members = (h.members || []).slice().sort(
    (a, b) => (a.line_number || 0) - (b.line_number || 0),
  );
  const head = members.find(m => m.id === h.head_member) || members[0] || {};
  const headName = [head.surname, head.first_name].filter(Boolean).join(" ")
                   || "(no head)";
  const payload = h.source_payload || null;
  const qMembersByLine = {};
  if (payload?.members) {
    for (const qm of payload.members) {
      qMembersByLine[qm.line_number] = qm;
    }
  }

  return {
    rid: h.id,
    head: headName,
    status: "Registered",
    hh: members.length,
    sex: (head.sex || "").toUpperCase().startsWith("F") ? "F" : "M",
    subreg:   h.sub_region_name || h.sub_region || "—",
    district: h.district_name   || h.district   || "—",
    parish:   h.parish_name     || h.parish     || "—",
    village:  h.village_name    || h.village    || "—",
    code:     h.parish          || "—",
    gps: (h.gps_lat != null && h.gps_lng != null)
      ? { lat: Number(h.gps_lat), lng: Number(h.gps_lng),
          acc: h.gps_accuracy_m ?? null }
      : null,
    pmt: h.current_pmt_score != null
      ? { score: Number(h.current_pmt_score) / 100,
          band: h.current_vulnerability_band || "—",
          model: null, computedAt: null }
      : null,
    phone: head.telephone_1 || "—",
    capturedAt: (h.created_at || "").slice(0, 19).replace("T", " ") || "—",
    capturedBy: payload?._source_keys?.kobo_submitted_by || "—",
    source: (h.current_intake_source || "").toUpperCase() || "—",
    enumerationArea: h.enumeration_area || "",
    householdNumber: h.household_number || "",
    programmes: [],  // populated when REF wires in
    members: members.map(m => {
      const qm = qMembersByLine[m.line_number] || {};
      return {
        id: m.id,
        line: m.line_number,
        name: [m.surname, m.first_name].filter(Boolean).join(" ") || "—",
        rel: (m.id === h.head_member) ? "Head" : (m.relationship_to_head || "—"),
        sex: m.sex || "—",
        age: m.age_years ?? "—",
        nin: m.nin_last4 ? `…${m.nin_last4}` : "—",
        dob: m.date_of_birth || "—",
        phone: m.telephone_1 || "",
        // Questionnaire blocks (per-member) — may be null when this
        // household didn't come from Kobo.
        literacy:           _eduLabel(qm.education?.literacy),
        everSchool:         _yesNo(qm.education?.ever_school),
        highestGrade:       qm.education?.highest_grade || "—",
        currentlyAttending: _yesNo(qm.education?.currently_attending),
        neverReason:        qm.education?.never_school_reason || "—",
        health: qm.health || null,
        education: qm.education || null,
        employment: qm.employment || null,
      };
    }),
    questionnaire: payload,
    sourcePayload: payload,
  };
};

const _yesNo = (code) => ({"1":"Yes","2":"No"}[String(code)] || (code ? `code ${code}` : "—"));
const _eduLabel = (code) => ({
  "1": "Reads + writes", "2": "Reads only", "3": "Neither",
})[String(code)] || (code ? `code ${code}` : "—");


// Tab definitions match the redesign's IDs + count badges.
const HH_TABS = [
  { id: "over",  label: "Overview" },
  { id: "rost",  label: "Roster" },
  { id: "hd",    label: "Health & Disability" },
  { id: "ed",    label: "Education" },
  { id: "emp",   label: "Employment" },
  { id: "hous",  label: "Housing & Assets" },
  { id: "food",  label: "Food & Shocks" },
  { id: "hist",  label: "Updates history" },
  { id: "grm",   label: "Grievances" },
  { id: "prog",  label: "Programmes" },
  { id: "cons",  label: "Consent" },
  { id: "aud",   label: "Audit" },
];


const _HouseholdScreenInner = ({ householdId, onNavigate }) => {
  const [tab, setTab] = useStateHH("over");
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

  const h = useMemoHH(() => liveHh || (householdId ? null : DEMO_HH), [liveHh, householdId]);

  if (dataSource === "loading") {
    return (
      <div className="page">
        <div className="card mt-3" style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
          <Icon name="clock" size={32} color="var(--neutral-300)"/>
          <div className="t-bodysm mt-2">
            Loading household <span className="t-mono">{(householdId || "").slice(0, 12)}…</span>
          </div>
        </div>
      </div>
    );
  }
  if (dataSource === "error") {
    return (
      <div className="page">
        <div className="card mt-3" style={{padding:32, borderLeft:"3px solid var(--accent-danger)"}}>
          <div className="t-h3">Couldn't load household</div>
          <p className="muted">
            Request to <code>/api/v1/data-management/households/{householdId}/</code>
            failed: <strong>{loadError}</strong>
          </p>
          <p className="muted">
            Make sure you're logged into <a href="/admin/" target="_blank" rel="noreferrer">Django admin</a>
            first — session-cookie auth carries through to the API.
          </p>
        </div>
      </div>
    );
  }
  if (!h) return null;

  return (
    <div className="page">
      <PageHeader
        eyebrow={`HOUSEHOLD DETAIL · ${h.rid}`}
        title={h.head + (dataSource === "live" ? "   (live)" : dataSource === "mock" ? "   (mock)" : "")}
        sub={`${h.village} · ${h.code} · ${h.parish}, ${h.district} · ${h.subreg}`}
        right={onNavigate ? (
          <button className="btn" onClick={() => onNavigate("registry")}>
            <Icon name="chevronLeft" size={14}/> Back to Registry
          </button>
        ) : null}
      />

      {/* Summary card with 5 Facts + status bar */}
      <div className="card" style={{padding:0, marginBottom:16}}>
        <div style={{padding:"18px 20px", display:"grid",
                     gridTemplateColumns:"1.4fr 2fr 1.4fr 1fr 1fr", gap:24,
                     alignItems:"flex-start"}}>
          <Fact label="Head of household" big={h.head}
            sub={`HH size ${h.hh} · ${h.members.filter(m => m.sex === "F").length}F / ${h.members.filter(m => m.sex === "M").length}M`}/>
          <Fact label="Location"
            big={`${h.village}, ${h.parish}, ${h.district}`}
            sub={`${h.subreg}`}/>
          <Fact label="GPS"
            big={h.gps ? <span className="t-mono" style={{fontSize:14}}>
              {h.gps.lat.toFixed(6)}, {h.gps.lng.toFixed(6)}
            </span> : <span className="muted">—</span>}
            sub={h.gps?.acc != null ? `${h.gps.acc}m accuracy` : null}/>
          <div>
            <div className="t-cap">PMT</div>
            {h.pmt ? (
              <>
                <div className="row gap-2" style={{marginTop:2}}>
                  <span className="muted t-bodysm">score</span>
                  <span style={{fontSize:22, fontWeight:700}}>
                    {h.pmt.score.toFixed(2)}
                  </span>
                </div>
                <div className="row gap-2 mt-1">
                  <Chip size="sm" tone="eligibility">{h.pmt.band}</Chip>
                </div>
              </>
            ) : <div className="t-bodysm muted mt-1">not scored</div>}
          </div>
          <div>
            <div className="t-cap">Source</div>
            <div className="row gap-2 mt-1">
              <Chip size="sm" tone="data">{h.source.toLowerCase()}</Chip>
            </div>
            <div className="t-cap mt-2">Captured {h.capturedAt}</div>
          </div>
        </div>
        <div style={{borderTop:"1px solid var(--neutral-200)", padding:"12px 20px",
                     display:"flex", alignItems:"center", gap:12,
                     background:"var(--neutral-50)"}}>
          <Chip>{h.status}</Chip>
          <span className="t-bodysm muted">
            {dataSource === "live"
              ? `Registry ID confirmed · captured by ${h.capturedBy}`
              : "Status confirmed · design-preview content"}
          </span>
          <div style={{flex:1}}/>
          <button className="btn"><Icon name="edit" size={14}/> Open update</button>
          <button className="btn"><Icon name="message" size={14}/> Open grievance</button>
          <button className="btn btn-ghost"><Icon name="moreH" size={14}/></button>
        </div>
      </div>

      {/* Tabs */}
      <div role="tablist" style={{display:"flex", gap:0,
            borderBottom:"1px solid var(--neutral-300)",
            marginBottom:0, flexWrap:"wrap"}}>
        {HH_TABS.map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} role="tab" onClick={() => setTab(t.id)} style={{
              display:"inline-flex", alignItems:"center", gap:6,
              padding:"10px 16px", border:0,
              borderBottom: active ? "2px solid var(--primary-900)" : "2px solid transparent",
              background:"transparent", cursor:"pointer",
              color: active ? "var(--primary-900)" : "var(--neutral-700)",
              fontWeight: active ? 600 : 500, fontSize:13.5, marginBottom:-1,
            }}>{t.label}</button>
          );
        })}
      </div>

      <div className="card" style={{borderTopLeftRadius:0, borderTopRightRadius:0,
            padding:0, marginTop:0}}>
        {tab === "over"  && <TabOverview h={h}/>}
        {tab === "rost"  && <TabRoster h={h}/>}
        {tab === "hd"    && <TabHealth h={h}/>}
        {tab === "ed"    && <TabEducation h={h}/>}
        {tab === "emp"   && <TabEmployment h={h}/>}
        {tab === "hous"  && <TabHousing h={h}/>}
        {tab === "food"  && <TabFood h={h}/>}
        {tab === "hist"  && <TabHistory h={h} live={dataSource === "live"} onNavigate={onNavigate}/>}
        {tab === "grm"   && <TabGrievances h={h}/>}
        {tab === "prog"  && <TabProgrammes h={h}/>}
        {tab === "cons"  && <TabConsent h={h} live={dataSource === "live"}/>}
        {tab === "aud"   && <TabAudit h={h} live={dataSource === "live"}/>}
      </div>

      <div className="t-cap mt-4" style={{textAlign:"center"}}>
        Read-only registry view (AC-UPD-VERSION). All edits open a UPD ChangeRequest.
        Audit chain available under the Audit tab.
      </div>
    </div>
  );
};


// ────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────
const Fact = ({ label, big, sub }) => (
  <div style={{minWidth:0}}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm" style={{fontWeight:600, fontSize:15, marginTop:2,
                                       color:"var(--neutral-900)",
                                       overflowWrap:"anywhere"}}>{big}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

const TabHeader = ({ title, sub, action }) => (
  <div style={{padding:"16px 20px", borderBottom:"1px solid var(--neutral-200)",
                display:"flex", alignItems:"center", justifyContent:"space-between",
                gap:12}}>
    <div>
      <h3 className="t-h3" style={{margin:0}}>{title}</h3>
      {sub && <div className="t-cap mt-1">{sub}</div>}
    </div>
    {action}
  </div>
);

const KVCard = ({ title, rows, tint }) => (
  <div className="card" style={{boxShadow:"none",
        border:"1px solid var(--neutral-200)", padding:0,
        borderLeft: tint ? `3px solid var(--accent-${tint})` : "1px solid var(--neutral-200)"}}>
    <div style={{padding:"12px 16px", borderBottom:"1px solid var(--neutral-200)",
                  fontSize:14, fontWeight:600}}>{title}</div>
    <div style={{padding:14, display:"grid", gridTemplateColumns:"130px 1fr",
                  rowGap:8, columnGap:12, fontSize:13}}>
      {rows.map(([k, v], i) => (
        <React.Fragment key={i}>
          <div className="muted">{k}</div>
          <div>{(v === "" || v == null) ? <span className="muted">—</span> : v}</div>
        </React.Fragment>
      ))}
    </div>
  </div>
);

const Stat = ({ label, value, tint = "data" }) => (
  <div style={{minWidth:140, padding:"10px 14px",
                border:"1px solid var(--neutral-200)",
                borderLeft:`3px solid var(--accent-${tint})`,
                borderRadius:4, background:"var(--neutral-0)"}}>
    <div className="t-cap">{label}</div>
    <div style={{fontSize:20, fontWeight:700, color: `var(--accent-${tint})`,
                  letterSpacing:"-0.01em", marginTop:2}}>{value}</div>
  </div>
);

const _NoQuestionnaire = ({ section }) => (
  <div style={{padding:"24px 20px", color:"var(--neutral-500)"}}>
    <div className="t-h3">{section}</div>
    <p className="muted">
      No questionnaire payload attached to this household — likely a
      walk-in CAPI record. The {section.toLowerCase()} block ships
      when the matching collector lands.
    </p>
  </div>
);


// ────────────────────────────────────────────────────────────────
// Tab bodies
// ────────────────────────────────────────────────────────────────

const TabOverview = ({ h }) => (
  <div>
    <TabHeader title="Overview" sub="Snapshot of the most-referenced fields. Open any tab below for the full record."/>
    <div style={{padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:16}}>
      <KVCard title="Household composition" rows={[
        ["Members", h.hh],
        ["Female / male", `${h.members.filter(m => m.sex === "F").length} / ${h.members.filter(m => m.sex === "M").length}`],
        ["Children < 5",  h.members.filter(m => m.age !== "—" && m.age < 5).length],
        ["Children 5–17", h.members.filter(m => m.age !== "—" && m.age >= 5 && m.age < 18).length],
        ["Adults 18–59",  h.members.filter(m => m.age !== "—" && m.age >= 18 && m.age < 60).length],
        ["Elderly 60+",   h.members.filter(m => m.age !== "—" && m.age >= 60).length],
      ]}/>
      <KVCard title="Identification" rows={[
        ["Registry ID", <span className="t-mono">{h.rid}</span>],
        ["Head NIN",    <span className="t-mono">{h.members[0]?.nin || "—"}</span>],
        ["Phone",       <span className="t-mono">{h.phone}</span>],
        ["Source",      <Chip size="sm" tone="data">{h.source.toLowerCase()}</Chip>],
        ["Captured by", h.capturedBy],
        ["Captured at", h.capturedAt],
      ]}/>
      <KVCard title="Location" tint="data" rows={[
        ["Village",     h.village],
        ["Parish",      h.parish],
        ["District",    h.district],
        ["Sub-region",  h.subreg],
        ["GPS",         h.gps ? <span className="t-mono">{h.gps.lat.toFixed(6)}, {h.gps.lng.toFixed(6)}</span> : null],
        ["EA / HH #",   `${h.enumerationArea || "—"} · ${h.householdNumber || "—"}`],
      ]}/>
      <KVCard title="Welfare snapshot" tint="eligibility" rows={[
        ["PMT score",   h.pmt ? <span className="t-mono">{h.pmt.score.toFixed(3)}</span> : null],
        ["PMT band",    h.pmt ? <Chip size="sm" tone="eligibility">{h.pmt.band}</Chip> : null],
        ["Source",      h.source.toLowerCase()],
        ["Roof",        h.questionnaire?.housing?.roof_material || null],
        ["Water source", h.questionnaire?.housing?.water_source || null],
      ]}/>
    </div>
  </div>
);

const TabRoster = ({ h }) => (
  <div>
    <TabHeader title={`Roster — ${h.members.length} members`}
      sub="Per-individual record. Click a line to open the member detail (IDV module)."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Propose new member</button>}/>
    <table className="tbl">
      <thead><tr>
        <th style={{width:40}}>Line</th>
        <th>Name</th>
        <th>Relation</th>
        <th>Sex</th>
        <th>Age</th>
        <th>DoB</th>
        <th>NIN</th>
        <th>Phone</th>
        <th className="col-actions"></th>
      </tr></thead>
      <tbody>
        {h.members.map(m => (
          <tr key={m.line} style={{cursor:"pointer"}}>
            <td>
              <span style={{display:"inline-grid", placeItems:"center", width:24, height:24,
                            borderRadius:"50%",
                            background: m.rel === "Head" ? "var(--accent-identity-bg)" : "var(--neutral-100)",
                            color: m.rel === "Head" ? "var(--accent-identity)" : "var(--neutral-700)",
                            fontSize:11, fontWeight:600}}>{m.line}</span>
            </td>
            <td>
              <div style={{fontWeight: m.rel === "Head" ? 600 : 500}}>
                {m.name}
                {m.rel === "Head" && <span className="t-cap" style={{marginLeft:8, color:"var(--accent-identity)"}}>head</span>}
              </div>
            </td>
            <td className="t-bodysm">{m.rel}</td>
            <td><Chip size="sm">{m.sex}</Chip></td>
            <td className="t-num">{m.age}</td>
            <td className="t-cap">{m.dob}</td>
            <td className="col-id">{m.nin}</td>
            <td className="t-bodysm t-mono" style={{fontSize:12}}>{m.phone || "—"}</td>
            <td className="col-actions"><Icon name="chevronRight" size={14} color="var(--neutral-500)"/></td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const TabHealth = ({ h }) => {
  if (!h.questionnaire) return <_NoQuestionnaire section="Health & Disability"/>;
  const _disab = (c) => ({"01":"None","02":"Some","03":"A lot","04":"Cannot"}[String(c)] || "—");
  return (
    <div>
      <TabHeader title="Health & Disability"
        sub="Per-member Washington Group disability set + chronic illness."/>
      <table className="tbl">
        <thead><tr><th>Line</th><th>Name</th>
          <th>Chronic</th><th>Seeing</th><th>Hearing</th>
          <th>Walking</th><th>Remembering</th><th>Self-care</th><th>Communicating</th></tr></thead>
        <tbody>
          {h.members.map(m => (
            <tr key={m.line}>
              <td>{m.line}</td>
              <td>{m.name}</td>
              <td>{m.health ? _yesNo(m.health.chronic_illness) : <span className="muted">—</span>}</td>
              <td>{m.health ? _disab(m.health.seeing) : <span className="muted">—</span>}</td>
              <td>{m.health ? _disab(m.health.hearing) : <span className="muted">—</span>}</td>
              <td>{m.health ? _disab(m.health.walking) : <span className="muted">—</span>}</td>
              <td>{m.health ? _disab(m.health.remembering) : <span className="muted">—</span>}</td>
              <td>{m.health ? _disab(m.health.self_care) : <span className="muted">—</span>}</td>
              <td>{m.health ? _disab(m.health.communicating) : <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const TabEducation = ({ h }) => (
  <div>
    <TabHeader title="Education — per member"
      sub="Literacy, ever-school, highest grade, current attendance, and reason for never attending."
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>}/>
    <table className="tbl">
      <thead><tr>
        <th style={{width:40}}>Line</th>
        <th>Name</th>
        <th>Literacy</th>
        <th>Ever school</th>
        <th>Highest grade</th>
        <th>Currently attending</th>
        <th>Never-school reason</th>
      </tr></thead>
      <tbody>
        {h.members.map(m => (
          <tr key={m.line}>
            <td>{m.line}</td>
            <td style={{fontWeight: m.rel === "Head" ? 600 : 400}}>{m.name}</td>
            <td>
              {m.literacy === "Reads + writes"
                ? <Chip size="sm" tone="data">Reads + writes</Chip>
                : m.literacy === "Neither"
                  ? <Chip size="sm" tone="quality">Neither</Chip>
                  : <span className="muted">{m.literacy}</span>}
            </td>
            <td>
              {m.everSchool === "Yes" ? <Chip size="sm" tone="data">Yes</Chip>
                : m.everSchool === "No" ? <Chip size="sm" tone="danger">No</Chip>
                : <span className="muted">—</span>}
            </td>
            <td className="t-num">{m.highestGrade && m.highestGrade !== "—"
              ? String(m.highestGrade).padStart(2, "0")
              : <span className="muted">—</span>}</td>
            <td>{m.currentlyAttending === "Yes"
              ? <Chip size="sm" tone="data">Yes</Chip>
              : <span className="muted">{m.currentlyAttending}</span>}</td>
            <td>{m.neverReason && m.neverReason !== "—"
              ? <span className="t-mono" style={{color:"var(--neutral-700)"}}>code {m.neverReason}</span>
              : <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const TabEmployment = ({ h }) => {
  if (!h.questionnaire) return <_NoQuestionnaire section="Employment"/>;
  return (
    <div>
      <TabHeader title="Employment & livelihoods" sub="Activity and primary occupation per member."/>
      <table className="tbl">
        <thead><tr><th>Line</th><th>Name</th>
          <th>Main job</th><th>Sector</th><th>Frequency</th>
          <th>Status</th><th>Programmes</th><th>Savings</th></tr></thead>
        <tbody>
          {h.members.map(m => (
            <tr key={m.line}>
              <td>{m.line}</td>
              <td>{m.name}</td>
              <td>{m.employment?.main_job || <span className="muted">—</span>}</td>
              <td>{m.employment?.work_sector || <span className="muted">—</span>}</td>
              <td>{m.employment?.work_frequency || <span className="muted">—</span>}</td>
              <td>{m.employment?.work_status || <span className="muted">—</span>}</td>
              <td>{m.employment?.programmes || <span className="muted">—</span>}</td>
              <td>{m.employment?.made_savings ? _yesNo(m.employment.made_savings) : <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const TabHousing = ({ h }) => {
  const hg = h.questionnaire?.housing;
  if (!hg) return <_NoQuestionnaire section="Housing & Assets"/>;
  const assetCodes = (hg.assets_owned || "").split(/\s+/).filter(Boolean);
  return (
    <div>
      <TabHeader title="Housing & Assets"/>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:16}}>
        <KVCard title="Dwelling" tint="eligibility" rows={[
          ["Tenure", hg.tenure],
          ["Roof",   hg.roof_material],
          ["Walls",  hg.wall_material],
          ["Floor",  hg.floor_material],
          ["Rooms",  `${hg.rooms_total ?? "—"} (${hg.rooms_sleeping ?? "—"} sleeping)`],
          ["Lighting", hg.lighting_source],
        ]}/>
        <KVCard title="Water, sanitation & energy" tint="eligibility" rows={[
          ["Drinking water", hg.water_source],
          ["Toilet",         hg.toilet_type],
          ["Share toilet",   _yesNo(hg.share_toilet)],
          ["Share-toilet HHs", hg.share_toilet_households],
          ["Cooking fuel",   hg.cooking_fuel],
          ["Waste disposal", hg.waste_disposal],
        ]}/>
        <KVCard title="Assets owned" tint="programme" rows={[
          ["Codes recorded", assetCodes.length],
          ...["mattress", "solar", "bed", "tv", "bicycle", "phone"].map(k => [
            k.charAt(0).toUpperCase() + k.slice(1),
            hg.asset_counts?.[k] != null ? `${hg.asset_counts[k]}` : "—",
          ]),
        ]}/>
        <KVCard title="Livelihoods" tint="programme" rows={[
          ["Primary livelihood", hg.livelihood_source],
          ["Crop production", h.questionnaire.agriculture?.crop_production],
          ["Livestock", h.questionnaire.agriculture?.livestock],
          ["Livestock counts", h.questionnaire.agriculture?.livestock_counts],
          ["Crops grown", h.questionnaire.agriculture?.crops_grown],
          ["Land ownership", h.questionnaire.agriculture?.land_ownership],
        ]}/>
      </div>
    </div>
  );
};

const TabFood = ({ h }) => {
  if (!h.questionnaire?.food_security && !h.questionnaire?.shocks_coping) {
    return <_NoQuestionnaire section="Food & Shocks"/>;
  }
  const fs = h.questionnaire.food_security || {};
  const sc = h.questionnaire.shocks_coping || {};
  const fiesKeys = Object.keys(fs.fies || {});
  const fiesYes = fiesKeys.filter(k => String(fs.fies[k]) === "1").length;
  const fiesPct = fiesKeys.length ? Math.round((fiesYes / fiesKeys.length) * 100) : 0;
  const groups = fs.food_groups || {};
  return (
    <div>
      <TabHeader title="Food security & Shocks"
        sub="Last 12 months · FIES + 7-day food consumption + shock module"/>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:16}}>
        <div className="card" style={{padding:16, boxShadow:"none",
                                       border:"1px solid var(--neutral-200)"}}>
          <h4 className="t-h3" style={{margin:"0 0 12px"}}>Food Insecurity Experience Scale (FIES)</h4>
          <div className="t-cap mb-2">Score {fiesYes} of {fiesKeys.length} · {fiesPct}%</div>
          <div style={{height:8, background:"var(--neutral-100)", borderRadius:4,
                        overflow:"hidden", marginBottom:14}}>
            <div style={{width:`${fiesPct}%`, height:"100%",
                          background: fiesPct > 60 ? "var(--accent-danger)"
                                    : fiesPct > 30 ? "var(--accent-quality)"
                                    : "var(--accent-eligibility)"}}/>
          </div>
          {fiesKeys.map(k => {
            const yes = String(fs.fies[k]) === "1";
            return (
              <div key={k} className="row gap-3"
                style={{padding:"6px 0", borderBottom:"1px dashed var(--neutral-200)"}}>
                <Icon name={yes ? "checkCircle" : "xCircle"} size={14}
                  color={yes ? "var(--accent-quality)" : "var(--neutral-300)"}/>
                <span className="t-bodysm" style={{flex:1}}>{k.replace(/_fies$/, "").toUpperCase()}</span>
                <span className="t-bodysm" style={{color: yes ? "var(--accent-quality)" : "var(--neutral-500)"}}>
                  {yes ? "Yes" : "No"}
                </span>
              </div>
            );
          })}
        </div>
        <div className="card" style={{padding:16, boxShadow:"none",
                                       border:"1px solid var(--neutral-200)"}}>
          <h4 className="t-h3" style={{margin:"0 0 12px"}}>7-day food consumption</h4>
          <table className="tbl" style={{boxShadow:"none"}}>
            <thead><tr><th>Group</th><th>Days</th><th>Primary source</th></tr></thead>
            <tbody>
              {Object.entries(groups).map(([label, g]) => (
                <tr key={label}>
                  <td style={{textTransform:"capitalize"}}>{label.replace(/_/g, " ")}</td>
                  <td className="t-num">{g.days != null ? g.days : "—"}</td>
                  <td className="t-bodysm">{g.source_primary || <span className="muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="tint-quality mt-3" style={{padding:12, borderRadius:4,
                                                      borderLeft:"3px solid var(--accent-quality)"}}>
            <div className="row gap-2" style={{marginBottom:4}}>
              <Icon name="alert" size={14} color="var(--accent-quality)"/>
              <strong className="t-bodysm">Shocks & coping</strong>
            </div>
            <div className="t-bodysm muted">
              Shock affected: <strong>{_yesNo(sc.shock_affected)}</strong> ·
              {" "}{Object.keys(sc.coping || {}).length} coping strategies recorded.
              See `_source_keys` in the StageRecord for the per-strategy detail.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const TabHistory = ({ h, live, onNavigate }) => {
  const [crs, setCrs] = useStateHH(null);
  const [err, setErr] = useStateHH(null);
  useEffectHH(() => {
    if (!live || !h.rid) return undefined;
    let cancelled = false;
    fetch(`/api/v1/upd/change-requests/?entity_id=${encodeURIComponent(h.rid)}&page_size=100`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => { if (!cancelled) setCrs((data.results || data).slice()); })
      .catch(e => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [live, h.rid]);

  return (
    <div>
      <TabHeader title="Updates history"
        sub="All ChangeRequests since registration. Each event opens the original UPD diff."
        action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>}/>
      {err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Couldn't load: {err}</div>}
      {live && !crs && !err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Loading…</div>}
      {live && crs?.length === 0 && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>
          No change requests recorded against this household.
        </div>
      )}
      {(live ? crs && crs.length > 0 : true) && (
        <table className="tbl">
          <thead><tr>
            <th>UPD ID</th><th>Change type</th><th>Submitted by</th>
            <th>Reviewer</th><th>Submitted</th><th>Decided</th>
            <th>PMT impact</th><th>Status</th>
          </tr></thead>
          <tbody>
            {(live ? crs : [
              { id: "UPD-2026-04-22-00188", change_type: "Roster: edit member age",
                requester: "Mukasa R.", approver: "Adong F.",
                created_at: "2026-04-20T00:00:00", decided_at: "2026-04-22T00:00:00",
                pmt_relevant: false, status: "approved" },
              { id: "UPD-2026-04-04-00112", change_type: "Housing: roof material",
                requester: "Mukasa R.", approver: "Adong F.",
                created_at: "2026-04-01T00:00:00", decided_at: "2026-04-04T00:00:00",
                pmt_relevant: true, status: "approved" },
            ]).map(cr => (
              <tr key={cr.id} style={{cursor:"pointer"}}
                onClick={() => onNavigate?.("upd", { changeRequestId: cr.id })}>
                <td className="col-id">{cr.id}</td>
                <td>{cr.change_type}</td>
                <td className="t-bodysm">{cr.requester || <span className="muted">—</span>}</td>
                <td className="t-bodysm">{cr.approver || <span className="muted">—</span>}</td>
                <td className="t-cap">{(cr.created_at || "").slice(0, 10)}</td>
                <td className="t-cap">{(cr.decided_at || "").slice(0, 10) || "—"}</td>
                <td>{cr.pmt_relevant
                  ? <Chip size="sm" tone="eligibility">pmt_relevant</Chip>
                  : <span className="muted">—</span>}</td>
                <td><Chip size="sm">{cr.status}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

const TabGrievances = ({ h }) => (
  <div>
    <TabHeader title="Grievances"
      sub="GRM cases filed against or referencing this household. Live API wiring deferred — design-preview content shown."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> File grievance</button>}/>
    <div style={{padding:20}}>
      <p className="muted t-bodysm">
        Live wiring to <code>/api/v1/grm/grievances/?household_id={h.rid}</code> ships
        when the GRM cross-link query lands. Inspect the live chain in the
        Audit tab today, or use <a href="/admin/grievance/grievance/" target="_blank" rel="noreferrer">Django admin</a>.
      </p>
    </div>
  </div>
);

const TabProgrammes = ({ h }) => (
  <div>
    <TabHeader title="Programmes"
      sub="Active enrolments, exits, and payment events from partner programmes. Live wiring deferred."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Add referral</button>}/>
    <div style={{padding:20}}>
      <p className="muted t-bodysm">
        Live wiring to <code>/api/v1/ref/programme-referrals/?household_id={h.rid}</code>
        ships when the REF module exposes the per-household enrolment endpoint.
      </p>
    </div>
  </div>
);

const TabConsent = ({ h, live }) => {
  const consent = h.questionnaire?.interview?.consent;
  const respondent = h.questionnaire?.interview?.respondent_name;
  return (
    <div>
      <TabHeader title="Consent"
        sub="Data Protection and Privacy Act 2019 (Uganda). Evidence captured at the interview."/>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"1.4fr 1fr", gap:16}}>
        <div className="tint-update" style={{padding:18, borderRadius:6,
              borderLeft:"3px solid var(--accent-update)"}}>
          <div className="row gap-2" style={{marginBottom:8}}>
            <Icon name="shield" size={14} color="var(--accent-update)"/>
            <strong>Consent statement (read to the respondent)</strong>
          </div>
          <p style={{margin:0, fontSize:13.5, lineHeight:1.7}}>
            "I, the respondent, consent to the collection and processing of my
            household's data by the Ministry of Gender, Labour and Social
            Development (MGLSD) under the Data Protection and Privacy Act 2019
            of Uganda. I understand my data may be shared with partner agencies
            under a signed Data Sharing Agreement. I understand I may request
            access, correction, or erasure at any time through the parish office."
          </p>
        </div>
        <KVCard title="Evidence" rows={[
          ["Consent given", live && consent
            ? <Chip size="sm" tone="data"><Icon name="check" size={11}/> {_yesNo(consent)}</Chip>
            : (live ? <span className="muted">not recorded</span> : <Chip size="sm" tone="data">Yes</Chip>)],
          ["Respondent", respondent || (live ? <span className="muted">—</span> : "Sample respondent")],
          ["Captured at", h.capturedAt],
          ["Operator witness", h.capturedBy],
          ["Method", live ? "Kobo digital capture" : "Verbal + thumbprint"],
          ["Erasure requests", <span className="muted">None</span>],
        ]}/>
      </div>
    </div>
  );
};

const TabAudit = ({ h, live }) => {
  const [events, setEvents] = useStateHH(null);
  const [err, setErr] = useStateHH(null);
  useEffectHH(() => {
    if (!live || !h.rid) return undefined;
    let cancelled = false;
    fetch(`/api/v1/security/audit-events/?entity_id=${encodeURIComponent(h.rid)}&page_size=200`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => { if (!cancelled) setEvents((data.results || data).slice()); })
      .catch(e => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [live, h.rid]);

  // Mock fallback (design preview)
  const mockRows = [
    { actor_id:"akello.p",  actor_kind:"user",   action:"viewed household detail",
      entity_type:"household", entity_id:h.rid, reason:"Read · Overview tab",
      occurred_at:"2026-05-16T09:14:00", self_hash:"a1b2c3d4e5f6" },
    { actor_id:"system",    actor_kind:"system", action:"promote",
      entity_type:"stage_record", entity_id:"01HXP2K...", reason:"DIH pipeline",
      occurred_at:"2026-03-08T08:50:00", self_hash:"9b21f3a045b8" },
  ];
  const rows = live ? (events || []) : mockRows;

  return (
    <div>
      <TabHeader title="Audit chain"
        sub="Tamper-evident event chain · permanent · DPO-accessible."
        action={<>
          <button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>
        </>}/>
      {err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Couldn't load: {err}</div>}
      {live && !events && !err && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Loading…</div>
      )}
      {live && events?.length === 0 && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>
          No audit events recorded for this household yet.
        </div>
      )}
      {rows.length > 0 && rows.map((e, i) => {
        const initials = (e.actor_id || "?").split(/[\s._-]+/).map(s => s[0]).slice(0, 2).join("").toUpperCase();
        const isSystem = e.actor_kind === "system";
        return (
          <div key={e.id || i} className="audit-row" style={{padding:"14px 20px"}}>
            <div className="audit-avatar" style={{
              background: isSystem ? "var(--neutral-200)" : "var(--primary-100)",
              color: isSystem ? "var(--neutral-700)" : "var(--primary-900)"}}>{initials}</div>
            <div>
              <div><strong>{e.actor_id || "—"}</strong>
                <span className="t-cap"> · {e.actor_kind}</span></div>
              <div className="audit-action mt-1" style={{fontWeight:400, color:"var(--neutral-700)"}}>
                {e.action}
              </div>
              <div className="audit-detail">
                {e.entity_type}:<span className="t-mono">{(e.entity_id || "").slice(0, 12)}…</span>
                {e.reason ? ` — ${e.reason}` : ""}
              </div>
              <div className="t-cap mt-1">
                Self hash <span className="t-mono">
                  {e.self_hash ? `${e.self_hash.slice(0, 10)}…${e.self_hash.slice(-4)}` : "—"}
                </span>
              </div>
            </div>
            <div className="audit-time">{(e.occurred_at || "").slice(0, 19).replace("T", " ") || "—"}</div>
          </div>
        );
      })}
    </div>
  );
};


// Public export wrapped in the error boundary
const HouseholdScreenWithBoundary = (props) => (
  <HouseholdErrorBoundary>
    <_HouseholdScreenInner {...props}/>
  </HouseholdErrorBoundary>
);
Object.assign(window, { HouseholdScreen: HouseholdScreenWithBoundary });
