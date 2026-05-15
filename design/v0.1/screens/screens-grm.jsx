/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, ReasonModal, ActionBar, Toast */
// NSR MIS — GRM workbench (US-S8-006). Parity-or-better with the
// Django admin surface from S4-005 + S6-001: list + SLA badge + bulk
// assign/escalate/resolve/close. Talks the same shape as
// /api/v1/grm/grievances/ from apps.grievance.api.

const { useState: useStateGrm, useMemo: useMemoGrm } = React;

// Tier vocabulary mirrors apps.grievance.models.Tier. Labels chosen
// for the workbench column header — operators speak "L1/L2/L3/L4"
// in the corridor; the long names live in the row detail.
const GRM_TIERS = {
  l1_parish_chief: { short: "L1", label: "Parish Chief", sla_hours: 24 },
  l2_cdo:          { short: "L2", label: "CDO",          sla_hours: 48 },
  l3_district:     { short: "L3", label: "District",     sla_hours: 72 },
  l4_nsr_unit:     { short: "L4", label: "NSR Unit",     sla_hours: 168 },
};

const GRM_CATEGORIES = {
  data_correction:  "Data correction",
  exclusion_error:  "Wrongly excluded",
  inclusion_error:  "Wrongly included",
  programme_issue:  "Programme issue",
  operator_conduct: "Operator conduct",
  other:            "Other",
};

const GRM_STATUSES = {
  open:        { label: "Open",         tone: "data" },
  in_progress: { label: "In progress",  tone: "update" },
  escalated:   { label: "Escalated",    tone: "danger" },
  resolved:    { label: "Resolved",     tone: "eligibility" },
  closed:      { label: "Closed",       tone: "neutral" },
};

// Mock rows that mirror the GrievanceSerializer shape (apps/grievance/
// api.py GrievanceSerializer.Meta.fields). hours_to_breach is
// computed: positive = within SLA, negative = breached.
const GRM_ROWS = [
  { id: "01GRM2026051400001", category: "data_correction", tier: "l1_parish_chief", status: "open",        household_id: "01HXY7K3B2N9PVQE4M6FZRWS18", member_id: "01HXY7K3B2N9PVQE4M6FZRWS19", reporter_name: "Sarah Nakato",  reporter_phone: "+256 786 234 567", relationship: "Daughter",      assigned_to: "",                  opened_at: "14 May 09:12", hours_to_breach:  18, narrative: "Surname spelled OKELO instead of OKELLO on receipt slip." },
  { id: "01GRM2026051400002", category: "exclusion_error", tier: "l2_cdo",          status: "in_progress", household_id: "01HXZ9MR4N8P2QFB7K6FZRWS33", member_id: "",                              reporter_name: "Akello Grace", reporter_phone: "+256 772 991 234", relationship: "Self · head",   assigned_to: "Adong Florence",    opened_at: "13 May 17:40", hours_to_breach:  -3, narrative: "Household enumerated but not appearing in CDO register; PMT band missing." },
  { id: "01GRM2026051400003", category: "programme_issue", tier: "l3_district",     status: "escalated",   household_id: "01HXZBVK6QN8M2PFB7K6FZRWS41", member_id: "01HXZBVK6QN8M2PFB7K6FZRWS42", reporter_name: "Onyango David",reporter_phone: "+256 752 110 080", relationship: "Self · head",   assigned_to: "Twikirize J. · DM&E",opened_at: "12 May 11:05", hours_to_breach: -27, narrative: "Eligible for PDM SACCO; partner says NSR ID not on roster." },
  { id: "01GRM2026051400004", category: "operator_conduct",tier: "l2_cdo",          status: "open",        household_id: "",                                  member_id: "",                              reporter_name: "Anonymous",     reporter_phone: "",                  relationship: "—",              assigned_to: "",                  opened_at: "14 May 06:55", hours_to_breach:  41, narrative: "Enumerator requested money to register family. Tablet ID PCH-4421." },
  { id: "01GRM2026051400005", category: "data_correction", tier: "l1_parish_chief", status: "open",        household_id: "01HY09KRS1P9MN6FB7K6FZRWS84", member_id: "01HY09KRS1P9MN6FB7K6FZRWS85", reporter_name: "Lokwang Peter", reporter_phone: "+256 782 005 511", relationship: "Self · head",   assigned_to: "Akiteng L.",        opened_at: "13 May 16:30", hours_to_breach:  -1, narrative: "DOB recorded as 1985 but birth-cert shows 1987." },
  { id: "01GRM2026051400006", category: "inclusion_error", tier: "l4_nsr_unit",     status: "escalated",   household_id: "01HY02FNQ9P8MN6FB7K6FZRWS67", member_id: "",                              reporter_name: "Programme MIS · PDM", reporter_phone: "",          relationship: "—",              assigned_to: "Coordinator",       opened_at: "08 May 13:20", hours_to_breach:  19, narrative: "Household marked deceased by NIRA reverse-feed but still showing in PDM roster." },
  { id: "01GRM2026051400007", category: "data_correction", tier: "l1_parish_chief", status: "resolved",    household_id: "01HY04MQR0N8P2FB7K6FZRWS73", member_id: "01HY04MQR0N8P2FB7K6FZRWS74", reporter_name: "Auma Beatrice", reporter_phone: "+256 778 213 994", relationship: "Self · head",   assigned_to: "Akiteng L.",        opened_at: "12 May 08:00", hours_to_breach:   0, narrative: "Telephone updated; UPD 01HXYUPD20260512EFAB committed by CDO." },
];

// Hours-to-breach -> SLA chip. Mirrors the format_html badge from
// apps/grievance/admin.py — green/amber/red is the corridor signal.
const slaChip = (h, status) => {
  if (status === "resolved" || status === "closed") return <Chip size="sm" tone="neutral">—</Chip>;
  if (h < 0)  return <Chip size="sm" tone="danger"><Icon name="clock" size={11}/> {Math.abs(h)}h overdue</Chip>;
  if (h <= 6) return <Chip size="sm" tone="quality"><Icon name="clock" size={11}/> {h}h to breach</Chip>;
  return <Chip size="sm" tone="data"><Icon name="clock" size={11}/> {h}h left</Chip>;
};

const QUICK_FILTERS_GRM = [
  { id: "breach",    label: "Past SLA (any tier)",       icon: "alert",      tone: "danger",  predicate: r => r.hours_to_breach < 0 && r.status !== "resolved" && r.status !== "closed" },
  { id: "open_l1",   label: "Open L1 — Parish Chief",    icon: "users",      tone: "data",    predicate: r => r.tier === "l1_parish_chief" && r.status === "open" },
  { id: "escalated", label: "Escalated — needs me",      icon: "arrowUp",    tone: "update",  predicate: r => r.status === "escalated" },
  { id: "mine",      label: "Assigned to me",            icon: "user",       tone: "programme", predicate: r => r.assigned_to !== "" && r.status !== "closed" },
];

const GRMScreen = () => {
  const [selectedRow, setSelectedRow] = useStateGrm(GRM_ROWS[1].id);
  const [selection, setSelection] = useStateGrm(new Set());
  const [quickFilter, setQuickFilter] = useStateGrm(null);
  const [modal, setModal] = useStateGrm(null); // 'assign' | 'escalate' | 'resolve' | 'close'
  const [auditOpen, setAuditOpen] = useStateGrm(false);
  const [toast, setToast] = useStateGrm("");

  const rows = useMemoGrm(() => {
    if (!quickFilter) return GRM_ROWS;
    const def = QUICK_FILTERS_GRM.find(f => f.id === quickFilter);
    return def ? GRM_ROWS.filter(def.predicate) : GRM_ROWS;
  }, [quickFilter]);

  const current = useMemoGrm(() => GRM_ROWS.find(r => r.id === selectedRow), [selectedRow]);

  const toggleSel = (id) => {
    const next = new Set(selection);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection(next);
  };
  const toggleAll = () => {
    if (selection.size === rows.length) setSelection(new Set());
    else setSelection(new Set(rows.map(r => r.id)));
  };

  // Reasons mirror the service-layer guards (apps.grievance.services).
  // Surfacing them as canned options reduces narrative-quality drift.
  const reasonsEscalate = [
    "L1 SLA breached without resolution",
    "Requires CDO authority (programme override)",
    "Citizen escalation request on record",
    "Other (specify in note)",
  ];
  const reasonsResolve = [
    "Data correction committed via linked UPD",
    "Operator follow-up — issue not substantiated",
    "Citizen withdrew complaint",
    "Other (specify in note)",
  ];
  const reasonsClose = [
    "Resolution confirmed by reporter",
    "30-day grace expired without dispute",
    "Other (specify in note)",
  ];

  const fire = (kind, n) => {
    const map = {
      assign:   `${n || selection.size} grievance(s) assigned. Audit chain updated.`,
      escalate: `${n || selection.size} grievance(s) escalated one tier. SLA window reset.`,
      resolve:  `Grievance resolved. Linked UPD will close it on commit.`,
      close:    `${n || selection.size} grievance(s) closed.`,
    };
    setToast(map[kind] || "Done."); setModal(null); setSelection(new Set());
  };

  const auditEvents = current ? [
    { who: "Reporter",       action: "opened grievance",     detail: `Via ${current.reporter_phone ? 'parish channel · ' + current.reporter_phone : 'anonymous web form'}`, time: current.opened_at, audit: `A-2026-05-${current.id.slice(-2)}-001`, tone: "user" },
    { who: "System GRM",     action: "computed SLA",         detail: `Tier ${GRM_TIERS[current.tier].short} window = ${GRM_TIERS[current.tier].sla_hours}h from open`, time: current.opened_at, audit: `A-2026-05-${current.id.slice(-2)}-002`, tone: "system" },
    ...(current.assigned_to ? [{ who: "Supervisor", action: "assigned to",       detail: current.assigned_to, time: "12m later", audit: `A-2026-05-${current.id.slice(-2)}-003`, tone: "user" }] : []),
    ...(current.status === "escalated" ? [{ who: "System GRM", action: "escalated tier", detail: "SLA breach auto-escalator (US-S7-001 pattern)", time: `${Math.abs(current.hours_to_breach)}h later`, audit: `A-2026-05-${current.id.slice(-2)}-004`, tone: "system" }] : []),
    ...(current.status === "resolved" ? [{ who: "CDO",        action: "resolved with",     detail: "Linked UPD 01HXYUPD20260512EFAB · awaiting commit", time: "later", audit: `A-2026-05-${current.id.slice(-2)}-005`, tone: "user" }] : []),
  ] : [];

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow="GRM WORKBENCH · US-S8-006"
        title={<>Grievance management <Chip>{GRM_ROWS.filter(r => r.status !== "closed" && r.status !== "resolved").length} active</Chip></>}
        sub="Triage, assign, escalate, resolve. SLA = 24h L1 / 48h L2 / 72h L3 / 7d L4 (per SAD §11.1)."
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn"><Icon name="download"/> Export CSV</button>
          <button className="btn primary"><Icon name="plus"/> Open grievance</button>
        </>}
      />

      {/* Quick-filter bar */}
      <div className="card" style={{padding:"14px 20px", marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:"wrap"}}>
          <span className="t-cap" style={{fontWeight:600}}>QUICK FILTERS</span>
          {QUICK_FILTERS_GRM.map(f => {
            const count = GRM_ROWS.filter(f.predicate).length;
            const active = quickFilter === f.id;
            return (
              <button
                key={f.id}
                className={`chip-btn ${active ? "active" : ""}`}
                onClick={() => setQuickFilter(active ? null : f.id)}
                style={{
                  display:"inline-flex", alignItems:"center", gap:6,
                  padding:"6px 10px", borderRadius:8, fontSize:13, fontWeight:500,
                  border: active ? `1px solid var(--accent-${f.tone})` : "1px solid var(--neutral-300)",
                  background: active ? `var(--accent-${f.tone}-bg)` : "white",
                  color: active ? `var(--accent-${f.tone})` : "var(--neutral-800)",
                  cursor:"pointer",
                }}>
                <Icon name={f.icon} size={13}/>
                {f.label}
                <span style={{
                  marginLeft:4, padding:"1px 6px", borderRadius:10, fontSize:11,
                  background: active ? `var(--accent-${f.tone})` : "var(--neutral-200)",
                  color: active ? "white" : "var(--neutral-700)",
                }}>{count}</span>
              </button>
            );
          })}
          {quickFilter && (
            <button className="btn ghost" onClick={() => setQuickFilter(null)}>
              <Icon name="x" size={13}/> Clear
            </button>
          )}
        </div>
      </div>

      {/* List + detail split */}
      <div style={{display:"grid", gridTemplateColumns:"1fr 380px", gap:16}}>
        <div className="card">
          <div className="card-toolbar">
            <strong className="t-bodysm">
              {selection.size > 0
                ? <>{selection.size} selected of {rows.length}</>
                : <>{rows.length} grievances</>}
            </strong>
            <div style={{flex:1}}/>
            {selection.size > 0 && (
              <div className="row gap-2">
                <button className="btn" onClick={() => setModal("assign")}>
                  <Icon name="user" size={13}/> Assign
                </button>
                <button className="btn" onClick={() => setModal("escalate")}>
                  <Icon name="arrowUp" size={13}/> Escalate
                </button>
                <button className="btn" onClick={() => setModal("close")}>
                  <Icon name="check" size={13}/> Close
                </button>
              </div>
            )}
          </div>

          {/* Header */}
          <div style={{display:"grid", gridTemplateColumns:"32px 1fr 110px 100px 130px 140px 130px", borderBottom:"1px solid var(--neutral-200)", background:"var(--neutral-50)", fontSize:11, fontWeight:600, letterSpacing:"0.06em", textTransform:"uppercase", color:"var(--neutral-700)"}}>
            <div style={{padding:"10px 8px", textAlign:"center"}}>
              <input type="checkbox" checked={selection.size === rows.length && rows.length > 0} onChange={toggleAll}/>
            </div>
            <div style={{padding:"10px 16px"}}>Subject / Reporter</div>
            <div style={{padding:"10px 8px"}}>Tier</div>
            <div style={{padding:"10px 8px"}}>Status</div>
            <div style={{padding:"10px 8px"}}>SLA</div>
            <div style={{padding:"10px 8px"}}>Assigned</div>
            <div style={{padding:"10px 8px"}}>Opened</div>
          </div>

          {rows.map(r => {
            const sel = selection.has(r.id);
            const active = selectedRow === r.id;
            const status = GRM_STATUSES[r.status];
            const tier = GRM_TIERS[r.tier];
            return (
              <div
                key={r.id}
                onClick={() => setSelectedRow(r.id)}
                style={{
                  display:"grid", gridTemplateColumns:"32px 1fr 110px 100px 130px 140px 130px",
                  borderBottom:"1px solid var(--neutral-200)",
                  background: active ? "var(--accent-data-bg)" : sel ? "var(--neutral-50)" : "white",
                  cursor:"pointer",
                  alignItems:"center",
                }}>
                <div style={{padding:"12px 8px", textAlign:"center"}} onClick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>
                  <input type="checkbox" checked={sel} onChange={() => {}}/>
                </div>
                <div style={{padding:"12px 16px"}}>
                  <div style={{fontSize:13, fontWeight:500, color:"var(--neutral-900)"}}>
                    {GRM_CATEGORIES[r.category]}
                    {r.household_id && <span className="t-mono muted" style={{marginLeft:8, fontSize:11}}>· hh {r.household_id.slice(0,12)}…</span>}
                  </div>
                  <div className="t-bodysm muted" style={{marginTop:2}}>
                    {r.reporter_name}{r.relationship !== "—" && ` · ${r.relationship}`}{r.reporter_phone && ` · ${r.reporter_phone}`}
                  </div>
                </div>
                <div style={{padding:"12px 8px"}}>
                  <Chip size="sm" tone="data" title={tier.label}>{tier.short}</Chip>
                </div>
                <div style={{padding:"12px 8px"}}>
                  <Chip size="sm" tone={status.tone}>{status.label}</Chip>
                </div>
                <div style={{padding:"12px 8px"}}>
                  {slaChip(r.hours_to_breach, r.status)}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color: r.assigned_to ? "var(--neutral-800)" : "var(--neutral-500)"}}>
                  {r.assigned_to || <em>unassigned</em>}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {r.opened_at}
                </div>
              </div>
            );
          })}

          {rows.length === 0 && (
            <div style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
              <Icon name="inbox" size={32} color="var(--neutral-300)"/>
              <div className="t-bodysm mt-2">No grievances match this filter.</div>
            </div>
          )}
        </div>

        {/* Detail rail */}
        {current && (
          <div className="col gap-3">
            <div className="card" style={{borderTop:"3px solid var(--accent-data)"}}>
              <div className="card-header" style={{padding:"12px 16px"}}>
                <div>
                  <div className="t-cap"><Icon name="message" size={11}/> CASE DETAIL</div>
                  <h3 className="t-h3" style={{margin:"2px 0 0"}}>{GRM_CATEGORIES[current.category]}</h3>
                </div>
                <Chip tone={GRM_STATUSES[current.status].tone}>{GRM_STATUSES[current.status].label}</Chip>
              </div>
              <div style={{padding:16}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>ID</div>
                <div className="t-mono" style={{fontSize:12}}>{current.id}</div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>TIER + SLA</div>
                <div className="row gap-2">
                  <Chip tone="data">{GRM_TIERS[current.tier].short} · {GRM_TIERS[current.tier].label}</Chip>
                  {slaChip(current.hours_to_breach, current.status)}
                </div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>NARRATIVE</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)", lineHeight:1.5}}>
                  {current.narrative}
                </div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>REPORTER</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.reporter_name}</div>
                <div className="t-bodysm muted">{current.relationship}</div>
                {current.reporter_phone && <div className="t-bodysm muted t-mono" style={{fontSize:12}}>{current.reporter_phone}</div>}

                {current.household_id && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>SUBJECT</div>
                    <div className="t-mono" style={{fontSize:12}}>{current.household_id}</div>
                    {current.member_id && <div className="t-mono muted" style={{fontSize:11, marginTop:2}}>member: {current.member_id.slice(0,18)}…</div>}
                  </>
                )}

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>ASSIGNED</div>
                <div className="t-bodysm" style={{color: current.assigned_to ? "var(--neutral-800)" : "var(--neutral-500)"}}>
                  {current.assigned_to || <em>unassigned — pick this case up</em>}
                </div>
              </div>
            </div>

            {/* Per-row actions */}
            <div className="card">
              <div style={{padding:"12px 16px"}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:8}}>ACTIONS</div>
                <div className="col gap-2">
                  {!current.assigned_to && (
                    <button className="btn" onClick={() => setModal("assign")}>
                      <Icon name="user" size={13}/> Assign to me
                    </button>
                  )}
                  {current.status !== "resolved" && current.status !== "closed" && current.tier !== "l4_nsr_unit" && (
                    <button className="btn" onClick={() => setModal("escalate")}>
                      <Icon name="arrowUp" size={13}/> Escalate one tier
                    </button>
                  )}
                  {current.status !== "resolved" && current.status !== "closed" && (
                    <button className="btn primary" onClick={() => setModal("resolve")}>
                      <Icon name="check" size={13}/> Resolve with narrative
                    </button>
                  )}
                  {current.status === "resolved" && (
                    <button className="btn primary" onClick={() => setModal("close")}>
                      <Icon name="lock" size={13}/> Close grievance
                    </button>
                  )}
                  {current.category === "data_correction" && current.status !== "closed" && (
                    <button className="btn">
                      <Icon name="edit" size={13}/> Open linked UPD
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Modal stack — wired to canned reason lists from the service guards.
          ReasonModal in components.jsx expects open + reasonOptions +
          onClose + onConfirm({reason, note}); intent drives the button tone. */}
      <ReasonModal
        open={modal === "escalate"}
        title="Escalate to next tier"
        intent="update"
        recordLabel={current?.id}
        reasonOptions={reasonsEscalate}
        onClose={() => setModal(null)}
        onConfirm={() => fire("escalate", 1)}/>

      <ReasonModal
        open={modal === "resolve"}
        title="Resolve grievance"
        intent="success"
        recordLabel={current?.id}
        reasonOptions={reasonsResolve}
        onClose={() => setModal(null)}
        onConfirm={() => fire("resolve", 1)}/>

      <ReasonModal
        open={modal === "close"}
        title={selection.size > 1 ? `Close ${selection.size} grievances` : "Close grievance"}
        recordLabel={current?.id}
        reasonOptions={reasonsClose}
        onClose={() => setModal(null)}
        onConfirm={() => fire("close")}/>

      <Modal
        open={modal === "assign"}
        title="Assign grievance(s)"
        onClose={() => setModal(null)}
        footer={<>
          <button className="btn" onClick={() => setModal(null)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => fire("assign")}>Assign</button>
        </>}>
        <div className="t-bodysm" style={{marginBottom:12}}>
          Assign {selection.size > 1 ? `${selection.size} grievances` : "this grievance"} to:
        </div>
        <select className="field-select" style={{width:"100%"}}>
          <option>Adong Florence · CDO Tapac</option>
          <option>Akiteng Lillian · Parish Chief, Nakiloro</option>
          <option>Twikirize J. · District M&amp;E</option>
          <option>NSR Unit duty officer</option>
        </select>
      </Modal>

      <AuditDrawer open={auditOpen} events={auditEvents} onClose={() => setAuditOpen(false)}/>
      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};
