/* global React, Icon, Chip, KPI, PageHeader, AuditDrawer, ActionBar, ReasonModal, Modal */
// NSR MIS — 11.3 NSR Unit DIH review queue

const { useState: useStateDIH, useMemo: useMemoDIH } = React;

const DIH_ROWS = [
  { id: "01HXY7K3B2N9PVQE4M6FZRWS18", head: "Lokol Naume",      hh: 6, region: "Karamoja",    parish: "Nakiloro · Moroto", source: "Walk-in", channel: "CAPI", ddup: null, dqa: { b: 0, w: 3, i: 1 }, idv: "Matched", ageH: "47m", sla: "ok",     status: "Pending" },
  { id: "01HXZ9MR4N8P2QFB7K6FZRWS33", head: "Akello Grace",     hh: 5, region: "Acholi",      parish: "Pageya · Gulu",     source: "Walk-in", channel: "CAPI", ddup: 0.83, dqa: { b: 0, w: 2, i: 0 }, idv: "Matched", ageH: "1h 12m", sla: "warn", status: "Pending" },
  { id: "01HXZBVK6QN8M2PFB7K6FZRWS41", head: "Onyango David",   hh: 7, region: "West Nile",   parish: "Logiri · Arua",     source: "Bulk",    channel: "OPM-PDM", ddup: null, dqa: { b: 0, w: 0, i: 2 }, idv: "Matched", ageH: "2h 04m", sla: "ok",  status: "Pending" },
  { id: "01HXZGN3W8MN6P2FB7K6FZRWS52", head: "Nakato Sarah",    hh: 4, region: "West Nile",   parish: "Kuluba · Yumbe",    source: "Walk-in", channel: "CAPI", ddup: 0.91, dqa: { b: 1, w: 0, i: 0 }, idv: "Mismatch","ageH": "3h 18m", sla: "ok", status: "Pending" },
  { id: "01HY02FNQ9P8MN6FB7K6FZRWS67", head: "Mugisha James",   hh: 6, region: "Karamoja",    parish: "Lorengedwat · Napak", source: "Walk-in", channel: "CAPI", ddup: 0.95, dqa: { b: 0, w: 1, i: 0 }, idv: "Matched", ageH: "5h 41m", sla: "ok",     status: "Pending" },
  { id: "01HY04MQR0N8P2FB7K6FZRWS73", head: "Auma Beatrice",    hh: 8, region: "Karamoja",    parish: "Apeitolim · Napak", source: "Walk-in", channel: "CAPI", ddup: null, dqa: { b: 0, w: 0, i: 0 }, idv: "Matched", ageH: "9h 22m", sla: "ok",     status: "Pending" },
  { id: "01HY09KRS1P9MN6FB7K6FZRWS84", head: "Lopuwa John",     hh: 7, region: "Karamoja",    parish: "Kakingol · Moroto", source: "Walk-in", channel: "CAPI", ddup: 0.86, dqa: { b: 0, w: 2, i: 1 }, idv: "Matched", ageH: "18h 15m", sla: "crit", status: "Pending" },
  { id: "01HY0AMNT8P2N6FB7K6FZRWS92", head: "Acheng Rose",      hh: 3, region: "Acholi",      parish: "Aywee · Gulu",      source: "Walk-in", channel: "CAPI", ddup: null, dqa: { b: 0, w: 0, i: 0 }, idv: "Matched", ageH: "21h 03m", sla: "crit", status: "Pending" },
];

const QUICK_FILTERS = [
  { id: "sla24", label: "Walk-in 24h SLA at risk", icon: "clock", tone: "quality", count: 14 },
  { id: "ddup", label: "Has DDUP match ≥ 0.90", icon: "duplicate", tone: "danger", count: 6 },
  { id: "bulk", label: "Bulk awaiting batch approval", icon: "inbox", tone: "update", count: 4 },
];

const DIHScreen = () => {
  const [selectedRow, setSelectedRow] = useStateDIH(DIH_ROWS[1].id);
  const [auditOpen, setAuditOpen] = useStateDIH(false);
  const [modal, setModal] = useStateDIH(null); // 'promote' | 'merge' | 'hold' | 'reject'
  const [toast, setToast] = useStateDIH("");
  const [selection, setSelection] = useStateDIH(new Set());
  const [quickFilter, setQuickFilter] = useStateDIH(null);

  const current = useMemoDIH(() => DIH_ROWS.find(r => r.id === selectedRow), [selectedRow]);

  const auditEvents = [
    { who: "System DIH", action: "received from", detail: "Capture channel CAPI · tablet PCH-7411 · Parish Office Pageya", time: "1h 12m ago", audit: "A-2026-05-14-00471", tone: "system" },
    { who: "System DQA", action: "evaluated", detail: "Ruleset DQA-v3.4 · 2 warnings raised · 0 blocking", time: "1h 11m ago", audit: "A-2026-05-14-00472", tone: "system" },
    { who: "System IDV", action: "matched to NIRA", detail: "NIN CM89241023ABCD · confidence 0.97 (AC-IDV-MATCH)", time: "1h 11m ago", audit: "A-2026-05-14-00473", tone: "system" },
    { who: "System DDUP", action: "found candidate", detail: "Match 01HXP2KR3N8M2QF · composite 0.83 · weak queue", time: "1h 10m ago", audit: "A-2026-05-14-00474", tone: "system" },
    { who: "Akello Patience", action: "opened for review", detail: "NSR Unit Coordinator · viewed three-column compare", time: "12m ago", audit: "A-2026-05-14-00501", tone: "user" },
  ];

  const reasonsReject = [
    "Duplicate of existing registered household",
    "Failed IDV — NIRA mismatch (AC-IDV-MATCH)",
    "Blocking DQA failure not resolved",
    "Consent statement missing or refused",
    "Geographic data outside operator scope",
    "Other (specify in note)",
  ];
  const reasonsHold = [
    "Awaiting NIRA reconciliation",
    "Awaiting parish-side evidence (photo, witness)",
    "Awaiting GRM case resolution",
    "Other (specify in note)",
  ];
  const reasonsPromote = [
    "All DQA warnings reviewed and accepted",
    "IDV matched, no DDUP candidate above threshold",
    "Manual override (specify in note)",
  ];

  const fire = (kind) => {
    const map = { promote: "Promoted to Registered. Same Registry ID retained.", merge: "Promote-as-merge committed. PMT recompute queued.", hold: "Held for more info. Citizen notified by SMS.", reject: "Rejected. Provisional ID voided. Reason written to audit chain." };
    setToast(map[kind] || "Done.");
    setModal(null);
  };

  const toggleSel = (id) => {
    const next = new Set(selection);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection(next);
  };

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow="DIH REVIEW QUEUE · US-109"
        title={<>NSR Unit DIH review queue <Chip>342 pending</Chip></>}
        sub="Promote, promote-as-merge, hold, or reject. Walk-in SLA = 24 hours from capture."
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn"><Icon name="download"/> Export CSV</button>
        </>}
      />

      {/* Filter bar */}
      <div className="card" style={{padding:'14px 20px', marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:'wrap'}}>
          <div className="row gap-2">
            <span className="t-cap" style={{fontWeight:600}}>QUICK FILTERS</span>
          </div>
          {QUICK_FILTERS.map(f => (
            <button key={f.id} onClick={() => setQuickFilter(quickFilter === f.id ? null : f.id)}
              style={{
                display:'inline-flex', alignItems:'center', gap:6,
                padding:'6px 10px', borderRadius:16, fontSize:12.5, fontWeight:500,
                border: `1px solid ${quickFilter === f.id ? `var(--accent-${f.tone})` : 'var(--neutral-300)'}`,
                background: quickFilter === f.id ? `var(--accent-${f.tone}-bg)` : 'var(--neutral-0)',
                color: quickFilter === f.id ? `var(--accent-${f.tone})` : 'var(--neutral-700)',
                cursor:'pointer',
              }}>
              <Icon name={f.icon} size={13}/>{f.label}
              <span style={{padding:'1px 6px', borderRadius:10, background:'var(--neutral-100)', color:'var(--neutral-700)', fontSize:11}}>{f.count}</span>
            </button>
          ))}

          <div style={{width:1, height:24, background:'var(--neutral-300)', margin:'0 6px'}}/>

          {[
            ["Source", ["Walk-in","Bulk","API"]],
            ["Sub-region", ["Karamoja","West Nile","Acholi","Teso"]],
            ["Channel", ["CAPI","OPM-PDM","NUSAF","UBOS"]],
            ["DQA", ["Any","No flags","Warnings only","Blocking"]],
            ["IDV", ["Any","Matched","Mismatch","Pending"]],
          ].map(([label, opts]) => (
            <select key={label} className="field-select" style={{height:30, width:'auto', minWidth:130, fontSize:13}}>
              <option>{label}</option>
              {opts.map(o => <option key={o}>{o}</option>)}
            </select>
          ))}

          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost"><Icon name="filter" size={14}/> Reset</button>
        </div>
      </div>

      {/* Queue table */}
      <div className="card" style={{marginBottom:16}}>
        <div className="card-toolbar">
          <div className="row gap-3">
            <span className="t-bodysm" style={{fontWeight:600}}>Staged records</span>
            <span className="t-cap">8 of 342 shown · sort by SLA risk</span>
          </div>
          <div style={{flex:1}}/>
          <button className="btn btn-sm" disabled={selection.size === 0}>
            <Icon name="check" size={14}/> Bulk approve ({selection.size})
          </button>
          <button className="btn btn-sm btn-ghost"><Icon name="sliders" size={14}/> Density</button>
        </div>
        <div style={{maxHeight:280, overflowY:'auto'}}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{width:36}}></th>
                <th>Provisional ID</th>
                <th>Head · Parish</th>
                <th>Source</th>
                <th>DQA</th>
                <th>IDV</th>
                <th>DDUP</th>
                <th>Age</th>
                <th>SLA</th>
                <th className="col-actions">Status</th>
              </tr>
            </thead>
            <tbody>
              {DIH_ROWS.map(r => (
                <tr key={r.id} className={r.id === selectedRow ? "selected" : ""} onClick={() => setSelectedRow(r.id)} style={{cursor:'pointer'}}>
                  <td onClick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>
                    <input type="checkbox" checked={selection.has(r.id)} readOnly disabled={r.dqa.b > 0 || r.ddup !== null}/>
                  </td>
                  <td className="col-id">{r.id.slice(0,18)}…</td>
                  <td>
                    <div style={{fontWeight:500}}>{r.head}</div>
                    <div className="t-cap">HH {r.hh} · {r.parish}</div>
                  </td>
                  <td>
                    <div>{r.source}</div>
                    <div className="t-cap">{r.channel}</div>
                  </td>
                  <td>
                    <div className="row gap-2">
                      {r.dqa.b > 0 && <Chip size="sm" tone="danger">B {r.dqa.b}</Chip>}
                      {r.dqa.w > 0 && <Chip size="sm" tone="quality">W {r.dqa.w}</Chip>}
                      {r.dqa.i > 0 && <Chip size="sm" tone="system">I {r.dqa.i}</Chip>}
                      {!r.dqa.b && !r.dqa.w && !r.dqa.i && <span className="muted t-cap">clean</span>}
                    </div>
                  </td>
                  <td>
                    {r.idv === "Matched" ? <Chip size="sm" tone="identity"><Icon name="check" size={11}/> Matched</Chip>
                    : r.idv === "Mismatch" ? <Chip size="sm" tone="danger">Mismatch</Chip>
                    : <Chip size="sm" tone="quality">Pending</Chip>}
                  </td>
                  <td>
                    {r.ddup === null
                      ? <span className="muted t-cap">no match</span>
                      : <Chip size="sm" tone={r.ddup >= 0.9 ? "danger" : "quality"}>{r.ddup.toFixed(2)}</Chip>}
                  </td>
                  <td className="t-cap">{r.ageH}</td>
                  <td>
                    {r.sla === 'crit' ? <Chip size="sm" tone="danger"><Icon name="alert" size={11}/> 24h</Chip>
                    : r.sla === 'warn' ? <Chip size="sm" tone="quality">at risk</Chip>
                    : <Chip size="sm" tone="data">ok</Chip>}
                  </td>
                  <td className="col-actions"><Chip size="sm">{r.status}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Three-column compare */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 360px', gap:16}}>
        {/* Column 1: Staged */}
        <div className="card" style={{borderTop:'3px solid var(--accent-data)'}}>
          <div className="card-header" style={{padding:'14px 20px'}}>
            <div>
              <div className="t-cap" style={{color:'var(--accent-data)'}}><Icon name="database" size={11}/> STAGED RECORD</div>
              <h3 className="t-h3" style={{margin:'2px 0 0'}}>{current.head}</h3>
              <div className="t-cap">{current.parish} · HH {current.hh} · Captured 14:35 EAT today</div>
            </div>
            <Chip>{current.status}</Chip>
          </div>
          <div style={{padding:16}}>
            <RecordSummary
              fields={[
                ["Provisional ID", current.id, "mono"],
                ["Head NIN", "CM89241023ABCD", "mono"],
                ["Phone", "+256 781 552119"],
                ["Parish", "Pageya · Bobi · Gulu"],
                ["GPS", "2.79103, 32.29841 · 8m", "mono"],
                ["Members", "5 (head + spouse + 3 dependants)"],
                ["PMT band", <Chip tone="eligibility">Poorest 40%</Chip>],
                ["Roof material", "Iron sheets"],
                ["Source", "Walk-in CAPI · Lokwang Peter (PCH-7411)"],
              ]}
            />
            <SectionAccordion title="Roster (5 members)" tint="identity" defaultOpen>
              <RosterTable members={[
                { name: "Akello Grace",     rel: "Head",    sex: "F", age: 34, nin: "CM89241023ABCD" },
                { name: "Okello Charles",   rel: "Spouse",  sex: "M", age: 38, nin: "CM89110218EFGH" },
                { name: "Akello Joy",       rel: "Daughter",sex: "F", age: 12, nin: "—" },
                { name: "Okello Brian",     rel: "Son",     sex: "M", age: 9,  nin: "—" },
                { name: "Akello Mercy",     rel: "Daughter",sex: "F", age: 4,  nin: "—" },
              ]}/>
            </SectionAccordion>
            <SectionAccordion title="Health & Disability" tint="danger">
              <SimpleKV rows={[["Members with disability","0"],["Chronic conditions","none reported"],["Pregnant / lactating","1 (head)"]]}/>
            </SectionAccordion>
            <SectionAccordion title="Education" tint="update">
              <SimpleKV rows={[["School-age children","3 of 3 enrolled"],["Adult literacy","head literate"]]}/>
            </SectionAccordion>
            <SectionAccordion title="Housing & Assets" tint="eligibility">
              <SimpleKV rows={[["Roof","Iron sheets"],["Walls","Brick (burnt)"],["Floor","Cement"],["Toilet","Pit latrine (covered)"],["Water source","Borehole, < 1 km"]]}/>
            </SectionAccordion>
          </div>
        </div>

        {/* Column 2: Registry match candidate */}
        <div className="card" style={{borderTop:'3px solid var(--accent-danger)'}}>
          <div className="card-header" style={{padding:'14px 20px'}}>
            <div>
              <div className="t-cap" style={{color:'var(--accent-danger)'}}><Icon name="duplicate" size={11}/> DDUP CANDIDATE · COMPOSITE 0.83</div>
              <h3 className="t-h3" style={{margin:'2px 0 0'}}>Akello Grace <span className="t-cap" style={{marginLeft:8}}>weak queue</span></h3>
              <div className="t-cap">01HXP2KR3N8M2QF · Registered 8 Nov 2025 · same parish</div>
            </div>
            <Chip tone="danger">0.83</Chip>
          </div>
          <div style={{padding:16}}>
            <CompareTable
              left={[
                ["Provisional ID", "01HXZ9MR…RWS33", null, "mono"],
                ["Head name", "Akello Grace", 1.00, null],
                ["NIN", "CM89241023ABCD", 1.00, "mono"],
                ["Phone", "+256 781 552119", 0.45, "mono"],
                ["DoB", "12 Mar 1991", 1.00, null],
                ["Parish", "Pageya · Bobi · Gulu", 1.00, null],
                ["GPS distance", "—", null, null],
                ["HH size", "5", 0.80, null],
                ["PMT band", "Poorest 40%", 1.00, null],
              ]}
              right={[
                ["Registry ID", "01HXP2KR3N8M2QF", null, "mono"],
                ["Head name", "Akello Grace", null, null],
                ["NIN", "CM89241023ABCD", null, "mono"],
                ["Phone", "+256 700 110492", null, "mono"],
                ["DoB", "12 Mar 1991", null, null],
                ["Parish", "Pageya · Bobi · Gulu", null, null],
                ["GPS distance", "2.4 km", null, null],
                ["HH size", "4 → 5 (added in 2025)", null, null],
                ["PMT band", "Poorest 40%", null, null],
              ]}
            />
          </div>
        </div>

        {/* Column 3: Decision panel */}
        <div className="col gap-3">
          <div className="card" style={{borderTop:'3px solid var(--primary-900)'}}>
            <div className="card-header" style={{padding:'14px 16px'}}>
              <h3 className="t-h3" style={{margin:0}}>Decision panel</h3>
            </div>
            <div style={{padding:16}}>
              {/* DQA */}
              <div>
                <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DQA OUTCOMES</div>
                <div className="row-wrap" style={{marginBottom:8}}>
                  <Chip tone="quality">2 warnings</Chip>
                  <Chip tone="system">0 info</Chip>
                  <Chip tone="data">0 blocking</Chip>
                </div>
                <div className="t-bodysm muted">AC-DQA-PHONE-LENGTH, AC-DQA-AGE-HEAD raised. Acknowledge to clear.</div>
              </div>

              <div className="divider"/>

              {/* IDV */}
              <div>
                <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>IDV (NIRA)</div>
                <Chip tone="identity"><Icon name="check" size={11}/> Matched · 0.97</Chip>
                <div className="t-bodysm muted mt-2">NIN CM89241023ABCD reconciled · sex/age aligned · AC-IDV-MATCH passed.</div>
              </div>

              <div className="divider"/>

              {/* DDUP */}
              <div>
                <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DDUP CANDIDATES</div>
                <div className="row gap-2" style={{padding:'8px 10px', background:'var(--accent-danger-bg)', borderRadius:4, border:'1px solid rgba(169,50,38,0.15)', marginBottom:6}}>
                  <Chip size="sm" tone="danger">0.83</Chip>
                  <div className="flex-1">
                    <div className="t-bodysm" style={{fontWeight:500}}>01HXP2KR3N8M2QF · Akello Grace</div>
                    <div className="t-cap">phone differs · HH size +1</div>
                  </div>
                </div>
                <div className="t-bodysm muted">Below 0.90 — consider <strong>Promote-as-merge</strong> only after manual review.</div>
              </div>

              <div className="divider"/>

              {/* Walk-in SLA */}
              <div className="row gap-2" style={{padding:'10px 12px', background:'var(--accent-quality-bg)', borderRadius:4, borderLeft:'3px solid var(--accent-quality)'}}>
                <Icon name="clock" size={16} color="var(--accent-quality)"/>
                <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>
                  <strong>SLA at risk:</strong> 22h 48m until walk-in cutoff (24h from capture).
                </div>
              </div>
            </div>
          </div>

          <div className="card" style={{padding:16, borderLeft:'3px solid var(--accent-update)'}}>
            <div className="row gap-2" style={{marginBottom:6}}>
              <Icon name="info" size={14} color="var(--accent-update)"/>
              <strong className="t-bodysm">Keyboard shortcut</strong>
            </div>
            <div className="t-bodysm muted">
              <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>⌘</kbd> + <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>↵</kbd> approve · <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>⌘</kbd> + <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>⌫</kbd> reject
            </div>
          </div>
        </div>
      </div>

      {/* Sticky action bar */}
      <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
        <ActionBar left={<>Reviewing <span className="t-mono" style={{color:'var(--neutral-900)'}}>{current.id.slice(0,18)}…</span> · {current.head} · 1 of 342</>}>
          <button className="btn btn-danger" onClick={() => setModal('reject')}><Icon name="xCircle" size={14}/> Reject</button>
          <button className="btn btn-warn" onClick={() => setModal('hold')}><Icon name="clock" size={14}/> Hold for info</button>
          <button className="btn" onClick={() => setModal('merge')}><Icon name="duplicate" size={14}/> Promote-as-merge</button>
          <button className="btn btn-success" onClick={() => setModal('promote')}><Icon name="check" size={14}/> Promote</button>
        </ActionBar>
      </div>

      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} events={auditEvents} title={`Audit · ${current.head}`}/>

      <ReasonModal open={modal === 'promote'} title="Promote to Registered" intent="success"
        reasonOptions={reasonsPromote} recordLabel={current.id}
        onClose={() => setModal(null)} onConfirm={() => fire('promote')}/>
      <ReasonModal open={modal === 'merge'} title="Promote as merge" intent="primary"
        reasonOptions={["Accept DDUP candidate as same household","Both records are same household — keep this one","Other (specify in note)"]}
        recordLabel={current.id}
        onClose={() => setModal(null)} onConfirm={() => fire('merge')}/>
      <ReasonModal open={modal === 'hold'} title="Hold for more information" intent="primary"
        reasonOptions={reasonsHold} recordLabel={current.id}
        onClose={() => setModal(null)} onConfirm={() => fire('hold')}/>
      <ReasonModal open={modal === 'reject'} title="Reject submission" intent="danger"
        reasonOptions={reasonsReject} recordLabel={current.id}
        onClose={() => setModal(null)} onConfirm={() => fire('reject')}/>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

const RecordSummary = ({ fields }) => (
  <div style={{display:'grid', gridTemplateColumns:'120px 1fr', rowGap:8, columnGap:12}}>
    {fields.map(([k, v, m], i) => (
      <React.Fragment key={i}>
        <div className="t-cap" style={{color:'var(--neutral-500)'}}>{k}</div>
        <div className={m === 'mono' ? 't-mono' : 't-bodysm'} style={{fontSize: m === 'mono' ? 12.5 : 13}}>{v}</div>
      </React.Fragment>
    ))}
  </div>
);

const SectionAccordion = ({ title, tint = "data", defaultOpen = false, children }) => {
  const [open, setOpen] = useStateDIH(defaultOpen);
  return (
    <div style={{marginTop:12, border:'1px solid var(--neutral-200)', borderRadius:4, borderLeft: `3px solid var(--accent-${tint})`, overflow:'hidden'}}>
      <button onClick={() => setOpen(!open)} style={{width:'100%', display:'flex', alignItems:'center', gap:8, padding:'10px 12px', border:0, background:'var(--neutral-50)', cursor:'pointer', textAlign:'left'}}>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14}/>
        <strong className="t-bodysm">{title}</strong>
      </button>
      {open && <div style={{padding:12, background:'var(--neutral-0)'}}>{children}</div>}
    </div>
  );
};

const SimpleKV = ({ rows }) => (
  <div style={{display:'grid', gridTemplateColumns:'140px 1fr', rowGap:6, columnGap:12, fontSize:13}}>
    {rows.map(([k, v], i) => (<React.Fragment key={i}><div className="muted">{k}</div><div>{v}</div></React.Fragment>))}
  </div>
);

const RosterTable = ({ members }) => (
  <table className="tbl" style={{fontSize:12.5}}>
    <thead><tr><th>Name</th><th>Rel</th><th>Sex</th><th>Age</th><th>NIN</th></tr></thead>
    <tbody>{members.map((m, i) => (
      <tr key={i}><td>{m.name}</td><td className="muted">{m.rel}</td><td className="muted">{m.sex}</td><td className="t-num">{m.age}</td><td className="col-id">{m.nin}</td></tr>
    ))}</tbody>
  </table>
);

const CompareTable = ({ left, right }) => (
  <div style={{display:'grid', gridTemplateColumns:'100px 1fr 1fr', rowGap:8, columnGap:10, fontSize:13}}>
    <div className="t-cap" style={{color:'var(--neutral-500)'}}>Field</div>
    <div className="t-cap" style={{color:'var(--accent-data)'}}>Staged</div>
    <div className="t-cap" style={{color:'var(--accent-danger)'}}>Registry candidate</div>
    {left.map((row, i) => {
      const [field, val, sim, mono] = row;
      const [, rval] = right[i];
      const diff = sim !== null && sim !== undefined && sim < 1;
      return (
        <React.Fragment key={i}>
          <div className="muted" style={{paddingTop:4}}>{field}</div>
          <div className={mono === 'mono' ? 't-mono' : ''} style={{padding:'4px 8px', borderRadius:3, background: diff ? 'var(--accent-danger-bg)' : 'transparent', borderLeft: diff ? '2px solid var(--accent-danger)' : '2px solid transparent', fontSize: mono === 'mono' ? 12 : 13}}>
            {val}
            {sim !== null && sim !== undefined && <span className="t-cap" style={{marginLeft:6, color: diff ? 'var(--accent-danger)' : 'var(--accent-data)'}}>{sim.toFixed(2)}</span>}
          </div>
          <div className={mono === 'mono' ? 't-mono' : ''} style={{padding:'4px 8px', borderRadius:3, background: diff ? 'var(--accent-danger-bg)' : 'transparent', borderLeft: diff ? '2px solid var(--accent-danger)' : '2px solid transparent', fontSize: mono === 'mono' ? 12 : 13}}>{rval}</div>
        </React.Fragment>
      );
    })}
  </div>
);

Object.assign(window, { DIHScreen });
