/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — Home (role-aware dashboard) + Kit page

const { useState: useStateHome } = React;

/* ============================================================
   ROLE config
   ============================================================ */
const ROLE_CONTENT = {
  "nsr-unit": {
    name: "NSR Unit Coordinator",
    person: "Akello Patience",
    org: "MGLSD · NSR Unit",
    kpis: [
      { title: "DIH review queue", value: "342", trend: "up", trendValue: "+38 today", foot: "vs. 7-day avg 287", spark: [180,210,250,235,280,310,342] },
      { title: "Fast-track auto-promote", value: "61.4", suffix: "%", trend: "up", trendValue: "+2.1pp wk", foot: "Target ≥ 60% (AC-DIH-AUTO)", spark: [54,55,58,57,60,59,61.4] },
      { title: "Bulk batches awaiting dual-approval", value: "4", trend: "flat", trendValue: "no change", foot: "1 batch > 10,000 (US-108)", spark: [4,3,4,5,4,4,4] },
      { title: "Partner DSAs expiring in 30d", value: "3", trend: "down", trendValue: "−1 since Monday", foot: "Renewal owner notified", spark: [6,5,5,5,4,4,3] },
    ],
    queues: [
      { title: "Pending DIH promotions", icon: "inbox", count: 342, items: [
        { id: "01HXY7K3B2N9PVQE4M6FZRWS18", who: "Lokol Naume · Nakiloro, Moroto", note: "Walk-in · No DDUP match · 0 warnings", chip: "Pending", age: "12m" },
        { id: "01HXZ9MR4N8P2QFB7K6FZRWS33", who: "Akello Grace · Pageya, Gulu", note: "Walk-in · DDUP 0.83 · 2 warnings", chip: "Pending", age: "47m" },
        { id: "01HXZBVK6QN8M2PFB7K6FZRWS41", who: "Onyango David · Logiri, Arua", note: "Bulk OPM-PDM · 0 warnings", chip: "Pending", age: "2h" },
        { id: "01HXZGN3W8MN6P2FB7K6FZRWS52", who: "Nakato Sarah · Kuluba, Yumbe", note: "Walk-in · NIRA mismatch · 1 blocking", chip: "Pending", age: "3h" },
      ]},
      { title: "Bulk batches awaiting dual-approval", icon: "duplicate", count: 4, items: [
        { id: "CR-2026-05-13-00112", who: "UBOS-NUSAF-2026-BULK", note: "11,402 records · awaits second approver", chip: "Pending Approval", age: "yesterday" },
        { id: "CR-2026-05-12-00031", who: "OPM-PDM-2026-Q2-BULK",  note: "8,213 records · awaits second approver",  chip: "Pending Approval", age: "2d" },
      ]},
    ],
  },
  "parish": {
    name: "Parish Chief",
    person: "Lokwang Peter",
    org: "Nakiloro Parish · Tapac · Moroto",
    kpis: [
      { title: "Captures today", value: "14", trend: "up", trendValue: "+3 vs. yesterday", foot: "8 in queue, 6 promoted", spark: [4,7,9,11,12,13,14] },
      { title: "Drafts about to expire", value: "2", trend: "flat", trendValue: "—", foot: "Both due in < 3 days", spark: [3,3,2,2,3,2,2] },
      { title: "GRM L1 cases (my parish)", value: "5", trend: "down", trendValue: "−1 this week", foot: "Avg L1 close 2.4 days", spark: [7,6,6,6,5,5,5] },
      { title: "Sync queue (CAPI)", value: "0", trend: "flat", trendValue: "all synced", foot: "Last sync 09:12 EAT", spark: [4,2,1,3,1,0,0] },
    ],
    queues: [
      { title: "Today's captures", icon: "users", count: 14, items: [
        { id: "01HXY7K3B2N9PVQE4M6FZRWS18", who: "Lokol Naume · HH size 6 · 14:35 EAT", note: "Submitted · 3 warnings, 0 blocking", chip: "Provisional", age: "8m" },
        { id: "01HXY7H1B0N7PVQE4M6FZRWS09", who: "Lochoro Mary · HH size 4 · 13:22 EAT", note: "Submitted · 0 warnings", chip: "Provisional", age: "1h" },
        { id: "01HXY6X9B0M6PVQE4M6FZRWS00", who: "Lopuwa John · HH size 7 · 11:58 EAT", note: "Promoted · Registry confirmed", chip: "Registered", age: "2h" },
      ]},
      { title: "Drafts about to expire", icon: "clock", count: 2, items: [
        { id: "DRAFT-2026-05-11-00012", who: "Nakong Anna · partial (4/7 sections)", note: "Expires in 2 days (Draft TTL = 14d)", chip: "Draft", age: "12d" },
      ]},
    ],
  },
  "cdo": {
    name: "Community Development Officer",
    person: "Adong Florence",
    org: "Tapac Sub-county · Moroto",
    kpis: [
      { title: "UPD review queue", value: "23", trend: "up", trendValue: "+5 today", foot: "9 PMT-relevant", spark: [12,14,15,18,20,22,23] },
      { title: "GRM L2 cases", value: "8", trend: "flat", trendValue: "—", foot: "2 awaiting citizen response", spark: [8,9,8,8,9,8,8] },
      { title: "Programme referrals", value: "16", trend: "up", trendValue: "+4 wk", foot: "OPM-PDM batch incoming", spark: [10,12,11,13,14,15,16] },
      { title: "Avg approval time (UPD)", value: "1.8", suffix: "d", trend: "down", trendValue: "−0.4d wk", foot: "SLA = 3 working days", spark: [2.6,2.4,2.2,2.0,1.9,1.8,1.8] },
    ],
    queues: [
      { title: "Pending UPD reviews", icon: "edit", count: 23, items: [
        { id: "UPD-2026-05-14-00237", who: "01HXY7K3… · pmt_relevant", note: "Roster: add member · evidence: photo, witness", chip: "Pending Approval", age: "3h" },
        { id: "UPD-2026-05-14-00231", who: "01HXZ9MR… · cosmetic", note: "Phone number update · evidence: USSD echo", chip: "Pending Approval", age: "6h" },
        { id: "UPD-2026-05-13-00188", who: "01HXZGN3… · pmt_relevant", note: "Housing: roof material change · evidence: photo", chip: "Pending Approval", age: "yesterday" },
      ]},
      { title: "GRM L2 cases", icon: "message", count: 8, items: [
        { id: "GRV-2026-05-14-00091", who: "Akello Grace · Pageya, Gulu", note: "Missed enrolment in OPM-PDM 2026 Q2", chip: "In progress", age: "2d" },
        { id: "GRV-2026-05-13-00088", who: "Nakato Sarah · Kuluba, Yumbe", note: "NIRA mismatch on head of household", chip: "Awaiting citizen response", age: "3d" },
      ]},
    ],
  },
  "dpo": {
    name: "Data Protection Officer",
    person: "Mukasa Robert",
    org: "MGLSD · DPO Office",
    kpis: [
      { title: "Anomaly alerts (US-103)", value: "3", trend: "up", trendValue: "+2 today", foot: "1 critical: 30d > DSA budget +18%", spark: [1,1,2,2,1,2,3] },
      { title: "Rows shipped 7d", value: "2.4", suffix: "M", trend: "up", trendValue: "+11% wk", foot: "Across 14 active requesters", spark: [1.8,1.9,2.1,2.0,2.2,2.3,2.4] },
      { title: "Erasure requests", value: "6", trend: "flat", trendValue: "—", foot: "2 awaiting controller review", spark: [4,5,5,6,5,6,6] },
      { title: "DPIA review tasks", value: "2", trend: "down", trendValue: "−1", foot: "Both due in next 7 days", spark: [4,3,3,3,3,2,2] },
    ],
    queues: [
      { title: "Active anomalies", icon: "alert", count: 3, items: [
        { id: "ANOM-2026-05-14-008", who: "MoH-Vital-Stats · CSV via DRS", note: "30-day volume 124% of DSA budget (US-103 AC-DPO-VOL)", chip: "Blocking", age: "47m" },
        { id: "ANOM-2026-05-14-005", who: "UBOS-NUSAF-2026-BULK · query reused 6x", note: "Identical query hash across 6 requesters", chip: "Warning", age: "3h" },
      ]},
    ],
  },
};

const ROLES = Object.keys(ROLE_CONTENT);

/* ============================================================
   Home dashboard
   ============================================================ */
const HomeScreen = ({ role, onNavigate }) => {
  const r = ROLE_CONTENT[role] || ROLE_CONTENT["nsr-unit"];
  return (
    <div className="page">
      <PageHeader
        eyebrow="HOME"
        title={<span>Good afternoon, <span style={{color:'var(--primary-900)'}}>{r.person.split(' ')[0]}</span></span>}
        sub={<>Signed in as {r.name}. Scope: {r.org}. Today is Thursday, 14 May 2026.</>}
        right={<>
          <button className="btn"><Icon name="download"/> Export brief</button>
          <button className="btn btn-primary"><Icon name="plus"/> New capture</button>
        </>}
      />

      <div className="grid grid-4">
        {r.kpis.map((k, i) => <KPI key={i} {...k}/>)}
      </div>

      <div className="grid grid-2 mt-5">
        {r.queues.map((q, i) => (
          <div className="card" key={i}>
            <div className="card-header">
              <div className="row gap-3">
                <div style={{width:32, height:32, borderRadius:6, background:'var(--primary-100)', color:'var(--primary-900)', display:'grid', placeItems:'center'}}>
                  <Icon name={q.icon} size={18}/>
                </div>
                <div>
                  <h3 className="t-h3" style={{margin:0}}>{q.title}</h3>
                  <div className="t-cap">{q.count} open</div>
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => onNavigate?.('dih')}>Open queue <Icon name="chevronRight" size={14}/></button>
            </div>
            <div>
              {q.items.map((item, j) => (
                <div key={j} className="row gap-3" style={{padding:'12px 20px', borderBottom: j < q.items.length - 1 ? '1px solid var(--neutral-200)' : 'none', cursor:'pointer'}}
                     onClick={() => onNavigate?.('dih')}>
                  <div style={{minWidth:0, flex:1}}>
                    <div className="t-mono" style={{color:'var(--neutral-700)', fontSize:12, marginBottom:2}}>{item.id}</div>
                    <div style={{fontWeight:500}}>{item.who}</div>
                    <div className="t-bodysm muted" style={{marginTop:2}}>{item.note}</div>
                  </div>
                  <div className="col" style={{alignItems:'flex-end', gap:6}}>
                    <Chip>{item.chip}</Chip>
                    <span className="t-cap">{item.age}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card mt-5">
        <div className="card-header">
          <h3 className="t-h3" style={{margin:0}}>Across the registry</h3>
          <span className="t-cap">Refreshed 14:35 EAT · poll 60s</span>
        </div>
        <div className="grid grid-4" style={{padding:20}}>
          <RegistryStat label="Total households (Registered)" value="9,847,221" sub="of 12.1M target (81.4%)"/>
          <RegistryStat label="Provisional, pending promotion" value="124,309" sub="walk-in 38k · bulk 86k"/>
          <RegistryStat label="Confirmed individuals" value="48,116,802" sub="avg HH size 4.89"/>
          <RegistryStat label="Connectors active (7d)" value="11 / 14" sub="2 paused · 1 quarantined"/>
        </div>
      </div>

      <div className="t-cap" style={{marginTop:24, textAlign:'center'}}>
        NSR MIS v0.1 · Solution Architecture Document v0.6 · ERD v0.6 · NITA-U Government Data Centre
      </div>
    </div>
  );
};

const RegistryStat = ({ label, value, sub }) => (
  <div style={{borderRight:'1px solid var(--neutral-200)', paddingRight:20}}>
    <div className="t-cap">{label}</div>
    <div className="t-num" style={{fontSize:22, fontWeight:700, margin:'2px 0', letterSpacing:'-0.01em'}}>{value}</div>
    <div className="t-cap" style={{color:'var(--neutral-700)'}}>{sub}</div>
  </div>
);

/* ============================================================
   Kit page — design system reference
   ============================================================ */
const KitScreen = () => {
  const allStatuses = [
    ["Registry ID", ["Provisional","Pending","Registered","Rejected","Voided"]],
    ["Submission / Change Request", ["Draft","Submitted","Pending QA","Accepted","Pending Approval","Approved","Rejected","Committed","Reversed"]],
    ["Dedup pair", ["Pending","Merged","Rejected","On hold","Cross-household"]],
    ["Connector run", ["Queued","Running","Completed","Failed","Cancelled"]],
    ["DRS request", ["Draft","Submitted","Pending DPO review","Approved","Generating","Delivered","Expired","Rejected","Revoked"]],
    ["Grievance", ["Open","In progress","Awaiting citizen response","Resolved","Closed"]],
    ["DQA severity", ["Blocking","Warning","Info"]],
    ["Sensitivity (DRS)", ["Public","Internal","Personal","Sensitive"]],
  ];
  const moduleAccents = [
    ["primary",      "Primary",       "var(--primary-900)",   "Nav, primary CTA"],
    ["data",         "DAT — Data",    "var(--accent-data)",   "Captures, success"],
    ["quality",      "DQA — Quality", "var(--accent-quality)","Warnings"],
    ["danger",       "DDUP — Danger", "var(--accent-danger)", "Errors, blocking"],
    ["identity",     "IDV — Identity","var(--accent-identity)","NIRA, member detail"],
    ["update",       "UPD — Update",  "var(--accent-update)", "Update workflow"],
    ["eligibility",  "PMT — Eligibility","var(--accent-eligibility)","PMT scoring"],
    ["programme",    "REF — Programme","var(--accent-programme)","Programmes"],
    ["grm",          "GRM — Grievance","var(--accent-grm)",    "Cases"],
    ["reference",    "REF-DATA",      "var(--accent-reference)","Reference data"],
    ["system",       "API / SEC / RPT","var(--accent-system)", "System"],
  ];

  return (
    <div className="page">
      <PageHeader
        eyebrow="DESIGN SYSTEM"
        title="NSR MIS visual kit"
        sub="Tokens per Section 4. Components per Section 5. Status vocabulary per Section 8 of the brief."
        right={<button className="btn"><Icon name="download"/> Export tokens.css</button>}
      />

      {/* Module accents */}
      <div className="card">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Module accent palette</h3><span className="t-cap">11 module tints — one per SAD module</span></div>
        <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:16}}>
          {moduleAccents.map(([k, label, color, usage]) => (
            <div key={k} className={`tint-${k === 'primary' ? 'data' : k}`} style={{border:'1px solid var(--neutral-300)', borderRadius:8, padding:14, background: k === 'primary' ? 'var(--primary-100)' : undefined}}>
              <div style={{height:48, borderRadius:4, background: color, marginBottom:10}}/>
              <div style={{fontWeight:600, fontSize:13.5}}>{label}</div>
              <div className="t-cap">{usage}</div>
              <div className="t-mono t-cap" style={{marginTop:4}}>--accent-{k}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Status chips */}
      <div className="card mt-5">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Status vocabulary</h3><span className="t-cap">Section 8 — use these labels verbatim</span></div>
        <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:24}}>
          {allStatuses.map(([family, items]) => (
            <div key={family}>
              <div className="t-cap" style={{marginBottom:8, color:'var(--neutral-700)', fontWeight:600}}>{family}</div>
              <div className="row-wrap">
                {items.map(s => <Chip key={s}>{s}</Chip>)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Typography */}
      <div className="card mt-5">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Type scale</h3><span className="t-cap">Inter — operator web; Roboto — CAPI Android; Calibri — exports</span></div>
        <div style={{padding:20}}>
          <div style={{display:'grid', gridTemplateColumns:'120px 1fr 1fr', columnGap:24, rowGap:14, alignItems:'baseline'}}>
            <div className="t-cap">Display 32/40</div><div className="t-display">National Social Registry</div><div className="t-cap t-mono">700 / -0.02em</div>
            <div className="t-cap">H1 24/32</div><div className="t-h1">DIH review queue · 342 pending</div><div className="t-cap t-mono">700 / -0.01em</div>
            <div className="t-cap">H2 20/28</div><div className="t-h2">Karamoja sub-region · Moroto district</div><div className="t-cap t-mono">600</div>
            <div className="t-cap">H3 16/24</div><div className="t-h3">Roster section — 6 members</div><div className="t-cap t-mono">600</div>
            <div className="t-cap">Body 14/20</div><div className="t-body">Lokol Naume's household at Nakiloro Parish was captured by Parish Chief Lokwang Peter on 14 May 2026 at 14:35 EAT.</div><div className="t-cap t-mono">400</div>
            <div className="t-cap">Body sm 13/18</div><div className="t-bodysm">Helper text appears below form inputs. Errors are red and reference the rule.</div><div className="t-cap t-mono">400</div>
            <div className="t-cap">Caption 12/16</div><div className="t-cap" style={{color:'var(--neutral-900)'}}>Audit ID #A-2026-05-14-00471 · written to chain</div><div className="t-cap t-mono">400</div>
            <div className="t-cap">Mono 13/18</div><div className="t-mono">01HXY7K3B2N9PVQE4M6FZRWS18</div><div className="t-cap t-mono">JetBrains Mono</div>
          </div>
        </div>
      </div>

      {/* Buttons + actions */}
      <div className="grid grid-2 mt-5">
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Buttons</h3></div>
          <div style={{padding:20, display:'flex', flexWrap:'wrap', gap:12}}>
            <button className="btn btn-primary"><Icon name="check"/> Promote</button>
            <button className="btn btn-success"><Icon name="checkCircle"/> Approve</button>
            <button className="btn btn-danger"><Icon name="xCircle"/> Reject</button>
            <button className="btn btn-warn"><Icon name="clock"/> Hold</button>
            <button className="btn">Cancel</button>
            <button className="btn btn-ghost"><Icon name="moreH"/></button>
            <button className="btn btn-primary" disabled>Disabled</button>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>KPI card</h3></div>
          <div style={{padding:20}}>
            <KPI title="DIH review queue" value="342" trend="up" trendValue="+38 today" foot="vs. 7-day avg 287" spark={[180,210,250,235,280,310,342]}/>
          </div>
        </div>
      </div>

      {/* Form controls */}
      <div className="card mt-5">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Form controls</h3></div>
        <div style={{padding:20}}>
          <div className="field-row-3">
            <Field label="Respondent name" required>
              <input className="field-input" defaultValue="Lokol Naume"/>
            </Field>
            <Field label="Phone (E.164)" required hint="Format: +256 XXX XXXXXX">
              <input className="field-input" defaultValue="+256 786 234567"/>
            </Field>
            <Field label="Household size" required error="Must be at least 1 (AC-CAP-HHSIZE)">
              <input className="field-input" defaultValue="0"/>
            </Field>
          </div>
          <div className="field-row mt-4">
            <Field label="Consent statement" required>
              <div className="seg">
                <button className="on">Yes — consented</button>
                <button>No</button>
              </div>
            </Field>
            <Field label="Urban / Rural" required>
              <div className="seg">
                <button>Urban</button>
                <button className="on">Rural</button>
              </div>
            </Field>
          </div>
        </div>
      </div>

      {/* Spacing & elevation */}
      <div className="grid grid-2 mt-5">
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Spacing scale (4-point)</h3></div>
          <div style={{padding:20}}>
            {[1,2,3,4,5,6,7,8,9,10].map(n => (
              <div key={n} className="row" style={{gap:16, marginBottom:6}}>
                <div className="t-cap t-mono" style={{width:64}}>--space-{n}</div>
                <div className="t-cap" style={{width:42}}>{[4,8,12,16,20,24,32,40,48,64][n-1]}px</div>
                <div style={{height:8, background:'var(--primary-700)', width: [4,8,12,16,20,24,32,40,48,64][n-1]}}/>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Shape & elevation</h3></div>
          <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:16}}>
            <div className="card center" style={{height:120, border:'1px solid var(--neutral-300)', boxShadow:'none'}}>radius 4</div>
            <div className="card center" style={{height:120}}>radius 8 + lvl 1</div>
            <div className="center" style={{height:120, borderRadius:2, background:'var(--neutral-100)', border:'1px solid var(--neutral-300)'}}>radius 2 (tag)</div>
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { HomeScreen, KitScreen, ROLES, ROLE_CONTENT });
