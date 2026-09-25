/* global React, window, Icon, Modal, HouseholdPicker,
   GRM_CATEGORY_OPTIONS, GRM_TIER_OPTIONS */
// One "Open a grievance" dialog.
//
// There were two, and they disagreed about what a grievance is.
//
// The workbench's asked "is this about a household?" and made you
// search for one; it could not name a MEMBER at all, so a complaint
// about one person in a household of nine was filed against the
// household and whoever picked it up had to read the narrative to find
// out who. The household screen's knew the household already and DID
// offer the roster — but drew its categories and tiers from its own
// copy of the vocabulary, under different labels, so the same
// grievance read differently depending on which screen raised it. It
// validated differently too, and only one of the two offered a way to
// jump to what it had just created.
//
// This is that dialog. It is given a household or it asks for one; it
// offers the roster either way; and everything it knows about
// categories and tiers comes from v0.1/data/grm-vocabulary.jsx.

const {
  useState: _ogState,
  useEffect: _ogEffect,
} = React;

const OG_BLANK = {
  category: "data_correction",
  tier: "l1_parish_chief",
  description: "",
  household_id: "",
  member_id: "",
  reporter_name: "",
  reporter_phone: "",
  reporter_relationship: "",
};

const _ogCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
};

// The roster for a household, so the dialog can name a person.
//
// The workbench had no way to do this: the household picker returns
// list rows, and a list row has no members on it. Fetched on demand
// rather than bundled into every search result — most grievances are
// household-level and never open this select.
const _ogFetchMembers = (householdId) => {
  if (!householdId) return Promise.resolve([]);
  return fetch(
    `/api/v1/data-management/members/?household=${encodeURIComponent(householdId)}&page_size=100`,
    { credentials: "same-origin", headers: { Accept: "application/json" } },
  )
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => (d && (d.results || d)) || [])
    .catch(() => []);
};

const _ogMemberLabel = (m) => {
  const name = [m.first_name, m.surname].filter(Boolean).join(" ")
    || m.name || m.full_name || "(unnamed)";
  const line = m.line_number ?? m.line;
  return line ? `Line ${line} · ${name}` : name;
};

/**
 * @param household  {id, label, sub} when the caller already knows it.
 *                   Given, the household question is not asked — the
 *                   operator is raising this FROM that record and
 *                   re-picking it is not a choice they should be able
 *                   to get wrong.
 * @param initial    prefill, e.g. from the member-detail screen's
 *                   "Open grievance" button.
 * @param onOpened   called with the created grievance.
 */
const OpenGrievanceModal = ({
  open, onClose, onOpened, household = null, initial = null, width = 640,
}) => {
  const [form, setForm] = _ogState(OG_BLANK);
  const [picked, setPicked] = _ogState(null);
  // null = unanswered, so the dialog cannot be submitted with the
  // question silently skipped.
  const [aboutHousehold, setAboutHousehold] = _ogState(null);
  const [members, setMembers] = _ogState([]);
  const [busy, setBusy] = _ogState(false);
  const [err, setErr] = _ogState("");

  const locked = Boolean(household && household.id);
  const householdId = locked ? household.id : form.household_id;

  _ogEffect(() => {
    if (!open) return;
    setErr("");
    setPicked(null);
    setForm({
      ...OG_BLANK,
      ...(initial || {}),
      household_id: locked ? household.id : ((initial || {}).household_id || ""),
    });
    const known = locked || Boolean((initial || {}).household_id);
    setAboutHousehold(known ? true : null);
  }, [open, locked, household && household.id, initial]);

  _ogEffect(() => {
    if (!open || !householdId) { setMembers([]); return; }
    let live = true;
    _ogFetchMembers(householdId).then(rows => { if (live) setMembers(rows); });
    return () => { live = false; };
  }, [open, householdId]);

  const submit = () => {
    if (!form.description.trim()) {
      setErr("Describe the grievance — the narrative is what the handler reads first.");
      return;
    }
    if (aboutHousehold === null) {
      setErr("Say whether this is about a household in the registry.");
      return;
    }
    if (aboutHousehold && !householdId) {
      setErr("Choose the household this grievance is about.");
      return;
    }
    setBusy(true);
    setErr("");
    fetch("/api/v1/grm/grievances/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _ogCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({ ...form, household_id: aboutHousehold ? householdId : "" }),
    })
      .then(async r => {
        if (r.status === 201) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(g => { onOpened?.(g); onClose?.(); })
      .catch(e => setErr(String(e.message || e)))
      .finally(() => setBusy(false));
  };

  const set = (patch) => setForm(f => ({ ...f, ...patch }));

  return (
    <Modal
      width={width}
      open={open}
      title="Open a grievance"
      onClose={() => !busy && onClose?.()}
      footer={<>
        <button className="btn" disabled={busy} onClick={() => onClose?.()}>Cancel</button>
        <button className="btn btn-primary" disabled={busy} onClick={submit}>
          {busy ? "Opening…" : "Open grievance"}
        </button>
      </>}>
      <div className="col gap-2">
        <div className="row gap-3">
          <label style={{flex:1}}>
            <div className="t-cap" style={{fontWeight:600}}>CATEGORY</div>
            <select className="field-select" style={{width:"100%"}}
                    value={form.category}
                    onChange={(e) => set({ category: e.target.value })}>
              {GRM_CATEGORY_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label style={{flex:1}}>
            <div className="t-cap" style={{fontWeight:600}}>TIER</div>
            <select className="field-select" style={{width:"100%"}}
                    value={form.tier}
                    onChange={(e) => set({ tier: e.target.value })}>
              {GRM_TIER_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>
                  {o.label} ({o.sla_hours}h SLA)
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="t-cap" style={{fontWeight:600, marginTop:8}}>NARRATIVE *</label>
        <textarea className="field-text"
                  style={{width:"100%", minHeight:80, padding:8, fontFamily:"inherit"}}
                  placeholder="Describe the grievance. What happened, when, who reported it."
                  value={form.description}
                  onChange={(e) => set({ description: e.target.value })}/>

        {/* Asked outright, because the answer decides whether this can
            ever become a data correction — and because the box it
            replaced took a Registry ID as free text with a ULID for a
            placeholder. Nobody types a ULID; a typo made a grievance
            that pointed at nothing. */}
        <div style={{
          marginTop: 12, padding: 12, borderRadius: 6,
          border: "1px solid var(--neutral-200)", background: "var(--neutral-50)",
        }}>
          <div className="t-cap" style={{fontWeight:600, marginBottom:6}}>
            IS THIS ABOUT A HOUSEHOLD IN THE REGISTRY?
          </div>
          {locked ? (
            <div className="t-bodysm">
              Yes — raised from this record.
              <div style={{marginTop:4}}>{household.label}</div>
              {household.sub && <div className="t-cap muted">{household.sub}</div>}
              <div className="t-mono muted" style={{fontSize:11}}>{household.id}</div>
            </div>
          ) : (
            <>
              <div className="row gap-3" style={{marginBottom: aboutHousehold ? 10 : 0}}>
                <label className="row gap-1" style={{alignItems:"center", cursor:"pointer"}}>
                  <input type="radio" name="og-about-hh" checked={aboutHousehold === true}
                         onChange={() => setAboutHousehold(true)}/>
                  <span className="t-bodysm">Yes</span>
                </label>
                <label className="row gap-1" style={{alignItems:"center", cursor:"pointer"}}>
                  <input type="radio" name="og-about-hh" checked={aboutHousehold === false}
                         onChange={() => {
                           setAboutHousehold(false);
                           setPicked(null);
                           set({ household_id: "", member_id: "" });
                         }}/>
                  <span className="t-bodysm">
                    No — operator conduct, a programme issue, or general
                  </span>
                </label>
              </div>
              {aboutHousehold && (
                <HouseholdPicker
                  value={picked}
                  onChange={(hh) => {
                    setPicked(hh);
                    set({ household_id: hh ? hh.id : "", member_id: "" });
                  }}/>
              )}
              {aboutHousehold && !householdId && (
                <div className="t-cap muted" style={{marginTop:6}}>
                  A data-correction grievance can only open an update once
                  it names a household.
                </div>
              )}
            </>
          )}

          {/* Which person. The workbench could not ask this, so a
              complaint about one member of a household of nine was
              filed against the household. */}
          {aboutHousehold && householdId && (
            <label style={{display:"block", marginTop:10}}>
              <div className="t-cap" style={{fontWeight:600}}>WHO IS IT ABOUT?</div>
              <select className="field-select" style={{width:"100%"}}
                      value={form.member_id}
                      onChange={(e) => set({ member_id: e.target.value })}>
                <option value="">— The household as a whole —</option>
                {members.map(m => (
                  <option key={m.id} value={m.id}>{_ogMemberLabel(m)}</option>
                ))}
              </select>
              {members.length === 0 && (
                <div className="t-cap muted" style={{marginTop:4}}>
                  No roster loaded for this household — it can still be
                  raised at household level.
                </div>
              )}
            </label>
          )}
        </div>

        <label className="t-cap" style={{fontWeight:600, marginTop:8}}>REPORTER</label>
        <div className="row gap-2">
          <input className="field-text" type="text" placeholder="Name"
                 style={{flex:2, padding:6}}
                 value={form.reporter_name}
                 onChange={(e) => set({ reporter_name: e.target.value })}/>
          <input className="field-text" type="text" placeholder="Phone (+256…)"
                 style={{flex:2, padding:6}}
                 value={form.reporter_phone}
                 onChange={(e) => set({ reporter_phone: e.target.value })}/>
          <input className="field-text" type="text" placeholder="Relationship"
                 style={{flex:1, padding:6}}
                 value={form.reporter_relationship}
                 onChange={(e) => set({ reporter_relationship: e.target.value })}/>
        </div>

        {err && (
          <div className="t-bodysm" style={{
            marginTop: 8, color:"var(--accent-danger)",
            padding:"8px 10px", background:"var(--neutral-50)",
            border:"1px solid var(--accent-danger)", borderRadius:6,
          }}>
            <Icon name="alert" size={12}/> {err}
          </div>
        )}
      </div>
    </Modal>
  );
};

window.OpenGrievanceModal = OpenGrievanceModal;
