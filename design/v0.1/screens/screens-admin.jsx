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


// Reads Django's csrftoken cookie — required for session-auth POSTs
// against the DRF endpoints. Same shape as `_getCsrfToken` in
// screens-dih / screens-drs / screens-upd / screens-grm. The
// admin-login flow sets this cookie automatically; preview harnesses
// running under file:// won't have it and the catch branch of the
// trigger fetch falls back to the mock path.
const _adminCsrfToken = () => {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

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

// Format an ISO timestamp as "26 May 2026 · 22:10 EAT". EAT (UTC+3)
// is the rendering timezone per CLAUDE.md "persist as UTC, render
// as EAT in UI". Africa/Kampala is the canonical TZ id for Uganda.
const _formatRunDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const date = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Kampala",
    day: "2-digit", month: "short", year: "numeric",
  }).format(d);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Kampala",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(d);
  return `${date} · ${time} EAT`;
};

// Map a /api/v1/dih/connector-runs/ server row into the row shape the
// table renders. Duration + started_h are computed client-side from
// the timestamps so the backend stays lean. Returns null if the input
// is malformed so a single bad row doesn't kill the whole render.
const _runApiToRow = (r) => {
  if (!r || !r.id) return null;
  const started = r.started_at ? new Date(r.started_at) : null;
  const finished = r.finished_at ? new Date(r.finished_at) : null;
  const now = new Date();
  const endMs = (finished || now).getTime();
  const elapsedMs = started ? endMs - started.getTime() : 0;
  const startedH = elapsedMs / (1000 * 60 * 60);
  // Compact duration string mirroring the existing mock vocabulary:
  // "12m" / "5h 02m" for finished, "running 1.2h" for in-flight.
  const fmt = (ms) => {
    const totalMin = Math.max(0, Math.floor(ms / 60000));
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h === 0) return `${m}m`;
    return `${h}h ${String(m).padStart(2, "0")}m`;
  };
  const duration = finished
    ? fmt(elapsedMs)
    : (startedH >= 1
        ? `running ${startedH.toFixed(1)}h`
        : `running ${Math.floor(elapsedMs / 60000)}m`);
  const connectorLabel = r.source_code
    ? `${r.source_code}${r.run_type === "test" ? " (test)" : ""}`
    : (r.connector_name || "");
  return {
    id: r.id,
    connector: connectorLabel,
    status: r.status,
    started_h: startedH,
    started_at: r.started_at || null,
    duration,
    landed: r.records_landed || 0,
    staged: r.records_staged || 0,
    promoted: r.records_promoted || 0,
    quarantined: r.records_quarantined || 0,
    rejected: r.records_rejected || 0,
  };
};

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

// ── Run-connector modal (US-S11-021, US-S11-022) ──────────────────────
// Operator picks a SourceSystem + form_uid + dry-run flag, posts to
// /api/v1/dih/source-systems/{id}/trigger-run/. On success the new
// ConnectorRun row appears at the top of the runs table. Kobo is the
// only kind wired today — the rest stay disabled with a "(coming
// soon)" suffix to keep the UI honest.
//
// The form-picker dropdown is the US-S11-022 fix for the
// 2026-05-26 incident: when a Kobo workspace carries multiple
// deployed forms (legacy v1 + current v2), forms[0] silently picks
// whichever Kobo returned first, and a wrong-form pick canonicalises
// 100% of rows to KeyError → "quarantined" tally with zero
// StageRecords created. The picker makes the choice explicit.
const RunConnectorModal = ({ sources, onClose, onSubmit, submitting }) => {
  const koboSources = useMemoAdmin(
    () => sources.filter(s => s.kind === "kobo" && s.is_active),
    [sources],
  );
  const [sourceId, setSourceId] = useStateAdmin(koboSources[0]?.id || "");
  const [dryRun, setDryRun] = useStateAdmin(false);
  // Form-picker state: forms come from /forms/ when the source
  // changes; if the fetch fails (e.g. file:// preview) we leave it
  // empty and the picker hides itself — submit falls back to the
  // server-side default (Connector.config or forms[0]).
  const [forms, setForms] = useStateAdmin([]);
  const [formUid, setFormUid] = useStateAdmin("");
  const [formsLoading, setFormsLoading] = useStateAdmin(false);
  const [formsError, setFormsError] = useStateAdmin("");

  useEffectAdmin(() => {
    if (!sourceId && koboSources.length > 0) setSourceId(koboSources[0].id);
  }, [koboSources, sourceId]);

  // Fetch the form list whenever the picked source changes. Only
  // fires for Kobo sources because non-Kobo kinds 400 the endpoint.
  useEffectAdmin(() => {
    const src = sources.find(s => s.id === sourceId);
    if (!src || src.kind !== "kobo") {
      setForms([]); setFormUid(""); setFormsError("");
      return;
    }
    let cancelled = false;
    setFormsLoading(true); setFormsError("");
    fetch(`/api/v1/dih/source-systems/${sourceId}/forms/`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (cancelled) return;
        setFormsLoading(false);
        if (!ok) {
          setForms([]); setFormUid("");
          setFormsError(body.detail || "form list unavailable");
          return;
        }
        const deployed = (body || []).filter(f => f.deployed);
        setForms(deployed);
        // Default to the first deployed form so submit-with-no-pick
        // is unambiguous; operator can override before submitting.
        setFormUid(deployed[0]?.uid || "");
      })
      .catch(() => {
        if (cancelled) return;
        setFormsLoading(false);
        setForms([]); setFormUid("");
        setFormsError("");  // silent — fall back to server-side default
      });
    return () => { cancelled = true; };
  }, [sourceId, sources]);

  const submit = (e) => {
    e.preventDefault();
    if (!sourceId) return;
    onSubmit({ sourceId, dryRun, formUid });
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

        {/* Form picker — visible only when /forms/ returned a non-empty
            list. While loading we show a small notice; on error we
            stay silent and let the server pick (Connector.config →
            forms[0]). */}
        {(forms.length > 0 || formsLoading) && (
          <>
            <label className="t-cap" style={{display:"block", marginBottom:4}}>
              Form {formsLoading && <span className="muted">(loading…)</span>}
            </label>
            <select
              value={formUid}
              onChange={e => setFormUid(e.target.value)}
              disabled={submitting || formsLoading || forms.length === 0}
              style={{width:"100%", padding:"8px", marginBottom:16,
                      border:"1px solid var(--neutral-300)", borderRadius:"4px",
                      fontSize:13}}
            >
              {forms.map(f => (
                <option key={f.uid} value={f.uid}>
                  {f.name || "(no name)"} — {f.uid}
                </option>
              ))}
            </select>
          </>
        )}
        {formsError && (
          <p className="t-bodysm" style={{color:"var(--accent-danger)", marginTop:0, marginBottom:16}}>
            {formsError}
          </p>
        )}

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

// ── Delete-runs confirm modal (US-S11-023) ─────────────────────────────
// Operator confirms the cascade before any row is dropped. The reason
// field is required because the audit event is the only paper trail
// after the rows are gone.
const DeleteRunsConfirmModal = ({ rows, onClose, onConfirm, submitting }) => {
  const [reason, setReason] = useStateAdmin("");
  const submit = (e) => {
    e.preventDefault();
    if (!reason.trim()) return;
    onConfirm(reason.trim());
  };
  return (
    <div
      role="dialog"
      aria-label="Delete connector runs"
      style={{
        position:"fixed", inset:0, background:"rgba(0,0,0,0.4)",
        display:"flex", alignItems:"center", justifyContent:"center", zIndex:1000,
      }}
      onClick={() => !submitting && onClose()}
    >
      <form
        onClick={e => e.stopPropagation()}
        onSubmit={submit}
        style={{
          background:"white", padding:"24px", borderRadius:"8px",
          minWidth:"460px", maxWidth:"560px",
          boxShadow:"0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 className="t-h3" style={{marginTop:0, color:"var(--accent-danger)"}}>
          Delete {rows.length} connector run{rows.length === 1 ? "" : "s"}?
        </h3>
        <p className="t-bodysm muted" style={{marginTop:4, marginBottom:12}}>
          Cascades through StageRecord → RawLanding for each run. The
          backend refuses if any run has promoted records (Household
          lineage is preserved). This action is irreversible — the
          audit event is the only paper trail.
        </p>
        <ul
          className="t-mono"
          style={{
            fontSize:11, background:"var(--neutral-50)",
            padding:"8px 12px", borderRadius:"4px",
            maxHeight:"160px", overflowY:"auto",
            marginBottom:16,
          }}
        >
          {rows.map(r => (
            <li key={r.id}>{r.id} — {r.connector} ({r.status})</li>
          ))}
        </ul>

        <label className="t-cap" style={{display:"block", marginBottom:4}}>
          Reason <span style={{color:"var(--accent-danger)"}}>*</span>
        </label>
        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          rows={3}
          disabled={submitting}
          placeholder="e.g. wrong Kobo form pulled; canonicalize failed on every row"
          style={{
            width:"100%", padding:"8px",
            border:"1px solid var(--neutral-300)", borderRadius:"4px",
            fontSize:13, fontFamily:"inherit", resize:"vertical",
            marginBottom:20,
          }}
        />

        <div style={{display:"flex", justifyContent:"flex-end", gap:8}}>
          <button
            type="button" className="btn"
            onClick={onClose} disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="submit" className="btn"
            style={{
              background:"var(--accent-danger)", color:"white",
              borderColor:"var(--accent-danger)",
            }}
            disabled={submitting || !reason.trim()}
          >
            {submitting ? "Deleting…" : `Delete ${rows.length}`}
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
  // Delete-runs confirm modal state (US-S11-023). `deleteTargets`
  // holds the row objects up for deletion — single-row delete clicks
  // populate it with one row; bulk-delete passes the selection.
  const [deleteTargets, setDeleteTargets] = useStateAdmin([]);
  const [deleteSubmitting, setDeleteSubmitting] = useStateAdmin(false);

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

  // Live-fetch ConnectorRuns from the DRF endpoint (US-S11-022).
  // Replaces the static CONNECTOR_RUNS mock that previously hid every
  // real run from the dashboard. Auto-refresh while any row is
  // running (matches the S10-005 spec UI-ADMIN-2 5-second poll); the
  // interval drops when nothing is in-flight to keep the network
  // chatter low. Fall back to mock if the fetch fails so file://
  // previews still render.
  const fetchRuns = (signal) => fetch("/api/v1/dih/connector-runs/", {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  })
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => {
      const items = data.results || data;
      if (!Array.isArray(items)) return null;
      return items.map(_runApiToRow).filter(Boolean);
    });

  useEffectAdmin(() => {
    let cancelled = false;
    const controller = new AbortController();
    fetchRuns(controller.signal)
      .then(rows => { if (rows && !cancelled) setRuns(rows); })
      .catch(() => {});
    return () => { cancelled = true; controller.abort(); };
  }, []);

  // Auto-refresh: 5s tick while any row is running, paused otherwise.
  const anyRunning = useMemoAdmin(
    () => runs.some(r => r.status === "running" || r.status === "pending"),
    [runs],
  );
  useEffectAdmin(() => {
    if (!anyRunning) return undefined;
    const controller = new AbortController();
    const id = setInterval(() => {
      fetchRuns(controller.signal)
        .then(rows => { if (rows) setRuns(rows); })
        .catch(() => {});
    }, 5000);
    return () => { clearInterval(id); controller.abort(); };
  }, [anyRunning]);

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

  const deleteRuns = (reason) => {
    if (deleteTargets.length === 0) return;
    setDeleteSubmitting(true);
    const ids = deleteTargets.map(r => r.id);
    Promise.all(ids.map(id => fetch(
      `/api/v1/dih/connector-runs/${id}/delete/`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": _adminCsrfToken(),
        },
        body: JSON.stringify({ reason }),
      },
    ).then(r => r.json().then(body => ({ id, ok: r.ok, body })))
      .catch(err => ({ id, ok: false, body: { detail: String(err) } }))))
      .then(results => {
        setDeleteSubmitting(false);
        setDeleteTargets([]);
        const okIds = new Set(
          results.filter(x => x.ok).map(x => x.id),
        );
        // Remove successfully-deleted rows from the table and the
        // selection set. Failed rows stay so the operator can see
        // what blocked them via the toast.
        setRuns(prev => prev.filter(r => !okIds.has(r.id)));
        setSelection(prev => {
          const next = new Set(prev);
          for (const id of okIds) next.delete(id);
          return next;
        });
        const failed = results.filter(x => !x.ok);
        if (failed.length === 0) {
          setToast(`Deleted ${okIds.size} run(s).`);
        } else {
          const detail = failed
            .map(f => `${f.id}: ${f.body.detail || "failed"}`)
            .join(" · ");
          setToast(
            `Deleted ${okIds.size}, refused ${failed.length}. ${detail}`,
          );
        }
      });
  };

  const triggerRun = ({ sourceId, dryRun, formUid }) => {
    const source = sources.find(s => s.id === sourceId);
    if (!source) return;
    setSubmitting(true);
    const body = { dry_run: dryRun };
    if (formUid) body.form_uid = formUid;
    fetch(`/api/v1/dih/source-systems/${sourceId}/trigger-run/`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": _adminCsrfToken(),
      },
      body: JSON.stringify(body),
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
            <>
              <button className="btn" onClick={fireBulk}>
                <Icon name="alert" size={13}/> Mark stuck runs as FAILED
              </button>
              <button
                className="btn"
                style={{marginLeft:8, color:"var(--accent-danger)"}}
                onClick={() => setDeleteTargets(
                  runs.filter(r => selection.has(r.id)),
                )}
              >
                <Icon name="trash" size={13}/> Delete selected
              </button>
            </>
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

        <div style={{display:"grid", gridTemplateColumns:"32px 1fr 180px 130px 100px 90px 90px 90px 90px 40px",
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
          <div style={{padding:"10px 8px"}}>Started</div>
          <div style={{padding:"10px 8px"}}>Status</div>
          <div style={{padding:"10px 8px"}}>Duration</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Landed</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Promoted</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Quarantined</div>
          <div style={{padding:"10px 8px", textAlign:"right"}}>Rejected</div>
          <div style={{padding:"10px 8px"}}/>
        </div>

        {runs.map(r => {
          const sel = selection.has(r.id);
          const stuck = isStuck(r);
          return (
            <div key={r.id}
                 style={{display:"grid", gridTemplateColumns:"32px 1fr 180px 130px 100px 90px 90px 90px 90px 40px",
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
              <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                {_formatRunDate(r.started_at)}
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
              <div style={{padding:"12px 8px", textAlign:"center"}}>
                <button
                  type="button"
                  aria-label={`Delete run ${r.id}`}
                  title="Delete run"
                  onClick={() => setDeleteTargets([r])}
                  style={{
                    background:"transparent", border:"none", cursor:"pointer",
                    padding:"4px", color:"var(--neutral-500)",
                    display:"inline-flex", alignItems:"center",
                  }}
                  onMouseEnter={e => (e.currentTarget.style.color = "var(--accent-danger)")}
                  onMouseLeave={e => (e.currentTarget.style.color = "var(--neutral-500)")}
                >
                  <Icon name="trash" size={14}/>
                </button>
              </div>
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
      {deleteTargets.length > 0 && (
        <DeleteRunsConfirmModal
          rows={deleteTargets}
          submitting={deleteSubmitting}
          onClose={() => !deleteSubmitting && setDeleteTargets([])}
          onConfirm={deleteRuns}
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
    DeleteRunsConfirmModal,
    ConnectorRunsTab,
    MOCK_SOURCE_SYSTEMS,
    _formatRunDate,
    _runApiToRow,
  });
}
