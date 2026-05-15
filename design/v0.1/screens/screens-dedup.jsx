/* global React, Icon, Chip, PageHeader, Modal, ReasonModal, ActionBar, Toast */
// NSR MIS — 11.5 Dedup Operator side-by-side compare

const { useState: useStateDup } = React;

const PAIR = {
  id: "MP-2026-05-14-00045",
  score: 0.92,
  model: "v3.2-aug-2026",
  queue: "Strong (≥ 0.90)",
  status: "Pending",
  fields: [
    // key, label, A, B, choice (A|B|Both), similarity, list, note
    { key: "registry_id", label: "Registry ID", A: "01HXY7K3B2N9PVQE4M6FZRWS18", B: "01HZ9NK2P5M3QFB7K6FZRWS22", sim: null, list: false, mono: true, fixed: null },
    { key: "head_name",   label: "Head name",   A: "Lokol Naume",     B: "Lokol Naumi",   sim: 0.94, list: false, note: "Soundex match · Levenshtein 1" },
    { key: "head_nin",    label: "Head NIN",    A: "CM12345678ABCD",   B: "CM12345678ABCD", sim: 1.00, list: false, mono: true },
    { key: "dob",         label: "Date of birth",A: "12 Mar 1989",     B: "12 Mar 1991",   sim: 0.50, list: false, note: "Off by 2 years — must choose" },
    { key: "sex",         label: "Sex",         A: "F",                B: "F",             sim: 1.00, list: false },
    { key: "phone",       label: "Phone",       A: "+256 786 234567",  B: "+256 781 552119", sim: 0.20, list: true, mono: true, note: "Different operators — keep both" },
    { key: "parish",      label: "Parish",      A: "Nakiloro · Moroto",B: "Nakiloro · Moroto", sim: 1.00 },
    { key: "village",     label: "Village",     A: "Lopuwapuwa A",     B: "Lopuwapuwa B",  sim: 0.78 },
    { key: "gps",         label: "GPS",         A: "2.49423, 34.65103",B: "2.49481, 34.65118", sim: 0.96, mono: true },
    { key: "hh_size",     label: "Household size",A: "6",              B: "6",             sim: 1.00 },
    { key: "roster_n",    label: "Roster members",A: "6 members",      B: "7 members",     sim: 0.85, note: "B has additional dependant — review" },
    { key: "roof",        label: "Roof material",A: "Iron sheets",     B: "Iron sheets",   sim: 1.00 },
    { key: "pmt_band",    label: "PMT band",    A: "Poorest 40%",      B: "Poorest 40%",   sim: 1.00 },
    { key: "captured_at", label: "Captured at", A: "14 May 2026",      B: "9 Apr 2026",    sim: null, fixed: "A", note: "Most recent capture wins (rule MERGE-LATEST)" },
  ],
};

const REASON_OPTS_REJECT = [
  "Not the same household (different addresses, members)",
  "Cross-household relatives (siblings/cousins) — not duplicate",
  "Insufficient evidence to merge",
  "Other (specify in note)",
];

const DedupScreen = () => {
  const initial = {};
  PAIR.fields.forEach(f => { initial[f.key] = f.fixed || (f.sim === 1 ? "A" : f.list ? "Both" : ""); });
  const [choice, setChoice] = useStateDup(initial);
  const [note, setNote] = useStateDup("");
  const [confirm, setConfirm] = useStateDup(false);
  const [rejectOpen, setRejectOpen] = useStateDup(false);
  const [toast, setToast] = useStateDup("");

  const allChosen = PAIR.fields.every(f => f.fixed || choice[f.key]);
  const noteOk = note.trim().length >= 6;

  const set = (k, v) => setChoice({ ...choice, [k]: v });

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow="DUPLICATES · US-083"
        title={<>Dedup compare <span className="t-mono" style={{fontSize:14, marginLeft:8, color:'var(--neutral-500)'}}>{PAIR.id}</span></>}
        sub="Decide which record survives. Per-field similarity is shown to the right of each value."
        right={<>
          <button className="btn"><Icon name="history" size={14}/> Pair history</button>
          <button className="btn"><Icon name="moreH" size={14}/></button>
        </>}
      />

      {/* Pair metadata strip */}
      <div className="card" style={{padding:'14px 20px', marginBottom:16, display:'flex', alignItems:'center', gap:24, flexWrap:'wrap'}}>
        <div>
          <div className="t-cap">COMPOSITE SCORE</div>
          <div className="row gap-2"><Chip tone="danger">{PAIR.score.toFixed(2)}</Chip><span className="t-bodysm muted">strong</span></div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">MODEL</div>
          <div className="t-bodysm t-mono" style={{color:'var(--neutral-900)'}}>{PAIR.model}</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">QUEUE</div>
          <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>{PAIR.queue}</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">RAISED</div>
          <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>14 May 2026 · 08:11 EAT</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">STATUS</div>
          <div className="row gap-2 mt-1"><Chip>{PAIR.status}</Chip></div>
        </div>
        <div style={{flex:1}}/>
        <button className="btn btn-danger" onClick={() => setRejectOpen(true)}><Icon name="xCircle" size={14}/> Reject pair</button>
        <button className="btn"><Icon name="clock" size={14}/> Hold</button>
        <button className="btn"><Icon name="save" size={14}/> Save draft</button>
      </div>

      {/* Three-column header + table */}
      <div className="card">
        <div style={{display:'grid', gridTemplateColumns:'180px 1fr 1fr 220px 1fr', borderBottom:'1px solid var(--neutral-200)', background:'var(--neutral-50)'}}>
          <div style={{padding:'12px 16px'}} className="t-cap">FIELD</div>
          <div style={{padding:'12px 16px', borderLeft:'3px solid var(--accent-data)'}}>
            <div className="t-cap" style={{color:'var(--accent-data)'}}>CANDIDATE A</div>
            <div className="t-bodysm" style={{fontWeight:600}}>Lokol Naume · 01HXY7K3…</div>
          </div>
          <div style={{padding:'12px 16px', borderLeft:'3px solid var(--accent-update)'}}>
            <div className="t-cap" style={{color:'var(--accent-update)'}}>CANDIDATE B</div>
            <div className="t-bodysm" style={{fontWeight:600}}>Lokol Naumi · 01HZ9NK2…</div>
          </div>
          <div style={{padding:'12px 16px'}}>
            <div className="t-cap">PICK</div>
            <div className="t-bodysm">A / B / Both</div>
          </div>
          <div style={{padding:'12px 16px', borderLeft:'3px solid var(--accent-danger)'}}>
            <div className="t-cap" style={{color:'var(--accent-danger)'}}>MERGE RESULT</div>
            <div className="t-bodysm" style={{fontWeight:600}}>Surviving record</div>
          </div>
        </div>

        {PAIR.fields.map((f) => (
          <DedupRow key={f.key} field={f} value={choice[f.key]} onChange={(v) => set(f.key, v)}/>
        ))}
      </div>

      {/* Add note */}
      <div className="card mt-4" style={{padding:16}}>
        <div className="t-cap" style={{marginBottom:6}}>OPERATOR NOTE <span style={{color:'var(--accent-danger)'}}>*</span></div>
        <textarea className="field-textarea" rows={3} placeholder="Describe the basis for the merge decision. Will be written to audit chain (min 6 chars)."
          value={note} onChange={(e) => setNote(e.target.value)}/>
        <div className="row mt-2" style={{justifyContent:'space-between'}}>
          <span className="t-cap">{note.length} chars · min 6</span>
          <span className="t-cap"><Icon name="shield" size={11}/> Note is permanent and visible to DPO audits.</span>
        </div>
      </div>

      {/* Action bar */}
      <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
        <ActionBar left={<>{PAIR.fields.filter(f => f.fixed || choice[f.key]).length} of {PAIR.fields.length} fields chosen{!noteOk && " · note required"}</>}>
          <button className="btn">Reject pair</button>
          <button className="btn">Hold for evidence</button>
          <button className="btn btn-primary" disabled={!allChosen || !noteOk} onClick={() => setConfirm(true)}>
            <Icon name="check" size={14}/> Commit merge
          </button>
        </ActionBar>
      </div>

      {/* Commit modal */}
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Commit merge?" width={560}
        footer={<>
          <button className="btn" onClick={() => setConfirm(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => { setConfirm(false); setToast("Merged into 01HXY7K3B2N9PVQE4M6FZRWS18. Loser 01HZ9NK2P5M3QFB7… archived. PMT recompute queued."); }}>
            <Icon name="check" size={14}/> Confirm commit
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>You are about to merge two records. This action is reversible only via an NSR Unit Coordinator override (AC-DDUP-REVERSE).</p>
          <div style={{display:'grid', gridTemplateColumns:'120px 1fr', rowGap:6, columnGap:12, fontSize:13}}>
            <div className="muted">Surviving ID</div><div className="t-mono">01HXY7K3B2N9PVQE4M6FZRWS18</div>
            <div className="muted">Archived ID</div><div className="t-mono">01HZ9NK2P5M3QFB7K6FZRWS22</div>
            <div className="muted">Fields from A</div><div>{PAIR.fields.filter(f => (f.fixed || choice[f.key]) === 'A').length}</div>
            <div className="muted">Fields from B</div><div>{PAIR.fields.filter(f => (f.fixed || choice[f.key]) === 'B').length}</div>
            <div className="muted">Combined (list)</div><div>{PAIR.fields.filter(f => (f.fixed || choice[f.key]) === 'Both').length}</div>
          </div>
          <div className="tint-update" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
            <div className="row gap-2"><Icon name="info" size={14} color="var(--accent-update)"/><strong className="t-bodysm">Downstream effects</strong></div>
            <ul className="t-bodysm" style={{margin:'6px 0 0', paddingLeft:20, color:'var(--neutral-700)'}}>
              <li>PMT score will be recomputed on surviving household.</li>
              <li>Programme enrolments transfer from archived → surviving.</li>
              <li>Citizens linked to archived ID will receive SMS notification.</li>
            </ul>
          </div>
        </div>
      </Modal>

      <ReasonModal open={rejectOpen} title="Reject this pair" intent="danger"
        reasonOptions={REASON_OPTS_REJECT} recordLabel={PAIR.id}
        onClose={() => setRejectOpen(false)} onConfirm={() => { setRejectOpen(false); setToast("Pair rejected. Records remain separate."); }}/>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

const DedupRow = ({ field, value, onChange }) => {
  const f = field;
  const pickable = !f.fixed && f.sim !== 1.00;
  const effective = f.fixed || value || "";
  let result = "";
  if (effective === 'A') result = f.A;
  else if (effective === 'B') result = f.B;
  else if (effective === 'Both') result = `${f.A}; ${f.B}`;
  else result = "—";

  const diffTone = (s) => {
    if (s === null || s === undefined) return null;
    if (s === 1) return 'data';
    if (s >= 0.8) return 'quality';
    return 'danger';
  };
  const tone = diffTone(f.sim);

  return (
    <div style={{display:'grid', gridTemplateColumns:'180px 1fr 1fr 220px 1fr', borderBottom:'1px solid var(--neutral-200)', alignItems:'stretch'}}>
      <div style={{padding:'12px 16px', display:'flex', flexDirection:'column', justifyContent:'center', borderRight:'1px solid var(--neutral-200)'}}>
        <div style={{fontWeight:500, fontSize:13}}>{f.label}</div>
        {f.sim !== null && f.sim !== undefined && <div className="row gap-2 mt-1"><Chip size="sm" tone={tone}>{f.sim.toFixed(2)}</Chip></div>}
        {f.note && <div className="t-cap" style={{marginTop:4, fontStyle:'italic'}}>{f.note}</div>}
      </div>
      <div style={{padding:'12px 16px', borderRight:'1px solid var(--neutral-200)', background: effective === 'A' || effective === 'Both' ? 'var(--accent-data-bg)' : 'transparent', display:'flex', alignItems:'center'}}>
        <span className={f.mono ? 't-mono' : ''} style={{fontSize: f.mono ? 12.5 : 13.5}}>{f.A}</span>
      </div>
      <div style={{padding:'12px 16px', borderRight:'1px solid var(--neutral-200)', background: effective === 'B' || effective === 'Both' ? 'var(--accent-update-bg)' : 'transparent', display:'flex', alignItems:'center'}}>
        <span className={f.mono ? 't-mono' : ''} style={{fontSize: f.mono ? 12.5 : 13.5}}>{f.B}</span>
      </div>
      <div style={{padding:'12px 16px', borderRight:'1px solid var(--neutral-200)', display:'flex', alignItems:'center'}}>
        {f.fixed ? (
          <span className="t-bodysm muted"><Icon name="lock" size={11}/> Fixed: {f.fixed} <span style={{marginLeft:4}}>(rule)</span></span>
        ) : (
          // Native radio group — arrow keys move within the row for free;
          // aria-disabled flags the Both option when the field is non-list.
          <fieldset className="radio-group" aria-label={`Choose value for ${f.label}`}>
            <legend>Choose value for {f.label}</legend>
            {['A', 'B', 'Both'].map(opt => {
              const disabled = opt === 'Both' && !f.list;
              const inputId = `pick-${f.label.replace(/\s+/g, '-')}-${opt}`;
              return (
                <React.Fragment key={opt}>
                  <input
                    type="radio"
                    id={inputId}
                    name={`pick-${f.label}`}
                    value={opt}
                    checked={value === opt}
                    onChange={() => !disabled && onChange(opt)}
                    disabled={disabled}
                  />
                  <label
                    htmlFor={inputId}
                    aria-disabled={disabled || undefined}
                    title={disabled ? "Disabled — only list-like fields support Both" : ""}
                  >{opt}</label>
                </React.Fragment>
              );
            })}
          </fieldset>
        )}
      </div>
      <div style={{padding:'12px 16px', background:'var(--accent-danger-bg)', borderLeft:'3px solid var(--accent-danger)', display:'flex', alignItems:'center'}}>
        <span className={f.mono ? 't-mono' : ''} style={{fontSize: f.mono ? 12.5 : 13.5, color: effective ? 'var(--neutral-900)' : 'var(--neutral-500)'}}>{result}</span>
      </div>
    </div>
  );
};

Object.assign(window, { DedupScreen });
