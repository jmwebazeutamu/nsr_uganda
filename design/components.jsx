/* global React */
// NSR MIS — Shared components & utilities

const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ============================================================
   Inline SVG icons (Lucide-style stroke set)
   ============================================================ */
const Icon = ({ name, size = 16, color = "currentColor", style }) => {
  const paths = {
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></>,
    bell: <><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></>,
    chevronRight: <path d="m9 6 6 6-6 6"/>,
    chevronDown: <path d="m6 9 6 6 6-6"/>,
    chevronLeft: <path d="m15 6-6 6 6 6"/>,
    chevronUp: <path d="m6 15 6-6 6 6"/>,
    check: <path d="M5 12.5 10 17l9-10"/>,
    checkCircle: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
    x: <path d="M6 6l12 12M6 18 18 6"/>,
    xCircle: <><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M9 15l6-6"/></>,
    alert: <><path d="M12 3 2 21h20Z"/><path d="M12 10v5"/><circle cx="12" cy="18" r="0.5" fill="currentColor"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 8v.5"/></>,
    home: <><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/></>,
    users: <><circle cx="9" cy="8" r="3.5"/><path d="M3 21c0-3 3-5 6-5s6 2 6 5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M21 21c0-2.5-2-4-4-4.5"/></>,
    inbox: <><path d="M3 13h5l1 3h6l1-3h5"/><path d="m4 6 1 7v6h14v-6l1-7"/><path d="M5 6h14"/></>,
    edit: <><path d="M15 4l5 5L8 21H3v-5z"/></>,
    duplicate: <><rect x="9" y="3" width="12" height="12" rx="2"/><rect x="3" y="9" width="12" height="12" rx="2"/></>,
    message: <><path d="M21 12a8 8 0 0 1-12 7l-6 2 2-6a8 8 0 1 1 16-3z"/></>,
    flag: <><path d="M4 21V4h14l-2 4 2 4H4"/></>,
    download: <><path d="M12 3v12m0 0-4-4m4 4 4-4"/><path d="M4 17v3h16v-3"/></>,
    barchart: <><path d="M3 21V5"/><path d="M9 21V11"/><path d="M15 21V8"/><path d="M21 21V3"/></>,
    shield: <><path d="M12 3l8 3v7c0 5-4 7-8 8-4-1-8-3-8-8V6Z"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 4.4 17l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.4l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1A2 2 0 1 1 19.6 7l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    minus: <path d="M5 12h14"/>,
    filter: <path d="M3 5h18l-7 9v6l-4-2v-4Z"/>,
    sort: <><path d="M7 4v16M3 8l4-4 4 4"/><path d="M17 20V4M13 16l4 4 4-4"/></>,
    moreH: <><circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/></>,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
    eyeOff: <><path d="M3 3l18 18"/><path d="M10.5 5.5A10.7 10.7 0 0 1 12 5c6 0 10 7 10 7a18 18 0 0 1-3.2 3.7M6.6 6.6C3.6 8.5 2 12 2 12s4 7 10 7c1.6 0 3-.4 4.3-1.1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    pause: <><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></>,
    play: <path d="M7 4v16l13-8Z"/>,
    refresh: <><path d="M21 12a9 9 0 0 1-15 7l-3-3"/><path d="M3 12a9 9 0 0 1 15-7l3 3"/><path d="M21 3v5h-5M3 21v-5h5"/></>,
    chevronsLeft: <path d="M11 6l-6 6 6 6M19 6l-6 6 6 6"/>,
    chevronsRight: <path d="M13 6l6 6-6 6M5 6l6 6-6 6"/>,
    file: <><path d="M14 3H6v18h12V8z"/><path d="M14 3v5h4"/></>,
    book: <><path d="M4 4h14a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2Z"/><path d="M4 19a2 2 0 0 1 2-2h14"/></>,
    lock: <><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></>,
    mapPin: <><path d="M12 21s-7-6.5-7-12a7 7 0 1 1 14 0c0 5.5-7 12-7 12Z"/><circle cx="12" cy="9" r="2.5"/></>,
    phone: <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></>,
    print: <><path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="9"/><path d="M6 15h12v6H6z"/></>,
    qr: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v3M14 20h3M20 20v1"/></>,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v5l3 2"/></>,
    arrowRight: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    arrowUp: <path d="M12 19V5m0 0-5 5m5-5 5 5"/>,
    arrowDown: <path d="M12 5v14m0 0-5-5m5 5 5-5"/>,
    camera: <><path d="M3 8h4l2-3h6l2 3h4v12H3z"/><circle cx="12" cy="13" r="4"/></>,
    save: <><path d="M5 3h11l4 4v14H5z"/><path d="M7 3v6h9V3M7 21v-8h10v8"/></>,
    target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></>,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>,
    git: <><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M6 8.5v3a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v-3M12 15v.5"/></>,
    sliders: <><path d="M4 6h10M4 12h6M4 18h14"/><circle cx="17" cy="6" r="2"/><circle cx="13" cy="12" r="2"/><circle cx="20" cy="18" r="2" fill="none"/></>,
  };
  const p = paths[name];
  if (!p) return <span style={{display:'inline-block', width: size, height: size}}/>;
  return (
    <svg className="icon-svg" width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" style={style}>
      {p}
    </svg>
  );
};

/* ============================================================
   Chip — covers all Section-8 statuses
   ============================================================ */
const CHIP_MAP = {
  // Registry lifecycle
  "Provisional":   { tone: "update",  dot: true },
  "Pending":       { tone: "quality", dot: true },
  "Registered":    { tone: "data",    dot: true, icon: "check" },
  "Rejected":      { tone: "danger",  dot: true },
  "Voided":        { tone: "neutral", dot: true },
  // Submission/CR
  "Draft":         { tone: "neutral" },
  "Submitted":     { tone: "update" },
  "Pending QA":    { tone: "quality" },
  "Accepted":      { tone: "data" },
  "Pending Approval": { tone: "update" },
  "Approved":      { tone: "data" },
  "Committed":     { tone: "data" },
  "Reversed":      { tone: "neutral" },
  // Dedup
  "Merged":        { tone: "data" },
  "On hold":       { tone: "quality" },
  "Cross-household": { tone: "identity" },
  // Connector run
  "Queued":        { tone: "neutral" },
  "Running":       { tone: "update", dot: true },
  "Completed":     { tone: "data" },
  "Failed":        { tone: "danger" },
  "Cancelled":     { tone: "neutral" },
  // DRS
  "Pending DPO review": { tone: "quality" },
  "Generating":    { tone: "update" },
  "Delivered":     { tone: "data" },
  "Expired":       { tone: "neutral" },
  "Revoked":       { tone: "danger" },
  // Grievance
  "Open":          { tone: "grm" },
  "In progress":   { tone: "update" },
  "Awaiting citizen response": { tone: "quality" },
  "Resolved":      { tone: "data" },
  "Closed":        { tone: "neutral" },
  // DQA
  "Blocking":      { tone: "danger" },
  "Warning":       { tone: "quality" },
  "Info":          { tone: "system" },
  // Sensitivity
  "Public":        { tone: "system" },
  "Internal":      { tone: "programme" },
  "Personal":      { tone: "eligibility" },
  "Sensitive":     { tone: "danger", icon: "lock" },
};
const Chip = ({ children, tone, dot, icon, size, style }) => {
  const m = CHIP_MAP[children] || {};
  const t = tone || m.tone || "neutral";
  const showDot = dot ?? m.dot ?? false;
  const ic = icon || m.icon;
  return (
    <span className={`chip chip-${t} ${size === 'sm' ? 'chip-sm' : ''}`} style={style}>
      {showDot && <span className="chip-dot"/>}
      {ic && <Icon name={ic} size={11}/>}
      {children}
    </span>
  );
};

/* ============================================================
   KPI card
   ============================================================ */
const KPI = ({ title, value, suffix, trend, trendValue, foot, spark }) => (
  <div className="kpi">
    <div className="kpi-title">{title}</div>
    <div className="kpi-value">{value}{suffix && <span style={{fontSize:'18px', marginLeft:4, color:'var(--neutral-500)'}}>{suffix}</span>}</div>
    <div className="kpi-foot">
      {trend && (
        <span className={`kpi-trend ${trend}`}>
          <Icon name={trend === 'up' ? 'arrowUp' : trend === 'down' ? 'arrowDown' : 'arrowRight'} size={12}/>
          {trendValue}
        </span>
      )}
      {foot && <span>{foot}</span>}
    </div>
    {spark && <Sparkline className="kpi-spark" points={spark} color={trend === 'down' ? 'var(--accent-danger)' : 'var(--accent-data)'}/>}
  </div>
);

const Sparkline = ({ points, color = 'var(--accent-data)', className }) => {
  const w = 64, h = 24, pad = 1;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const xs = points.map((_, i) => pad + i * (w - 2*pad) / (points.length - 1));
  const ys = points.map(v => h - pad - ((v - min) / span) * (h - 2*pad));
  const d = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${ys[i].toFixed(1)}`).join(' ');
  return (
    <svg className={className} viewBox={`0 0 ${w} ${h}`} fill="none">
      <path d={d} stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
};

/* ============================================================
   Modal
   ============================================================ */
const Modal = ({ open, onClose, title, children, footer, width = 480 }) => {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ maxWidth: width }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="t-h2">{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x"/></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
};

/* ============================================================
   Reason-required modal — used for Approve/Reject/etc.
   ============================================================ */
const ReasonModal = ({ open, title, intent, onClose, onConfirm, reasonOptions, recordLabel, defaultNote = "" }) => {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState(defaultNote);
  useEffect(() => { if (open) { setReason(""); setNote(defaultNote || ""); } }, [open, defaultNote]);
  const canSubmit = reason && note.trim().length >= 6;
  return (
    <Modal open={open} onClose={onClose} title={title}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button
          className={`btn ${intent === 'danger' ? 'btn-danger' : intent === 'success' ? 'btn-success' : 'btn-primary'}`}
          disabled={!canSubmit}
          onClick={() => onConfirm?.({ reason, note })}
        >
          {intent === 'danger' ? 'Confirm reject' : intent === 'success' ? 'Confirm approve' : 'Confirm'}
        </button>
      </>}
    >
      <div className="col gap-4">
        {recordLabel && (
          <div className="t-bodysm muted">Action will be applied to <span className="t-mono" style={{color:'var(--neutral-900)'}}>{recordLabel}</span></div>
        )}
        <div className="field">
          <label className="field-label">Reason <span className="req">*</span></label>
          <select className="field-select" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Select a reason…</option>
            {(reasonOptions || []).map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <span className="field-help">Reason is written to the audit chain.</span>
        </div>
        <div className="field">
          <label className="field-label">Note <span className="req">*</span></label>
          <textarea className="field-textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="Add context for the audit record (min 6 chars)." />
        </div>
        <div className="t-cap" style={{display:'flex',alignItems:'center',gap:6}}>
          <Icon name="shield" size={12}/> All actions are written to the audit chain (AC-AUDIT-EVENT).
        </div>
      </div>
    </Modal>
  );
};

/* ============================================================
   Action bar
   ============================================================ */
const ActionBar = ({ left, children }) => (
  <div className="action-bar">
    <div className="ab-info">{left}</div>
    <div style={{flex:1}}/>
    {children}
  </div>
);

/* ============================================================
   Field block
   ============================================================ */
const Field = ({ label, required, hint, error, children }) => (
  <div className="field">
    <label className="field-label">{label}{required && <span className="req">*</span>}</label>
    {children}
    {hint && !error && <span className="field-help">{hint}</span>}
    {error && <span className="field-error">{error}</span>}
  </div>
);

/* ============================================================
   Geographic Tree Picker
   ============================================================
   Drills the full UBOS hierarchy live from
   /api/v1/reference-data/geographic-units/.
   7 levels: region → sub_region → district → county → sub_county →
   parish → village. (County is needed as a traversal step because
   sub_counties FK to counties, not districts — even though many
   questionnaires collapse county away in their final payload.)
   Each <select> fetches its options on demand keyed by the parent's
   `code`. parent_code="" returns top-level rows (regions). */

// One <GeoLevel/> per drop-down. Lazily fetches its options when
// either the level itself changes or its parent code changes. Reads
// `useApi` off the global so this stays loadable before
// api-client.jsx parses (Babel-standalone resolves globals at
// invocation time).
const GeoLevel = ({ label, level, parentCode, parentReady, value, onSelect, placeholder, optional = false }) => {
  const url = parentReady
    ? `/api/v1/reference-data/geographic-units/?level=${encodeURIComponent(level)}&parent_code=${encodeURIComponent(parentCode || "")}&status=active`
    : null;
  const useApiHook = (typeof window !== "undefined" && window.useApi) ? window.useApi : null;
  const [resp, meta] = useApiHook
    ? useApiHook(url)
    : [null, { loading: false, error: null }];
  const rows = (resp && Array.isArray(resp.results))
    ? resp.results
    : (Array.isArray(resp) ? resp : []);
  const loading = meta && meta.loading;
  return (
    <Field label={optional ? `${label} (optional)` : label} required={!optional}>
      <select className="field-select"
        value={value || ""}
        disabled={!parentReady || loading}
        onChange={(e) => onSelect && onSelect(e.target.value)}>
        <option value="">
          {!parentReady ? placeholder : (loading ? "Loading…" : "Select…")}
        </option>
        {rows.map(r => (
          <option key={r.code} value={r.code}>{r.name}</option>
        ))}
      </select>
    </Field>
  );
};

const GeoTreePicker = ({ value, onChange }) => {
  const v = value || {};
  const set = (k, val) => {
    const next = { ...v, [k]: val };
    // Cascading reset — clear every descendant level on a change.
    const chain = ["region", "subregion", "district", "county", "subcounty", "parish", "village"];
    const idx = chain.indexOf(k);
    if (idx >= 0) {
      chain.slice(idx + 1).forEach((c) => { next[c] = ""; });
    }
    onChange && onChange(next);
  };
  return (
    <div className="col gap-3">
      <div className="field-row-3">
        <GeoLevel label="Region" level="region"
          parentCode="" parentReady={true}
          value={v.region}
          onSelect={(c) => set("region", c)}/>
        <GeoLevel label="Sub-region" level="sub_region"
          parentCode={v.region} parentReady={!!v.region}
          placeholder="Choose region first"
          value={v.subregion}
          onSelect={(c) => set("subregion", c)}/>
        <GeoLevel label="District" level="district"
          parentCode={v.subregion} parentReady={!!v.subregion}
          placeholder="Choose sub-region first"
          value={v.district}
          onSelect={(c) => set("district", c)}/>
      </div>
      <div className="field-row-3">
        <GeoLevel label="County" level="county"
          parentCode={v.district} parentReady={!!v.district}
          placeholder="Choose district first"
          value={v.county}
          onSelect={(c) => set("county", c)}/>
        <GeoLevel label="Sub-county" level="sub_county"
          parentCode={v.county} parentReady={!!v.county}
          placeholder="Choose county first"
          value={v.subcounty}
          onSelect={(c) => set("subcounty", c)}/>
        <GeoLevel label="Parish" level="parish"
          parentCode={v.subcounty} parentReady={!!v.subcounty}
          placeholder="Choose sub-county first"
          value={v.parish}
          onSelect={(c) => set("parish", c)}/>
      </div>
      <div className="field-row-3">
        <GeoLevel label="Village" level="village"
          parentCode={v.parish} parentReady={!!v.parish}
          placeholder="Choose parish first"
          value={v.village}
          onSelect={(c) => set("village", c)}
          optional/>
        <Field label="Enumeration Area" required hint="UBOS 2024 EA frame">
          <input className="field-input" placeholder="EA-7411-002" defaultValue="EA-7411-002"/>
        </Field>
        <Field label=""/>
      </div>
    </div>
  );
};

/* ============================================================
   Audit panel drawer
   ============================================================ */
const AuditDrawer = ({ open, onClose, events = [], title = "Audit chain" }) => (
  <>
    <div className={`drawer-backdrop ${open ? 'open' : ''}`} onClick={onClose}/>
    <aside className={`drawer ${open ? 'open' : ''}`} aria-hidden={!open}>
      <div className="drawer-header">
        <div>
          <div className="t-cap">RECORD HISTORY</div>
          <h3 className="t-h2" style={{margin:'2px 0 0'}}>{title}</h3>
        </div>
        <button className="icon-btn" onClick={onClose}><Icon name="x"/></button>
      </div>
      <div className="drawer-body">
        <div className="drawer-filter">
          <div className="row gap-2">
            <select className="field-select" style={{height:30}}><option>All actors</option><option>NSR Unit</option><option>CDO</option><option>System</option></select>
            <select className="field-select" style={{height:30}}><option>All actions</option><option>Created</option><option>Approved</option><option>Rejected</option><option>Update</option></select>
          </div>
        </div>
        {events.map((e, i) => (
          <div className="audit-row" key={i}>
            <div className="audit-avatar" style={{ background: e.tone === 'system' ? 'var(--neutral-200)' : 'var(--primary-100)', color: e.tone === 'system' ? 'var(--neutral-700)' : 'var(--primary-900)' }}>
              {e.who.split(' ').map(s => s[0]).slice(0,2).join('')}
            </div>
            <div>
              <div className="audit-action">{e.who} <span style={{fontWeight:400, color:'var(--neutral-700)'}}>{e.action}</span></div>
              <div className="audit-detail">{e.detail}</div>
              <div className="t-cap" style={{marginTop:4}}>Audit ID <span className="t-mono">{e.audit}</span></div>
            </div>
            <div className="audit-time">{e.time}</div>
          </div>
        ))}
        <div style={{padding:24, textAlign:'center'}} className="t-cap">End of audit chain ({events.length} events)</div>
      </div>
    </aside>
  </>
);

/* ============================================================
   Toast
   ============================================================ */
const Toast = ({ message, onDone, duration = 3000 }) => {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => onDone?.(), duration);
    return () => clearTimeout(t);
  }, [message]);
  if (!message) return null;
  return <div className="toast" role="status">{message}</div>;
};

/* ============================================================
   Page chrome helper
   ============================================================ */
const PageHeader = ({ eyebrow, title, sub, right }) => (
  <div className="page-header">
    <div>
      {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
      <h1 className="page-title t-h1">{title}</h1>
      {sub && <div className="page-sub">{sub}</div>}
    </div>
    {right && <div className="row gap-3">{right}</div>}
  </div>
);

/* ============================================================
   Helper — initials
   ============================================================ */
const initials = (name) => name.split(/\s+/).map(s => s[0]).slice(0,2).join('').toUpperCase();

/* ============================================================
   Export to global scope so other scripts can use
   ============================================================ */
Object.assign(window, {
  Icon, Chip, KPI, Sparkline,
  Modal, ReasonModal,
  ActionBar, Field, GeoTreePicker, AuditDrawer, Toast, PageHeader,
  initials,
});
