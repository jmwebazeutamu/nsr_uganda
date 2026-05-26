/* global React, Icon, Chip, PageHeader, Toast */
// NSR MIS — Admin console (US-S11-001).
//
// Tabbed surface that mirrors the Django admin work shipped in
// recent sprints. Rather than fork a separate UI per resource, this
// is a single AdminScreen with a tab strip. Two tabs are fully
// implemented today; the rest are stubs that link out to /admin/.
//
// First-class tabs:
// - DDUP model versions (S10-002) — feedback counters
//   (auto/manual × merge/reverse + auto_reverse_rate)
// - Connector runs (S10-005) — status with STUCK badge, duration,
//   bulk "mark stuck FAILED" action
//
// Stub tabs (link out):
// - UPD routing matrix (S4-003)
// - Partners & DSAs (S3-002, S4-001)
// - Operator scopes (S2-003, S4-001 PARTNER scope)

const { useState: useStateAdmin, useMemo: useMemoAdmin, useEffect: useEffectAdmin } = React;

// Mock data — mirrors the live serializer output from
// /api/v1/ddup/model-versions/ (S10-002) so the fetch wiring is
// a one-line swap.
const DDUP_MODEL_VERSIONS = [
  {
    id: "01DDUPMV2026010100001",
    version: 1, status: "active",
    description: "Tier-1 NIN deterministic, tier-3 surname+DOB blocking",
    author: "akello.p", approved_by: "mukasa.r",
    approved_at: "10 Jan 2026", effective_from: "15 Jan 2026",
    auto_merge_count: 142, manual_merge_count: 38,
    auto_reverse_count: 4, manual_reverse_count: 1,
    auto_reverse_rate: 0.0282,
  },
  {
    id: "01DDUPMV2025090100002",
    version: 0, status: "retired",
    description: "Initial pilot — tier-1 only, no probabilistic",
    author: "okello.j", approved_by: "mukasa.r",
    approved_at: "08 Sep 2025", effective_from: "15 Sep 2025",
    auto_merge_count: 0, manual_merge_count: 12,
    auto_reverse_count: 0, manual_reverse_count: 0,
    auto_reverse_rate: null,
  },
  {
    id: "01DDUPMV2026051400003",
    version: 2, status: "draft",
    description: "Tier-3 threshold lowered to 0.82 (pilot data)",
    author: "akello.p", approved_by: "",
    approved_at: "", effective_from: "",
    auto_merge_count: 0, manual_merge_count: 0,
    auto_reverse_count: 0, manual_reverse_count: 0,
    auto_reverse_rate: null,
  },
];

// Mock ConnectorRun rows — mirrors apps.ingestion_hub.admin
// list_display + status_badge from S10-005.
const CONNECTOR_RUNS = [
  { id: "01CR2026051400001", connector: "kobo-pilot",     status: "succeeded",   started_h: 0.8,  duration: "12m", landed: 47, staged: 47, promoted: 45, quarantined: 1, rejected: 1 },
  { id: "01CR2026051400002", connector: "pdm-mis-pull",   status: "running",     started_h: 1.2,  duration: "running 1.2h",  landed: 234, staged: 230, promoted: 218, quarantined: 8, rejected: 4 },
  { id: "01CR2026051400003", connector: "nusaf-mis-pull", status: "running",     started_h: 8.5,  duration: "running 8.5h",  landed: 511, staged: 481, promoted: 0,   quarantined: 0, rejected: 0 },
  { id: "01CR2026051300001", connector: "kobo-pilot",     status: "failed",      started_h: 26.0, duration: "2h 14m",  landed: 14, staged: 12, promoted: 9, quarantined: 2, rejected: 1 },
  { id: "01CR2026051200002", connector: "ubos-historic-load", status: "succeeded", started_h: 48.0, duration: "5h 02m",  landed: 12480, staged: 12480, promoted: 12451, quarantined: 21, rejected: 8 },
  { id: "01CR2026051400004", connector: "wfp-scope-pull", status: "quarantined", started_h: 3.2,  duration: "47m",  landed: 89, staged: 14, promoted: 12, quarantined: 75, rejected: 2 },
];

const STUCK_THRESHOLD_HOURS = 6;

// ── Status helpers ─────────────────────────────────────────────────────
const statusToneCR = {
  pending:     "neutral",
  running:     "update",
  succeeded:   "data",
  failed:      "danger",
  quarantined: "quality",
};

const isStuck = (r) =>
  r.status === "running" && r.started_h >= STUCK_THRESHOLD_HOURS;

// ── DDUP model-version tab ─────────────────────────────────────────────
const ModelVersionsTab = () => {
  const [selectedId, setSelectedId] = useStateAdmin(DDUP_MODEL_VERSIONS[0].id);
  const current = useMemoAdmin(
    () => DDUP_MODEL_VERSIONS.find(v => v.id === selectedId),
    [selectedId],
  );

  const summarise = (v) => {
    if (v.auto_reverse_rate === null) {
      return `${v.auto_merge_count} auto / ${v.manual_merge_count} manual`;
    }
    return `${v.auto_merge_count} auto (${(v.auto_reverse_rate * 100).toFixed(1)}% reversed) / ${v.manual_merge_count} manual`;
  };

  const rateChip = (v) => {
    if (v.auto_reverse_rate === null) return null;
    const rate = v.auto_reverse_rate;
    const tone = rate < 0.02 ? "data" : rate < 0.05 ? "quality" : "danger";
    return <Chip size="sm" tone={tone}>{(rate * 100).toFixed(1)}%</Chip>;
  };

  return (
    <div style={{display:"grid", gridTemplateColumns:"1fr 360px", gap:16}}>
      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">DDUP model versions</strong>
          <div style={{flex:1}}/>
          <span className="t-cap">
            Auto-merge feedback is the strongest signal for threshold tuning (US-S10-002)
          </span>
        </div>

        <div style={{display:"grid", gridTemplateColumns:"80px 100px 1fr 160px 80px",
                       borderBottom:"1px solid var(--neutral-200)", background:"var(--neutral-50)",
                       fontSize:11, fontWeight:600, letterSpacing:"0.06em",
                       textTransform:"uppercase", color:"var(--neutral-700)"}}>
          <div style={{padding:"10px 16px"}}>Version</div>
          <div style={{padding:"10px 8px"}}>Status</div>
          <div style={{padding:"10px 8px"}}>Merges</div>
          <div style={{padding:"10px 8px"}}>Author / Approver</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Rate</div>
        </div>

        {DDUP_MODEL_VERSIONS.map(v => {
          const active = selectedId === v.id;
          const statusTone = {
            active: "data", retired: "neutral",
            draft: "update", pending_approval: "quality",
          }[v.status] || "neutral";
          return (
            <div key={v.id}
                 onClick={() => setSelectedId(v.id)}
                 style={{display:"grid", gridTemplateColumns:"80px 100px 1fr 160px 80px",
                          borderBottom:"1px solid var(--neutral-200)",
                          background: active ? "var(--accent-data-bg)" : "white",
                          cursor:"pointer", alignItems:"center"}}>
              <div style={{padding:"12px 16px", fontFamily:"monospace", fontSize:14, fontWeight:600}}>
                v{v.version}
              </div>
              <div style={{padding:"12px 8px"}}>
                <Chip size="sm" tone={statusTone}>{v.status}</Chip>
              </div>
              <div style={{padding:"12px 8px", fontSize:13}}>
                {summarise(v)}
              </div>
              <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                {v.author}{v.approved_by && <> · approved {v.approved_by}</>}
              </div>
              <div style={{padding:"12px 8px", textAlign:"right"}}>
                {rateChip(v)}
              </div>
            </div>
          );
        })}
      </div>

      {/* Detail rail */}
      {current && (
        <div className="col gap-3">
          <div className="card" style={{borderTop:"3px solid var(--accent-data)"}}>
            <div className="card-header" style={{padding:"12px 16px"}}>
              <div>
                <div className="t-cap"><Icon name="duplicate" size={11}/> MODEL VERSION</div>
                <h3 className="t-h3" style={{margin:"2px 0 0", fontFamily:"monospace"}}>v{current.version}</h3>
              </div>
              <Chip tone={current.status === "active" ? "data" : "neutral"}>{current.status}</Chip>
            </div>
            <div style={{padding:16}}>
              <div className="t-bodysm muted" style={{marginBottom:12}}>
                {current.description}
              </div>

              <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>
                FEEDBACK (US-S10-002)
              </div>
              <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:8, marginBottom:12}}>
                <div style={{padding:10, background:"var(--neutral-50)", borderRadius:6}}>
                  <div className="t-cap" style={{color:"var(--neutral-700)"}}>AUTO MERGES</div>
                  <div style={{fontFamily:"monospace", fontSize:22, fontWeight:600}}>{current.auto_merge_count}</div>
                  <div className="t-cap muted" style={{marginTop:2}}>
                    {current.auto_reverse_count} reversed
                  </div>
                </div>
                <div style={{padding:10, background:"var(--neutral-50)", borderRadius:6}}>
                  <div className="t-cap" style={{color:"var(--neutral-700)"}}>MANUAL MERGES</div>
                  <div style={{fontFamily:"monospace", fontSize:22, fontWeight:600}}>{current.manual_merge_count}</div>
                  <div className="t-cap muted" style={{marginTop:2}}>
                    {current.manual_reverse_count} reversed
                  </div>
                </div>
              </div>

              <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>
                AUTO-REVERSE RATE
              </div>
              {current.auto_reverse_rate === null
                ? <div className="t-bodysm muted">no auto-merges yet for this version</div>
                : <>
                    <div style={{display:"flex", alignItems:"baseline", gap:8}}>
                      <span style={{fontFamily:"monospace", fontSize:26, fontWeight:700}}>
                        {(current.auto_reverse_rate * 100).toFixed(1)}%
                      </span>
                      <span className="t-bodysm muted">
                        ({current.auto_reverse_count} of {current.auto_merge_count})
                      </span>
                    </div>
                    {current.auto_reverse_rate >= 0.05 && (
                      <div className="t-bodysm" style={{marginTop:8, padding:8, background:"var(--accent-danger-bg)", color:"var(--accent-danger)", borderRadius:6, lineHeight:1.4}}>
                        Above 5% — consider raising
                        config.tier3.auto_merge_threshold for this version.
                      </div>
                    )}
                  </>
              }

              {current.status === "active" && (
                <>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>APPROVED BY</div>
                  <div className="t-bodysm">{current.approved_by}</div>
                  <div className="t-cap muted">on {current.approved_at}</div>
                </>
              )}
            </div>
          </div>

          {current.status === "draft" && (
            <div className="card">
              <div style={{padding:"12px 16px"}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:8}}>ACTIONS</div>
                <button className="btn primary" style={{width:"100%"}}>
                  <Icon name="check" size={13}/> Request approval (AC-DDUP-MODEL-VERSION)
                </button>
                <div className="t-bodysm muted" style={{marginTop:8, lineHeight:1.4}}>
                  Activation needs a different approver from the author.
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Mock SourceSystems for the "Run connector" modal — populated live
// from /api/v1/dih/source-systems/ when the harness is running on
// the same origin as the Django backend (matches the fetch-or-fall-
// back-to-mock pattern in screens-dih.jsx).
const MOCK_SOURCE_SYSTEMS = [
  { id: "01SS2026010100001", code: "KOBO-PILOT",     name: "Kobo pilot",      kind: "kobo",      is_active: true },
  { id: "01SS2026010100002", code: "PDM-MIS",        name: "PDM MIS",         kind: "partner_mis", is_active: true },
  { id: "01SS2026010100003", code: "NUSAF-MIS",      name: "NUSAF MIS",       kind: "partner_mis", is_active: true },
  { id: "01SS2026010100004", code: "WFP-SCOPE",      name: "WFP SCOPE",       kind: "wfp_scope", is_active: true },
];

// ── Run-connector modal (US-S11-021) ──────────────────────────────────
// Operator picks a SourceSystem + dry-run flag, posts to
// /api/v1/dih/source-systems/{id}/trigger-run/. On success the new
// ConnectorRun row appears at the top of the runs table. Kobo is the
// only kind wired today — the rest stay disabled with a "(coming
// soon)" suffix to keep the UI honest.
const RunConnectorModal = ({ sources, onClose, onSubmit, submitting }) => {
  const koboSources = useMemoAdmin(
    () => sources.filter(s => s.kind === "kobo" && s.is_active),
    [sources],
  );
  const [sourceId, setSourceId] = useStateAdmin(koboSources[0]?.id || "");
  const [dryRun, setDryRun] = useStateAdmin(false);

  useEffectAdmin(() => {
    if (!sourceId && koboSources.length > 0) setSourceId(koboSources[0].id);
  }, [koboSources, sourceId]);

  const submit = (e) => {
    e.preventDefault();
    if (!sourceId) return;
    onSubmit({ sourceId, dryRun });
  };

  return (
    <div
      role="dialog"
      aria-label="Run connector"
      style={{
        position:"fixed", inset:0, background:"rgba(0,0,0,0.4)",
        display:"flex", alignItems:"center", justifyContent:"center", zIndex:1000,
      }}
      onClick={onClose}
    >
      <form
        onClick={e => e.stopPropagation()}
        onSubmit={submit}
        style={{
          background:"white", padding:"24px", borderRadius:"8px",
          minWidth:"420px", maxWidth:"480px",
          boxShadow:"0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 className="t-h3" style={{marginTop:0}}>Run connector</h3>
        <p className="t-bodysm muted" style={{marginTop:4, marginBottom:16}}>
          Triggers a Kobo pull through the same path the scheduled Celery
          beat uses. Requires an active DPA and stored credentials.
        </p>

        <label className="t-cap" style={{display:"block", marginBottom:4}}>
          Source system
        </label>
        <select
          value={sourceId}
          onChange={e => setSourceId(e.target.value)}
          style={{width:"100%", padding:"8px", marginBottom:16,
                  border:"1px solid var(--neutral-300)", borderRadius:"4px",
                  fontSize:13}}
          disabled={submitting}
        >
          {sources.map(s => {
            const kobo = s.kind === "kobo" && s.is_active;
            return (
              <option key={s.id} value={s.id} disabled={!kobo}>
                {s.code} — {s.name}
                {kobo ? "" : " (coming soon)"}
              </option>
            );
          })}
        </select>

        <label
          style={{display:"flex", alignItems:"center", gap:8,
                  marginBottom:20, fontSize:13, cursor:"pointer"}}
        >
          <input
            type="checkbox"
            checked={dryRun}
            onChange={e => setDryRun(e.target.checked)}
            disabled={submitting}
          />
          <span>
            <strong>Dry run</strong>
            <span className="muted" style={{display:"block", fontSize:11, marginTop:2}}>
              Verifies credentials + form list. Counts but does not land submission rows.
            </span>
          </span>
        </label>

        <div style={{display:"flex", justifyContent:"flex-end", gap:8}}>
          <button
            type="button" className="btn"
            onClick={onClose} disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="submit" className="btn primary"
            disabled={submitting || !sourceId}
          >
            {submitting ? "Running…" : (dryRun ? "Run dry-run" : "Run pull")}
          </button>
        </div>
      </form>
    </div>
  );
};

// ── Connector runs tab ─────────────────────────────────────────────────
const ConnectorRunsTab = () => {
  const [selection, setSelection] = useStateAdmin(new Set());
  const [toast, setToast] = useStateAdmin("");
  // Local copy so the optimistic prepend after a successful trigger
  // survives across renders without mutating the module-level mock.
  const [runs, setRuns] = useStateAdmin(CONNECTOR_RUNS);
  const [sources, setSources] = useStateAdmin(MOCK_SOURCE_SYSTEMS);
  const [modalOpen, setModalOpen] = useStateAdmin(false);
  const [submitting, setSubmitting] = useStateAdmin(false);

  // Live-fetch source systems from the DRF endpoint when the harness
  // runs on the same origin as the Django backend; otherwise we keep
  // the mock list so the design preview still works under file://.
  useEffectAdmin(() => {
    let cancelled = false;
    fetch("/api/v1/dih/source-systems/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        const items = data.results || data;
        if (Array.isArray(items) && items.length > 0) setSources(items);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const toggleSel = (id) => {
    const next = new Set(selection);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection(next);
  };

  const stuckIds = useMemoAdmin(() => (
    runs.filter(r => selection.has(r.id) && isStuck(r))
        .map(r => r.id)
  ), [selection, runs]);

  const fireBulk = () => {
    if (stuckIds.length === 0) {
      setToast("No selected rows are STUCK (RUNNING for ≥ 6h).");
      return;
    }
    setToast(
      `Marked ${stuckIds.length} stuck run(s) as FAILED. ` +
      `Note appended: "stuck since…". ` +
      `${selection.size - stuckIds.length} skipped (not stuck).`,
    );
    setSelection(new Set());
  };

  const triggerRun = ({ sourceId, dryRun }) => {
    const source = sources.find(s => s.id === sourceId);
    if (!source) return;
    setSubmitting(true);
    fetch(`/api/v1/dih/source-systems/${sourceId}/trigger-run/`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ dry_run: dryRun }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setSubmitting(false);
        setModalOpen(false);
        if (!ok) {
          setToast(`Trigger failed: ${body.detail || "unknown error"}`);
          return;
        }
        // Optimistic prepend so the operator sees the new row
        // immediately. The next live-fetch tick (S10-005's 5-second
        // poll) will replace it with the server-truth row.
        const newRow = {
          id: body.run_id,
          connector: `${body.source_code}${dryRun ? " (dry-run)" : ""}`,
          status: "succeeded",
          started_h: 0,
          duration: dryRun ? "dry-run" : "just now",
          landed: body.landed || 0,
          staged: body.staged || 0,
          promoted: 0,
          quarantined: body.quarantined || 0,
          rejected: body.errored || 0,
        };
        setRuns(prev => [newRow, ...prev]);
        setToast(
          dryRun
            ? `Dry-run complete: would have landed ${body.landed} row(s).`
            : `Pull complete: landed ${body.landed} row(s), staged ${body.staged}.`,
        );
      })
      .catch(err => {
        setSubmitting(false);
        setModalOpen(false);
        // file:// preview or network error — fall back to the mock
        // path so the UI is still demonstrable.
        const mockRow = {
          id: `01CRMOCK${Date.now()}`,
          connector: `${source.code}${dryRun ? " (dry-run)" : ""}`,
          status: "succeeded", started_h: 0,
          duration: dryRun ? "dry-run" : "just now",
          landed: 3, staged: 3, promoted: 0, quarantined: 0, rejected: 0,
        };
        setRuns(prev => [mockRow, ...prev]);
        setToast(
          dryRun
            ? "Dry-run queued (mock — no backend reachable)."
            : `Pull queued (mock — no backend reachable; ${err}).`,
        );
      });
  };

  return (
    <>
      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">
            {selection.size > 0
              ? <>{selection.size} selected of {runs.length}</>
              : <>{runs.length} runs</>}
          </strong>
          <div style={{flex:1}}/>
          {selection.size > 0 && (
            <button className="btn" onClick={fireBulk}>
              <Icon name="alert" size={13}/> Mark stuck runs as FAILED
            </button>
          )}
          {selection.size === 0 && (
            <>
              <span className="t-cap">
                STUCK threshold: {STUCK_THRESHOLD_HOURS}h since start (US-S10-005)
              </span>
              <button
                className="btn primary"
                style={{marginLeft:12}}
                onClick={() => setModalOpen(true)}
              >
                <Icon name="arrowRight" size={13}/> Run connector
              </button>
            </>
          )}
        </div>

        <div style={{display:"grid", gridTemplateColumns:"32px 1fr 130px 100px 90px 90px 90px 90px",
                       borderBottom:"1px solid var(--neutral-200)", background:"var(--neutral-50)",
                       fontSize:11, fontWeight:600, letterSpacing:"0.06em",
                       textTransform:"uppercase", color:"var(--neutral-700)"}}>
          <div style={{padding:"10px 8px", textAlign:"center"}}>
            <input type="checkbox"
                   checked={selection.size === runs.length}
                   onChange={() => setSelection(
                     selection.size === runs.length
                       ? new Set() : new Set(runs.map(r => r.id))
                   )}/>
          </div>
          <div style={{padding:"10px 16px"}}>Connector / Run ID</div>
          <div style={{padding:"10px 8px"}}>Status</div>
          <div style={{padding:"10px 8px"}}>Duration</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Landed</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Promoted</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Quarantined</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Rejected</div>
        </div>

        {runs.map(r => {
          const sel = selection.has(r.id);
          const stuck = isStuck(r);
          return (
            <div key={r.id}
                 style={{display:"grid", gridTemplateColumns:"32px 1fr 130px 100px 90px 90px 90px 90px",
                          borderBottom:"1px solid var(--neutral-200)",
                          background: sel ? "var(--accent-data-bg)" : "white",
                          alignItems:"center"}}>
              <div style={{padding:"12px 8px", textAlign:"center"}}>
                <input type="checkbox" checked={sel} onChange={() => toggleSel(r.id)}/>
              </div>
              <div style={{padding:"12px 16px"}}>
                <div style={{fontSize:13, fontWeight:500}}>{r.connector}</div>
                <div className="t-mono muted" style={{fontSize:11, marginTop:2}}>{r.id}</div>
              </div>
              <div style={{padding:"12px 8px"}}>
                {stuck
                  ? <Chip size="sm" tone="danger">STUCK &gt; 6h</Chip>
                  : <Chip size="sm" tone={statusToneCR[r.status] || "neutral"}>{r.status}</Chip>}
              </div>
              <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                {r.duration}
              </div>
              <div style={{padding:"12px 8px", textAlign:"right", fontFamily:"monospace", fontSize:12}}>{r.landed.toLocaleString()}</div>
              <div style={{padding:"12px 8px", textAlign:"right", fontFamily:"monospace", fontSize:12}}>{r.promoted.toLocaleString()}</div>
              <div style={{padding:"12px 8px", textAlign:"right", fontFamily:"monospace", fontSize:12, color: r.quarantined ? "var(--accent-quality)" : "var(--neutral-500)"}}>{r.quarantined.toLocaleString()}</div>
              <div style={{padding:"12px 8px", textAlign:"right", fontFamily:"monospace", fontSize:12, color: r.rejected ? "var(--accent-danger)" : "var(--neutral-500)"}}>{r.rejected.toLocaleString()}</div>
            </div>
          );
        })}
      </div>
      {modalOpen && (
        <RunConnectorModal
          sources={sources}
          submitting={submitting}
          onClose={() => !submitting && setModalOpen(false)}
          onSubmit={triggerRun}
        />
      )}
      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </>
  );
};

// ── Stub tab — links out to /admin/ for the not-yet-built ones ──────
const AdminStubTab = ({ title, adminPath, sprintRef, description }) => (
  <div className="card" style={{padding:"32px 24px", textAlign:"center"}}>
    <Icon name="settings" size={48} color="var(--neutral-300)"/>
    <h3 className="t-h3" style={{marginTop:12}}>{title}</h3>
    <p className="t-bodysm muted" style={{maxWidth:480, margin:"8px auto 16px", lineHeight:1.5}}>
      {description}
    </p>
    <a className="btn primary" href={adminPath} target="_blank" rel="noopener noreferrer">
      <Icon name="arrowRight" size={13}/> Open in Django admin
    </a>
    <div className="t-cap muted" style={{marginTop:12}}>
      Backend already shipped — {sprintRef}. Native React form is a future ticket.
    </div>
  </div>
);

// Partners & DSAs — admin launchpad. Replaces the AdminStubTab that
// only pointed at /admin/. The Data Sharing Agreements workspace +
// the Partners list both live as their own console screens; the
// admin tab is now the canonical discovery surface for them (the
// top-level sidebar entry for DSAs was removed when this tab took
// over that role).
const PartnersAndDsasTab = ({ onNavigate }) => (
  <div className="col gap-4">
    <PartnersAdminTile
      title="Data Sharing Agreements"
      iconName="file"
      tone="data"
      lede="The DSA workspace — list every active / draft DSA across partners, edit scope on a draft, propose v(N+1) clones on an active row, or start a new DSA from a wizard."
      ctaLabel="Open DSA workspace"
      onClick={() => onNavigate && onNavigate("dsas")}
      secondary={[
        ["Backend",  <span className="t-mono">apps.partners</span>],
        ["Endpoint", <span className="t-mono">GET /api/v1/dsas/</span>],
        ["Spec",     "US-S27-004 cross-partner DSA workbench"],
      ]}
    />
    <PartnersAdminTile
      title="Partners"
      iconName="users"
      tone="programme"
      lede="Partner organisations registry. Open a partner to see their identity record, DSAs, programmes, contacts, usage, activity feed, and compliance posture."
      ctaLabel="Open Partners workspace"
      onClick={() => onNavigate && onNavigate("partners")}
      secondary={[
        ["Backend",  <span className="t-mono">apps.partners</span>],
        ["Endpoint", <span className="t-mono">GET /api/v1/partners/</span>],
        ["Spec",     "US-S23-008..010 + US-S27 follow-ups"],
      ]}
    />
    <div className="card" style={{padding:"14px 16px", background:"var(--neutral-50)"}}>
      <div className="row gap-2">
        <Icon name="settings" size={14} color="var(--neutral-700)"/>
        <strong className="t-bodysm">Django admin shortcut</strong>
      </div>
      <div className="t-cap" style={{marginTop:4}}>
        Raw model edits (overrides, hot-fixes, support tickets) still go
        through the Django admin:
        {" "}
        <a className="t-mono" href="/admin/partners/datasharingagreement/" target="_blank" rel="noopener noreferrer">
          /admin/partners/datasharingagreement/
        </a>.
      </div>
    </div>
  </div>
);

const PartnersAdminTile = ({ title, iconName, tone, lede, ctaLabel, onClick, secondary }) => (
  <div className="card" style={{
    padding: 0, borderLeft: `3px solid var(--accent-${tone})`,
  }}>
    <div style={{padding:"16px 20px", display:"flex", alignItems:"flex-start", gap:16}}>
      <div style={{
        width:40, height:40, borderRadius:8,
        background:`var(--accent-${tone}-bg)`, color:`var(--accent-${tone})`,
        display:"grid", placeItems:"center", flexShrink:0,
      }}>
        <Icon name={iconName} size={20}/>
      </div>
      <div style={{flex:1, minWidth:0}}>
        <div style={{fontWeight:600, fontSize:15}}>{title}</div>
        <p className="t-bodysm muted" style={{margin:"6px 0 0", lineHeight:1.5}}>
          {lede}
        </p>
      </div>
      <button className="btn btn-primary" onClick={onClick}>
        {ctaLabel} <Icon name="chevronRight" size={13}/>
      </button>
    </div>
    <div style={{
      padding:"10px 20px", background:"var(--neutral-50)",
      borderTop:"1px solid var(--neutral-200)",
      display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gap:12,
    }}>
      {secondary.map(([k, v], i) => (
        <div key={i}>
          <div className="t-cap">{k}</div>
          <div className="t-bodysm" style={{marginTop:2}}>{v}</div>
        </div>
      ))}
    </div>
  </div>
);

// ── Main screen ────────────────────────────────────────────────────────
const TABS = [
  { id: "model-versions", label: "DDUP model versions", icon: "duplicate" },
  { id: "connector-runs", label: "Connector runs",      icon: "inbox"     },
  { id: "routing-matrix", label: "UPD routing matrix",  icon: "edit"      },
  { id: "partners",       label: "Partners & DSAs",     icon: "download"  },
  { id: "scopes",         label: "Operator scopes",     icon: "shield"    },
];

const AdminScreen = ({ onNavigate }) => {
  const [tab, setTab] = useStateAdmin("model-versions");

  return (
    <div className="page" style={{paddingBottom:0, position:"relative"}}>
      <PageHeader
        eyebrow="SYSTEM ADMIN · US-S11-001"
        title={<>Administration</>}
        sub="Operations-side controls. Audit-bearing changes go through the audit chain regardless of surface."
        right={<>
          <a className="btn" href="/admin/" target="_blank" rel="noopener noreferrer">
            <Icon name="arrowRight" size={13}/> Full Django admin
          </a>
        </>}
      />

      {/* Tab strip */}
      <div className="card" style={{padding:0, marginBottom:16}}>
        <div className="row" style={{borderBottom:"1px solid var(--neutral-200)"}}>
          {TABS.map(t => {
            const active = tab === t.id;
            return (
              <button key={t.id}
                      onClick={() => setTab(t.id)}
                      style={{
                        flex:1, padding:"14px 16px", border:0,
                        background: active ? "white" : "transparent",
                        borderBottom: active ? "3px solid var(--accent-data)" : "3px solid transparent",
                        marginBottom:-1,
                        cursor:"pointer", display:"flex", alignItems:"center",
                        justifyContent:"center", gap:8,
                        fontSize:13, fontWeight: active ? 600 : 500,
                        color: active ? "var(--accent-data)" : "var(--neutral-700)",
                      }}>
                <Icon name={t.icon} size={14}/>
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {tab === "model-versions" && <ModelVersionsTab/>}
      {tab === "connector-runs" && <ConnectorRunsTab/>}
      {tab === "routing-matrix" && (
        <AdminStubTab title="UPD routing matrix"
                       adminPath="/admin/update_workflow/updroutingrule/"
                       sprintRef="US-S4-003"
                       description="(change_type × pmt_relevant) → (required_role, sla_hours). Operations-editable from REF-DATA — change SLA windows or required roles without a deploy. Defaults seeded from SAD §4.4.4."/>
      )}
      {tab === "partners" && (
        <PartnersAndDsasTab onNavigate={onNavigate}/>
      )}
      {tab === "scopes" && (
        <AdminStubTab title="Operator scopes"
                       adminPath="/admin/security/operatorscope/"
                       sprintRef="US-S2-003, US-S4-001"
                       description="Per-operator geographic OR partner scopes — the source of every ABAC filter on personal-data viewsets. Five mixin patterns cover the read side (geographic, household-id subquery, entity-type union, both-ends-in-scope, partner-org)."/>
      )}
    </div>
  );
};

// Expose the trigger-run pieces for Vitest. Under Babel-standalone in
// the browser harness these are already top-level consts; this shim
// just makes them reachable from a Node-side dynamic import.
if (typeof globalThis !== "undefined") {
  Object.assign(globalThis, {
    RunConnectorModal,
    ConnectorRunsTab,
    MOCK_SOURCE_SYSTEMS,
  });
}
