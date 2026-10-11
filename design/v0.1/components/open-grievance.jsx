/* global React, window, document, fetch, FileReader, Icon, Modal,
   HouseholdPicker, useChoiceList,
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
  // A code from the `sex` ChoiceList, the same vocabulary Member.sex
  // uses, fetched below — never a label and never a local list. The
  // server refuses anything the list does not carry.
  reporter_gender: "",
  reporter_age_years: "",
};

// The list that says what sex NSR records. `Member.sex` holds a code
// from it; so does `Grievance.reporter_gender`.
const OG_SEX_LIST = "sex";

// What the registry will accept as an attachment, asked rather than
// assumed. The caps belong to the blob store
// (apps/update_workflow/evidence_storage.py) and are enforced by
// services.attach_document; a copy here would be a second policy free
// to disagree with the one that actually refuses. Until the answer
// arrives the picker takes files and lets the server speak.
const OG_LIMITS_URL = "/api/v1/grm/grievances/attachment-limits/";

const _ogHumanBytes = (n) => {
  if (!Number.isFinite(n)) return "";
  if (n >= 1024 * 1024) return `${Math.round(n / (1024 * 1024))} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} bytes`;
};

// FileReader gives "data:<mime>;base64,<payload>"; the API wants the
// payload. Reading in the browser rather than posting multipart keeps
// the request one JSON body — the same shape UPD's change-request
// bundle uses, so there is one way to send this registry a document.
const _ogReadFile = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
  reader.onload = () => {
    const text = String(reader.result || "");
    const comma = text.indexOf(",");
    resolve({
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
      data_base64: comma >= 0 ? text.slice(comma + 1) : text,
    });
  };
  reader.readAsDataURL(file);
});

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
  // Documents picked but not yet sent. They go with the case in one
  // request, so a refused file refuses the grievance rather than
  // leaving a case whose evidence vanished.
  const [docs, setDocs] = _ogState([]);
  const [limits, setLimits] = _ogState(null);

  // The sex codes, from the one list that holds them.
  const [sexOptions] = (typeof useChoiceList === "function")
    ? useChoiceList(OG_SEX_LIST)
    : [[]];

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
    setDocs([]);
  }, [open, locked, household && household.id, initial]);

  _ogEffect(() => {
    if (!open || limits) return;
    let live = true;
    fetch(OG_LIMITS_URL, {
      credentials: "same-origin", headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { if (live) setLimits(d); })
      // No limits means the hint goes unsaid, not that the picker
      // stops working — the server still refuses what it will not take.
      .catch(() => {});
    return () => { live = false; };
  }, [open, limits]);

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
      body: JSON.stringify({
        ...form,
        household_id: aboutHousehold ? householdId : "",
        // An unanswered age is absent, not nought. A complainant who
        // did not say is not a newborn, and the server stores null.
        reporter_age_years: String(form.reporter_age_years || "").trim() === ""
          ? null
          : Number(form.reporter_age_years),
        documents: docs.map(d => ({
          filename: d.filename,
          content_type: d.content_type,
          data_base64: d.data_base64,
        })),
      }),
    })
      .then(async r => {
        if (r.status === 201) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(g => { onOpened?.(g); onClose?.(); })
      .catch(e => setErr(`We could not create the grievance: ${String(e.message || e)}`))
      .finally(() => setBusy(false));
  };

  const set = (patch) => setForm(f => ({ ...f, ...patch }));

  const addFiles = (fileList) => {
    const picked = Array.from(fileList || []);
    if (!picked.length) return;
    setErr("");
    Promise.all(picked.map(_ogReadFile))
      .then(read => setDocs(d => {
        // The server collapses the same bytes to one attachment; this
        // stops the list showing the same file twice before it gets
        // there. Matched on name and size because the digest is the
        // server's to compute.
        const seen = new Set(d.map(x => `${x.filename}:${x.size}`));
        return [...d, ...read.filter(x => !seen.has(`${x.filename}:${x.size}`))];
      }))
      .catch(e => setErr(String(e.message || e)));
  };

  const dropFile = (index) => setDocs(d => d.filter((_, i) => i !== index));

  const docsBytes = docs.reduce((n, d) => n + (d.size || 0), 0);

  return (
    <Modal
      width={width}
      open={open}
      title="New grievance"
      onClose={() => !busy && onClose?.()}
      footer={<>
        <button className="btn" disabled={busy} onClick={() => onClose?.()}>Cancel</button>
        <button className="btn btn-primary" disabled={busy} onClick={submit}>
          {busy ? "Creating…" : "Create grievance"}
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

        {/* The reporter, in five fields rather than three.
            Sex and age were nowhere, so a GRM that is reported on by
            sex and age group had nothing to report. Five inputs will
            not sit in one row at this width, so the block is a grid of
            two: who they are, then who they are for counting. Every
            one of them is optional — a complaint may be anonymous and
            refusing it for that would be the wrong trade. */}
        <div style={{marginTop:12}}>
          <div className="row" style={{
            justifyContent:"space-between", alignItems:"baseline",
            marginBottom:6,
          }}>
            <div className="t-cap" style={{fontWeight:600}}>REPORTER</div>
            <div className="t-cap muted">All optional</div>
          </div>
          <div style={{
            display:"grid", gap:8,
            gridTemplateColumns:"minmax(0,2fr) minmax(0,2fr) minmax(0,1.4fr)",
          }}>
            <label>
              <div className="t-cap muted" style={{marginBottom:2}}>Name</div>
              <input className="field-text" type="text" placeholder="Name"
                     style={{width:"100%", padding:6}}
                     value={form.reporter_name}
                     onChange={(e) => set({ reporter_name: e.target.value })}/>
            </label>
            <label>
              <div className="t-cap muted" style={{marginBottom:2}}>Phone</div>
              <input className="field-text" type="tel" placeholder="+256…"
                     style={{width:"100%", padding:6}}
                     value={form.reporter_phone}
                     onChange={(e) => set({ reporter_phone: e.target.value })}/>
            </label>
            <label>
              <div className="t-cap muted" style={{marginBottom:2}}>Relationship</div>
              <input className="field-text" type="text" placeholder="e.g. Head"
                     style={{width:"100%", padding:6}}
                     value={form.reporter_relationship}
                     onChange={(e) => set({ reporter_relationship: e.target.value })}/>
            </label>
            <label>
              <div className="t-cap muted" style={{marginBottom:2}}>Sex</div>
              {/* The options are the `sex` ChoiceList's, fetched. A
                  local Male/Female pair would be a second vocabulary
                  for a field Member.sex already reads from one list,
                  and the codes — not the words — are what is stored. */}
              <select className="field-select" style={{width:"100%"}}
                      aria-label="Reporter sex"
                      value={form.reporter_gender}
                      onChange={(e) => set({ reporter_gender: e.target.value })}>
                <option value="">— Not stated —</option>
                {(sexOptions || []).map(o => (
                  <option key={o.code} value={o.code}>{o.label}</option>
                ))}
              </select>
            </label>
            <label>
              <div className="t-cap muted" style={{marginBottom:2}}>Age</div>
              <input className="field-text" type="number" min="0" step="1"
                     placeholder="Years" aria-label="Reporter age in years"
                     style={{width:"100%", padding:6}}
                     value={form.reporter_age_years}
                     onChange={(e) => set({ reporter_age_years: e.target.value })}/>
            </label>
            <div className="t-cap muted" style={{alignSelf:"end", paddingBottom:6}}>
              Counted, never used to decide the case.
            </div>
          </div>
        </div>

        {/* Evidence. A complaint often arrives as a photograph of the
            posted list or a scan of the letter it was written on, and
            there was nowhere to put one: the file stayed on the
            officer's phone and the case was argued from the narrative
            alone. Sent with the case in one request, so a refused file
            refuses the grievance instead of leaving a case whose
            evidence quietly went missing. */}
        <div style={{marginTop:12}}>
          <div className="row" style={{
            justifyContent:"space-between", alignItems:"baseline",
            marginBottom:6,
          }}>
            <div className="t-cap" style={{fontWeight:600}}>ATTACHMENTS</div>
            {limits && (
              <div className="t-cap muted">
                Up to {limits.max_files}, {_ogHumanBytes(limits.max_file_bytes)} each
                {docs.length > 0 && ` · ${_ogHumanBytes(docsBytes)} chosen`}
              </div>
            )}
          </div>

          {docs.length > 0 && (
            <div style={{
              border:"1px solid var(--neutral-200)", borderRadius:6,
              marginBottom:8, overflow:"hidden",
            }}>
              {docs.map((d, i) => (
                <div key={`${d.filename}:${d.size}:${i}`} className="row"
                     style={{
                       justifyContent:"space-between", alignItems:"center",
                       padding:"6px 8px", gap:8,
                       borderTop: i ? "1px solid var(--neutral-200)" : "none",
                     }}>
                  <div className="row gap-2" style={{alignItems:"center", minWidth:0}}>
                    <Icon name="file" size={12}/>
                    <span className="t-bodysm" style={{
                      overflow:"hidden", textOverflow:"ellipsis",
                      whiteSpace:"nowrap",
                    }}>{d.filename}</span>
                  </div>
                  <div className="row gap-2" style={{alignItems:"center"}}>
                    <span className="t-cap muted">{_ogHumanBytes(d.size)}</span>
                    <button className="btn btn-sm btn-ghost" disabled={busy}
                            aria-label={`Remove ${d.filename}`}
                            onClick={() => dropFile(i)}>
                      <Icon name="x" size={11}/>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <label className="btn btn-sm" style={{cursor: busy ? "default" : "pointer"}}>
            <Icon name="plus" size={12}/> Add a document
            <input type="file" hidden multiple disabled={busy}
                   data-testid="og-file-input"
                   accept={(limits && limits.allowed_content_types
                     ? limits.allowed_content_types.join(",") : undefined)}
                   onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}/>
          </label>
          {!docs.length && (
            <div className="t-cap muted" style={{marginTop:6}}>
              A photograph of the posted list, or the letter the complaint
              came on.
            </div>
          )}
        </div>

        {err && (
          <div className="t-bodysm" role="alert" aria-live="assertive" style={{
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
