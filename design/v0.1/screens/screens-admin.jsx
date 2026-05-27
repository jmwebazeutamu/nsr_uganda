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
  // Per-pull row cap (US-S11-033). Bounded 1..500 — must match the
  // serializer min/max in apps/ingestion_hub/api.py. 50 matches the
  // server-side default (services.TRIGGER_PULL_BATCH_CAP).
  const [batchCap, setBatchCap] = useStateAdmin(50);
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

  // Fetch the form list — extracted so the "Retry" button can call it
  // again after an upstream 5xx (e.g. Kobo Toolbox 503 outage) without
  // forcing the operator to Cancel + reopen the modal.
  const _fetchForms = (signal) => {
    setFormsLoading(true); setFormsError("");
    return fetch(`/api/v1/dih/source-systems/${sourceId}/forms/`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal,
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setFormsLoading(false);
        if (!ok) {
          setForms([]); setFormUid("");
          setFormsError(body.detail || "form list unavailable");
          return;
        }
        const deployed = (body || []).filter(f => f.deployed);
        setForms(deployed);
        // US-S11-026: prefer the server-pinned form so the dropdown
        // matches what the server would default to. Without this,
        // the modal silently selected forms[0] (whatever Kobo
        // returned first) even when the server was ready to pin a
        // known-good form — the 2026-05-26 trap.
        const pinned = deployed.find(f => f.pinned);
        setFormUid(pinned?.uid || deployed[0]?.uid || "");
      })
      .catch(() => {
        setFormsLoading(false);
        setForms([]); setFormUid("");
        setFormsError("");  // silent — fall back to server-side default
      });
  };

  // Auto-fetch the form list whenever the picked source changes. Only
  // fires for Kobo sources because non-Kobo kinds 400 the endpoint.
  useEffectAdmin(() => {
    const src = sources.find(s => s.id === sourceId);
    if (!src || src.kind !== "kobo") {
      setForms([]); setFormUid(""); setFormsError("");
      return;
    }
    const controller = new AbortController();
    _fetchForms(controller.signal);
    return () => controller.abort();
  }, [sourceId, sources]);

  const submit = (e) => {
    e.preventDefault();
    if (!sourceId) return;
    onSubmit({ sourceId, dryRun, formUid, batchCap });
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
                  {f.pinned ? "✓ " : ""}{f.name || "(no name)"} — {f.uid}
                </option>
              ))}
            </select>
          </>
        )}
        {formsError && (
          <div
            style={{
              display:"flex", alignItems:"flex-start", gap:8,
              marginTop:0, marginBottom:16,
            }}
          >
            <p className="t-bodysm" style={{color:"var(--accent-danger)", margin:0, flex:1}}>
              {formsError}
            </p>
            <button
              type="button"
              className="btn"
              onClick={() => _fetchForms()}
              disabled={submitting || formsLoading}
              style={{flexShrink:0}}
            >
              {formsLoading ? "Retrying…" : "Retry"}
            </button>
          </div>
        )}

        <label className="t-cap" style={{display:"block", marginBottom:4}}>
          Records to pull (cap)
        </label>
        <input
          type="number" min={1} max={500} step={1}
          value={batchCap}
          onChange={e => {
            const v = parseInt(e.target.value, 10);
            // Clamp client-side to the same bounds the serializer
            // enforces — saves a 400 round-trip when the operator
            // types 9999.
            if (Number.isNaN(v)) setBatchCap(50);
            else if (v < 1) setBatchCap(1);
            else if (v > 500) setBatchCap(500);
            else setBatchCap(v);
          }}
          disabled={submitting}
          style={{width:"100%", padding:"8px", marginBottom:6,
                  border:"1px solid var(--neutral-300)", borderRadius:"4px",
                  fontSize:13}}
        />
        <p className="t-bodysm muted" style={{margin:"0 0 16px", fontSize:11}}>
          Per-pull cap to keep the request short. Bounded 1..500;
          larger backlogs run via the scheduled Celery beat.
        </p>

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
            disabled={submitting || !sourceId || !formUid}
            title={
              !formUid
                ? "Pick a form before submitting (or hit Retry if /forms/ failed)"
                : ""
            }
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

  const triggerRun = ({ sourceId, dryRun, formUid, batchCap }) => {
    const source = sources.find(s => s.id === sourceId);
    if (!source) return;
    setSubmitting(true);
    const body = { dry_run: dryRun };
    if (formUid) body.form_uid = formUid;
    if (batchCap && batchCap !== 50) body.batch_cap = batchCap;
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


// ── Operator scopes tab (US-S11-028) ──────────────────────────────────
// Console surface that replaces the stub linking to
// /admin/security/operatorscope/. Lists every OperatorScope row,
// supports a per-row revoke, and opens a Grant Scope modal with a
// cascading geographic picker + multi-select. Backend mirrors:
//   /api/v1/security/operator-scopes/         (list, retrieve, destroy)
//   /api/v1/security/operator-scopes/bulk-grant/
//   /api/v1/security/users/?q=                (user picker)
//   /api/v1/reference-data/geographic-units/  (cascade source)
//   /api/v1/partners/                         (partner picker)

// Levels in UBOS order — used for the cascading parent picker. The
// modal walks 0..(targetIdx-1) to pick the parent of the target
// level, then loads peers at targetIdx for the multi-select.
const _GEO_LEVELS_ORDER = [
  "region", "sub_region", "district", "sub_county", "parish", "village",
];

const _SCOPE_LEVEL_OPTIONS = [
  { value: "national",   label: "National (wildcard)" },
  { value: "region",     label: "Region" },
  { value: "sub_region", label: "Sub-region" },
  { value: "district",   label: "District" },
  { value: "sub_county", label: "Sub-county" },
  { value: "parish",     label: "Parish" },
  { value: "village",    label: "Village" },
  { value: "partner",    label: "Partner (data-request scope)" },
];

const _scopeLevelLabel = (v) => {
  const opt = _SCOPE_LEVEL_OPTIONS.find(o => o.value === v);
  return opt ? opt.label : v;
};


// Cascading geographic picker — walks the UBOS ladder one level at
// a time, fetching peers of the parent each time. The leaf level
// (the one the operator is granting scope at) gets rendered as a
// multi-select checkbox list rather than a dropdown so "all parishes
// in District X" is one submit.
const GeoCascadePicker = ({ targetLevel, value, onChange, disabled }) => {
  // Stack of parent picks, e.g. when granting at sub_county:
  // [{level:"region", code:"R-CENTRAL"}, {level:"sub_region", code:"SR-..."}, {level:"district", code:"D-..."}]
  // After all parents are picked, peers at targetLevel become the
  // multi-select source.
  const targetIdx = _GEO_LEVELS_ORDER.indexOf(targetLevel);
  const [parents, setParents] = useStateAdmin([]);
  const [peerOptions, setPeerOptions] = useStateAdmin({});  // level -> [{code, name, parent_code}]
  const [loadingLevel, setLoadingLevel] = useStateAdmin("");

  // Fetch peers at a given level + parent_code. Falls silently to
  // an empty list under file:// preview.
  const _fetchPeers = (level, parentCode) => {
    setLoadingLevel(level);
    const qs = new URLSearchParams({ level });
    qs.set("parent_code", parentCode || "");
    qs.set("page_size", "500");
    fetch(`/api/v1/reference-data/geographic-units/?${qs.toString()}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        const items = (data.results || data || [])
          .map(u => ({ code: u.code, name: u.name, parent_code: u.parent_code || "" }));
        setPeerOptions(prev => ({ ...prev, [level]: items }));
        setLoadingLevel("");
      })
      .catch(() => { setLoadingLevel(""); });
  };

  // Reset everything when targetLevel changes.
  useEffectAdmin(() => {
    setParents([]);
    setPeerOptions({});
    onChange([]);
    if (targetIdx === 0) {
      // No parents to pick — load regions directly.
      _fetchPeers("region", "");
    } else {
      _fetchPeers("region", "");
    }
  }, [targetLevel]);

  // When a parent is picked at level i, load level i+1 peers under it.
  const pickParent = (level, code) => {
    const idx = _GEO_LEVELS_ORDER.indexOf(level);
    const newParents = [..._GEO_LEVELS_ORDER.slice(0, idx).map(
      (lvl, j) => parents[j] || { level: lvl, code: "" },
    ), { level, code }];
    setParents(newParents);
    onChange([]);
    // Load the next level (which may be the target).
    const nextIdx = idx + 1;
    if (nextIdx <= targetIdx) {
      const nextLevel = _GEO_LEVELS_ORDER[nextIdx];
      _fetchPeers(nextLevel, code);
    }
  };

  const toggleLeaf = (code) => {
    if (value.includes(code)) onChange(value.filter(c => c !== code));
    else onChange([...value, code]);
  };

  const selectAllLeaves = () => {
    const all = (peerOptions[targetLevel] || []).map(o => o.code);
    onChange(all);
  };

  const clearLeaves = () => onChange([]);

  // Build the rendered rows: one dropdown per parent level up to
  // (targetIdx - 1), then a checkbox grid at targetLevel.
  const parentRows = _GEO_LEVELS_ORDER.slice(0, targetIdx).map((lvl, i) => {
    const options = peerOptions[lvl] || [];
    const picked = parents[i]?.code || "";
    return (
      <div key={lvl} style={{marginBottom:12}}>
        <label className="t-cap" style={{display:"block", marginBottom:4, textTransform:"capitalize"}}>
          {lvl.replace("_", " ")}
          {loadingLevel === lvl && <span className="muted"> (loading…)</span>}
        </label>
        <select
          value={picked}
          onChange={e => pickParent(lvl, e.target.value)}
          disabled={disabled || loadingLevel === lvl || options.length === 0}
          style={{width:"100%", padding:"8px", border:"1px solid var(--neutral-300)",
                  borderRadius:"4px", fontSize:13}}
        >
          <option value="">— pick a {lvl.replace("_", " ")} —</option>
          {options.map(o => (
            <option key={o.code} value={o.code}>{o.name} ({o.code})</option>
          ))}
        </select>
      </div>
    );
  });

  const leaves = peerOptions[targetLevel] || [];
  const parentsReady = targetIdx === 0 || parents.length === targetIdx;
  return (
    <div>
      {parentRows}
      <label className="t-cap" style={{display:"block", marginBottom:4, textTransform:"capitalize"}}>
        {targetLevel.replace("_", " ")}{loadingLevel === targetLevel && <span className="muted"> (loading…)</span>}
      </label>
      {!parentsReady && (
        <p className="t-bodysm muted" style={{margin:"4px 0 12px"}}>
          Pick a {_GEO_LEVELS_ORDER[parents.length].replace("_", " ")} above to see {targetLevel.replace("_", " ")} options.
        </p>
      )}
      {parentsReady && (
        <>
          {leaves.length === 0 && !loadingLevel && (
            <p className="t-bodysm muted" style={{margin:"4px 0 12px"}}>
              No {targetLevel.replace("_", " ")} units found for this parent.
            </p>
          )}
          {leaves.length > 0 && (
            <>
              <div style={{display:"flex", gap:8, marginBottom:4}}>
                <button type="button" className="btn"
                  style={{fontSize:11, padding:"4px 8px"}}
                  onClick={selectAllLeaves} disabled={disabled}
                >Select all {leaves.length}</button>
                <button type="button" className="btn"
                  style={{fontSize:11, padding:"4px 8px"}}
                  onClick={clearLeaves} disabled={disabled || value.length === 0}
                >Clear</button>
                <span className="t-cap" style={{alignSelf:"center", marginLeft:"auto"}}>
                  {value.length} of {leaves.length} selected
                </span>
              </div>
              <div style={{
                border:"1px solid var(--neutral-300)", borderRadius:"4px",
                maxHeight:"180px", overflowY:"auto", padding:"4px 8px",
                background:"var(--neutral-50)",
              }}>
                {leaves.map(o => (
                  <label key={o.code} style={{
                    display:"flex", alignItems:"center", gap:8, padding:"4px 0",
                    fontSize:13, cursor:"pointer",
                  }}>
                    <input
                      type="checkbox"
                      checked={value.includes(o.code)}
                      onChange={() => toggleLeaf(o.code)}
                      disabled={disabled}
                    />
                    <span>{o.name} <span className="t-mono muted">({o.code})</span></span>
                  </label>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
};


// User-picker — search-as-you-type against /api/v1/security/users/.
const UserPicker = ({ value, onChange, disabled }) => {
  const [q, setQ] = useStateAdmin("");
  const [results, setResults] = useStateAdmin([]);
  const [loading, setLoading] = useStateAdmin(false);

  useEffectAdmin(() => {
    let cancelled = false;
    setLoading(true);
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    fetch(`/api/v1/security/users/${qs}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        setResults(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q]);

  return (
    <div>
      <input
        type="text" value={q} onChange={e => setQ(e.target.value)}
        placeholder="Search by username or name"
        disabled={disabled}
        style={{width:"100%", padding:"8px", border:"1px solid var(--neutral-300)",
                borderRadius:"4px", fontSize:13, marginBottom:8}}
      />
      <div style={{
        border:"1px solid var(--neutral-300)", borderRadius:"4px",
        maxHeight:"160px", overflowY:"auto", background:"var(--neutral-50)",
      }}>
        {loading && <p className="t-cap muted" style={{padding:"8px"}}>Searching…</p>}
        {!loading && results.length === 0 && (
          <p className="t-cap muted" style={{padding:"8px"}}>No users match.</p>
        )}
        {results.map(u => {
          const selected = value?.id === u.id;
          return (
            <button
              key={u.id} type="button"
              onClick={() => onChange(u)}
              disabled={disabled}
              style={{
                display:"block", width:"100%", textAlign:"left",
                padding:"6px 8px", fontSize:13,
                background: selected ? "var(--accent-data-bg)" : "transparent",
                border:"none", borderBottom:"1px solid var(--neutral-200)",
                cursor:"pointer",
              }}
            >
              <strong>{u.username}</strong>
              {u.display_name !== u.username && (
                <span className="muted"> — {u.display_name}</span>
              )}
              {u.groups.length > 0 && (
                <div className="t-cap muted">{u.groups.join(", ")}</div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};


// Grant Scope modal — user → level → (parents → leaves) → submit.
const GrantScopeModal = ({ onClose, onSubmit, submitting }) => {
  const [user, setUser] = useStateAdmin(null);
  const [scopeLevel, setScopeLevel] = useStateAdmin("");
  const [scopeCodes, setScopeCodes] = useStateAdmin([]);
  const [partnerCode, setPartnerCode] = useStateAdmin("");
  const [partners, setPartners] = useStateAdmin([]);
  const [note, setNote] = useStateAdmin("");

  // Partner list for the partner-level picker.
  useEffectAdmin(() => {
    if (scopeLevel !== "partner") return;
    let cancelled = false;
    fetch("/api/v1/partners/?page_size=200", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        const items = data.results || data || [];
        setPartners(items);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [scopeLevel]);

  // Reset downstream state when scope level changes.
  useEffectAdmin(() => {
    setScopeCodes([]);
    setPartnerCode("");
  }, [scopeLevel]);

  const isGeographic = _GEO_LEVELS_ORDER.includes(scopeLevel);
  const canSubmit = (
    !submitting && user && scopeLevel && (
      scopeLevel === "national"
      || (isGeographic && scopeCodes.length > 0)
      || (scopeLevel === "partner" && partnerCode)
    )
  );

  const submit = (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    const codes = scopeLevel === "national"
      ? []
      : (scopeLevel === "partner" ? [partnerCode] : scopeCodes);
    onSubmit({
      user_id: user.id,
      scope_level: scopeLevel,
      scope_codes: codes,
      note,
    });
  };

  return (
    <div
      role="dialog"
      aria-label="Grant operator scope"
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
          minWidth:"520px", maxWidth:"600px", maxHeight:"86vh",
          overflowY:"auto",
          boxShadow:"0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 className="t-h3" style={{marginTop:0}}>Grant operator scope</h3>
        <p className="t-bodysm muted" style={{marginTop:4, marginBottom:16}}>
          Assigns one or more ABAC scopes to a user. Geographic scopes pick a
          UBOS unit; partner scope ties the user to a partner organisation's
          data requests. National is the wildcard reserved for NSR Unit /
          DPO roles.
        </p>

        <div style={{marginBottom:16}}>
          <label className="t-cap" style={{display:"block", marginBottom:4}}>User</label>
          <UserPicker value={user} onChange={setUser} disabled={submitting}/>
          {user && (
            <p className="t-bodysm" style={{margin:"6px 0 0", color:"var(--accent-data)"}}>
              ✓ Selected: <strong>{user.username}</strong>
              {user.display_name !== user.username && ` — ${user.display_name}`}
            </p>
          )}
        </div>

        <div style={{marginBottom:16}}>
          <label className="t-cap" style={{display:"block", marginBottom:4}}>Scope level</label>
          <select
            value={scopeLevel} onChange={e => setScopeLevel(e.target.value)}
            disabled={submitting}
            style={{width:"100%", padding:"8px", border:"1px solid var(--neutral-300)",
                    borderRadius:"4px", fontSize:13}}
          >
            <option value="">— pick a level —</option>
            {_SCOPE_LEVEL_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {isGeographic && (
          <div style={{marginBottom:16}}>
            <GeoCascadePicker
              targetLevel={scopeLevel}
              value={scopeCodes}
              onChange={setScopeCodes}
              disabled={submitting}
            />
          </div>
        )}

        {scopeLevel === "partner" && (
          <div style={{marginBottom:16}}>
            <label className="t-cap" style={{display:"block", marginBottom:4}}>Partner</label>
            <select
              value={partnerCode} onChange={e => setPartnerCode(e.target.value)}
              disabled={submitting || partners.length === 0}
              style={{width:"100%", padding:"8px", border:"1px solid var(--neutral-300)",
                      borderRadius:"4px", fontSize:13}}
            >
              <option value="">— pick a partner —</option>
              {partners.map(p => (
                <option key={p.code} value={p.code}>{p.name} ({p.code})</option>
              ))}
            </select>
          </div>
        )}

        {scopeLevel === "national" && (
          <p className="t-bodysm" style={{marginBottom:16, color:"var(--accent-data)"}}>
            National scope grants visibility to every Household — reserved for NSR Unit Coordinator and DPO roles.
          </p>
        )}

        <div style={{marginBottom:20}}>
          <label className="t-cap" style={{display:"block", marginBottom:4}}>
            Note <span className="muted">(optional)</span>
          </label>
          <textarea
            value={note} onChange={e => setNote(e.target.value)}
            rows={2}
            disabled={submitting}
            placeholder="e.g. field-ops staff covering Wakiso + Kampala"
            style={{
              width:"100%", padding:"8px",
              border:"1px solid var(--neutral-300)", borderRadius:"4px",
              fontSize:13, fontFamily:"inherit", resize:"vertical",
            }}
          />
        </div>

        <div style={{display:"flex", justifyContent:"flex-end", gap:8}}>
          <button type="button" className="btn" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            type="submit" className="btn primary" disabled={!canSubmit}
            title={!canSubmit ? "Pick a user, a scope level, and at least one target" : ""}
          >
            {submitting ? "Granting…" : (
              isGeographic && scopeCodes.length > 1
                ? `Grant ${scopeCodes.length} scopes`
                : "Grant scope"
            )}
          </button>
        </div>
      </form>
    </div>
  );
};


// Revoke confirm modal — used for single-row revoke from the table.
const RevokeScopeConfirm = ({ row, onClose, onConfirm, submitting }) => (
  <div
    role="dialog"
    aria-label="Revoke operator scope"
    style={{
      position:"fixed", inset:0, background:"rgba(0,0,0,0.4)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:1000,
    }}
    onClick={() => !submitting && onClose()}
  >
    <div
      onClick={e => e.stopPropagation()}
      style={{
        background:"white", padding:"24px", borderRadius:"8px",
        minWidth:"420px", maxWidth:"520px",
        boxShadow:"0 8px 32px rgba(0,0,0,0.2)",
      }}
    >
      <h3 className="t-h3" style={{marginTop:0, color:"var(--accent-danger)"}}>
        Revoke scope?
      </h3>
      <p className="t-bodysm" style={{margin:"4px 0 16px"}}>
        Removes <strong>{_scopeLevelLabel(row.scope_level)}</strong>{" "}
        <span className="t-mono">{row.scope_label || row.scope_code || "*"}</span>{" "}
        from <strong>{row.username}</strong>. The audit event survives the
        deletion.
      </p>
      <div style={{display:"flex", justifyContent:"flex-end", gap:8}}>
        <button type="button" className="btn" onClick={onClose} disabled={submitting}>
          Cancel
        </button>
        <button
          type="button" className="btn"
          style={{
            background:"var(--accent-danger)", color:"white",
            borderColor:"var(--accent-danger)",
          }}
          onClick={onConfirm} disabled={submitting}
        >
          {submitting ? "Revoking…" : "Revoke"}
        </button>
      </div>
    </div>
  </div>
);


const OperatorScopesTab = () => {
  const [rows, setRows] = useStateAdmin([]);
  const [loading, setLoading] = useStateAdmin(true);
  const [error, setError] = useStateAdmin("");
  const [filterLevel, setFilterLevel] = useStateAdmin("");
  const [filterQ, setFilterQ] = useStateAdmin("");
  const [modalOpen, setModalOpen] = useStateAdmin(false);
  const [submitting, setSubmitting] = useStateAdmin(false);
  const [revokeTarget, setRevokeTarget] = useStateAdmin(null);
  const [revokeSubmitting, setRevokeSubmitting] = useStateAdmin(false);
  const [toast, setToast] = useStateAdmin("");
  // US-S11-042 — Impersonate-user modal state. Same surface area as
  // OperatorScope admin (this tab already has the user-search + the
  // nsr_admin gate), so it's a natural home.
  const [impersonateOpen, setImpersonateOpen] = useStateAdmin(false);

  const _fetchScopes = () => {
    setLoading(true); setError("");
    const qs = filterLevel ? `?scope_level=${encodeURIComponent(filterLevel)}` : "";
    fetch(`/api/v1/security/operator-scopes/${qs}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setLoading(false);
        if (!ok) {
          setError(body.detail || "Failed to load operator scopes.");
          return;
        }
        const items = body.results || body || [];
        setRows(items);
      })
      .catch(() => {
        setLoading(false);
        setError("Network error loading operator scopes.");
      });
  };

  useEffectAdmin(() => { _fetchScopes(); }, [filterLevel]);

  const visibleRows = useMemoAdmin(() => {
    if (!filterQ.trim()) return rows;
    const q = filterQ.toLowerCase();
    return rows.filter(r =>
      (r.username || "").toLowerCase().includes(q)
      || (r.display_name || "").toLowerCase().includes(q)
      || (r.scope_code || "").toLowerCase().includes(q)
      || (r.scope_label || "").toLowerCase().includes(q),
    );
  }, [rows, filterQ]);

  const grant = ({ user_id, scope_level, scope_codes, note }) => {
    setSubmitting(true);
    fetch("/api/v1/security/operator-scopes/bulk-grant/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": _adminCsrfToken(),
      },
      body: JSON.stringify({ user_id, scope_level, scope_codes, note }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setSubmitting(false);
        if (!ok) {
          setToast(`Grant failed: ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`);
          return;
        }
        setModalOpen(false);
        const g = body.granted?.length || 0;
        const s = body.skipped_existing?.length || 0;
        setToast(
          s > 0
            ? `Granted ${g}, skipped ${s} duplicate(s).`
            : `Granted ${g} scope(s).`,
        );
        _fetchScopes();
      })
      .catch(err => {
        setSubmitting(false);
        setToast(`Grant failed: ${err}`);
      });
  };

  const revoke = () => {
    if (!revokeTarget) return;
    setRevokeSubmitting(true);
    fetch(`/api/v1/security/operator-scopes/${revokeTarget.id}/`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": _adminCsrfToken(),
      },
    })
      .then(r => {
        setRevokeSubmitting(false);
        if (!r.ok && r.status !== 204) {
          setToast(`Revoke failed: HTTP ${r.status}`);
          return;
        }
        setRows(prev => prev.filter(x => x.id !== revokeTarget.id));
        setToast(
          `Revoked ${_scopeLevelLabel(revokeTarget.scope_level)} ${revokeTarget.scope_code || "*"} from ${revokeTarget.username}.`,
        );
        setRevokeTarget(null);
      })
      .catch(err => {
        setRevokeSubmitting(false);
        setToast(`Revoke failed: ${err}`);
      });
  };

  return (
    <>
      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">
            {loading
              ? "Loading…"
              : <>{visibleRows.length} of {rows.length} scopes</>}
          </strong>
          <div style={{flex:1}}/>
          <input
            type="text" placeholder="Filter by user or code"
            value={filterQ}
            onChange={e => setFilterQ(e.target.value)}
            style={{padding:"6px 8px", border:"1px solid var(--neutral-300)",
                    borderRadius:"4px", fontSize:12, marginRight:8, width:"200px"}}
          />
          <select
            value={filterLevel}
            onChange={e => setFilterLevel(e.target.value)}
            style={{padding:"6px 8px", border:"1px solid var(--neutral-300)",
                    borderRadius:"4px", fontSize:12, marginRight:8}}
          >
            <option value="">All levels</option>
            {_SCOPE_LEVEL_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button className="btn" onClick={() => setImpersonateOpen(true)}
                  title="Log into the console as another user (audit-bearing, read-only)">
            <Icon name="shield" size={13}/> Impersonate user
          </button>
          <button className="btn primary" onClick={() => setModalOpen(true)}>
            <Icon name="plus" size={13}/> Grant scope
          </button>
        </div>

        {error && (
          <p style={{padding:"12px 16px", color:"var(--accent-danger)", margin:0}}>{error}</p>
        )}

        <div style={{
          display:"grid",
          gridTemplateColumns:"1fr 130px 1fr 160px 100px 40px",
          borderBottom:"1px solid var(--neutral-200)",
          background:"var(--neutral-50)",
          fontSize:11, fontWeight:600, letterSpacing:"0.06em",
          textTransform:"uppercase", color:"var(--neutral-700)",
        }}>
          <div style={{padding:"10px 16px"}}>User</div>
          <div style={{padding:"10px 8px"}}>Level</div>
          <div style={{padding:"10px 8px"}}>Scope</div>
          <div style={{padding:"10px 8px"}}>Granted at</div>
          <div style={{padding:"10px 8px"}}>Active</div>
          <div style={{padding:"10px 8px"}}/>
        </div>

        {!loading && visibleRows.length === 0 && (
          <p style={{padding:"24px 16px", color:"var(--neutral-500)", margin:0}}>
            No scopes match the current filter. Click <strong>Grant scope</strong> to add one.
          </p>
        )}
        {visibleRows.map(r => (
          <div key={r.id} style={{
            display:"grid",
            gridTemplateColumns:"1fr 130px 1fr 160px 100px 40px",
            borderBottom:"1px solid var(--neutral-200)",
            alignItems:"center",
          }}>
            <div style={{padding:"12px 16px"}}>
              <div style={{fontSize:13, fontWeight:500}}>{r.username}</div>
              {r.display_name && r.display_name !== r.username && (
                <div className="muted" style={{fontSize:11}}>{r.display_name}</div>
              )}
            </div>
            <div style={{padding:"12px 8px", fontSize:12}}>
              <Chip size="sm" tone={r.scope_level === "national" ? "data" : (r.scope_level === "partner" ? "programme" : "neutral")}>
                {_scopeLevelLabel(r.scope_level)}
              </Chip>
            </div>
            <div style={{padding:"12px 8px", fontSize:12}}>
              {r.scope_label || r.scope_code || "*"}
            </div>
            <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
              {_formatRunDate(r.granted_at)}
            </div>
            <div style={{padding:"12px 8px"}}>
              <Chip size="sm" tone={r.active ? "data" : "neutral"}>
                {r.active ? "active" : "inactive"}
              </Chip>
            </div>
            <div style={{padding:"12px 8px", textAlign:"center"}}>
              <button
                type="button"
                aria-label={`Revoke scope ${r.id}`}
                title="Revoke scope"
                onClick={() => setRevokeTarget(r)}
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
        ))}
      </div>

      {modalOpen && (
        <GrantScopeModal
          onClose={() => !submitting && setModalOpen(false)}
          onSubmit={grant}
          submitting={submitting}
        />
      )}
      {revokeTarget && (
        <RevokeScopeConfirm
          row={revokeTarget}
          submitting={revokeSubmitting}
          onClose={() => !revokeSubmitting && setRevokeTarget(null)}
          onConfirm={revoke}
        />
      )}
      {impersonateOpen && (
        <ImpersonateUserModal
          onClose={() => setImpersonateOpen(false)}
          onSuccess={() => {
            // Reload so /me/ refreshes + the topbar banner appears.
            window.location.reload();
          }}
          onError={(msg) => setToast(`Impersonate failed: ${msg}`)}
        />
      )}
      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </>
  );
};


// ── ImpersonateUserModal (US-S11-042) ─────────────────────────────────
// Two-step: pick a user (search) → confirm with a reason → POST to
// /api/v1/security/impersonate/ → page reload. The banner across the
// top of the shell takes over from there.
const ImpersonateUserModal = ({ onClose, onSuccess, onError }) => {
  const [user, setUser] = useStateAdmin(null);
  const [reason, setReason] = useStateAdmin("");
  const [submitting, setSubmitting] = useStateAdmin(false);

  const canSubmit = !submitting && user && reason.trim();

  const submit = (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    fetch("/api/v1/security/impersonate/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": _adminCsrfToken(),
      },
      body: JSON.stringify({ user_id: user.id, reason: reason.trim() }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setSubmitting(false);
        if (!ok) {
          onError(typeof body.detail === "string" ? body.detail : "unknown error");
          return;
        }
        onSuccess(body);
      })
      .catch(err => {
        setSubmitting(false);
        onError(String(err));
      });
  };

  return (
    <div
      role="dialog" aria-label="Impersonate user"
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
          minWidth:"500px", maxWidth:"560px",
          boxShadow:"0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 className="t-h3" style={{marginTop:0}}>Impersonate user</h3>
        <p className="t-bodysm muted" style={{marginTop:4, marginBottom:12}}>
          Log into the console as the selected user. Writes are
          <strong> disabled</strong> in impersonation mode — this is
          read-only debugging. Audit chain captures both identities
          plus the reason; banner across the top reminds you you're
          impersonating until you stop.
        </p>

        <label className="t-cap" style={{display:"block", marginBottom:4}}>
          User
        </label>
        <UserPicker value={user} onChange={setUser} disabled={submitting}/>
        {user && (
          <p className="t-bodysm" style={{margin:"6px 0 12px", color:"var(--accent-data)"}}>
            ✓ Will impersonate: <strong>{user.username}</strong>
            {user.display_name !== user.username && ` — ${user.display_name}`}
          </p>
        )}

        <label className="t-cap" style={{display:"block", marginBottom:4, marginTop:8}}>
          Reason <span style={{color:"var(--accent-danger)"}}>*</span>
        </label>
        <textarea
          value={reason} onChange={e => setReason(e.target.value)}
          rows={2} disabled={submitting}
          placeholder="e.g. Debugging the DRS field-selector bug from ticket #847"
          style={{
            width:"100%", padding:"8px", marginBottom:16,
            border:"1px solid var(--neutral-300)", borderRadius:"4px",
            fontSize:13, fontFamily:"inherit", resize:"vertical",
          }}
        />

        <div style={{display:"flex", justifyContent:"flex-end", gap:8}}>
          <button type="button" className="btn" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            type="submit" className="btn"
            style={{background:"var(--accent-quality)", color:"white",
                    borderColor:"var(--accent-quality)"}}
            disabled={!canSubmit}
          >
            {submitting ? "Switching…" : "Impersonate"}
          </button>
        </div>
      </form>
    </div>
  );
};


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
      {tab === "scopes" && <OperatorScopesTab/>}
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
    // US-S11-028 OperatorScope pieces
    OperatorScopesTab,
    GrantScopeModal,
    GeoCascadePicker,
    UserPicker,
    RevokeScopeConfirm,
    _SCOPE_LEVEL_OPTIONS,
    _GEO_LEVELS_ORDER,
    _scopeLevelLabel,
  });
}
