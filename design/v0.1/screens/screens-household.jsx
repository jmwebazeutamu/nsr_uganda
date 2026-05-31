/* global React, Icon, Chip, KPI, PageHeader, Modal, Toast */
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
//
// US-S22-005f wiring: every coded field reads from the API's
// resolved label (e.g. `m.sex_label`, `payloadLabels.housing.tenure`)
// rather than from a hardcoded code-to-string map in this file.
// Raw codes remain available on the view-model for the Audit tab
// and for diagnostic display.
const _hhApiToView = (h) => {
  const members = (h.members || []).slice().sort(
    (a, b) => (a.line_number || 0) - (b.line_number || 0),
  );
  const head = members.find(m => m.id === h.head_member) || members[0] || {};
  const headName = [head.surname, head.first_name].filter(Boolean).join(" ")
                   || "(no head)";
  const payload = h.source_payload || null;
  const payloadLabels = h.source_payload_labels || {};
  const qMembersByLine = {};
  if (payload?.members) {
    for (const qm of payload.members) {
      qMembersByLine[qm.line_number] = qm;
    }
  }
  const labelMembersByLine = {};
  if (Array.isArray(payloadLabels?.members)) {
    payloadLabels.members.forEach((lm, idx) => {
      const lineNo = payload?.members?.[idx]?.line_number ?? (idx + 1);
      labelMembersByLine[lineNo] = lm || {};
    });
  }

  return {
    rid: h.id,
    head: headName,
    status: "Registered",
    hh: members.length,
    // Use head's resolved sex_label so the chip shows "Male" / "Female",
    // not "M" / "F".
    sex: head.sex_label || head.sex || "—",
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
      const lm = labelMembersByLine[m.line_number] || {};
      return {
        id: m.id,
        line: m.line_number,
        name: [m.surname, m.first_name].filter(Boolean).join(" ") || "—",
        rel: (m.id === h.head_member) ? "Head" : (m.relationship_to_head_label || m.relationship_to_head || "—"),
        relationship_to_head: m.relationship_to_head || "",
        sex: m.sex_label || m.sex || "—",
        sexRaw: m.sex || "",
        age: m.age_years ?? "—",
        nin: m.nin_last4 ? `…${m.nin_last4}` : "—",
        dob: m.date_of_birth || "—",
        phone: m.telephone_1 || "",
        // Questionnaire blocks (per-member) — labels resolve against
        // the same ChoiceList catalogue the API used.
        literacy:           lm.education?.literacy           ?? qm.education?.literacy           ?? "—",
        everSchool:         lm.education?.ever_school        ?? qm.education?.ever_school        ?? "—",
        highestGrade:       qm.education?.highest_grade || "—",
        currentlyAttending: lm.education?.currently_attending ?? qm.education?.currently_attending ?? "—",
        neverReason:        lm.education?.never_school_reason ?? qm.education?.never_school_reason ?? "—",
        health: m.health || qm.health || null,
        healthLabels: lm.health || null,
        disability: m.disability || qm.disability || null,
        education: m.education || qm.education || null,
        educationLabels: lm.education || null,
        employment: m.employment || qm.employment || null,
        employmentLabels: lm.employment || null,
      };
    }),
    questionnaire: payload,
    questionnaireLabels: payloadLabels,
    householdRecord: h,
    dwelling: h.dwelling || null,
    utilities: h.utilities || null,
    livelihood: h.livelihood || null,
    food_security: h.food_security || null,
    food_consumption: h.food_consumption || null,
    sourcePayload: payload,
  };
};


// CSRF cookie reader for DRF session-auth POSTs (same pattern as
// screens-grm + screens-upd).
const _hhCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

// US-S22-002 — Grievance form vocabularies. The Open Update flow
// lives in the full-page change-request screen
// (design/v0.1/screens/change-request/), which carries its own
// field catalog + change-type vocabulary + routing matrix.
const _GRM_CATEGORIES = [
  { value: "data_correction",  label: "Data correction" },
  { value: "exclusion_error",  label: "Wrongly excluded" },
  { value: "inclusion_error",  label: "Wrongly included" },
  { value: "programme_issue",  label: "Programme issue" },
  { value: "operator_conduct", label: "Operator conduct" },
  { value: "other",            label: "Other" },
];

const _GRM_TIERS = [
  { value: "l1_parish_chief", label: "L1 — Parish Chief" },
  { value: "l2_cdo",          label: "L2 — CDO" },
  { value: "l3_district",     label: "L3 — District" },
  { value: "l4_nsr_unit",     label: "L4 — NSR Unit" },
];


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
  { id: "dqa",   label: "DQA" },
  { id: "aud",   label: "Audit" },
];


const _HouseholdScreenInner = ({ householdId, onNavigate }) => {
  const [tab, setTab] = useStateHH("over");
  const [liveHh, setLiveHh] = useStateHH(null);
  const [loadError, setLoadError] = useStateHH(null);
  const [dataSource, setDataSource] = useStateHH(householdId ? "loading" : "mock");

  // US-S22-002 — Open Grievance wiring state. (Open Update is no
  // longer modal — it navigates to the full-page change-request
  // screen, which owns its own actor/requester binding.)
  // `modal` is the open dialog ("grm" | null). `lastCreated` powers
  // the post-submit toast that offers a one-click jump to GRM.
  const [modal, setModal] = useStateHH(null);
  const [toast, setToast] = useStateHH("");
  const [busy, setBusy] = useStateHH(false);
  const [lastCreated, setLastCreated] = useStateHH(null);
  const [grmForm, setGrmForm] = useStateHH({
    category: "data_correction",
    tier: "l1_parish_chief",
    description: "",
    member_id: "",
    reporter_name: "",
    reporter_phone: "",
    reporter_relationship: "",
  });
  const [formErr, setFormErr] = useStateHH("");

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

  // Open the full-page Open-CR submitter (US-S22-004). Replaces the
  // legacy ChangeRequestModal — see design/v0.1/screens/change-request/.
  // The new screen handles its own POST + success toast; we project
  // the household's live roster into the navigate payload so
  // member-scope CRs can submit with a real Member ULID instead of
  // the synthesized M-…-NNN fallback the server rejects.
  const openUpdate = () => {
    if (!h || !onNavigate) return;
    const roster = Array.isArray(h.members) ? h.members.map(m => ({
      id: m.id,
      line: m.line,
      name: m.name,
      rel: m.rel,
      sex: m.sex,
      age: m.age,
      dob: m.dob === "—" ? "" : m.dob,
      nin: m.nin === "—" ? "" : m.nin,
      // ninStatus drives the row's "verified / not on file" chip in
      // the bundle. The view-model only carries a masked last-4 so
      // treat any value as "verified" and absence as not on file.
      ninStatus: m.nin && m.nin !== "—" ? "verified" : "not-issued",
    })) : null;
    onNavigate("change-request", {
      householdId: h.rid,
      initialScope: "household",
      roster,
    });
  };

  const openGrievance = () => {
    if (!h) return;
    setGrmForm({
      category: "data_correction",
      tier: "l1_parish_chief",
      description: "",
      member_id: "",
      reporter_name: h.head || "",
      reporter_phone: h.phone && h.phone !== "—" ? h.phone : "",
      reporter_relationship: "Self · head",
    });
    setFormErr("");
    setModal("grm");
  };

  const submitOpenGrievance = () => {
    if (!h) return;
    if (!grmForm.description) {
      setFormErr("Description is required.");
      return;
    }
    setBusy(true);
    setFormErr("");
    fetch("/api/v1/grm/grievances/", {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _hhCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({
        category: grmForm.category,
        tier: grmForm.tier,
        description: grmForm.description,
        household_id: h.rid,
        member_id: grmForm.member_id || "",
        reporter_name: grmForm.reporter_name,
        reporter_phone: grmForm.reporter_phone,
        reporter_relationship: grmForm.reporter_relationship,
      }),
    })
      .then(async r => {
        if (r.status === 201) return r.json();
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || JSON.stringify(j) || `HTTP ${r.status}`);
      })
      .then(grievance => {
        setLastCreated({ kind: "grm", id: grievance.id });
        setToast(`Grievance ${grievance.id.slice(0, 12)}… opened.`);
        setModal(null);
      })
      .catch(e => setFormErr(String(e.message || e)))
      .finally(() => setBusy(false));
  };

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
            sub={`HH size ${h.hh} · ${h.members.filter(m => m.sex === "Female").length}F / ${h.members.filter(m => m.sex === "Male").length}M`}/>
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
          <button className="btn"
            disabled={dataSource !== "live"}
            title={dataSource !== "live" ? "Live data required — log in via /admin/" : ""}
            onClick={openUpdate}>
            <Icon name="edit" size={14}/> Open update
          </button>
          <button className="btn"
            disabled={dataSource !== "live"}
            title={dataSource !== "live" ? "Live data required — log in via /admin/" : ""}
            onClick={openGrievance}>
            <Icon name="message" size={14}/> Open grievance
          </button>
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
        {tab === "grm"   && <TabGrievances h={h} live={dataSource === "live"}/>}
        {tab === "prog"  && <TabProgrammes h={h} live={dataSource === "live"}/>}
        {tab === "cons"  && <TabConsent h={h} live={dataSource === "live"}/>}
        {tab === "dqa"   && <TabDqa h={h} live={dataSource === "live"} onNavigate={onNavigate}/>}
        {tab === "aud"   && <TabAudit h={h} live={dataSource === "live"}/>}
      </div>

      <div className="t-cap mt-4" style={{textAlign:"center"}}>
        Read-only registry view (AC-UPD-VERSION). All edits open a UPD ChangeRequest.
        Audit chain available under the Audit tab.
      </div>

      {/* US-S22-002 — Open Grievance modal */}
      <Modal open={modal === "grm"} onClose={() => !busy && setModal(null)}
        title="Open a grievance"
        width={560}
        footer={
          <>
            <button className="btn" disabled={busy} onClick={() => setModal(null)}>Cancel</button>
            <button className="btn btn-success" disabled={busy} onClick={submitOpenGrievance}>
              {busy ? "Opening…" : "Open grievance"}
            </button>
          </>
        }>
        <div className="col gap-3">
          <div className="t-bodysm muted">
            Creates a grievance pinned to this household. SLA and tier
            routing are stamped server-side from the SAD §4.5 matrix.
          </div>

          <div className="row gap-3">
            <label style={{flex:1}}>
              <div className="t-cap">Category</div>
              <select value={grmForm.category}
                onChange={(e) => setGrmForm({...grmForm, category: e.target.value})}>
                {_GRM_CATEGORIES.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <label style={{flex:1}}>
              <div className="t-cap">Tier</div>
              <select value={grmForm.tier}
                onChange={(e) => setGrmForm({...grmForm, tier: e.target.value})}>
                {_GRM_TIERS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
          </div>

          <label>
            <div className="t-cap">Member (optional)</div>
            <select value={grmForm.member_id}
              onChange={(e) => setGrmForm({...grmForm, member_id: e.target.value})}>
              <option value="">— Household-level grievance —</option>
              {(h?.members || []).map(m => (
                <option key={m.id} value={m.id}>
                  Line {m.line} · {m.name}{m.rel === "Head" ? " (head)" : ""}
                </option>
              ))}
            </select>
          </label>

          <label>
            <div className="t-cap">Description *</div>
            <textarea rows={3} value={grmForm.description}
              onChange={(e) => setGrmForm({...grmForm, description: e.target.value})}
              placeholder="Describe the complaint in the operator's own words."/>
          </label>

          <div className="row gap-3">
            <label style={{flex:1}}>
              <div className="t-cap">Reporter name</div>
              <input type="text" value={grmForm.reporter_name}
                onChange={(e) => setGrmForm({...grmForm, reporter_name: e.target.value})}
                placeholder="Who is reporting"/>
            </label>
            <label style={{flex:1}}>
              <div className="t-cap">Reporter phone</div>
              <input type="text" value={grmForm.reporter_phone}
                onChange={(e) => setGrmForm({...grmForm, reporter_phone: e.target.value})}
                placeholder="+256…"/>
            </label>
          </div>

          <label>
            <div className="t-cap">Relationship</div>
            <input type="text" value={grmForm.reporter_relationship}
              onChange={(e) => setGrmForm({...grmForm, reporter_relationship: e.target.value})}
              placeholder="e.g., Self · head; Daughter; Neighbour"/>
          </label>

          {formErr && (
            <div className="t-bodysm" style={{color:"var(--accent-danger)",
              padding:"8px 10px", background:"var(--neutral-50)",
              border:"1px solid var(--accent-danger)", borderRadius:6}}>
              {formErr}
            </div>
          )}
        </div>
      </Modal>

      {/* Post-submit toast with one-click jump to the new grievance. */}
      {toast && (
        <div style={{position:"fixed", bottom:24, right:24, zIndex:50,
          padding:"12px 16px", background:"var(--primary-900)", color:"white",
          borderRadius:8, boxShadow:"0 4px 14px rgba(0,0,0,0.15)",
          display:"flex", alignItems:"center", gap:12, maxWidth:520}}>
          <span className="t-bodysm">{toast}</span>
          {lastCreated && onNavigate && (
            <button className="btn btn-sm"
              style={{background:"white", color:"var(--primary-900)"}}
              onClick={() => {
                onNavigate("grm");
                setToast("");
                setLastCreated(null);
              }}>
              Open in GRM
            </button>
          )}
          <button className="icon-btn" style={{color:"white"}}
            onClick={() => { setToast(""); setLastCreated(null); }}
            aria-label="Dismiss">
            <Icon name="x" size={14}/>
          </button>
        </div>
      )}
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
        ["Female / male", `${h.members.filter(m => m.sex === "Female").length} / ${h.members.filter(m => m.sex === "Male").length}`],
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
        ["Roof",        h.questionnaireLabels?.housing?.roof_material || h.questionnaire?.housing?.roof_material || null],
        ["Water source", h.questionnaireLabels?.housing?.water_source  || h.questionnaire?.housing?.water_source  || null],
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
  // Labels resolve against the seeded severity list — 01=None, 02=Some,
  // 03=A lot, 04=Cannot. Chronic illness is yes_no. ADR-0010 §6.
  const _cell = (mh, mhL, key) => {
    if (!mh) return <span className="muted">—</span>;
    const label = mhL?.[key];
    if (label) return label;
    return mh[key] || <span className="muted">—</span>;
  };
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
              <td>{_cell(m.health, m.healthLabels, "chronic_illness")}</td>
              <td>{_cell(m.health, m.healthLabels, "seeing")}</td>
              <td>{_cell(m.health, m.healthLabels, "hearing")}</td>
              <td>{_cell(m.health, m.healthLabels, "walking")}</td>
              <td>{_cell(m.health, m.healthLabels, "remembering")}</td>
              <td>{_cell(m.health, m.healthLabels, "self_care")}</td>
              <td>{_cell(m.health, m.healthLabels, "communicating")}</td>
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
              ? <span style={{color:"var(--neutral-700)"}}>{m.neverReason}</span>
              : <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const TabEmployment = ({ h }) => {
  if (!h.questionnaire) return <_NoQuestionnaire section="Employment"/>;
  const _emp = (m, key) => (m.employmentLabels?.[key]) || (m.employment?.[key]) || <span className="muted">—</span>;
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
              <td>{_emp(m, "main_job")}</td>
              <td>{_emp(m, "work_sector")}</td>
              <td>{_emp(m, "work_frequency")}</td>
              <td>{_emp(m, "work_status")}</td>
              <td>{m.employment?.programmes || <span className="muted">—</span>}</td>
              <td>{_emp(m, "made_savings")}</td>
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
  // ADR-0010 §6: every coded field reads its resolved label from
  // h.questionnaireLabels — never from a hardcoded code-to-string
  // map in this component. Raw codes remain in `hg` for the Audit
  // tab (rendered separately in TabAudit).
  const hgL = h.questionnaireLabels?.housing || {};
  const agL = h.questionnaireLabels?.agriculture || {};
  const ag = h.questionnaire?.agriculture || {};
  const assetCodes = (hg.assets_owned || "").split(/\s+/).filter(Boolean);
  const assetLabels = Array.isArray(hgL.assets_owned) ? hgL.assets_owned : null;
  return (
    <div>
      <TabHeader title="Housing & Assets"/>
      <div style={{padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:16}}>
        <KVCard title="Dwelling" tint="eligibility" rows={[
          ["Tenure",   hgL.tenure          || hg.tenure          || "—"],
          ["Roof",     hgL.roof_material   || hg.roof_material   || "—"],
          ["Walls",    hgL.wall_material   || hg.wall_material   || "—"],
          ["Floor",    hgL.floor_material  || hg.floor_material  || "—"],
          ["Rooms",    `${hg.rooms_total ?? "—"} (${hg.rooms_sleeping ?? "—"} sleeping)`],
          ["Lighting", hgL.lighting_source || hg.lighting_source || "—"],
        ]}/>
        <KVCard title="Water, sanitation & energy" tint="eligibility" rows={[
          ["Drinking water",   hgL.water_source   || hg.water_source   || "—"],
          ["Toilet",           hgL.toilet_type    || hg.toilet_type    || "—"],
          ["Share toilet",     hgL.share_toilet   || hg.share_toilet   || "—"],
          ["Share-toilet HHs", hg.share_toilet_households],
          ["Cooking fuel",     hgL.cooking_fuel   || hg.cooking_fuel   || "—"],
          ["Waste disposal",   hgL.waste_disposal || hg.waste_disposal || "—"],
        ]}/>
        <KVCard title="Assets owned" tint="programme" rows={[
          ["Codes recorded", assetCodes.length],
          ["Items",          assetLabels ? assetLabels.join(", ") : (assetCodes.join(" ") || "—")],
          ...["mattress", "solar", "bed", "tv", "bicycle", "phone"].map(k => [
            k.charAt(0).toUpperCase() + k.slice(1),
            hg.asset_counts?.[k] != null ? `${hg.asset_counts[k]}` : "—",
          ]),
        ]}/>
        <KVCard title="Livelihoods" tint="programme" rows={[
          ["Primary livelihood", hgL.livelihood_source || hg.livelihood_source || "—"],
          ["Crop production",    agL.crop_production   || ag.crop_production   || "—"],
          ["Livestock",          agL.livestock         || ag.livestock         || "—"],
          ["Livestock counts", ag.livestock_counts ?? "—"],
          ["Crops grown",      ag.crops_grown      ?? "—"],
          ["Land ownership",   agL.land_ownership || ag.land_ownership || "—"],
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
              Shock affected: <strong>{h.questionnaireLabels?.shocks_coping?.shock_affected || sc.shock_affected || "—"}</strong> ·
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

// US-S14-003: Grievances tab live wiring. Fetches
// /api/v1/grm/grievances/?household_id={h.rid}; falls back to a
// "no grievances" empty state. household_id was added to the
// GrievanceViewSet's filterset_fields as part of this same ticket.
const TabGrievances = ({ h, live }) => {
  const [rows, setRows] = useStateHH(null);
  const [err, setErr] = useStateHH(null);
  useEffectHH(() => {
    if (!live || !h.rid) return undefined;
    let cancelled = false;
    fetch(`/api/v1/grm/grievances/?household_id=${encodeURIComponent(h.rid)}&page_size=100`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => { if (!cancelled) setRows((data.results || data).slice()); })
      .catch(e => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [live, h.rid]);

  return (
    <div>
      <TabHeader title="Grievances"
        sub={live
          ? "GRM cases filed against or referencing this household."
          : "GRM cases filed against or referencing this household. Mock preview — log into /admin/ first."}
        action={<button className="btn btn-sm"><Icon name="plus" size={13}/> File grievance</button>}/>
      {err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Couldn't load: {err}</div>}
      {live && !rows && !err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Loading…</div>}
      {live && rows?.length === 0 && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>
          No grievances recorded against this household.
        </div>
      )}
      {(live ? rows && rows.length > 0 : true) && (
        <table className="tbl">
          <thead><tr>
            <th>GRM ID</th><th>Category</th><th>Description</th>
            <th>Reporter</th><th>Tier</th><th>Opened</th>
            <th>SLA</th><th>Status</th>
          </tr></thead>
          <tbody>
            {(live ? rows : [
              { id: "GRM-2026-04-02-00088", category: "Roster: missing member",
                sub_category: "—",
                description: "Daughter Mary was not enrolled in the roster.",
                reporter_name: "Sarah Nakato", tier: "l1_parish_chief",
                opened_at: "2026-04-02T09:00:00",
                sla_deadline: "2026-04-07T09:00:00", status: "closed" },
            ]).map(g => (
              <tr key={g.id}>
                <td className="col-id">{g.id}</td>
                <td>{g.category}</td>
                <td className="t-bodysm" style={{maxWidth:240, overflow:"hidden",
                                                 textOverflow:"ellipsis", whiteSpace:"nowrap"}}>
                  {g.description}
                </td>
                <td className="t-bodysm">{g.reporter_name || <span className="muted">—</span>}</td>
                <td><Chip size="sm">{(g.tier || "").replace(/^l(\d)_/, "L$1 · ").replace(/_/g, " ")}</Chip></td>
                <td className="t-cap">{(g.opened_at || "").slice(0, 10)}</td>
                <td className="t-cap">{(g.sla_deadline || "").slice(0, 10) || "—"}</td>
                <td><Chip size="sm" tone={g.status === "closed" ? "data"
                                          : g.status === "open" ? "update" : undefined}>
                  {g.status}
                </Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

// US-S14-003: Programmes tab live wiring. Fans out to two
// endpoints — enrolments (the source of truth) + referrals (the
// pipeline view) — and stitches both into one table. The `household`
// filter was added to both viewsets' filterset_fields as part of
// this same ticket.
const TabProgrammes = ({ h, live }) => {
  const [enrolments, setEnrolments] = useStateHH(null);
  const [referrals, setReferrals] = useStateHH(null);
  const [err, setErr] = useStateHH(null);
  useEffectHH(() => {
    if (!live || !h.rid) return undefined;
    let cancelled = false;
    const opts = { credentials: "same-origin", headers: { Accept: "application/json" } };
    Promise.all([
      fetch(`/api/v1/ref/enrolments/?household=${encodeURIComponent(h.rid)}&page_size=100`, opts)
        .then(r => r.ok ? r.json() : Promise.reject(`enrolments HTTP ${r.status}`)),
      fetch(`/api/v1/ref/referrals/?household=${encodeURIComponent(h.rid)}&page_size=100`, opts)
        .then(r => r.ok ? r.json() : Promise.reject(`referrals HTTP ${r.status}`)),
    ])
      .then(([e, r]) => {
        if (cancelled) return;
        setEnrolments((e.results || e).slice());
        setReferrals((r.results || r).slice());
      })
      .catch(e => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [live, h.rid]);

  const total = (enrolments?.length || 0) + (referrals?.length || 0);

  return (
    <div>
      <TabHeader title="Programmes"
        sub={live
          ? "Active enrolments and outstanding referrals under partner programmes (PDM, NUSAF, etc.)."
          : "Active enrolments and exits from partner programmes. Mock preview — log into /admin/ first."}
        action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Add referral</button>}/>
      {err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Couldn't load: {err}</div>}
      {live && (!enrolments || !referrals) && !err && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Loading…</div>
      )}
      {live && total === 0 && !err && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>
          No programme enrolments or referrals on file for this household.
        </div>
      )}
      {(live ? total > 0 : true) && (
        <table className="tbl">
          <thead><tr>
            <th>Programme</th><th>Type</th><th>Status</th><th>Effective</th>
            <th>Referral / Enrolment ID</th>
          </tr></thead>
          <tbody>
            {live ? <>
              {(enrolments || []).map(e => (
                <tr key={`e-${e.id}`}>
                  <td>
                    <div style={{fontWeight:600}}>{e.programme_code || e.programme}</div>
                    {e.programme_name && <div className="t-bodysm muted">{e.programme_name}</div>}
                  </td>
                  <td><Chip size="sm" tone="data">Enrolment</Chip></td>
                  <td><Chip size="sm" tone={e.status === "active" ? "data"
                                            : e.status === "exited" ? "neutral" : undefined}>
                    {e.status}
                  </Chip></td>
                  <td className="t-cap">{(e.effective_date || "").slice(0, 10) || "—"}</td>
                  <td className="col-id">{e.id}</td>
                </tr>
              ))}
              {(referrals || []).map(r => (
                <tr key={`r-${r.id}`}>
                  <td>
                    <div style={{fontWeight:600}}>{r.programme_code || r.programme}</div>
                    {r.programme_name && <div className="t-bodysm muted">{r.programme_name}</div>}
                  </td>
                  <td><Chip size="sm" tone="update">Referral</Chip></td>
                  <td><Chip size="sm" tone={r.status === "accepted" ? "data"
                                            : r.status === "rejected" ? "danger" : "update"}>
                    {r.status}
                  </Chip></td>
                  <td className="t-cap">{(r.sent_at || "").slice(0, 10) || "—"}</td>
                  <td className="col-id">{r.id}</td>
                </tr>
              ))}
            </> : (
              <tr>
                <td>
                  <div style={{fontWeight:600}}>OPM-PDM-2026</div>
                  <div className="t-bodysm muted">Parish Development Model</div>
                </td>
                <td><Chip size="sm" tone="data">Enrolment</Chip></td>
                <td><Chip size="sm" tone="data">active</Chip></td>
                <td className="t-cap">2026-04-01</td>
                <td className="col-id">ENR-2026-04-01-00018</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
};

const TabConsent = ({ h, live }) => {
  const consent = h.questionnaire?.interview?.consent;
  const respondent = h.questionnaire?.interview?.respondent_name;
  const [showManage, setShowManage] = useStateHH(false);
  // The view-model exposes the roster (with member ULIDs + resolved "Head"
  // relationship), not a head_member id — derive the head's ULID from it.
  const headMember = (h.members || []).find(m => m.rel === "Head") || (h.members || [])[0];
  const headId = headMember && headMember.id;
  const hasCluster = typeof window !== "undefined" && typeof window.ConsentBadgeCluster === "function";
  const hasPortal = typeof window !== "undefined" && typeof window.CitizenConsentScreen === "function";
  // Existing households gave a broad interview consent but have no per-purpose
  // ConsentRecords yet (the legacy column was never backfilled). Infer the
  // purposes that statement covers — registration, processing for eligibility,
  // and sharing under a DSA — so the detail card reflects reality instead of
  // showing every purpose as "Not captured". Inferred rows are clearly marked.
  const interviewConsented = live ? !!(consent || h.current_consent_state) : true;
  const inferredConsent = interviewConsented ? {
    codes: ["REGISTRATION", "ELIGIBILITY", "REFERRAL"],
    date: h.capturedAt,
    note: "It covers registration, processing for eligibility, and sharing with partner agencies under a Data Sharing Agreement.",
  } : null;
  return (
    <div>
      <TabHeader title="Consent"
        sub="Data Protection and Privacy Act 2019 (Uganda). Evidence captured at the interview."/>
      {/* US-CONSENT-08 — live per-purpose consent status for the head member,
          plus the capture / manage action (US-CONSENT-03 / -05). Reads
          GET /api/v1/consent/members/{head_member}; renders nothing when the
          consent module is dark or nothing has been captured. */}
      <div style={{padding:"16px 20px 0", display:"flex",
            justifyContent:"space-between", alignItems:"center",
            flexWrap:"wrap", gap:12}}>
        <div>
          <div className="t-cap" style={{marginBottom:8}}>Consent status · head of household</div>
          {hasCluster && headId
            ? React.createElement(window.ConsentBadgeCluster, { memberId: headId, size: "sm" })
            : <span className="muted t-bodysm">No per-purpose consent captured yet.</span>}
        </div>
        <button className="btn btn-primary"
          disabled={!hasPortal}
          title={hasPortal ? "Capture or manage this household's consent" : "Consent portal not loaded"}
          onClick={() => setShowManage(true)}>
          <Icon name="shield" size={14}/> Manage / capture consent
        </button>
      </div>
      {showManage && hasPortal && (
        <Modal open={showManage} onClose={() => setShowManage(false)}
          title="Consent management" width={920}>
          {/* The citizen consent screen is the design preview and renders
              sample household data, NOT this household — the live truth is the
              "Consent detail" card above. Flag it so the two aren't confused
              until the screen is wired to the live per-member API. */}
          <div className="tint-update" style={{
            padding: "8px 12px", borderRadius: 6, marginBottom: 12,
            fontSize: 12, color: "var(--neutral-700)"}}>
            <Icon name="info" size={12} style={{verticalAlign:"middle", marginRight:6}}/>
            Preview — shows sample data, not this household. The live per-purpose
            status for this household is in the “Consent detail” card.
          </div>
          {React.createElement(window.CitizenConsentScreen)}
        </Modal>
      )}
      {/* US-CONSENT-08 detail — full per-purpose consent breakdown
          (accepted / withdrawn / pending …) for the head member. Sits above
          the original interview-evidence cards, which are left untouched. */}
      {typeof window !== "undefined" && typeof window.ConsentStatusCard === "function" && headId && (
        <div style={{padding:"16px 20px 0"}}>
          {React.createElement(window.ConsentStatusCard, {
            memberId: headId,
            title: `Consent detail · per purpose · ${headMember && headMember.name ? headMember.name : "head of household"}`,
            inferred: inferredConsent,
          })}
        </div>
      )}
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
            ? <Chip size="sm" tone="data"><Icon name="check" size={11}/> {h.questionnaireLabels?.interview?.consent || consent}</Chip>
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

// US-S11-044 — Household detail · DQA tab. Shows the intra-household
// evaluation history for this household (newest first), grouped by
// stage. AC-DUPLICATE-MEMBER FAIL renders a "Open Dedup" link that
// pre-filters the Dedup Dashboard to the offending member ids per
// the spec (apps.dqa.pipeline emits offending_member_ids into the
// result row when the duplicates_by op fires).
const TabDqa = ({ h, live, onNavigate }) => {
  const [evals, setEvals] = useStateHH(null);
  const [vocab, setVocab] = useStateHH(null);
  const [err, setErr] = useStateHH(null);

  useEffectHH(() => {
    if (!live || !h.rid) return undefined;
    let cancelled = false;
    fetch(`/api/v1/dqa/evaluations/${encodeURIComponent(h.rid)}?limit=20`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => { if (!cancelled) setEvals(Array.isArray(data) ? data : (data.results || [])); })
      .catch(e => !cancelled && setErr(String(e)));
    fetch("/api/v1/dqa/severity-vocabulary",
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (!cancelled && data) setVocab(data); })
      .catch(() => { /* keep defaults */ });
    return () => { cancelled = true; };
  }, [live, h.rid]);

  const severityIndex = (() => {
    const map = {};
    const list = (vocab && vocab.severities) || [
      { value: "block", label: "Block", token: "status-danger", blocks_save: true },
      { value: "reject_with_override", label: "Reject (override)", token: "status-danger-soft", blocks_save: true },
      { value: "flag", label: "Flag", token: "status-warning", blocks_save: false },
      { value: "info", label: "Info", token: "status-info", blocks_save: false },
    ];
    for (const s of list) map[s.value] = s;
    return map;
  })();

  const toneByToken = { "status-danger": "danger", "status-danger-soft": "danger", "status-warning": "quality", "status-info": "data" };
  const stageLabel = { dih_ingest: "DIH ingest", dih_promote: "DIH promote", registry_post_promote: "Post-promote" };
  const outcomeTone = { pass: "data", review: "quality", block: "danger" };

  // Mock fallback for design preview — non-live mode.
  const mockEvals = [
    { id: "01EVALA", stage: "registry_post_promote", outcome: "pass",
      evaluator_service_version: "1.0", actor: "system",
      evaluated_at: "2026-05-26T08:14:00Z",
      results: [
        { rule_code: "AC-HOH-EXISTS", rule_version: 1, status: "pass", severity: "block",
          message: "", offending_member_ids: [] },
        { rule_code: "AC-DUPLICATE-MEMBER", rule_version: 1, status: "pass", severity: "block",
          message: "", offending_member_ids: [] },
      ] },
    { id: "01EVALB", stage: "dih_promote", outcome: "review",
      evaluator_service_version: "1.0", actor: "akello.p",
      evaluated_at: "2026-05-24T11:02:00Z",
      results: [
        { rule_code: "AC-MEMBER-COUNT-MATCH", rule_version: 1, status: "fail", severity: "flag",
          message: "Reported 5, roster has 4", offending_member_ids: [] },
      ] },
  ];
  const rows = live ? (evals || []) : mockEvals;

  // AC-DUPLICATE-MEMBER → Dedup hook. Picks any duplicate-member
  // failure across the evaluation history and surfaces a banner at
  // the top of the tab so operators can jump straight to triage.
  const dupBanner = (() => {
    for (const ev of rows) {
      const hit = (ev.results || []).find(
        r => r.rule_code === "AC-DUPLICATE-MEMBER" && r.status === "fail",
      );
      if (hit) return { ev, hit };
    }
    return null;
  })();

  return (
    <div>
      <TabHeader title="Data quality evaluations"
        sub="Intra-household rule history · evaluator emits one row per stage per evaluation."
        action={<>
          <button className="btn btn-sm"><Icon name="play" size={13}/> Re-evaluate</button>
        </>}/>

      {dupBanner && (
        <div className="tint-danger" style={{ margin: "0 20px 12px", padding: 12, borderLeft: "3px solid var(--accent-danger)" }}>
          <div className="row gap-2" style={{ alignItems: "center" }}>
            <Icon name="alert" size={14} color="var(--accent-danger)"/>
            <strong className="t-bodysm">AC-DUPLICATE-MEMBER failed</strong>
            <span className="t-bodysm">— {dupBanner.hit.message || "Duplicate member NIN hashes detected"}</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm btn-primary"
              onClick={() => onNavigate && onNavigate("dedup", {
                householdId: h.rid,
                memberIds: dupBanner.hit.offending_member_ids || [],
                evaluationId: dupBanner.ev.id,
              })}>
              <Icon name="search" size={12}/> Open Dedup ({(dupBanner.hit.offending_member_ids || []).length} member{(dupBanner.hit.offending_member_ids || []).length === 1 ? "" : "s"})
            </button>
          </div>
        </div>
      )}

      {err && <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Couldn't load: {err}</div>}
      {live && !evals && !err && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>Loading…</div>
      )}
      {live && evals && evals.length === 0 && (
        <div className="muted t-bodysm" style={{padding:"16px 20px"}}>
          No DQA evaluations recorded for this household yet.
        </div>
      )}

      {rows.map((ev, idx) => {
        const failures = (ev.results || []).filter(r => r.status !== "pass");
        return (
          <div key={ev.id || idx} style={{ padding: "14px 20px", borderTop: idx === 0 ? 0 : "1px solid var(--neutral-200)" }}>
            <div className="row gap-2" style={{ alignItems: "center", marginBottom: 6 }}>
              <Chip size="sm">{stageLabel[ev.stage] || ev.stage}</Chip>
              <Chip size="sm" tone={outcomeTone[ev.outcome] || "neutral"}>{ev.outcome}</Chip>
              <span className="t-cap">v{ev.evaluator_service_version || "1.0"}</span>
              <span className="t-cap">· {ev.actor || "—"}</span>
              <div style={{ flex: 1 }}/>
              <span className="t-cap">{(ev.evaluated_at || "").slice(0, 19).replace("T", " ") || "—"}</span>
            </div>
            {failures.length === 0 ? (
              <div className="t-bodysm muted">
                <Icon name="check" size={12} color="var(--accent-data)"/> All {(ev.results || []).length} rule{(ev.results || []).length === 1 ? "" : "s"} passing.
              </div>
            ) : (
              <table className="tbl" style={{ boxShadow: "none", marginTop: 4 }}>
                <thead><tr><th>Rule</th><th>Severity</th><th>Message</th><th>Members</th></tr></thead>
                <tbody>
                  {failures.map((r, i) => {
                    const sev = severityIndex[r.severity] || { label: r.severity, token: "status-info" };
                    const tone = toneByToken[sev.token] || "data";
                    const offenders = r.offending_member_ids || [];
                    return (
                      <tr key={`${ev.id}:${r.rule_code}:${i}`}>
                        <td className="t-mono t-bodysm">{r.rule_code} v{r.rule_version}</td>
                        <td><Chip size="sm" tone={tone}>{sev.label}</Chip></td>
                        <td className="t-bodysm">{r.message || "—"}</td>
                        <td className="t-cap">
                          {offenders.length === 0 ? "—"
                            : r.rule_code === "AC-DUPLICATE-MEMBER"
                              ? <button className="btn btn-link btn-sm"
                                  onClick={() => onNavigate && onNavigate("dedup", {
                                    householdId: h.rid, memberIds: offenders, evaluationId: ev.id,
                                  })}>{offenders.join(", ")}</button>
                              : offenders.join(", ")}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
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
