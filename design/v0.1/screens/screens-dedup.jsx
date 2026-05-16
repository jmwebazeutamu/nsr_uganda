/* global React, Icon, Chip, PageHeader, Modal, ReasonModal, ActionBar, Toast */
// NSR MIS — 11.5 Dedup Operator side-by-side compare
// US-S13-003: live wiring. On mount, fetch the first pending
// MatchPair from /api/v1/ddup/match-pairs/?status=pending; resolve
// both members via /api/v1/data-management/members/{id}/; build the
// activePair.fields list from the live members; render the same
// side-by-side compare. The actual merge service isn't exposed
// over REST today — merge / reject buttons toast with a hint to
// use the Django admin or wait for the celery auto-merge tick.

const { useState: useStateDup, useEffect: useEffectDup } = React;


const _fetchJson = (url) => fetch(url, {
  credentials: "same-origin",
  headers: { Accept: "application/json" },
}).then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`));


// Build the .fields list the screen renders from a MatchPair +
// two Member rows. per_field_scores from the pair is keyed by
// canonical field name (surname, first_name, dob, etc.) and gives
// the matcher's per-field similarity in [0, 1].
const _buildLivePair = (pair, mA, mB) => {
  const score = (k) => {
    const v = (pair.per_field_scores || {})[k];
    return v == null ? null : Number(v);
  };
  const fields = [
    { key: "registry_id", label: "Registry ID",
      A: mA.household || "—", B: mB.household || "—",
      sim: null, mono: true, fixed: null },
    { key: "head_name", label: "Name",
      A: `${mA.surname || ""} ${mA.first_name || ""}`.trim() || "—",
      B: `${mB.surname || ""} ${mB.first_name || ""}`.trim() || "—",
      sim: score("surname") ?? score("first_name") },
    { key: "head_nin", label: "NIN (last 4)",
      A: mA.nin_last4 ? `…${mA.nin_last4}` : "—",
      B: mB.nin_last4 ? `…${mB.nin_last4}` : "—",
      sim: score("nin") ?? (mA.nin_last4 && mA.nin_last4 === mB.nin_last4 ? 1 : null),
      mono: true },
    { key: "dob", label: "Date of birth",
      A: mA.date_of_birth || "—", B: mB.date_of_birth || "—",
      sim: score("dob_year") },
    { key: "sex", label: "Sex",
      A: mA.sex || "—", B: mB.sex || "—",
      sim: mA.sex && mA.sex === mB.sex ? 1.0 : 0 },
    { key: "phone", label: "Phone",
      A: mA.telephone_1 || "—", B: mB.telephone_1 || "—",
      sim: score("phone"), mono: true, list: true,
      note: "Different operators — keep both" },
  ];
  return {
    id: pair.id,
    score: Number(pair.composite_score ?? 0),
    model: `tier ${pair.tier} · ${pair.match_reason}`,
    queue: Number(pair.composite_score ?? 0) >= 0.9 ? "Strong (≥ 0.90)" : "Weak (< 0.90)",
    status: (pair.status || "pending").charAt(0).toUpperCase() + (pair.status || "pending").slice(1),
    fields,
    _live: true,
    _memberA: mA,
    _memberB: mB,
  };
};

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
  // US-S13-003: live pair fetched from API. Falls back to PAIR
  // mock when no pending pair exists or the fetch fails.
  const [livePair, setLivePair] = useStateDup(null);
  const [loadNote, setLoadNote] = useStateDup("");
  useEffectDup(() => {
    let cancelled = false;
    _fetchJson("/api/v1/ddup/match-pairs/?status=pending&page_size=1")
      .then(data => {
        const pairs = data.results || data;
        if (!pairs.length) {
          if (!cancelled) setLoadNote("queue empty");
          return null;
        }
        const pair = pairs[0];
        return Promise.all([
          _fetchJson(`/api/v1/data-management/members/${pair.record_a_id}/`),
          _fetchJson(`/api/v1/data-management/members/${pair.record_b_id}/`),
        ]).then(([mA, mB]) => {
          if (cancelled) return;
          setLivePair(_buildLivePair(pair, mA, mB));
        });
      })
      .catch(e => !cancelled && setLoadNote(`fetch failed: ${e}`));
    return () => { cancelled = true; };
  }, []);

  const activePair = livePair || PAIR;

  const initial = {};
  activePair.fields.forEach(f => {
    initial[f.key] = f.fixed || (f.sim === 1 ? "A" : f.list ? "Both" : "");
  });
  const [choice, setChoice] = useStateDup(initial);
  // Re-initialise choices when a different live pair arrives so
  // the action bar's "X of N chosen" reflects the new field list.
  useEffectDup(() => {
    const next = {};
    activePair.fields.forEach(f => {
      next[f.key] = f.fixed || (f.sim === 1 ? "A" : f.list ? "Both" : "");
    });
    setChoice(next);
  }, [activePair.id]);

  const [note, setNote] = useStateDup("");
  const [confirm, setConfirm] = useStateDup(false);
  const [rejectOpen, setRejectOpen] = useStateDup(false);
  const [toast, setToast] = useStateDup("");

  const allChosen = activePair.fields.every(f => f.fixed || choice[f.key]);
  const noteOk = note.trim().length >= 6;

  const set = (k, v) => setChoice({ ...choice, [k]: v });

  // US-S14-001 — wire Merge + Reject to /api/v1/ddup/match-pairs/{id}/.
  // Only fires in live mode (we have a real pair id from the API).
  // Picks the survivor by counting how many fields the operator
  // chose from A vs B; ties → A wins (matches the redesign default).
  const _getCsrfToken = () => {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  };
  const _post = (url, body) => fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": _getCsrfToken(),
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  const _refreshNext = () => {
    setLivePair(null);
    _fetchJson("/api/v1/ddup/match-pairs/?status=pending&page_size=1")
      .then(data => {
        const pairs = data.results || data;
        if (!pairs.length) return;
        const pair = pairs[0];
        return Promise.all([
          _fetchJson(`/api/v1/data-management/members/${pair.record_a_id}/`),
          _fetchJson(`/api/v1/data-management/members/${pair.record_b_id}/`),
        ]).then(([mA, mB]) => setLivePair(_buildLivePair(pair, mA, mB)));
      })
      .catch(() => {});
  };
  const commitMerge = () => {
    setConfirm(false);
    if (!livePair) {
      setToast("Merged into 01HXY7K3B2N9PVQE4M6FZRWS18. Loser 01HZ9NK2… archived.");
      return;
    }
    const aCount = activePair.fields.filter(f => (f.fixed || choice[f.key]) === "A").length;
    const bCount = activePair.fields.filter(f => (f.fixed || choice[f.key]) === "B").length;
    const survivor = bCount > aCount ? livePair._memberB : livePair._memberA;
    // Map chosen A/B values onto field names the service accepts.
    const FIELD_KEYS = { head_name: ["surname", "first_name"], phone: ["telephone_1"] };
    const chosen = {};
    activePair.fields.forEach(f => {
      const side = f.fixed || choice[f.key];
      if (side !== "A" && side !== "B") return;
      const value = side === "A" ? f.A : f.B;
      const targets = FIELD_KEYS[f.key] || [f.key];
      targets.forEach(t => { chosen[t] = value; });
    });
    _post(`/api/v1/ddup/match-pairs/${activePair.id}/merge/`, {
      surviving_id: survivor.id,
      chosen_field_values: chosen,
      actor: "admin",
      note,
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(() => {
        setToast(`Merge committed · survivor ${survivor.id.slice(0, 12)}…`);
        _refreshNext();
      })
      .catch(e => setToast(`Merge failed: ${e.message}`));
  };
  const commitReject = ({ reason, note: rNote } = {}) => {
    setRejectOpen(false);
    if (!livePair) {
      setToast("Pair rejected. Records remain separate.");
      return;
    }
    _post(`/api/v1/ddup/match-pairs/${activePair.id}/reject/`, {
      actor: "admin",
      reason: reason || rNote || "rejected via DDUP screen",
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(() => {
        setToast(`Pair rejected · ${activePair.id.slice(0, 12)}…`);
        _refreshNext();
      })
      .catch(e => setToast(`Reject failed: ${e.message}`));
  };

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow={livePair ? "DUPLICATES · US-083 · LIVE" : (loadNote ? `DUPLICATES · US-083 · ${loadNote}` : "DUPLICATES · US-083")}
        title={<>Dedup compare <span className="t-mono" style={{fontSize:14, marginLeft:8, color:'var(--neutral-500)'}}>{activePair.id}</span></>}
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
          <div className="row gap-2"><Chip tone="danger">{activePair.score.toFixed(2)}</Chip><span className="t-bodysm muted">strong</span></div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">MODEL</div>
          <div className="t-bodysm t-mono" style={{color:'var(--neutral-900)'}}>{activePair.model}</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">QUEUE</div>
          <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>{activePair.queue}</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">RAISED</div>
          <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>14 May 2026 · 08:11 EAT</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">STATUS</div>
          <div className="row gap-2 mt-1"><Chip>{activePair.status}</Chip></div>
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

        {activePair.fields.map((f) => (
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
        <ActionBar left={<>{activePair.fields.filter(f => f.fixed || choice[f.key]).length} of {activePair.fields.length} fields chosen{!noteOk && " · note required"}</>}>
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
          <button className="btn btn-primary" onClick={commitMerge}>
            <Icon name="check" size={14}/> Confirm commit
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>You are about to merge two records. This action is reversible by an NSR Unit Coordinator within the 30-day window below (AC-DDUP-REVERSE).</p>
          {(() => {
            // US-S15-001 — show concrete reverse-until date so the
            // operator sees the safety net before clicking Confirm.
            // 30-day window matches apps.ddup.services.merge_member_pair
            // (which writes reverse_window_until = now + 30 days).
            const until = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
            const fmt = until.toISOString().slice(0, 10);
            // Resolve surviving/archived IDs from live data when
            // available; fall back to the historical mock ULIDs so
            // the design preview still tells the visual story.
            const aCount = activePair.fields.filter(f => (f.fixed || choice[f.key]) === 'A').length;
            const bCount = activePair.fields.filter(f => (f.fixed || choice[f.key]) === 'B').length;
            const survivorId = livePair
              ? (bCount > aCount ? livePair._memberB.id : livePair._memberA.id)
              : "01HXY7K3B2N9PVQE4M6FZRWS18";
            const archivedId = livePair
              ? (bCount > aCount ? livePair._memberA.id : livePair._memberB.id)
              : "01HZ9NK2P5M3QFB7K6FZRWS22";
            return (
              <div style={{display:'grid', gridTemplateColumns:'140px 1fr', rowGap:6, columnGap:12, fontSize:13}}>
                <div className="muted">Surviving ID</div><div className="t-mono">{survivorId}</div>
                <div className="muted">Archived ID</div><div className="t-mono">{archivedId}</div>
                <div className="muted">Reversible until</div>
                <div>
                  <strong>{fmt}</strong>{" "}
                  <span className="muted">(30-day window · NSR Unit override required after)</span>
                </div>
                <div className="muted">Fields from A</div><div>{aCount}</div>
                <div className="muted">Fields from B</div><div>{bCount}</div>
                <div className="muted">Combined (list)</div><div>{activePair.fields.filter(f => (f.fixed || choice[f.key]) === 'Both').length}</div>
              </div>
            );
          })()}
          {/* US-S18-001 — per-field similarity in the confirm summary.
              Surfaces the matcher's evidence inside the modal so the
              operator doesn't have to scroll back to the compare table
              to remember WHY a merge was proposed. Skips fields with
              no similarity (registry_id, fixed-rule fields). */}
          {(() => {
            const tone = (s) => s >= 1 ? 'data' : s >= 0.8 ? 'quality' : 'danger';
            const rows = activePair.fields.filter(
              f => f.sim !== null && f.sim !== undefined,
            );
            if (!rows.length) return null;
            return (
              <div style={{border:'1px solid var(--neutral-200)', borderRadius:6, padding:10}}>
                <div className="t-cap" style={{marginBottom:6}}>SIMILARITY BY FIELD</div>
                <div style={{display:'grid', gridTemplateColumns:'1fr auto', rowGap:4, columnGap:12, fontSize:12.5}}>
                  {rows.map(f => (
                    <React.Fragment key={f.key}>
                      <div style={{color:'var(--neutral-700)'}}>{f.label}</div>
                      <div style={{textAlign:'right'}}>
                        <Chip size="sm" tone={tone(f.sim)}>{f.sim.toFixed(2)}</Chip>
                      </div>
                    </React.Fragment>
                  ))}
                </div>
              </div>
            );
          })()}
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
        reasonOptions={REASON_OPTS_REJECT} recordLabel={activePair.id}
        onClose={() => setRejectOpen(false)} onConfirm={commitReject}/>

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
