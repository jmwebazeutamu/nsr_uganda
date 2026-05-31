/* global React,
   Icon, Chip, PageHeader, Modal,
   HH, ROSTER,
   CHANGE_TYPES, routingFor, fieldDef, initials,
   SEED_DOCS, HISTORY, useFieldCatalog, useCurrentValues, catColor,
   HHContextStrip, RosterPicker, NumberedSection, FieldComposer,
   TweaksPanel, useTweaks, TweakSection, TweakRadio */
// NSR MIS — full-page Change Request submitter (US-S22-004 replacement
// of the modal). Used both as the standalone bundle preview (mounted
// by Change Request.html) and inside the main app shell (rendered by
// app.jsx when navigated from the household screen). Replaces the
// ChangeRequestModal component; payload + endpoint contract match
// /api/v1/upd/change-requests/bundle/.

const { useState: useApp, useMemo: useAppM, useEffect: useAppE } = React;

/* ================================================================
   Reason section
   ================================================================ */
const ReasonSection = ({ changeType, setChangeType, pmtRelevant, pmtOverride, setPmtOverride, autoPmt, note, setNote }) => (
  <div style={{padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:20}}>
    <div className="field">
      <label className="field-label">Change type <span className="req">*</span></label>
      <select className="field-select" value={changeType} onChange={(e) => setChangeType(e.target.value)}>
        {CHANGE_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <span className="field-help">{CHANGE_TYPES.find(c => c.value === changeType)?.hint}</span>
    </div>
    <div className="field">
      <label className="field-label">PMT impact</label>
      <div style={{
        display:"flex", alignItems:"center", gap:10,
        height:34, padding:"0 12px",
        border:"1px solid var(--neutral-300)",
        borderRadius:4, background:"var(--neutral-50)",
      }}>
        {pmtRelevant
          ? <Chip tone="eligibility"><Icon name="target" size={11}/> pmt_relevant</Chip>
          : <Chip tone="neutral">cosmetic</Chip>}
        <label style={{display:"flex", alignItems:"center", gap:6, fontSize:12, color:"var(--neutral-500)", cursor:"pointer", marginLeft:"auto"}}>
          <input type="checkbox" checked={pmtOverride} disabled={autoPmt}
            onChange={(e) => setPmtOverride(e.target.checked)}/>
          Force PMT
        </label>
      </div>
      <span className="field-help">
        {autoPmt
          ? "Auto-derived from one or more PMT-relevant fields above."
          : "Cosmetic by default — none of the selected fields feed the PMT model."}
      </span>
    </div>
    <div className="field" style={{gridColumn:"1 / -1"}}>
      <label className="field-label">Reason for the change <span className="req">*</span></label>
      <textarea className="field-textarea" rows={3} value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Describe why this change is being requested. Cite the evidence attached below. (min. 12 chars)"/>
      <span className="field-help">
        <Icon name="shield" size={11}/> Written verbatim to the audit chain (AC-AUDIT-EVENT) and shown to the reviewer.
        {note.trim().length > 0 && note.trim().length < 12 && (
          <span style={{color:"var(--accent-danger)", marginLeft:8}}>{12 - note.trim().length} more characters needed</span>
        )}
      </span>
    </div>
  </div>
);

/* ================================================================
   Supporting documents section
   ================================================================ */
const DOC_KINDS = [
  "Birth certificate", "Death certificate", "LC1 letter", "NIN card photo",
  "Marriage certificate", "Medical / clinic note", "Photograph",
  "Witness statement", "School record", "Other",
];

const DocsSection = ({ docs, setDocs }) => {
  const [dragOver, setDragOver] = useApp(false);
  const fakeUpload = () => {
    const sample = [
      { name: "Birth certificate scan.pdf",  kind: "Birth certificate", size: "142 KB" },
      { name: "Witness statement — Kato Joseph.pdf", kind: "Witness statement", size: "88 KB" },
      { name: "Photo IMG_2026-05-22.jpg",  kind: "Photograph", size: "1.2 MB" },
    ];
    const next = sample.find(s => !docs.some(d => d.name === s.name));
    if (next) setDocs([...docs, { ...next, uploadedBy: "You · just now" }]);
  };
  const removeDoc = (name) => setDocs(docs.filter(d => d.name !== name));
  const setKind = (name, kind) => setDocs(docs.map(d => d.name === name ? { ...d, kind } : d));

  return (
    <div style={{padding:20}}>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); fakeUpload(); }}
        onClick={fakeUpload}
        style={{
          display:"flex", flexDirection:"column", alignItems:"center", gap:6,
          padding:"22px 16px",
          border: dragOver ? "1.5px dashed var(--primary-700)" : "1.5px dashed var(--neutral-300)",
          background: dragOver ? "var(--primary-100)" : "var(--neutral-50)",
          borderRadius:4, cursor:"pointer",
          transition:"background 0.1s, border-color 0.1s",
        }}>
        <Icon name="download" size={22} color="var(--neutral-500)" style={{transform:"rotate(180deg)"}}/>
        <div style={{fontWeight:600}}>Drop files here, or click to browse</div>
        <div className="t-cap" style={{textAlign:"center"}}>
          PDF, JPG, PNG · 10 MB max per file · all attachments are stored against the change request
        </div>
      </div>

      {docs.length > 0 && (
        <div style={{marginTop:14}}>
          <div className="t-cap" style={{marginBottom:6, fontWeight:600, color:"var(--neutral-700)"}}>
            ATTACHED ({docs.length})
          </div>
          {docs.map(d => (
            <div key={d.name} style={{
              display:"grid",
              gridTemplateColumns:"32px 1fr 200px 32px",
              gap:12, alignItems:"center",
              padding:"10px 12px",
              border:"1px solid var(--neutral-200)",
              borderRadius:4, marginBottom:6, background:"#fff",
            }}>
              <div style={{
                width:32, height:32, borderRadius:4,
                background:"var(--accent-update-bg)", color:"var(--accent-update)",
                display:"grid", placeItems:"center", flex:"0 0 auto",
              }}>
                <Icon name="file" size={16}/>
              </div>
              <div style={{minWidth:0}}>
                <div style={{fontWeight:500, fontSize:13.5}}>{d.name}</div>
                <div className="t-cap mt-1">
                  {d.size} · {d.uploadedBy || "Stored 2 min ago"}
                </div>
              </div>
              <select className="field-select" value={d.kind}
                onChange={(e) => setKind(d.name, e.target.value)}>
                {DOC_KINDS.map(k => <option key={k} value={k}>{k}</option>)}
              </select>
              <button className="icon-btn" onClick={() => removeDoc(d.name)} aria-label="Remove">
                <Icon name="x" size={14}/>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

/* ================================================================
   Review & submit section — summary
   ================================================================ */
const ReviewSection = ({ scope, member, rows, changeType, pmtRelevant, note, docs, problems, liveCatalog, householdId }) => {
  const fieldCount = rows.length;
  const catCount = new Set(rows.map(r => r.cat)).size;
  const catByKey = (k) => (liveCatalog?.categories || []).find(c => c.key === k);
  return (
    <div style={{padding:20, display:"grid", gridTemplateColumns:"1fr 320px", gap:20}}>
      {/* Recap */}
      <div>
        <div style={{
          display:"grid", gridTemplateColumns:"140px 1fr",
          rowGap:10, columnGap:14, fontSize:13,
        }}>
          <div className="muted">Scope</div>
          <div>
            {scope === "household"
              ? <><Chip tone="data">Household-level</Chip> <span className="muted" style={{marginLeft:6}}>applies to the household record</span></>
              : <><Chip tone="update">Member-level</Chip> <span className="muted" style={{marginLeft:6}}>linked to member record</span></>}
          </div>

          {scope === "member" && member && (
            <>
              <div className="muted">Member</div>
              <div>
                <strong>{member.name}</strong> · line {member.line} · {(member.rel || "—").toLowerCase()}
                <div className="t-cap mt-1">
                  Sex {member.sex} · age {member.age} · NIN <span className="t-mono">{member.nin}</span>
                </div>
              </div>
            </>
          )}

          <div className="muted">Household</div>
          <div>
            <span className="t-mono">{(householdId || HH.id).slice(0, 18)}…</span>
            <div className="t-cap mt-1">{HH.head} · {HH.village}, {HH.parish}</div>
          </div>

          <div className="muted">Change type</div>
          <div>
            <Chip tone="update">{CHANGE_TYPES.find(c => c.value === changeType)?.label}</Chip>
            {pmtRelevant
              ? <Chip size="sm" tone="eligibility" style={{marginLeft:6}}><Icon name="target" size={10}/> pmt_relevant</Chip>
              : <Chip size="sm" tone="neutral" style={{marginLeft:6}}>cosmetic</Chip>}
          </div>

          <div className="muted">Field changes</div>
          <div>
            <strong>{fieldCount}</strong> {fieldCount === 1 ? "field" : "fields"} across <strong>{catCount}</strong> {catCount === 1 ? "category" : "categories"}
            {rows.length > 0 && (
              <div className="t-cap mt-1" style={{display:"flex", flexWrap:"wrap", gap:4}}>
                {[...new Set(rows.map(r => r.cat))].map(c => {
                  const col = catColor(catByKey(c));
                  return <Chip key={c} size="sm" tone={col.tone}>{col.label}</Chip>;
                })}
              </div>
            )}
          </div>

          <div className="muted">Documents</div>
          <div>
            {docs.length === 0
              ? <span className="muted">None attached</span>
              : <>{docs.length} attached · {docs.map(d => d.kind).join(", ")}</>}
          </div>

          <div className="muted">Reason</div>
          <div className="t-bodysm" style={{color: note ? "var(--neutral-900)" : "var(--neutral-500)"}}>
            {note || <em>No reason entered yet — required before submission.</em>}
          </div>
        </div>
      </div>

      {/* Validation + routing card */}
      <div>
        <div className="card" style={{
          padding:0, boxShadow:"none",
          border:"1px solid var(--neutral-200)",
          borderTop: `3px solid ${problems.length ? "var(--accent-quality)" : "var(--accent-data)"}`,
        }}>
          <div style={{padding:"12px 14px", borderBottom:"1px solid var(--neutral-200)"}}>
            <div className="t-cap" style={{
              color: problems.length ? "var(--accent-quality)" : "var(--accent-data)",
              fontWeight:600,
            }}>
              {problems.length ? "VALIDATION" : "READY TO SUBMIT"}
            </div>
            <div style={{fontWeight:600, fontSize:14, marginTop:2}}>
              {problems.length
                ? `${problems.length} thing${problems.length === 1 ? "" : "s"} to fix`
                : "All checks pass"}
            </div>
          </div>
          <div style={{padding:"12px 14px"}}>
            {problems.length > 0 ? (
              <ul style={{margin:0, paddingLeft:18, fontSize:13, color:"var(--neutral-700)"}}>
                {problems.map((p, i) => <li key={i} style={{marginBottom:4}}>{p}</li>)}
              </ul>
            ) : (
              <div style={{fontSize:13, color:"var(--neutral-700)"}}>
                Submission will create a <Chip size="sm" tone="update">DRAFT</Chip> ChangeRequest
                and advance to <Chip size="sm" tone="quality">PENDING_APPROVAL</Chip>.
              </div>
            )}
          </div>
          <div style={{padding:"12px 14px", background:"var(--neutral-50)", borderTop:"1px solid var(--neutral-200)"}}>
            <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)"}}>ROUTING</div>
            <div style={{display:"flex", alignItems:"center", gap:8, marginTop:4, fontSize:13}}>
              <Icon name="git" size={14} color="var(--neutral-500)"/>
              Reviewer: <strong>{routingFor(changeType, pmtRelevant)}</strong>
            </div>
            <div className="t-cap mt-1">
              From the <span className="t-mono">change_type × pmt_relevant</span> matrix (SAD §4.4.4).
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ================================================================
   Right-rail — Change history
   ================================================================ */
const HistoryRail = ({ open, setOpen, scope, member }) => {
  // Filter relevant rows
  const filtered = useAppM(() => {
    if (scope === "household") return HISTORY.filter(h => h.subject === "Household-level" || true); // show all
    if (member) return HISTORY.filter(h => h.subject.toLowerCase().includes(member.name.toLowerCase()) || h.subject === "Household-level");
    return HISTORY;
  }, [scope, member]);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} title="Show change history" style={{
        position:"sticky", top:80,
        width:48, height:140,
        marginTop:0,
        background:"var(--neutral-0)",
        border:"1px solid var(--neutral-300)",
        borderRight:0,
        borderRadius:"6px 0 0 6px",
        display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:8,
        cursor:"pointer", color:"var(--neutral-700)",
        boxShadow:"-2px 0 6px rgba(0,0,0,0.04)",
      }}>
        <Icon name="history" size={16}/>
        <span style={{writingMode:"vertical-rl", transform:"rotate(180deg)", fontSize:12, fontWeight:600, letterSpacing:"0.04em"}}>HISTORY</span>
      </button>
    );
  }

  return (
    <aside style={{
      position:"sticky", top:80,
      width:340, maxHeight:"calc(100vh - 120px)",
      background:"var(--neutral-0)",
      border:"1px solid var(--neutral-300)",
      borderRadius:8,
      display:"flex", flexDirection:"column",
      overflow:"hidden",
    }}>
      <div style={{
        padding:"12px 14px",
        borderBottom:"1px solid var(--neutral-200)",
        display:"flex", alignItems:"center", gap:8,
      }}>
        <Icon name="history" size={14} color="var(--neutral-700)"/>
        <strong className="t-bodysm">Change history</strong>
        <span className="t-cap">{filtered.length}</span>
        <div style={{flex:1}}/>
        <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Collapse">
          <Icon name="chevronsRight" size={14}/>
        </button>
      </div>
      <div style={{padding:"10px 14px", background:"var(--neutral-50)", borderBottom:"1px solid var(--neutral-200)"}}>
        <div className="t-cap">
          {scope === "household"
            ? <>All change requests against household <span className="t-mono">{HH.id.slice(0,12)}…</span></>
            : member
              ? <>Linked to <strong style={{color:"var(--neutral-900)"}}>{member.name}</strong> + parent household</>
              : <>Select a member to scope further</>}
        </div>
      </div>

      <div style={{flex:1, overflowY:"auto"}}>
        {filtered.map(h => (
          <div key={h.id} style={{
            padding:"12px 14px",
            borderBottom:"1px solid var(--neutral-200)",
            display:"flex", flexDirection:"column", gap:4,
          }}>
            <div style={{display:"flex", alignItems:"center", gap:8}}>
              <span className="t-mono" style={{fontSize:11.5, color:"var(--neutral-700)"}}>{h.id}</span>
              <div style={{flex:1}}/>
              <Chip size="sm" tone={statusTone(h.status)}>{h.status}</Chip>
            </div>
            <div style={{fontWeight:500, fontSize:13}}>{h.type}</div>
            <div className="t-cap">
              {h.subject} · decided {h.decided} by {h.by}
            </div>
            {h.note && (
              <div className="t-cap" style={{
                marginTop:4, padding:"6px 8px",
                background:"var(--accent-danger-bg)", color:"var(--accent-danger)",
                borderRadius:3,
              }}>
                <Icon name="info" size={10}/> {h.note}
              </div>
            )}
          </div>
        ))}
        <div className="t-cap" style={{padding:14, textAlign:"center"}}>
          End of history · {filtered.length} item{filtered.length === 1 ? "" : "s"}
        </div>
      </div>

      <div style={{
        padding:"10px 14px", borderTop:"1px solid var(--neutral-200)",
        background:"var(--neutral-50)",
        display:"flex", alignItems:"center", gap:8,
      }}>
        <Icon name="shield" size={12} color="var(--neutral-500)"/>
        <span className="t-cap">Full audit chain available under the household's Audit tab.</span>
      </div>
    </aside>
  );
};

const statusTone = (s) => ({
  "Approved": "data", "Committed": "data",
  "Rejected": "danger", "Reversed": "neutral",
  "Pending Approval": "quality", "Pending QA": "quality", "On hold": "quality",
  "Draft": "neutral", "Submitted": "update",
}[s] || "neutral");

/* ================================================================
   CSRF helper — required for DRF session-auth POSTs. Same pattern as
   _hhCsrf / _updCsrf elsewhere. file:// previews lack the cookie, so
   the POST 403s and the screen surfaces the error inline.
   ================================================================ */
const _crCsrf = () => {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

/* ================================================================
   Live POST to /api/v1/upd/change-requests/bundle/. Payload shape
   mirrors the modal it replaces (see ChangeRequestModal.submit).
   Resolves with the bundle response; throws Error with the server
   message on non-201.
   ================================================================ */
const submitBundle = async (payload) => {
  const r = await fetch("/api/v1/upd/change-requests/bundle/", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": _crCsrf(),
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (r.status !== 201) {
    throw new Error(data.detail || JSON.stringify(data) || `HTTP ${r.status}`);
  }
  return data;
};

/* ================================================================
   Main screen
   ================================================================ */
const ChangeRequestScreen = ({
  initialScope = "household",
  // Host household identity. When omitted (standalone preview) the
  // screen displays the mock HH constant and POSTs against its id.
  householdId,
  // Live roster projected by the consuming screen (household detail).
  // Items: {id, line, name, rel, sex, age, dob, nin, ninStatus}.
  // When present, replaces the bundle's mock ROSTER so member-scope
  // CRs submit with the real Member ULID. Falls back to ROSTER for
  // standalone preview where no household context exists.
  roster = null,
  // /api/v1/security/users/me/ payload, when available. Used for the
  // requester label in the sticky action bar.
  me,
  // Called when the bundle submit returns 201. Receives the bundle
  // response. App-shell consumers use this to navigate back to the
  // household screen carrying the new cr_id; standalone preview
  // leaves it undefined.
  onSuccess,
  // Called when the operator dismisses the screen without submitting.
  // App-shell consumers navigate back to the household screen.
  onBack,
}) => {
  const [t, setTweak] = useTweaks({ scope: initialScope });
  const scope = t.scope;
  // Effective roster — live when supplied, otherwise the bundle mock.
  const effectiveRoster = (Array.isArray(roster) && roster.length > 0)
    ? roster : ROSTER;
  const isLiveRoster = Array.isArray(roster) && roster.length > 0;

  const [member, setMember] = useApp(null);
  const [rows, setRows] = useApp([]);
  const [changeType, setChangeType] = useApp("correction");
  const [pmtOverride, setPmtOverride] = useApp(false);
  const [note, setNote] = useApp("");
  const [docs, setDocs] = useApp(SEED_DOCS);
  const [historyOpen, setHistoryOpen] = useApp(true);
  const [busy, setBusy] = useApp(false);
  const [error, setError] = useApp("");

  // Live field catalog from /api/v1/upd/field-catalog/. Drives the
  // composer, PMT auto-derivation, and the submit payload's native
  // (category, field) keys. ChangeRequestModal followed the same
  // pattern — we cannot ship a hardcoded UI catalog because the
  // server's validate_rows() rejects unknown (category, field) pairs
  // and the storage keys evolve faster than designer-bundle JSX.
  const liveCatalog = useFieldCatalog();

  // Live current values for the rows the operator has picked. Drives
  // the CURRENT column in section 2. Re-fetches when the (cat, field)
  // tuples change; stays inert until at least one row is queued.
  // Standalone preview without a session returns "" for every field;
  // the FieldComposer renders the dash placeholder in that case.
  // Member-scope current-values only fire when we have a real
  // Member ULID (live-roster path); mock rows are skipped server-side.
  const currentValues = useCurrentValues({
    householdId: householdId || HH.id,
    entity: scope === "household" ? "household" : "member",
    memberId: (scope === "member" && isLiveRoster && member?.id) ? member.id : "",
    rows,
  });

  // Reset on scope flip. Default-picked member differs between
  // standalone preview (spouse from the mock roster) and live mode
  // (first available, since the live roster's first row is the head
  // and operators almost always want a member who isn't the head).
  useAppE(() => {
    setRows([]);
    setPmtOverride(false);
    setError("");
    if (scope === "household") setMember(null);
    else if (!member) {
      const fallbackIdx = isLiveRoster
        ? Math.min(1, effectiveRoster.length - 1)
        : 1;
      setMember(effectiveRoster[fallbackIdx] || effectiveRoster[0]);
    }
  }, [scope]);

  const autoPmt = useAppM(
    () => rows.some(r => fieldDef(liveCatalog.fieldsFlat, r.cat, r.field)?.pmt),
    [rows, liveCatalog.fieldsFlat],
  );
  const pmtRelevant = autoPmt || pmtOverride;

  const memberRequired = scope === "member";
  const memberPicked = !memberRequired || !!member;
  const noteValid = note.trim().length >= 12;

  const problems = [];
  if (memberRequired && !member) problems.push("Pick a member from the roster.");
  if (rows.length === 0) problems.push("Add at least one field change.");
  else if (!rows.every(r => String(r.value).trim().length > 0)) problems.push("Every field change needs a new value.");
  if (!noteValid) problems.push(`Reason needs at least 12 characters (currently ${note.trim().length}).`);

  const canSubmit = problems.length === 0 && !busy;

  const [toast, setToast] = useApp("");
  // Live submit — POST to /api/v1/upd/change-requests/bundle/ and let
  // onSuccess take over (navigate back to the household record). On
  // file:// preview the fetch fails; we surface the error inline and
  // keep the operator on the page so nothing is silently lost.
  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    const payload = {
      household_id: householdId || HH.id,
      entity: scope === "household" ? "household" : "member",
      // Member ULID for member-scope CRs. Server requires exactly 26
      // chars; the live-roster path supplies a real Member.id, the
      // standalone-mock path has none (server will 400, which is the
      // correct signal that you can't submit member-scope from the
      // file:// preview).
      ...(scope === "member" && member?.id ? { member_id: member.id } : {}),
      change_type: changeType,
      pmt_relevant: pmtRelevant,
      rows: rows.map(r => ({
        category: r.cat,
        field: r.field,
        new_value: String(r.value),
      })),
      note,
    };
    try {
      const result = await submitBundle(payload);
      const routedTo = result.routed_to || routingFor(changeType, pmtRelevant);
      setToast(`Change request ${result.cr_id} submitted · routed to ${routedTo}`);
      setTimeout(() => setToast(""), 4500);
      onSuccess?.(result);
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{minHeight:"100vh", background:"var(--neutral-100)"}}>
      <div style={{
        maxWidth: 1600, margin: "0 auto",
        padding: "24px 24px 0",
        display:"grid",
        gridTemplateColumns: historyOpen ? "minmax(0, 1fr) 360px" : "minmax(0, 1fr) 48px",
        gap: 20,
        alignItems:"flex-start",
        transition:"grid-template-columns 0.18s ease",
      }}>
        {/* Main column */}
        <div style={{minWidth:0}}>
          <PageHeader
            eyebrow={<>UPDATES · US-090 · NEW CHANGE REQUEST</>}
            title="Open a change request"
            sub={<>
              Creates a <strong>DRAFT</strong> ChangeRequest scoped to household{" "}
              <span className="t-mono">{(householdId || HH.id).slice(0, 18)}…</span>, and advances it to{" "}
              <strong>PENDING_APPROVAL</strong> on submit.
            </>}
            right={<>
              <button className="btn"><Icon name="save" size={14}/> Save draft</button>
              {onBack
                ? <button className="btn btn-ghost" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to household</button>
                : <button className="btn btn-ghost"><Icon name="x" size={14}/> Discard</button>}
            </>}
          />

          {error && (
            <div className="card" role="alert" style={{
              padding:"12px 16px", marginBottom:16,
              borderLeft:"3px solid var(--accent-danger)",
              background:"var(--accent-danger-bg)",
              color:"var(--accent-danger)",
              display:"flex", alignItems:"flex-start", gap:10,
            }}>
              <Icon name="alert" size={16}/>
              <div style={{flex:1}}>
                <strong>Submit failed</strong>
                <div className="t-bodysm" style={{marginTop:2}}>{error}</div>
              </div>
              <button className="icon-btn" onClick={() => setError("")} aria-label="Dismiss">
                <Icon name="x" size={14}/>
              </button>
            </div>
          )}

          <HHContextStrip/>

          {/* Section 1 — Scope */}
          <NumberedSection n="1" title="Update scope"
            sub="Pick whether this change applies to the household as a whole, or to a specific member of the roster."
            right={<Chip tone={scope === "household" ? "data" : "update"}>
              {scope === "household" ? "Household-level" : "Member-level"}
            </Chip>}>
            <div style={{padding:20}}>
              <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12}}>
                <ScopeCard
                  active={scope === "household"}
                  onClick={() => setTweak("scope", "household")}
                  tone="data"
                  icon="home"
                  title="Household-level update"
                  body="The change applies to the household record as a whole — e.g. roof material, water source, phone number, address."
                />
                <ScopeCard
                  active={scope === "member"}
                  onClick={() => setTweak("scope", "member")}
                  tone="update"
                  icon="users"
                  title="Roster / member-level update"
                  body="The change applies to a specific household member — e.g. correcting a NIN, updating occupation, recording a disability."
                />
              </div>
            </div>
            {scope === "member" && (
              <div style={{borderTop:"1px solid var(--neutral-200)", background:"var(--neutral-50)"}}>
                <RosterPicker selected={member} onSelect={setMember} roster={effectiveRoster}/>
                {member && <SelectedMemberStrip member={member}/>}
              </div>
            )}
          </NumberedSection>

          {/* Section 2 — Field changes */}
          <NumberedSection n="2" title="Field changes"
            sub={scope === "household"
              ? "Pick the data field(s) you want to change. Each row shows the current value alongside your proposed new value."
              : memberPicked
                ? <>Showing fields relevant to <strong style={{color:"var(--neutral-900)"}}>{member.name}</strong> (member-scoped only).</>
                : "Pick a member above to see member-scoped fields."}
            locked={!memberPicked}
            right={rows.length > 0 && (
              <span className="t-cap">{rows.length} {rows.length === 1 ? "field" : "fields"} queued</span>
            )}>
            <FieldComposer scope={scope} member={member} rows={rows} setRows={setRows}
              liveCatalog={liveCatalog} currentValues={currentValues.values}/>
          </NumberedSection>

          {/* Section 3 — Reason */}
          <NumberedSection n="3" title="Reason for change"
            sub="Classify the change and explain why. Reviewer routing comes from the change type × PMT impact matrix."
            locked={!memberPicked || rows.length === 0}>
            <ReasonSection
              changeType={changeType} setChangeType={setChangeType}
              pmtRelevant={pmtRelevant} pmtOverride={pmtOverride} setPmtOverride={setPmtOverride}
              autoPmt={autoPmt} note={note} setNote={setNote}/>
          </NumberedSection>

          {/* Section 4 — Documents */}
          <NumberedSection n="4" title="Supporting documents"
            sub="Attach evidence — birth/death certificate, LC1 letter, photo, witness statement. Stored against the change request."
            locked={!memberPicked || rows.length === 0}
            right={<span className="t-cap">{docs.length} attached</span>}>
            <DocsSection docs={docs} setDocs={setDocs}/>
          </NumberedSection>

          {/* Section 5 — Review */}
          <NumberedSection n="5" title="Review & submit"
            sub="Final check before the request is created and routed to a reviewer."
            right={canSubmit
              ? <Chip tone="data"><Icon name="check" size={11}/> Ready</Chip>
              : <Chip tone="quality">{problems.length} to fix</Chip>}>
            <ReviewSection
              scope={scope} member={member} rows={rows}
              changeType={changeType} pmtRelevant={pmtRelevant}
              note={note} docs={docs} problems={problems}
              liveCatalog={liveCatalog} householdId={householdId}/>
          </NumberedSection>

          {/* Sticky action bar */}
          <div style={{
            position:"sticky", bottom:0, zIndex:20,
            marginLeft:-24, marginRight:-24, marginTop:0,
            background:"var(--neutral-0)",
            borderTop:"1px solid var(--neutral-300)",
            padding:"12px 24px",
            display:"flex", alignItems:"center", gap:12,
            boxShadow:"0 -2px 8px rgba(0,0,0,0.04)",
          }}>
            <div className="t-bodysm" style={{color:"var(--neutral-500)"}}>
              Requester: <strong style={{color:"var(--neutral-900)"}}>{me?.username || me?.display_name || "console-operator"}</strong> ·
              {" "}Scope: <strong style={{color:"var(--neutral-900)"}}>{scope === "household" ? "Household" : "Member"}</strong>
              {scope === "member" && member && <> ({member.name})</>} ·
              {" "}Routes to: <strong style={{color:"var(--neutral-900)"}}>{routingFor(changeType, pmtRelevant)}</strong>
            </div>
            <div style={{flex:1}}/>
            <button className="btn" disabled={busy}><Icon name="save" size={14}/> Save as draft</button>
            <button className="btn btn-ghost" disabled={busy} onClick={onBack}>
              <Icon name="x" size={14}/> Cancel
            </button>
            <button className="btn btn-success" disabled={!canSubmit} onClick={submit}
              title={!canSubmit ? problems.join("; ") : "Submit for review"}>
              <Icon name="check" size={14}/> {busy ? "Submitting…" : "Submit for review"}
              {!busy && rows.length > 0 && ` · ${rows.length} ${rows.length === 1 ? "change" : "changes"}`}
            </button>
          </div>
        </div>

        {/* Right rail — history */}
        <HistoryRail open={historyOpen} setOpen={setHistoryOpen} scope={scope} member={member}/>
      </div>

      {/* Tweaks */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="Preview">
          <TweakRadio
            label="Update scope"
            value={t.scope}
            onChange={(v) => setTweak("scope", v)}
            options={[
              { value: "household", label: "Household" },
              { value: "member",    label: "Member" },
            ]}
            hint="Toggle the page between the two update levels."/>
        </TweakSection>
      </TweaksPanel>

      {toast && (
        <div className="toast" role="status">{toast}</div>
      )}
    </div>
  );
};

/* ================================================================
   ScopeCard (segmented choice)
   ================================================================ */
const ScopeCard = ({ active, onClick, tone, icon, title, body }) => {
  const accent = `var(--accent-${tone})`;
  const bg = `var(--accent-${tone}-bg)`;
  return (
    <button onClick={onClick} style={{
      display:"flex", alignItems:"flex-start", gap:14,
      padding:"16px 18px",
      borderRadius:6,
      border: active ? `2px solid ${accent}` : "1px solid var(--neutral-300)",
      background: active ? bg : "var(--neutral-0)",
      cursor:"pointer", textAlign:"left",
      transition:"background 0.1s, border-color 0.1s",
      position:"relative",
    }}>
      <div style={{
        width:36, height:36, borderRadius:6,
        background: active ? accent : "var(--neutral-100)",
        color: active ? "#fff" : accent,
        display:"grid", placeItems:"center", flex:"0 0 auto",
      }}>
        <Icon name={icon} size={18}/>
      </div>
      <div style={{flex:1, minWidth:0}}>
        <div style={{display:"flex", alignItems:"center", gap:8, marginBottom:4}}>
          <strong style={{color:active ? accent : "var(--neutral-900)", fontSize:14}}>{title}</strong>
          {active && <Chip size="sm" tone={tone}>selected</Chip>}
        </div>
        <div className="t-bodysm" style={{color:"var(--neutral-700)"}}>{body}</div>
      </div>
      <div style={{
        position:"absolute", top:14, right:14,
        width:18, height:18, borderRadius:"50%",
        border: active ? `5px solid ${accent}` : "1.5px solid var(--neutral-300)",
        background:"#fff",
      }}/>
    </button>
  );
};

/* ================================================================
   Selected-member strip — shown after a member is picked
   ================================================================ */
const SelectedMemberStrip = ({ member }) => (
  <div style={{
    padding:"14px 20px",
    borderTop:"1px solid var(--neutral-200)",
    background:"var(--accent-update-bg)",
    display:"grid", gridTemplateColumns:"auto 1fr 1fr 1fr 1fr", gap:20, alignItems:"center",
  }}>
    <div style={{
      width:48, height:48, borderRadius:"50%",
      background:"var(--accent-update)", color:"#fff",
      display:"grid", placeItems:"center", fontSize:14, fontWeight:600,
    }}>{initials(member.name)}</div>
    <div>
      <div className="t-cap" style={{color:"var(--accent-update)", fontWeight:600}}>CHANGE SUBJECT</div>
      <div style={{fontWeight:600, fontSize:15, color:"var(--neutral-900)"}}>{member.name}</div>
      <div className="t-cap mt-1">Member · line {String(member.line).padStart(2,"0")} of household roster</div>
    </div>
    <div>
      <div className="t-cap">RELATION</div>
      <div style={{fontWeight:500, fontSize:13.5}}>{member.rel || "—"}</div>
      {member.marital && <div className="t-cap mt-1">Marital: {member.marital}</div>}
    </div>
    <div>
      <div className="t-cap">IDENTITY</div>
      <div className="t-mono" style={{fontSize:13}}>{member.nin || "—"}</div>
      <div className="t-cap mt-1">Sex {member.sex} · {member.age} yrs{member.dob ? ` (${member.dob})` : ""}</div>
    </div>
    <div>
      <div className="t-cap">MEMBER ID</div>
      <div className="t-mono" style={{fontSize:12}}>
        {member.id || `M-${HH.id.slice(-10)}-${String(member.line).padStart(3, "0")}`}
      </div>
      <div className="t-cap mt-1">
        <Icon name="info" size={10}/> Change will be linked to this record
      </div>
    </div>
  </div>
);

Object.assign(window, { ChangeRequestScreen });
