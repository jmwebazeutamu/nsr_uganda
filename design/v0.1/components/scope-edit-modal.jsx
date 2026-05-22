/* global React, Icon, Chip, Modal */
// NSR MIS — DSA scope-edit modal (US-S27-002, ADR-0016)
//
// Operator surface for POST /api/v1/dsas/{id}/edit-scope/. Pre-fills
// from the current DSA payload. On submit:
//
//   - draft DSA → backend mutates in place; modal closes, parent
//                 refreshes, same DSA id stays open.
//   - active DSA → backend clones to a v(N+1) draft, returns the
//                 new row. Modal closes, parent refreshes, and the
//                 onSuccess callback receives the new draft so the
//                 caller can switch focus to it.
//
// Mutable fields (per apps/partners/services/scope.py _SCALAR_SCOPE_FIELDS
// + _M2M_SCOPE_FIELD):
//   field_scope, entities_scope, monthly_row_budget,
//   sensitive_data_handling, retention_days, classification,
//   dpia_document_ref, breach_sla_hours, geographic_scope_ids.
//
// `geographic_scope_ids` is exposed as remove-only chips for v0.1.
// Adding new geographic units needs the picker that's already in the
// DRS query builder; reusing it here lands as a follow-up
// (OI-S27-SCOPE-GEO).
//
// Helpers (ENTITY_KEYS, FIELD_GROUP_KEYS, SENSITIVITY_OPTIONS,
// buildEditScopePayload, formatScopeError) are exported on window for
// the test file to pull off globalThis.

const { useState: useSEM, useEffect: useESEM, useMemo: useMSEM } = React;

// UBOS administrative levels (same order as `_GEO_CHAIN` in
// screens-drs-querybuilder.jsx). The picker defaults to sub_region —
// the level most DSAs scope at — but operators can pick any level.
const GEO_LEVELS = [
  { value: "region",     label: "Region" },
  { value: "sub_region", label: "Sub-region" },
  { value: "district",   label: "District" },
  { value: "county",     label: "County" },
  { value: "sub_county", label: "Sub-county" },
  { value: "parish",     label: "Parish" },
  { value: "village",    label: "Village" },
];

const GEO_LEVEL_LABEL = Object.fromEntries(
  GEO_LEVELS.map(l => [l.value, l.label]),
);

// Default API seam. Tests pass a stub via the `apiClient` prop so the
// network never actually fires. In the browser harness it falls back
// to window.nsrApi (US-S23-012). When window.nsrApi is missing (e.g.
// jsdom) both methods resolve to safe empties so the picker mounts
// without crashing — tests that exercise the picker pass an explicit
// stub.
const _defaultApiClient = () => ({
  fetchUnitsByLevel: (level) => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api) return Promise.resolve([]);
    return api.get(
      `/api/v1/reference-data/geographic-units/`
      + `?level=${encodeURIComponent(level)}`
      + `&status=active&page_size=500`,
    ).then(r => (r && r.results) || r || []);
  },
  fetchUnitById: (id) => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api) return Promise.resolve(null);
    return api.get(`/api/v1/reference-data/geographic-units/${id}/`);
  },
});

// Known entity flags that appear in entities_scope. The backend
// stores the JSONField verbatim, so unknown keys round-trip; the
// modal only renders checkboxes for the four documented entities.
const ENTITY_KEYS = [
  { key: "household",  label: "Household" },
  { key: "member",     label: "Member" },
  { key: "referral",   label: "Referral" },
  { key: "grievance",  label: "Grievance" },
];

// Known field-group keys that appear in field_scope. Same JSONField
// semantics — unknown keys round-trip untouched.
const FIELD_GROUP_KEYS = [
  { key: "Identifiers", label: "Identifiers" },
  { key: "PMT",         label: "PMT inputs" },
  { key: "Health",      label: "Health" },
  { key: "Education",   label: "Education" },
  { key: "Employment",  label: "Employment" },
  { key: "Housing",     label: "Housing & assets" },
  { key: "FoodShocks",  label: "Food & shocks" },
  { key: "Roster",      label: "Household roster" },
];

// sensitive_data_handling ChoiceList codes (ADR-0010 seed).
const SENSITIVITY_OPTIONS = [
  { value: "none",     label: "None — sensitive fields blocked (clause 4.2.b)" },
  { value: "specific", label: "Specific — opt-in clauses per field" },
  { value: "full",     label: "Full — sensitive fields included" },
];

// Build the JSON payload for /edit-scope/. Pure for testability.
// Returns the four scalar + two scope-dict + one M2M list payload
// the backend's allow-list expects.
const buildEditScopePayload = (form) => ({
  entities_scope: { ...form.entities_scope },
  field_scope: { ...form.field_scope },
  monthly_row_budget: Number(form.monthly_row_budget) || 0,
  sensitive_data_handling: form.sensitive_data_handling,
  retention_days: Number(form.retention_days) || 0,
  classification: form.classification || "",
  dpia_document_ref: form.dpia_document_ref || "",
  breach_sla_hours: Number(form.breach_sla_hours) || 0,
  geographic_scope_ids: [...form.geographic_scope_ids],
});

// Normalise an error from nsrApi.post into a user-visible string.
// DRF 400 responses come back as { detail: "…" } from ScopeEditError;
// other failures may have body strings or only a status code.
const formatScopeError = (err) => {
  if (!err) return "Unknown error.";
  const body = err.body;
  if (body && typeof body === "object" && body.detail) return String(body.detail);
  if (typeof body === "string" && body) return body;
  return String(err.message || err);
};

// Statuses that the backend accepts on /edit-scope/. Anything else
// raises ScopeEditError → 400. The trigger UI should already gate by
// status, but the modal mirrors the check so it never opens against
// an unhandled status.
const EDITABLE_STATUSES = new Set(["draft", "active"]);


// ────────────────────────────────────────────────────────────────
// The modal
// ────────────────────────────────────────────────────────────────
const ScopeEditModal = ({
  open,
  onClose,
  dsa,           // raw API DSA payload (must include id, status, version,
                 // entities_scope, field_scope, geographic_scope, …)
  me,
  onSubmit,      // (dsaId, payload) => Promise<dsaResponse>
                 //   default = nsrApi.post("/api/v1/dsas/{id}/edit-scope/", payload)
  onSuccess,     // (resultDsa, { cloned: bool }) => void
  apiClient,     // optional test seam:
                 //   { fetchUnitsByLevel(level), fetchUnitById(id) }
                 //   defaults to window.nsrApi-backed implementation.
}) => {
  const id = dsa?.id || "";
  const status = dsa?.status || "";
  const isActive = status === "active";
  const willClone = isActive;
  const blocked = !EDITABLE_STATUSES.has(status);

  // ── Form state ────────────────────────────────────────────────
  // Every field starts pre-filled from the source DSA on open. We
  // keep separate dicts for the two JSON scopes so unknown keys
  // survive a round-trip — only known checkboxes are rendered, but
  // unknown keys flow through buildEditScopePayload unchanged.
  const [entities, setEntities]           = useSEM({});
  const [fieldGroups, setFieldGroups]     = useSEM({});
  const [monthlyBudget, setMonthlyBudget] = useSEM("");
  const [sensitivity, setSensitivity]     = useSEM("none");
  const [retention, setRetention]         = useSEM("");
  const [classification, setClassification] = useSEM("");
  const [dpiaRef, setDpiaRef]             = useSEM("");
  const [breachSla, setBreachSla]         = useSEM("");
  const [geoIds, setGeoIds]               = useSEM([]);

  const [busy, setBusy] = useSEM(false);
  const [error, setError] = useSEM("");

  // geoLabels: { [unitId]: { name, level } }. Populated for every id
  // the picker adds (synchronously) and lazily for every id already
  // present in dsa.geographic_scope on open via fetchUnitById. Chips
  // render the resolved label when present and fall back to the id.
  const [geoLabels, setGeoLabels] = useSEM({});

  const api = apiClient || _defaultApiClient();

  useESEM(() => {
    if (!open || !dsa) return;
    setEntities({ ...(dsa.entities_scope || {}) });
    setFieldGroups({ ...(dsa.field_scope || {}) });
    setMonthlyBudget(dsa.monthly_row_budget == null ? "" : String(dsa.monthly_row_budget));
    setSensitivity(dsa.sensitive_data_handling || "none");
    setRetention(dsa.retention_days == null ? "" : String(dsa.retention_days));
    setClassification(dsa.classification || "");
    setDpiaRef(dsa.dpia_document_ref || "");
    setBreachSla(dsa.breach_sla_hours == null ? "" : String(dsa.breach_sla_hours));
    setGeoIds(Array.isArray(dsa.geographic_scope) ? [...dsa.geographic_scope] : []);
    setGeoLabels({});
    setBusy(false);
    setError("");
  }, [open, dsa]);

  // Resolve labels for ids already in geographic_scope on open. Each
  // fetch is fire-and-forget — a failure leaves the chip on its
  // truncated-id fallback rather than blocking the modal.
  useESEM(() => {
    if (!open || !dsa) return;
    const ids = Array.isArray(dsa.geographic_scope) ? dsa.geographic_scope : [];
    if (!ids.length) return;
    let cancelled = false;
    for (const id of ids) {
      Promise.resolve(api.fetchUnitById(id))
        .then((u) => {
          if (cancelled || !u) return;
          setGeoLabels(m => (m[id] ? m : { ...m, [id]: { name: u.name, level: u.level } }));
        })
        .catch(() => {});
    }
    return () => { cancelled = true; };
    // Only re-run when modal opens against a new DSA; geoLabels writes
    // would cause an infinite loop if listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dsa]);

  // Disabled-submit logic: classification and DPIA ref are free-text
  // and may legitimately be cleared, so the only hard precondition
  // here is that the form is bound to a DSA that the backend will
  // accept.
  const valid = !blocked && !!id;

  const toggleEntity = (key) =>
    setEntities((m) => ({ ...m, [key]: !m[key] }));

  const toggleFieldGroup = (key) =>
    setFieldGroups((m) => ({ ...m, [key]: !m[key] }));

  const removeGeo = (geoId) =>
    setGeoIds((ids) => ids.filter((x) => x !== geoId));

  // The picker passes back the full unit object so we get the label
  // for free (no extra round-trip). De-dupes against geoIds.
  const addGeoUnit = (unit) => {
    if (!unit || !unit.id) return;
    setGeoIds((ids) => (ids.includes(unit.id) ? ids : [...ids, unit.id]));
    setGeoLabels((m) => ({
      ...m, [unit.id]: { name: unit.name, level: unit.level },
    }));
  };

  const form = useMSEM(() => ({
    entities_scope: entities,
    field_scope: fieldGroups,
    monthly_row_budget: monthlyBudget,
    sensitive_data_handling: sensitivity,
    retention_days: retention,
    classification,
    dpia_document_ref: dpiaRef,
    breach_sla_hours: breachSla,
    geographic_scope_ids: geoIds,
  }), [entities, fieldGroups, monthlyBudget, sensitivity, retention,
       classification, dpiaRef, breachSla, geoIds]);

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    const payload = buildEditScopePayload(form);
    try {
      const fn = onSubmit
        || ((dsaId, body) => window.nsrApi.post(
          `/api/v1/dsas/${dsaId}/edit-scope/`, body));
      const result = await fn(id, payload);
      const cloned = result && result.id !== id;
      onSuccess?.(result, { cloned });
      onClose?.();
    } catch (e) {
      setError(formatScopeError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={() => !busy && onClose?.()}
      title={dsa
        ? `Edit DSA scope — ${dsa.reference || ""} v${dsa.version || ""}`
        : "Edit DSA scope"}
      width={760}
      footer={
        <div style={{display:"flex", alignItems:"center", width:"100%", gap:12}}>
          <span className="t-cap" style={{flex:1}}>
            {willClone
              ? <>This DSA is <strong>active</strong>. Saving will clone it to <strong>v{(dsa?.version || 0) + 1}</strong> draft for re-sign.</>
              : <>This DSA is <strong>{status || "—"}</strong>. Saving updates it in place.</>}
          </span>
          <button className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="btn btn-success"
            disabled={busy || !valid}
            onClick={submit}>
            <Icon name="check" size={14}/>
            {busy
              ? "Saving…"
              : (willClone ? "Save & clone to v+1" : "Save changes")}
          </button>
        </div>
      }>
      <div className="col gap-4">
        {/* Status banner — only shown when the modal opens against an
            unhandled status (defensive; the trigger UI should gate). */}
        {blocked && (
          <div className="t-bodysm" style={{color:"var(--accent-danger)",
            padding:"8px 12px", background:"var(--neutral-50)",
            border:"1px solid var(--accent-danger)", borderRadius:6}}>
            DSAs in status <strong>{status || "—"}</strong> cannot be scope-edited.
            Only <strong>draft</strong> and <strong>active</strong> DSAs are editable
            (ADR-0016 §"Decision 2").
          </div>
        )}

        {/* 1) Entities + field groups */}
        <div style={{
          display:"grid", gridTemplateColumns:"1fr 1fr",
          gap:12 }}>
          <ScopeCard title="Entities in scope"
            sub="Which record types the partner can pull.">
            <CheckboxGrid items={ENTITY_KEYS} values={entities}
              onToggle={toggleEntity} disabled={busy || blocked}/>
          </ScopeCard>

          <ScopeCard title="Field groups in scope"
            sub="Which field categories the partner can pull on those entities.">
            <CheckboxGrid items={FIELD_GROUP_KEYS} values={fieldGroups}
              onToggle={toggleFieldGroup} disabled={busy || blocked}/>
          </ScopeCard>
        </div>

        {/* 2) Sensitivity + classification */}
        <ScopeCard title="Sensitivity &amp; classification"
          sub="Sensitive-data handling drives the DAT-DQA mask layer (AC-DPO-SENS).">
          <div style={{
            display:"grid", gridTemplateColumns:"1.2fr 1fr 1fr",
            gap:12, padding:16 }}>
            <label className="col gap-1">
              <div className="t-cap">Sensitive data handling</div>
              <select className="field-select"
                value={sensitivity}
                disabled={busy || blocked}
                onChange={(e) => setSensitivity(e.target.value)}>
                {SENSITIVITY_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <label className="col gap-1">
              <div className="t-cap">Classification</div>
              <input className="field-input" type="text"
                value={classification}
                disabled={busy || blocked}
                onChange={(e) => setClassification(e.target.value)}
                placeholder="e.g. Internal-MDA"/>
            </label>
            <label className="col gap-1">
              <div className="t-cap">DPIA document ref</div>
              <input className="field-input t-mono" type="text"
                value={dpiaRef}
                disabled={busy || blocked}
                onChange={(e) => setDpiaRef(e.target.value)}
                placeholder="DPIA-OPM-2026-001"/>
            </label>
          </div>
        </ScopeCard>

        {/* 3) Volume & retention */}
        <ScopeCard title="Volume &amp; retention"
          sub="AC-DPO-VOL fires when the 30-day total exceeds the monthly budget.">
          <div style={{
            display:"grid", gridTemplateColumns:"1fr 1fr 1fr",
            gap:12, padding:16 }}>
            <label className="col gap-1">
              <div className="t-cap">Monthly row budget</div>
              <input className="field-input" type="number"
                value={monthlyBudget}
                disabled={busy || blocked}
                onChange={(e) => setMonthlyBudget(e.target.value)}
                placeholder="e.g. 250000"
                min="0"/>
            </label>
            <label className="col gap-1">
              <div className="t-cap">Retention (days post-project)</div>
              <input className="field-input" type="number"
                value={retention}
                disabled={busy || blocked}
                onChange={(e) => setRetention(e.target.value)}
                placeholder="e.g. 180"
                min="0"/>
            </label>
            <label className="col gap-1">
              <div className="t-cap">Breach SLA (hours)</div>
              <input className="field-input" type="number"
                value={breachSla}
                disabled={busy || blocked}
                onChange={(e) => setBreachSla(e.target.value)}
                placeholder="e.g. 72"
                min="0"/>
            </label>
          </div>
        </ScopeCard>

        {/* 4) Geographic scope */}
        <ScopeCard title={`Geographic scope · ${geoIds.length} unit${geoIds.length === 1 ? "" : "s"}`}
          sub="Narrow or widen the scope by removing or adding UBOS administrative units. Empty = partner's full national geography.">
          <div style={{padding:16, display:"flex", flexDirection:"column", gap:12}}>
            {geoIds.length === 0 ? (
              <div className="muted t-bodysm">
                No geographic units pinned. Scope spans the partner's full
                geography — add specific units below to narrow it.
              </div>
            ) : (
              <div data-testid="geo-chips"
                style={{display:"flex", flexWrap:"wrap", gap:6}}>
                {geoIds.map((gid) => {
                  const lbl = geoLabels[gid];
                  const text = lbl
                    ? `${lbl.name} · ${GEO_LEVEL_LABEL[lbl.level] || lbl.level}`
                    : `${String(gid).slice(0, 8)}…`;
                  return (
                    <span key={gid} data-testid="geo-chip"
                      data-geo-id={gid}
                      style={{display:"inline-flex", alignItems:"center", gap:6,
                              padding:"4px 8px",
                              border:"1px solid var(--neutral-200)",
                              borderRadius:999,
                              background:"var(--neutral-50)",
                              fontSize:12}}>
                      <span className={lbl ? "" : "t-mono"}>{text}</span>
                      <button type="button"
                        aria-label={`Remove geographic unit ${gid}`}
                        className="icon-btn"
                        disabled={busy || blocked}
                        onClick={() => removeGeo(gid)}
                        style={{padding:0, lineHeight:0,
                                background:"transparent", border:0,
                                cursor:"pointer"}}>
                        <Icon name="x" size={11}/>
                      </button>
                    </span>
                  );
                })}
              </div>
            )}

            <GeographicUnitPicker
              api={api}
              alreadyAdded={new Set(geoIds)}
              disabled={busy || blocked}
              onAdd={addGeoUnit}/>
          </div>
        </ScopeCard>

        {/* Error banner (post-submit failure) */}
        {error && (
          <div className="t-bodysm" data-testid="scope-edit-error"
            style={{color:"var(--accent-danger)",
              padding:"8px 12px", background:"var(--neutral-50)",
              border:"1px solid var(--accent-danger)", borderRadius:6}}>
            {error}
          </div>
        )}

        {/* Metadata row */}
        <div className="t-cap" style={{fontSize:11}}>
          Editor <strong>{me?.username || "admin"}</strong> · Source <strong>web</strong> ·
          Audit event <span className="t-mono">dsa_scope_changed</span>
          {willClone && (
            <> · v{(dsa?.version || 0) + 1} draft will need three signatures (ADR-0012)</>
          )}
        </div>
      </div>
    </Modal>
  );
};


// ────────────────────────────────────────────────────────────────
// Sub-components
// ────────────────────────────────────────────────────────────────
const ScopeCard = ({ title, sub, children }) => (
  <div className="card" style={{padding:0,
    border:"1px solid var(--neutral-200)", borderRadius:6,
    boxShadow:"none"}}>
    <div style={{
      padding:"10px 16px",
      borderBottom:"1px solid var(--neutral-200)",
      background:"white"}}>
      <strong style={{fontSize:13.5}}>{title}</strong>
      {sub && <div className="t-cap mt-1">{sub}</div>}
    </div>
    {children}
  </div>
);

const CheckboxGrid = ({ items, values, onToggle, disabled }) => (
  <div style={{padding:16, display:"grid",
    gridTemplateColumns:"1fr 1fr", gap:8}}>
    {items.map(({ key, label }) => (
      <label key={key}
        style={{display:"flex", alignItems:"center", gap:8,
                fontSize:13, color:"var(--neutral-900)",
                cursor: disabled ? "default" : "pointer"}}>
        <input type="checkbox"
          checked={!!values[key]}
          disabled={disabled}
          onChange={() => onToggle(key)}/>
        {label}
      </label>
    ))}
  </div>
);


// GeographicUnitPicker — level dropdown + unit dropdown + Add button.
// Lazy-loads units when the level changes via api.fetchUnitsByLevel.
// Skips the Add button (or marks it disabled) when the picked unit is
// already in alreadyAdded.
const GeographicUnitPicker = ({ api, alreadyAdded, disabled, onAdd }) => {
  const [level, setLevel] = useSEM("sub_region");
  const [units, setUnits] = useSEM([]);
  const [loading, setLoading] = useSEM(false);
  const [unitId, setUnitId] = useSEM("");
  const [err, setErr] = useSEM("");

  useESEM(() => {
    if (!level || !api) return;
    let cancelled = false;
    setLoading(true);
    setErr("");
    setUnitId("");
    Promise.resolve(api.fetchUnitsByLevel(level))
      .then((rows) => {
        if (cancelled) return;
        setUnits(Array.isArray(rows) ? rows : []);
      })
      .catch((e) => {
        if (cancelled) return;
        setUnits([]);
        setErr(formatScopeError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [level]);

  const picked = units.find((u) => u.id === unitId);
  const isDup = !!picked && alreadyAdded.has(picked.id);
  const canAdd = !!picked && !isDup && !disabled;

  return (
    <div data-testid="geo-picker"
      style={{display:"grid",
              gridTemplateColumns:"160px 1fr auto",
              gap:8, alignItems:"center",
              padding:"10px 12px",
              background:"var(--neutral-50)",
              border:"1px solid var(--neutral-200)",
              borderRadius:6}}>
      <label className="col gap-1" style={{minWidth:0}}>
        <span className="t-cap">Level</span>
        <select className="field-select"
          value={level}
          disabled={disabled}
          onChange={(e) => setLevel(e.target.value)}>
          {GEO_LEVELS.map(l => (
            <option key={l.value} value={l.value}>{l.label}</option>
          ))}
        </select>
      </label>
      <label className="col gap-1" style={{minWidth:0}}>
        <span className="t-cap">
          Unit{loading ? " · loading…" : units.length ? ` · ${units.length} available` : ""}
        </span>
        <select className="field-select"
          value={unitId}
          disabled={disabled || loading}
          onChange={(e) => setUnitId(e.target.value)}>
          <option value="">
            {loading ? "Loading…" : units.length ? "Pick a unit…" : "No units at this level"}
          </option>
          {units.map(u => (
            <option key={u.id} value={u.id}
              disabled={alreadyAdded.has(u.id)}>
              {u.name}{alreadyAdded.has(u.id) ? " (already added)" : ""}
            </option>
          ))}
        </select>
        {err && (
          <span className="t-cap" style={{color:"var(--accent-danger)"}}
            data-testid="geo-picker-error">
            {err}
          </span>
        )}
      </label>
      <button type="button" className="btn btn-sm btn-primary"
        disabled={!canAdd}
        onClick={() => {
          if (!picked) return;
          onAdd(picked);
          setUnitId("");
        }}
        style={{alignSelf:"end"}}>
        <Icon name="add" size={12}/>{" "}
        {isDup ? "Already added" : "Add to scope"}
      </button>
    </div>
  );
};


// Export helpers + the component for the test file.
Object.assign(window, {
  ScopeEditModal,
  ScopeEditModal_ENTITY_KEYS: ENTITY_KEYS,
  ScopeEditModal_FIELD_GROUP_KEYS: FIELD_GROUP_KEYS,
  ScopeEditModal_SENSITIVITY_OPTIONS: SENSITIVITY_OPTIONS,
  ScopeEditModal_GEO_LEVELS: GEO_LEVELS,
  buildEditScopePayload,
  formatScopeError,
});
