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

// PAIR mock removed — Dedup compare is now fully backend-driven.
// All pair data comes from /api/v1/ddup/match-pairs/ (+ resolved
// Member detail). Empty queue → renders the empty state; failure →
// renders an error banner.

const REASON_OPTS_REJECT = [
  "Not the same household (different addresses, members)",
  "Cross-household relatives (siblings/cousins) — not duplicate",
  "Insufficient evidence to merge",
  "Other (specify in note)",
];

const DedupScreen = () => {
  // Backend-driven queue view. The screen now keeps the FULL pending
  // list at the top and renders the adjudication panel for the
  // selected pair below. Click a row → adjudication switches.
  //
  // State machine for `pendingList`:
  //   null  → first load in flight; show loading card
  //   false → fetch errored; show error card
  //   []    → fetch succeeded but queue is empty; show empty card
  //   [...] → at least one pending pair; render list + adjudication
  //
  // `membersById` is the cross-pair member cache so we don't refetch
  // the same registry Member when two pairs reference it.
  const [pendingList, setPendingList] = useStateDup(null);
  const [membersById, setMembersById] = useStateDup({});
  const [selectedPairId, setSelectedPairId] = useStateDup(null);
  const [livePair, setLivePair] = useStateDup(null);
  const [loadNote, setLoadNote] = useStateDup("loading…");

  // Bulk-fetch helper: resolve every unique Member id referenced by
  // the list of pairs in parallel. Caches into membersById so the
  // adjudication panel's selection swap is instant.
  const _resolveMembers = (pairs, existing) => {
    const need = new Set();
    pairs.forEach(p => {
      if (p.record_a_id && !existing[p.record_a_id]) need.add(p.record_a_id);
      if (p.record_b_id && !existing[p.record_b_id]) need.add(p.record_b_id);
    });
    if (need.size === 0) return Promise.resolve(existing);
    return Promise.all(
      Array.from(need).map(id =>
        _fetchJson(`/api/v1/data-management/members/${id}/`)
          .then(m => [id, m])
          .catch(() => [id, null]),
      ),
    ).then(entries => {
      const next = { ...existing };
      for (const [id, m] of entries) { if (m) next[id] = m; }
      return next;
    });
  };

  // Load the queue list + every referenced member in one shot, then
  // auto-select the first pending pair. Triggered once on mount and
  // again by _refreshList after a Merge/Reject/Discard.
  const _loadQueue = (preferredId = null) => {
    setLoadNote("loading…");
    return _fetchJson(
      `/api/v1/ddup/match-pairs/?status=pending&page_size=50&_ts=${Date.now()}`,
    )
      .then(data => {
        const pairs = data.results || data;
        if (!pairs.length) {
          setPendingList([]);
          setSelectedPairId(null);
          setLivePair(false);
          setLoadNote("queue empty");
          return;
        }
        return _resolveMembers(pairs, membersById).then(nextMembers => {
          setMembersById(nextMembers);
          setPendingList(pairs);
          // Preserve a deliberate selection across refreshes when the
          // user pinned a specific pair (e.g. they were in the middle
          // of adjudicating); otherwise jump to the head of the queue.
          const target = preferredId && pairs.some(p => p.id === preferredId)
            ? preferredId : pairs[0].id;
          setSelectedPairId(target);
          setLoadNote("");
        });
      })
      .catch(e => {
        setPendingList(false);
        setLivePair(false);
        setLoadNote(`fetch failed: ${e}`);
      });
  };

  useEffectDup(() => { _loadQueue(); /* mount only */ }, []);

  // Derive livePair from the current selection. The members are
  // already in the cache from _loadQueue, so this is a pure compose
  // step — no fetch on selection change.
  useEffectDup(() => {
    if (!selectedPairId || !Array.isArray(pendingList)) return;
    const pair = pendingList.find(p => p.id === selectedPairId);
    if (!pair) { setLivePair(false); return; }
    const mA = membersById[pair.record_a_id];
    const mB = membersById[pair.record_b_id];
    if (mA && mB) setLivePair(_buildLivePair(pair, mA, mB));
  }, [selectedPairId, pendingList, membersById]);

  // Stable empty-shape so downstream choice-init / field-reduce calls
  // don't crash before livePair arrives or when the queue is empty.
  const EMPTY_PAIR = { id: "", score: 0, model: "", queue: "", status: "", fields: [] };
  const activePair = livePair || EMPTY_PAIR;

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
  // "Discard duplicate" modal — keeps one record intact, soft-deletes
  // the other. Different from Merge (no field combining) and Reject
  // (which marks the pair as not-a-duplicate, leaving both registered).
  const [discardOpen, setDiscardOpen] = useStateDup(false);
  const [discardSide, setDiscardSide] = useStateDup("A");
  const [discardReason, setDiscardReason] = useStateDup("");
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
  // Optimistic queue update after a Merge/Reject/Discard succeeds:
  // drop the acted-on pair, advance selection to the next pending
  // pair (or flip to empty if the queue is drained). Then reconcile
  // with the server so concurrent edits in another tab don't leave
  // stale rows on screen.
  const _refreshNext = () => {
    setLivePair(null);
    const actedId = selectedPairId;
    if (Array.isArray(pendingList) && actedId) {
      const remaining = pendingList.filter(p => p.id !== actedId);
      setPendingList(remaining);
      if (remaining.length === 0) {
        setSelectedPairId(null);
        setLivePair(false);
        setLoadNote("queue empty");
      } else {
        // Pick the pair that took the acted-on row's slot in the
        // list (or fall back to the head if we were on the tail).
        const idx = pendingList.findIndex(p => p.id === actedId);
        const next = remaining[Math.min(idx, remaining.length - 1)];
        setSelectedPairId(next.id);
      }
    }
    // Reconcile against the server. Pass the next-selected id so the
    // refresh keeps the operator on that row instead of jumping to
    // the queue head.
    _loadQueue(
      Array.isArray(pendingList) && actedId
        ? (pendingList.filter(p => p.id !== actedId)[0] || {}).id
        : null,
    );
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
  const commitDiscard = () => {
    setDiscardOpen(false);
    if (!livePair) {
      const kept = discardSide === "A" ? "A" : "B";
      setToast(`Discarded duplicate · kept candidate ${kept}. (preview — not persisted)`);
      return;
    }
    const survivor = discardSide === "A" ? livePair._memberA : livePair._memberB;
    _post(`/api/v1/ddup/match-pairs/${activePair.id}/discard/`, {
      surviving_id: survivor.id,
      actor: "admin",
      reason: discardReason || "discarded via DDUP screen",
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(() => {
        setToast(`Duplicate discarded · kept ${survivor.id.slice(0, 12)}…`);
        setDiscardReason("");
        _refreshNext();
      })
      .catch(e => setToast(`Discard failed: ${e.message}`));
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

  // ── Loading + empty / error gates ────────────────────────────────
  // The queue surface (PendingPairsTable) is the source of truth now.
  // While pendingList is still loading we render a single card; once
  // it resolves to [] or `false` we render the empty / error card.
  if (pendingList === null) {
    return (
      <div className="page" style={{paddingBottom:0}}>
        <PageHeader
          eyebrow="DUPLICATES · US-083"
          title="Dedup compare"
          sub="Loading pending pairs from the registry…"
        />
        <div className="card" style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
          <Icon name="clock" size={28} color="var(--neutral-300)"/>
          <div className="t-bodysm mt-2">Fetching /api/v1/ddup/match-pairs/?status=pending…</div>
        </div>
      </div>
    );
  }
  if (pendingList === false || (Array.isArray(pendingList) && pendingList.length === 0)) {
    const errored = loadNote && loadNote.startsWith("fetch failed");
    return (
      <div className="page" style={{paddingBottom:0}}>
        <PageHeader
          eyebrow="DUPLICATES · US-083"
          title="Dedup compare"
          sub={
            errored
              ? "The Dedup API call failed — log in via /admin/ and reload, or check the server logs."
              : "No pending pairs to review. Run NIN-pair discovery or promote new stage records that share a NIN with an existing member to populate the queue."
          }
          right={<>
            <button className="btn"
              onClick={() => { setPendingList(null); setLivePair(null); _loadQueue(); }}>
              <Icon name="play" size={14}/> Reload
            </button>
          </>}
        />
        <div className="card" style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
          <Icon name={errored ? "alert" : "inbox"} size={36} color={errored ? "var(--accent-danger)" : "var(--neutral-300)"}/>
          <div className="t-bodysm mt-2">
            {errored ? loadNote : "Queue is empty — backend-driven, no mock data."}
          </div>
          {!errored && (
            <div className="t-cap mt-2">
              To populate the queue: <code className="t-mono">python manage.py shell -c "from apps.ddup.services import discover_nin_pairs; print(len(discover_nin_pairs(actor='ops')))"</code>
            </div>
          )}
        </div>
        {toast && <Toast message={toast} onDone={() => setToast("")}/>}
      </div>
    );
  }

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow="DUPLICATES · US-083 · LIVE"
        title={<>Dedup compare <span className="t-bodysm muted" style={{marginLeft:10}}>{pendingList.length} pending</span></>}
        sub="Pick a pair from the queue to adjudicate. Decisions advance the queue automatically."
        right={<>
          <button className="btn" onClick={() => _loadQueue(selectedPairId)}>
            <Icon name="play" size={14}/> Refresh queue
          </button>
          <button className="btn"><Icon name="moreH" size={14}/></button>
        </>}
      />

      {/* ── Pending pairs queue (US-S15-001: queue + adjudication split) */}
      <div className="card" style={{padding:0, marginBottom:16}}>
        <div style={{padding:'10px 14px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:10}}>
          <strong className="t-bodysm">Pending pairs</strong>
          <span className="t-cap">{pendingList.length} row{pendingList.length === 1 ? '' : 's'} · click to adjudicate</span>
        </div>
        <div style={{maxHeight:260, overflowY:'auto'}}>
          <table className="tbl" style={{boxShadow:'none'}}>
            <thead>
              <tr>
                <th style={{width:36}}></th>
                <th>Pair</th>
                <th>Candidate A</th>
                <th>Candidate B</th>
                <th>Tier</th>
                <th>Reason</th>
                <th>Score</th>
                <th>Raised</th>
              </tr>
            </thead>
            <tbody>
              {pendingList.map(p => {
                const mA = membersById[p.record_a_id];
                const mB = membersById[p.record_b_id];
                const _name = (m) => m ? `${m.first_name || ''} ${m.surname || ''}`.trim() || '—' : '…';
                const _idShort = (id) => (id || '').slice(0, 12) + '…';
                const isSel = p.id === selectedPairId;
                // Friendly reason label. tier-1 NIN-exact matches are
                // deterministic so they don't carry a composite_score
                // in the DB — display the implicit "1.00 · exact"
                // instead of a dash. Tier-2+ pairs carry an actual
                // numeric composite_score; we show that with two
                // decimals. Anything else falls back to the raw
                // match_reason or "—".
                const reasonLabel = (
                  p.match_reason === 'nin'           ? 'NIN exact' :
                  p.match_reason === 'nin_last4'     ? 'NIN suffix' :
                  p.match_reason === 'name_phonetic' ? 'Name phonetic' :
                  p.match_reason === 'name_dob_geo'  ? 'Name + DOB + geo' :
                  (p.match_reason || '—')
                );
                const isDeterministicTier1 = (p.tier === 1);
                const scoreText = (
                  typeof p.composite_score === 'number'
                    ? p.composite_score.toFixed(2)
                    : isDeterministicTier1 ? '1.00' : '—'
                );
                const scoreTone = (
                  isDeterministicTier1 ? 'danger' :
                  typeof p.composite_score === 'number' && p.composite_score >= 0.90 ? 'danger' :
                  typeof p.composite_score === 'number' && p.composite_score >= 0.75 ? 'quality' :
                  'neutral'
                );
                const raised = (p.created_at || '').slice(0, 10) || '—';
                return (
                  <tr
                    key={p.id}
                    onClick={() => setSelectedPairId(p.id)}
                    style={{
                      cursor:'pointer',
                      background: isSel ? 'var(--primary-100, #eef3ff)' : undefined,
                    }}
                  >
                    <td>
                      {isSel && <Icon name="check" size={12} color="var(--primary-900)"/>}
                    </td>
                    <td className="t-mono t-bodysm">{_idShort(p.id)}</td>
                    <td>
                      <div className="t-bodysm">{_name(mA)}</div>
                      <div className="t-cap t-mono">{_idShort(p.record_a_id)}</div>
                    </td>
                    <td>
                      <div className="t-bodysm">{_name(mB)}</div>
                      <div className="t-cap t-mono">{_idShort(p.record_b_id)}</div>
                    </td>
                    <td><Chip size="sm">{`tier ${p.tier}`}</Chip></td>
                    <td className="t-bodysm">{reasonLabel}</td>
                    <td>
                      <Chip size="sm" tone={scoreTone}>{scoreText}</Chip>
                      {isDeterministicTier1 && (
                        <span className="t-cap" style={{marginLeft:6}}>exact</span>
                      )}
                    </td>
                    <td className="t-cap">{raised}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Adjudication panel (renders when a pair is selected and its
          members have resolved). Identical UI to before — only the
          source of `activePair` changed. */}
      {!livePair && (
        <div className="card" style={{padding:40, textAlign:'center', color:'var(--neutral-500)', marginBottom:16}}>
          <Icon name="duplicate" size={28} color="var(--neutral-300)"/>
          <div className="t-bodysm mt-2">
            Select a pair from the queue above to adjudicate.
          </div>
        </div>
      )}
      {livePair && <>
      <div className="t-cap" style={{marginBottom:8, display:'flex', alignItems:'center', gap:8}}>
        <Icon name="duplicate" size={12}/> Adjudicating
        <span className="t-mono" style={{color:'var(--neutral-900)'}}>{activePair.id}</span>
      </div>

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
          <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>2026-05-14</div>
        </div>
        <div style={{width:1, height:32, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">STATUS</div>
          <div className="row gap-2 mt-1"><Chip>{activePair.status}</Chip></div>
        </div>
        <div style={{flex:1}}/>
        <button className="btn btn-danger" onClick={() => setRejectOpen(true)}><Icon name="xCircle" size={14}/> Reject pair</button>
        <button className="btn" onClick={() => setDiscardOpen(true)}><Icon name="trash" size={14}/> Discard duplicate</button>
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

      {/* Discard-duplicate modal — same person, but one record is bad
          data (test entry, double-submission, garbled re-capture).
          No field combining — the surviving record stays exactly as
          captured. The discarded record is soft-deleted the same way
          a merge loser is, so the 30-day reverse window applies. */}
      <Modal open={discardOpen} onClose={() => setDiscardOpen(false)}
        title="Discard one record, keep the other" width={560}
        footer={<>
          <button className="btn" onClick={() => setDiscardOpen(false)}>Cancel</button>
          <button className="btn btn-danger"
            disabled={discardReason.trim().length < 6}
            onClick={commitDiscard}>
            <Icon name="trash" size={14}/> Confirm discard
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>
            Use this when both records ARE the same person but one is
            bad data (test entry, double-tap submission, garbled
            re-capture). The kept record stays untouched — no field
            values are copied. Reversible by an NSR Unit Coordinator
            within the same 30-day window as a merge.
          </p>
          <div>
            <div className="t-cap" style={{marginBottom:6}}>KEEP WHICH RECORD?</div>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
              {(() => {
                const aId = livePair ? livePair._memberA.id : "01HXY7K3B2N9PVQE4M6FZRWS18";
                const bId = livePair ? livePair._memberB.id : "01HZ9NK2P5M3QFB7K6FZRWS22";
                const opt = (side, label, id, tone) => {
                  const sel = discardSide === side;
                  return (
                    <button key={side} type="button" onClick={() => setDiscardSide(side)}
                      style={{
                        textAlign:'left', padding:'10px 12px',
                        border: sel ? `2px solid var(--accent-${tone})` : '1px solid var(--neutral-300)',
                        borderRadius:6, background: sel ? `var(--accent-${tone}-bg)` : 'white',
                        cursor:'pointer',
                      }}>
                      <div className="t-cap" style={{color:`var(--accent-${tone})`}}>{label}</div>
                      <div className="t-mono" style={{fontSize:12, marginTop:2}}>{id}</div>
                      <div className="t-bodysm muted" style={{marginTop:4}}>
                        {sel ? "Kept · stays in registry" : "Discard · soft-deleted"}
                      </div>
                    </button>
                  );
                };
                return [
                  opt("A", "CANDIDATE A", aId, "data"),
                  opt("B", "CANDIDATE B", bId, "update"),
                ];
              })()}
            </div>
          </div>
          <div>
            <div className="t-cap" style={{marginBottom:6}}>REASON <span style={{color:'var(--accent-danger)'}}>*</span></div>
            <textarea className="field-textarea" rows={3}
              placeholder="Why is the discarded record bad data? (min 6 chars · written to audit chain)"
              value={discardReason} onChange={(e) => setDiscardReason(e.target.value)}/>
            <div className="t-cap" style={{marginTop:4}}>{discardReason.length} chars · min 6</div>
          </div>
        </div>
      </Modal>
      </>}

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
