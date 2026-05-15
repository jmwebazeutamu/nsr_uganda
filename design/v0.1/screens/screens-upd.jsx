/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, ReasonModal, ActionBar, Toast */
// NSR MIS — 11.6 UPD reviewer with PMT preview

const { useState: useStateUpd } = React;

const UPD = {
  id: "UPD-2026-05-14-00237",
  household: "01HXY7K3B2N9PVQE4M6FZRWS18",
  head: "Lokol Naume",
  parish: "Nakiloro · Tapac · Moroto",
  change_type: "Roster: add member",
  pmt_impact: "pmt_relevant",
  sla: { days_open: 2, sla: 3, breach: false },
  submitter: "Lokwang Peter · Parish Chief · PCH-7411",
  reviewer: "Adong Florence · CDO Tapac",
  evidence: ["Photo (baby)", "Witness statement", "Health-centre note"],
  reason: "Birth of dependant in household (Apr 2026)",
  diff: [
    { field: "Household size",   before: "6",  after: "7", section: "Roster",    important: true },
    { field: "Member 07 · Name", before: "—",  after: "Lokol Sarah", section: "Roster" },
    { field: "Member 07 · Sex",  before: "—",  after: "F", section: "Roster" },
    { field: "Member 07 · DoB",  before: "—",  after: "8 Apr 2026", section: "Roster" },
    { field: "Member 07 · Relation", before: "—", after: "Daughter", section: "Roster" },
    { field: "Children under 5", before: "1",  after: "2", section: "Health & Disability", important: true },
    { field: "Birth-registered", before: "1",  after: "2", section: "Health & Disability" },
    { field: "Phone",            before: "+256 786 234567", after: "+256 786 234567", section: "Identification", unchanged: true },
    { field: "GPS lat,lng",      before: "2.49423, 34.65103", after: "2.49423, 34.65103", section: "Identification", unchanged: true },
    { field: "Roof material",    before: "Iron sheets", after: "Iron sheets", section: "Housing", unchanged: true },
    { field: "PMT score",        before: "0.412", after: "0.387", section: "PMT (recomputed)", important: true, mono: true },
    { field: "PMT band",         before: "Poorest 40%", after: "Poorest 20%", section: "PMT (recomputed)", important: true },
  ],
};

const UPDScreen = ({ changeRequestId }) => {
  const [showAll, setShowAll] = useStateUpd(false);
  const [auditOpen, setAuditOpen] = useStateUpd(false);
  const [modal, setModal] = useStateUpd(null);
  const [toast, setToast] = useStateUpd("");
  const [selfApprove] = useStateUpd(false); // disabled in UI

  // Cross-screen handoff (US-S9-004). When the GRM workbench navigates
  // here with a linked_change_request_id, we override the mock id so
  // the operator sees they landed on the right CR. Backend wiring is
  // unchanged — Grievance.linked_change_request_id (S2-008) is what
  // the real fetch will resolve.
  const effectiveId = changeRequestId || UPD.id;
  const fromGrm = Boolean(changeRequestId);

  const visible = showAll ? UPD.diff : UPD.diff.filter(d => !d.unchanged);
  const grouped = visible.reduce((acc, r) => {
    (acc[r.section] = acc[r.section] || []).push(r); return acc;
  }, {});

  const reasonsReject = [
    "Insufficient evidence (AC-UPD-EVIDENCE)",
    "Field outside operator scope",
    "Conflicting with active GRM case",
    "Other (specify in note)",
  ];

  const fire = (kind) => {
    const m = { approve: "Approved. New HouseholdVersion written. PMT recompute queued.", reject: "Rejected. Citizen will be notified by SMS.", hold: "Held for more info. Reviewer notified.", escalate: "Escalated to District M&E Officer." };
    setToast(m[kind] || "Done."); setModal(null);
  };

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow={fromGrm ? "UPDATES · US-090 · OPENED FROM GRM" : "UPDATES · US-090"}
        title={<>Change request <span className="t-mono" style={{fontSize:14, marginLeft:8, color:'var(--neutral-500)'}}>{effectiveId}</span></>}
        sub={<>
          {fromGrm && <Chip tone="data" size="sm" style={{marginRight:8}}>linked from grievance</Chip>}
          Household <span className="t-mono">{UPD.household.slice(0,18)}…</span> · {UPD.head} · {UPD.parish}
        </>}
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn"><Icon name="eye"/> Open household</button>
        </>}
      />

      {/* Header strip */}
      <div className="card" style={{padding:'16px 20px', display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr 1fr 1fr', gap:24, marginBottom:16, alignItems:'center'}}>
        <div>
          <div className="t-cap">CHANGE TYPE</div>
          <div className="row gap-2"><Chip tone="update">{UPD.change_type}</Chip></div>
          <div className="t-bodysm muted mt-2">{UPD.reason}</div>
        </div>
        <div>
          <div className="t-cap">PMT IMPACT</div>
          <Chip tone="eligibility"><Icon name="target" size={11}/> pmt_relevant</Chip>
          <div className="t-bodysm muted mt-2">Recompute previewed →</div>
        </div>
        <div>
          <div className="t-cap">EVIDENCE</div>
          <div className="row-wrap mt-1">
            {UPD.evidence.map((e, i) => <Chip key={i} size="sm" tone="programme">{e}</Chip>)}
          </div>
        </div>
        <div>
          <div className="t-cap">SLA</div>
          <div className="row gap-2"><Chip tone="data"><Icon name="clock" size={11}/> {UPD.sla.days_open}d / {UPD.sla.sla}d</Chip></div>
          <div className="t-bodysm muted mt-1">Within window</div>
        </div>
        <div>
          <div className="t-cap">PEOPLE</div>
          <div className="t-bodysm" style={{fontWeight:500}}>Submitted: {UPD.submitter.split(' · ')[0]}</div>
          <div className="t-cap">Reviewer: {UPD.reviewer.split(' · ')[0]}</div>
        </div>
      </div>

      {/* Diff + PMT preview */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 340px', gap:16}}>
        <div className="card">
          <div className="card-toolbar">
            <strong className="t-bodysm">Before / after diff</strong>
            <span className="t-cap">{visible.length} fields shown · {UPD.diff.length} total</span>
            <div style={{flex:1}}/>
            <label className="row gap-2" style={{fontSize:13}}>
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)}/>
              Show unchanged fields
            </label>
          </div>
          <div>
            {/* header */}
            <div style={{display:'grid', gridTemplateColumns:'200px 1fr 1fr', borderBottom:'1px solid var(--neutral-200)', background:'var(--neutral-50)'}}>
              <div className="t-cap" style={{padding:'10px 16px'}}>FIELD</div>
              <div className="t-cap" style={{padding:'10px 16px', borderLeft:'1px solid var(--neutral-200)'}}>BEFORE</div>
              <div className="t-cap" style={{padding:'10px 16px', borderLeft:'1px solid var(--neutral-200)'}}>AFTER</div>
            </div>

            {Object.entries(grouped).map(([section, rows]) => (
              <React.Fragment key={section}>
                <div style={{padding:'8px 16px', background:'var(--neutral-100)', fontSize:11, fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--neutral-700)', borderBottom:'1px solid var(--neutral-200)'}}>
                  {section}
                </div>
                {rows.map((row, i) => (
                  <div key={i} style={{display:'grid', gridTemplateColumns:'200px 1fr 1fr', borderBottom:'1px solid var(--neutral-200)', alignItems:'stretch'}}>
                    <div style={{padding:'10px 16px', fontSize:13, fontWeight:500, display:'flex', alignItems:'center', gap:6}}>
                      {row.important && <span style={{width:6, height:6, borderRadius:'50%', background:'var(--accent-update)'}}/>}
                      {row.field}
                    </div>
                    <div className={row.mono ? 't-mono' : ''} style={{padding:'10px 16px', borderLeft: row.unchanged ? '1px solid var(--neutral-200)' : '3px solid var(--neutral-200)', background: row.unchanged ? 'var(--neutral-50)' : 'transparent', fontSize: 13, color: row.unchanged ? 'var(--neutral-500)' : 'var(--neutral-900)'}}>
                      {row.before}
                    </div>
                    <div className={row.mono ? 't-mono' : ''} style={{padding:'10px 16px', borderLeft: row.unchanged ? '1px solid var(--neutral-200)' : '3px solid var(--accent-update)', background: row.unchanged ? 'var(--neutral-50)' : 'var(--accent-update-bg)', fontSize: 13, fontWeight: row.unchanged ? 400 : 500, color: row.unchanged ? 'var(--neutral-500)' : 'var(--neutral-900)'}}>
                      {row.after}
                    </div>
                  </div>
                ))}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* Right rail */}
        <div className="col gap-3">
          {/* PMT preview */}
          <div className="card" style={{borderTop:'3px solid var(--accent-eligibility)'}}>
            <div className="card-header" style={{padding:'12px 16px'}}>
              <div>
                <div className="t-cap" style={{color:'var(--accent-eligibility)'}}><Icon name="target" size={11}/> PMT PREVIEW</div>
                <h3 className="t-h3" style={{margin:'2px 0 0'}}>If approved</h3>
              </div>
              <Chip tone="eligibility">pmt_relevant</Chip>
            </div>
            <div style={{padding:16}}>
              <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>CURRENT</div>
              <div className="row" style={{justifyContent:'space-between'}}>
                <span className="t-mono" style={{fontSize:22, fontWeight:700}}>0.412</span>
                <Chip tone="eligibility">Poorest 40%</Chip>
              </div>
              <div className="t-bodysm muted mt-1">Calculated on 14 May 2026 · Model v2.4</div>

              <div className="row" style={{margin:'14px 0', justifyContent:'center'}}>
                <div style={{width:28, height:28, borderRadius:'50%', background:'var(--accent-eligibility-bg)', color:'var(--accent-eligibility)', display:'grid', placeItems:'center'}}>
                  <Icon name="arrowDown" size={14}/>
                </div>
                <span className="t-cap" style={{marginLeft:6}}>−0.025 score · 1 band poorer</span>
              </div>

              <div className="t-cap" style={{fontWeight:600, color:'var(--accent-eligibility)', marginBottom:6}}>RECOMPUTED IF APPROVED</div>
              <div className="row" style={{justifyContent:'space-between'}}>
                <span className="t-mono" style={{fontSize:22, fontWeight:700, color:'var(--accent-eligibility)'}}>0.387</span>
                <Chip tone="eligibility" style={{background:'var(--accent-eligibility)', color:'white', borderColor:'var(--accent-eligibility)'}}>Poorest 20%</Chip>
              </div>
              <div className="t-bodysm muted mt-1">Driven by: +1 dependant under 5 · roster size 7</div>

              <div className="divider"/>

              <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>PROGRAMME IMPLICATIONS</div>
              <ul className="t-bodysm" style={{margin:0, paddingLeft:18, color:'var(--neutral-700)'}}>
                <li>OPM-PDM 2026 Q2 — newly eligible</li>
                <li>NUSAF cash transfer — eligibility unchanged</li>
                <li>WFP food assistance — eligibility unchanged</li>
              </ul>
            </div>
          </div>

          {/* No self-approve */}
          <div className="card" style={{padding:14, borderLeft:'3px solid var(--accent-quality)'}}>
            <div className="row gap-2" style={{marginBottom:4}}>
              <Icon name="info" size={14} color="var(--accent-quality)"/>
              <strong className="t-bodysm">Self-approval policy</strong>
            </div>
            <div className="t-bodysm muted">
              Submitter is <strong>Lokwang Peter</strong>; current reviewer is <strong>Adong Florence</strong>. Approval is permitted (AC-UPD-NO-SELF-APPROVE).
            </div>
          </div>
        </div>
      </div>

      {/* Sticky action bar */}
      <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
        <ActionBar left={<>SLA: <strong>{UPD.sla.days_open}d</strong> of {UPD.sla.sla}d · Reviewer: {UPD.reviewer.split(' · ')[0]}</>}>
          <button className="btn btn-danger" onClick={() => setModal('reject')}><Icon name="xCircle" size={14}/> Reject</button>
          <button className="btn btn-warn" onClick={() => setModal('hold')}><Icon name="clock" size={14}/> Hold for info</button>
          <button className="btn" onClick={() => setModal('escalate')}><Icon name="arrowUp" size={14}/> Escalate</button>
          <button className="btn btn-success" disabled={selfApprove} title={selfApprove ? "You captured this request — self-approval blocked" : ""} onClick={() => setModal('approve')}>
            <Icon name="check" size={14}/> Approve
          </button>
        </ActionBar>
      </div>

      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} title={`Audit · ${UPD.id}`}
        events={[
          { who: "Lokwang Peter", action: "submitted change request", detail: `${UPD.change_type} · evidence: photo, witness, health-centre note`, time: "2d ago", audit: "A-2026-05-12-00091", tone: "user" },
          { who: "System DQA", action: "evaluated", detail: "0 warnings on update payload · ruleset v3.4", time: "2d ago", audit: "A-2026-05-12-00092", tone: "system" },
          { who: "System PMT", action: "previewed recompute", detail: "Δ −0.025 · band shift Poorest 40% → Poorest 20%", time: "2d ago", audit: "A-2026-05-12-00093", tone: "system" },
          { who: "Adong Florence", action: "opened for review", detail: "CDO Tapac · viewed diff and PMT preview", time: "8m ago", audit: "A-2026-05-14-00501", tone: "user" },
        ]}/>

      <ReasonModal open={modal === 'approve'} title="Approve change request" intent="success"
        reasonOptions={["Evidence sufficient · field-confirmed","PMT impact accepted","Routine cosmetic change","Other (specify in note)"]}
        recordLabel={UPD.id} onClose={() => setModal(null)} onConfirm={() => fire('approve')}/>
      <ReasonModal open={modal === 'reject'} title="Reject change request" intent="danger"
        reasonOptions={reasonsReject} recordLabel={UPD.id}
        onClose={() => setModal(null)} onConfirm={() => fire('reject')}/>
      <ReasonModal open={modal === 'hold'} title="Hold for more information" intent="primary"
        reasonOptions={["Awaiting additional photo / witness","Awaiting NIRA reconciliation","Awaiting GRM case resolution","Other"]}
        recordLabel={UPD.id} onClose={() => setModal(null)} onConfirm={() => fire('hold')}/>
      <ReasonModal open={modal === 'escalate'} title="Escalate to District M&E" intent="primary"
        reasonOptions={["Out of scope for CDO","Disputed change","Other"]}
        recordLabel={UPD.id} onClose={() => setModal(null)} onConfirm={() => fire('escalate')}/>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

Object.assign(window, { UPDScreen });
