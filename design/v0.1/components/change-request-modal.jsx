/* global React, Icon, Chip, Modal */
// NSR MIS — Open a change request (US-S22-003)
//
// Multi-row, multi-category change-request modal driven by a static
// field catalog and a deterministic routing matrix. The submit
// payload is the spec shape; the bundle endpoint at
// /api/v1/upd/change-requests/bundle/ accepts it directly.
//
// Three add-UX variants are supported (composer / picker / tree),
// switchable via the `addUx` prop. All three share the catalog +
// the already-added-disabled logic.
//
// Test surface lives at change-request-modal.test.jsx. Helpers
// (CATEGORIES, FIELDS_FLAT, routeFor, derivePmt) are exported on
// window for the test file to import without bundling.

const { useState: useCR, useEffect: useECR, useMemo: useMCR, useRef: useRCR } = React;

// ────────────────────────────────────────────────────────────────
// Field catalog — kept in lockstep with apps/update_workflow/field_catalog.py
// ────────────────────────────────────────────────────────────────
const CATEGORIES = [
  { key: "iden", label: "Identification",      tone: "identity",     fields: [
    { key: "phone",     label: "Phone",                type: "text",   pmt: false },
    { key: "email",     label: "Email",                type: "text",   pmt: false },
    { key: "head_name", label: "Head of household",    type: "text",   pmt: false },
    { key: "head_nin",  label: "Head NIN",             type: "text",   pmt: false },
    { key: "lang",      label: "Preferred language",   type: "select", pmt: false,
      options: ["English","Luganda","Swahili","Acholi","Karamojong","Lugbara","Runyankole"] },
  ]},
  { key: "loc", label: "Location",             tone: "data",         fields: [
    { key: "gps",         label: "GPS coordinates",   type: "text",   pmt: false },
    { key: "ea",          label: "Enumeration area",  type: "text",   pmt: false },
    { key: "urban_rural", label: "Urban / rural",     type: "select", pmt: true,
      // ADR-0010 seed codes (rural_urban: 1=Urban, 2=Rural).
      options: ["1","2"] },
    { key: "village",     label: "Village",           type: "text",   pmt: false },
    { key: "parish",      label: "Parish",            type: "text",   pmt: false },
  ]},
  { key: "rost", label: "Roster",              tone: "update",       fields: [
    { key: "hh_size",         label: "Household size",         type: "number", pmt: true },
    { key: "add_member",      label: "Add member (name)",      type: "text",   pmt: false },
    { key: "remove_member",   label: "Remove member (line #)", type: "number", pmt: false },
    { key: "member_name",     label: "Member name",            type: "text",   pmt: false },
    { key: "member_dob",      label: "Member date of birth",   type: "date",   pmt: false },
    { key: "member_sex",      label: "Member sex",             type: "select", pmt: false,
      // ADR-0010 seed codes (sex: 1=Male, 2=Female).
      options: ["1","2"] },
    { key: "member_relation", label: "Member relation to head", type: "text",   pmt: false },
  ]},
  { key: "hd", label: "Health & Disability",   tone: "danger",       fields: [
    { key: "disab",     label: "Disability status",          type: "select", pmt: true,
      options: ["none","mild","moderate","severe"] },
    { key: "chronic",   label: "Chronic illness",            type: "select", pmt: true,
      options: ["yes","no"] },
    { key: "u5_breg",   label: "Under-5 birth registration", type: "select", pmt: false,
      options: ["yes","no","partial"] },
    { key: "preg_lact", label: "Pregnant / lactating",       type: "select", pmt: false,
      options: ["yes","no"] },
  ]},
  { key: "ed", label: "Education",             tone: "programme",    fields: [
    { key: "ever_school", label: "Ever attended school", type: "select", pmt: true,
      options: ["yes","no"] },
    { key: "grade",       label: "Highest grade",        type: "text",   pmt: true },
    { key: "attending",   label: "Currently attending",  type: "select", pmt: false,
      options: ["yes","no"] },
  ]},
  { key: "emp", label: "Employment",           tone: "system",       fields: [
    { key: "occ",        label: "Primary occupation",  type: "text",   pmt: true },
    { key: "sector",     label: "Sector",              type: "select", pmt: true,
      options: ["agriculture","trade","services","manufacturing","public","none"] },
    { key: "income_src", label: "Main income source",  type: "text",   pmt: true },
  ]},
  { key: "hous", label: "Housing & Assets",    tone: "eligibility",  fields: [
    { key: "roof",        label: "Roof material",     type: "select", pmt: true,
      options: ["Iron sheets","Tiles","Thatch","Asbestos","Other"] },
    { key: "wall",        label: "Wall material",     type: "select", pmt: true,
      options: ["Brick","Mud","Wood","Iron sheets","Other"] },
    { key: "floor",       label: "Floor material",    type: "select", pmt: true,
      options: ["Cement","Earth","Tiles","Wood","Other"] },
    { key: "water",       label: "Water source",      type: "select", pmt: true,
      options: ["Tap","Borehole","Spring","River","Vendor","Other"] },
    { key: "toilet",      label: "Toilet type",       type: "select", pmt: true,
      options: ["Flush","Pit (covered)","Pit (open)","None","Other"] },
    { key: "fuel",        label: "Cooking fuel",      type: "select", pmt: true,
      options: ["Firewood","Charcoal","Gas","Electricity","Other"] },
    { key: "light",       label: "Lighting source",   type: "select", pmt: true,
      options: ["Electricity","Solar","Kerosene","Candle","Other"] },
    { key: "tenure",      label: "Dwelling tenure",   type: "select", pmt: true,
      options: ["Owned","Rented","Free","Other"] },
    { key: "land_acres",  label: "Land owned (acres)", type: "number", pmt: true },
    { key: "cattle",      label: "Cattle owned",       type: "number", pmt: true },
    { key: "goats",       label: "Goats owned",        type: "number", pmt: true },
    { key: "radio",       label: "Owns radio",         type: "select", pmt: true,
      options: ["yes","no"] },
    { key: "tv",          label: "Owns TV",            type: "select", pmt: true,
      options: ["yes","no"] },
    { key: "phone_owned", label: "Owns phone",         type: "select", pmt: true,
      options: ["yes","no"] },
  ]},
  { key: "food", label: "Food & Shocks",       tone: "quality",      fields: [
    { key: "meals",  label: "Meals per day",          type: "number", pmt: true },
    { key: "fcs",    label: "Food consumption score", type: "number", pmt: true },
    { key: "shock",  label: "Recent shock",           type: "select", pmt: true,
      options: ["drought","flood","death_head","theft","illness","none","other"] },
    { key: "coping", label: "Coping strategy",        type: "select", pmt: true,
      options: ["asset_sale","reduce_meals","skip_meal","borrow","migrate","none","other"] },
  ]},
];

// Flat lookup: "{category}:{field}" → { category, field, label, type, pmt, options? }
const FIELDS_FLAT = (() => {
  const out = {};
  for (const c of CATEGORIES) {
    for (const f of c.fields) {
      out[`${c.key}:${f.key}`] = { category: c.key, ...f, _categoryLabel: c.label, _tone: c.tone };
    }
  }
  return out;
})();

const CATEGORY_BY_KEY = Object.fromEntries(CATEGORIES.map(c => [c.key, c]));

// ────────────────────────────────────────────────────────────────
// Routing matrix — mirrors apps/update_workflow/routing.ROUTE_LABEL
// ────────────────────────────────────────────────────────────────
const ROUTING = {
  correction:    { cosmetic: "CDO (parish)",        pmt: "M&E Officer" },
  life_event:    { cosmetic: "CDO (parish)",        pmt: "M&E Officer" },
  verification:  { cosmetic: "CDO (parish)",        pmt: "M&E Officer" },
  address_move:  { cosmetic: "CDO + receiving CDO", pmt: "District M&E" },
  roster_change: { cosmetic: "CDO (parish)",        pmt: "District M&E" },
  asset_change:  { cosmetic: "CDO (parish)",        pmt: "District M&E" },
};

const routeFor = (change_type, pmt) =>
  ROUTING[change_type]?.[pmt ? "pmt" : "cosmetic"] || "—";

const CHANGE_TYPE_OPTIONS = [
  { value: "correction",    label: "Correction",        hint: "Fix incorrect data captured at registration." },
  { value: "life_event",    label: "Life event",        hint: "Birth, death, marriage. Affects roster." },
  { value: "verification",  label: "Verification",      hint: "Re-confirm an existing value (e.g., post-NIRA)." },
  { value: "address_move",  label: "Address move",      hint: "Household relocated — needs both CDOs." },
  { value: "roster_change", label: "Roster change",     hint: "Add / remove household members." },
  { value: "asset_change",  label: "Asset change",      hint: "Housing / assets updated; PMT impact likely." },
];

const ENTITY_OPTIONS = [
  { value: "household",   label: "This household" },
  { value: "member",      label: "A specific member…" },
  { value: "all_members", label: "All members" },
];

// Derive pmt_relevant from the picked rows. Any row whose catalog
// entry is PMT-relevant → derived true. The operator's manual
// Force-PMT checkbox can only raise (never lower) this.
const derivePmt = (rows) => rows.some(r => {
  const meta = FIELDS_FLAT[`${r.category}:${r.field}`];
  return !!meta?.pmt;
});

// Quick-add seeds for the empty state — the half-dozen common
// corrections operators reach for first.
const QUICK_ADDS = [
  { category: "iden", field: "phone" },
  { category: "hous", field: "roof" },
  { category: "rost", field: "hh_size" },
  { category: "loc",  field: "gps" },
  { category: "hous", field: "water" },
  { category: "emp",  field: "occ" },
];

// ────────────────────────────────────────────────────────────────
// Row inputs — keyed by field.type
// ────────────────────────────────────────────────────────────────
const RowInput = ({ meta, value, onChange, autoFocus }) => {
  const inputRef = useRCR(null);
  useECR(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);
  if (meta.type === "select") {
    return (
      <select ref={inputRef} className="field-select"
        value={value} onChange={(e) => onChange(e.target.value)}
        style={{ width:"100%" }}>
        <option value="">Select…</option>
        {meta.options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  return (
    <input ref={inputRef} type={meta.type === "number" ? "number"
                              : meta.type === "date" ? "date" : "text"}
      className="field-input"
      value={value} onChange={(e) => onChange(e.target.value)}
      placeholder={meta.type === "date" ? "" : "New value"}
      style={{ width:"100%" }}/>
  );
};

// ────────────────────────────────────────────────────────────────
// Add-row variants
// ────────────────────────────────────────────────────────────────

// Composer: dashed button → cascading category + field selects.
const AddComposer = ({ disabled, addedKeys, onAdd }) => {
  const [open, setOpen] = useCR(false);
  const [cat, setCat] = useCR("");
  const [fld, setFld] = useCR("");
  const cancel = () => { setOpen(false); setCat(""); setFld(""); };
  const fields = cat ? CATEGORY_BY_KEY[cat].fields : [];
  const canAdd = !!cat && !!fld;
  if (!open) {
    return (
      <button type="button" disabled={disabled}
        onClick={() => setOpen(true)}
        style={{
          width:"100%", padding:"12px 16px",
          background:"transparent",
          border:"2px dashed var(--neutral-300)", borderRadius:6,
          color:"var(--neutral-700)", cursor:"pointer", fontSize:13.5,
          display:"flex", alignItems:"center", justifyContent:"center", gap:6,
        }}>
        <Icon name="add" size={14}/> Add a field change
      </button>
    );
  }
  return (
    <div role="group" aria-label="Add a field"
      style={{ display:"grid",
               gridTemplateColumns:"1fr 1.4fr auto auto",
               gap:8, alignItems:"center",
               padding:"10px 12px", background:"var(--neutral-50)",
               border:"1px solid var(--neutral-200)", borderRadius:6 }}>
      <select className="field-select" value={cat}
        onChange={(e) => { setCat(e.target.value); setFld(""); }}>
        <option value="">Category…</option>
        {CATEGORIES.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
      </select>
      <select className="field-select" value={fld} disabled={!cat}
        onChange={(e) => setFld(e.target.value)}>
        <option value="">{cat ? "Field…" : "Pick a category first"}</option>
        {fields.map(f => {
          const k = `${cat}:${f.key}`;
          return (
            <option key={f.key} value={f.key} disabled={addedKeys.has(k)}>
              {f.label}{addedKeys.has(k) ? " (added)" : ""}
            </option>
          );
        })}
      </select>
      <button type="button" className="btn btn-sm" onClick={cancel}>Cancel</button>
      <button type="button" className="btn btn-sm btn-success"
        disabled={!canAdd}
        onClick={() => { onAdd(cat, fld); cancel(); }}>
        <Icon name="add" size={12}/> Add
      </button>
    </div>
  );
};

// Picker: a "Search registry fields to add…" button → search input +
// flat list of every (category, field) row.
const AddPicker = ({ disabled, addedKeys, onAdd }) => {
  const [open, setOpen] = useCR(false);
  const [q, setQ] = useCR("");
  const all = useMCR(() => Object.values(FIELDS_FLAT), []);
  const matches = useMCR(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return all;
    return all.filter(f =>
      f.label.toLowerCase().includes(needle)
      || f.key.toLowerCase().includes(needle)
      || f._categoryLabel.toLowerCase().includes(needle),
    );
  }, [q, all]);
  if (!open) {
    return (
      <button type="button" disabled={disabled} onClick={() => setOpen(true)}
        style={{
          width:"100%", padding:"12px 16px",
          background:"var(--neutral-50)",
          border:"1px solid var(--neutral-200)", borderRadius:6,
          color:"var(--neutral-700)", cursor:"pointer", fontSize:13.5,
          textAlign:"left", display:"flex", alignItems:"center", gap:6,
        }}>
        <Icon name="search" size={14}/> Search registry fields to add…
      </button>
    );
  }
  return (
    <div role="region" aria-label="Pick a field"
      style={{ border:"1px solid var(--neutral-200)", borderRadius:6,
               overflow:"hidden" }}>
      <div style={{ padding:"8px 10px", borderBottom:"1px solid var(--neutral-200)",
                    display:"flex", gap:6, alignItems:"center",
                    background:"var(--neutral-50)" }}>
        <Icon name="search" size={14}/>
        <input className="field-input" autoFocus
          placeholder="Search by category, field, or key…"
          value={q} onChange={(e) => setQ(e.target.value)}
          style={{ flex:1 }}/>
        <button type="button" className="btn btn-sm"
          onClick={() => { setOpen(false); setQ(""); }}>Done</button>
      </div>
      <div style={{ maxHeight:260, overflowY:"auto" }}>
        {matches.length === 0 && (
          <div style={{padding:"16px", color:"var(--neutral-500)", fontSize:13}}>
            No fields match “{q}”.
          </div>
        )}
        {matches.map(f => {
          const k = `${f.category}:${f.key}`;
          const taken = addedKeys.has(k);
          return (
            <div key={k} role="option"
              style={{
                display:"grid", gridTemplateColumns:"160px 1fr 80px 28px",
                gap:8, padding:"8px 12px",
                borderBottom:"1px solid var(--neutral-100)",
                alignItems:"center",
                opacity: taken ? 0.5 : 1,
                background: taken ? "var(--neutral-50)" : "white",
              }}>
              <Chip size="sm" tone={f._tone}>{f._categoryLabel}</Chip>
              <div style={{fontSize:13}}>
                <strong>{f.label}</strong>
                <span className="t-mono" style={{marginLeft:8, color:"var(--neutral-500)", fontSize:11}}>
                  {f.category}.{f.key}
                </span>
              </div>
              {f.pmt
                ? <Chip size="sm" tone="eligibility">PMT</Chip>
                : <span/>}
              <button type="button" className="icon-btn"
                disabled={taken}
                aria-label={`Add ${f.label}`}
                onClick={() => onAdd(f.category, f.key)}>
                <Icon name="add" size={14}/>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// Tree: each category folds out to its fields. Discovery-oriented.
const AddTree = ({ disabled, addedKeys, onAdd }) => {
  const [open, setOpen] = useCR(false);
  const [expanded, setExpanded] = useCR(() => new Set());
  const toggle = (key) => {
    const next = new Set(expanded);
    if (next.has(key)) { next.delete(key); } else { next.add(key); }
    setExpanded(next);
  };
  if (!open) {
    return (
      <button type="button" disabled={disabled} onClick={() => setOpen(true)}
        style={{
          width:"100%", padding:"12px 16px",
          background:"transparent",
          border:"1px solid var(--neutral-200)", borderRadius:6,
          color:"var(--neutral-700)", cursor:"pointer", fontSize:13.5,
          display:"flex", alignItems:"center", justifyContent:"center", gap:6,
        }}>
        <Icon name="duplicate" size={14}/> Browse fields by category
      </button>
    );
  }
  return (
    <div role="region" aria-label="Category tree"
      style={{ border:"1px solid var(--neutral-200)", borderRadius:6,
               overflow:"hidden" }}>
      <div style={{display:"flex", justifyContent:"space-between",
                    padding:"6px 10px", background:"var(--neutral-50)",
                    borderBottom:"1px solid var(--neutral-200)"}}>
        <span className="t-cap">{CATEGORIES.length} categories</span>
        <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>Done</button>
      </div>
      <div style={{ maxHeight:300, overflowY:"auto" }}>
        {CATEGORIES.map(c => {
          const isOpen = expanded.has(c.key);
          const hasPmt = c.fields.some(f => f.pmt);
          return (
            <div key={c.key}>
              <button type="button" onClick={() => toggle(c.key)}
                style={{
                  width:"100%", padding:"10px 12px",
                  display:"flex", alignItems:"center", gap:10,
                  background: isOpen ? "var(--neutral-50)" : "white",
                  borderBottom:"1px solid var(--neutral-100)",
                  border:0, cursor:"pointer", textAlign:"left",
                }}>
                <span style={{width:8, height:8, borderRadius:"50%",
                              background:`var(--accent-${c.tone})`}}/>
                <strong style={{fontSize:13.5}}>{c.label}</strong>
                <span className="t-cap">{c.fields.length} fields</span>
                {hasPmt && <Chip size="sm" tone="eligibility">PMT</Chip>}
                <span style={{flex:1}}/>
                <Icon name={isOpen ? "chevronDown" : "chevronRight"} size={14}/>
              </button>
              {isOpen && c.fields.map(f => {
                const k = `${c.key}:${f.key}`;
                const taken = addedKeys.has(k);
                return (
                  <div key={f.key}
                    style={{
                      display:"grid", gridTemplateColumns:"1fr 80px 28px",
                      gap:8, padding:"6px 12px 6px 32px",
                      borderBottom:"1px solid var(--neutral-100)",
                      alignItems:"center",
                      opacity: taken ? 0.5 : 1,
                      background: taken ? "var(--neutral-50)" : "white",
                    }}>
                    <div style={{fontSize:13}}>
                      {f.label}
                      <span className="t-mono" style={{marginLeft:8, color:"var(--neutral-500)", fontSize:11}}>
                        {f.key}
                      </span>
                    </div>
                    {f.pmt
                      ? <Chip size="sm" tone="eligibility">PMT</Chip>
                      : <span/>}
                    <button type="button" className="icon-btn"
                      disabled={taken}
                      aria-label={`Add ${f.label}`}
                      onClick={() => onAdd(c.key, f.key)}>
                      <Icon name="add" size={14}/>
                    </button>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ────────────────────────────────────────────────────────────────
// The modal
// ────────────────────────────────────────────────────────────────
// Format a current value for the "current: X" chip beside each row.
// Keys off the field meta so dates render as the EAT day, selects
// passthrough (codes match labels in the seeded ChoiceLists today),
// long strings truncate to keep the chip a fixed width.
const formatCurrent = (value, meta) => {
  if (value == null || value === "") return null;
  if (meta?.type === "date") {
    // YYYY-MM-DD on the wire; render as 14 May 2026 in the chip.
    const d = new Date(`${value}T00:00:00Z`);
    if (!Number.isNaN(d.getTime())) {
      const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    }
  }
  const s = String(value);
  return s.length > 28 ? s.slice(0, 26) + "…" : s;
};

const ChangeRequestModal = ({
  open,
  onClose,
  // Map of "category.field" → current value, projected by the consumer
  // from the household / member snapshot. Used to render "current: X"
  // beside each row so operators can verify the before-state without
  // opening another screen.
  currentValues = {},
  householdId,
  me,
  addUx = "composer", // "composer" | "picker" | "tree"
  borderLeftAccent = true,
  onSubmit,           // (payload) => Promise<{cr_id, audit_id, routed_to, ...}>
  onSuccess,          // (result, payload) => void
}) => {
  const [entity, setEntity]         = useCR("household");
  const [changeType, setChangeType] = useCR("correction");
  const [forcePmt, setForcePmt]     = useCR(false);
  const [rows, setRows]             = useCR([]);
  const [note, setNote]             = useCR("");
  const [busy, setBusy]             = useCR(false);
  const [error, setError]           = useCR("");
  const [focusFieldKey, setFocusFieldKey] = useCR("");

  // Reset every time the modal opens — operators expect a clean
  // sheet, not whatever they typed last time.
  useECR(() => {
    if (!open) return;
    setEntity("household");
    setChangeType("correction");
    setForcePmt(false);
    setRows([]);
    setNote("");
    setBusy(false);
    setError("");
    setFocusFieldKey("");
  }, [open]);

  const addedKeys = useMCR(
    () => new Set(rows.map(r => `${r.category}:${r.field}`)),
    [rows],
  );

  // Auto-derived PMT-relevance. Force-PMT can raise but not lower:
  // when derivedPmt is true the checkbox is disabled and stays on.
  const derivedPmt = useMCR(() => derivePmt(rows), [rows]);
  const pmtRelevant = derivedPmt || forcePmt;

  const reviewerLabel = routeFor(changeType, pmtRelevant);

  const valid =
    rows.length >= 1
    && rows.every(r => (r.value || "").trim().length > 0)
    && note.trim().length >= 6;

  const addRow = (category, field) => {
    if (addedKeys.has(`${category}:${field}`)) return;
    setRows(r => [...r, { category, field, value: "" }]);
    setFocusFieldKey(`${category}:${field}`);
    // The new row's input gets autoFocus=true and the input ref
    // calls .focus(); the surrounding grouped panel uses scrollIntoView
    // via a tiny rAF below.
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-row-key="${category}:${field}"]`);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
    });
  };

  const updateValue = (category, field, value) =>
    setRows(r => r.map(x => (x.category === category && x.field === field)
      ? { ...x, value } : x));

  const removeRow = (category, field) =>
    setRows(r => r.filter(x => !(x.category === category && x.field === field)));

  const clearAll = () => setRows([]);

  // Group rows by category. Order follows CATEGORIES so the rendered
  // layout matches the catalog (Identification first, etc.).
  const grouped = useMCR(() => {
    const map = new Map();
    for (const r of rows) {
      if (!map.has(r.category)) map.set(r.category, []);
      map.get(r.category).push(r);
    }
    return CATEGORIES
      .filter(c => map.has(c.key))
      .map(c => ({ category: c, rows: map.get(c.key) }));
  }, [rows]);

  const submit = async () => {
    if (!valid || !onSubmit) return;
    setBusy(true);
    setError("");
    const payload = {
      household_id: householdId,
      entity,
      change_type: changeType,
      pmt_relevant: pmtRelevant,
      rows: rows.map(r => ({
        category: r.category, field: r.field, new_value: r.value,
      })),
      note,
    };
    try {
      const result = await onSubmit(payload);
      onSuccess?.(result, payload);
      onClose?.();
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  // The note's remaining-chars hint surfaces only when under min.
  const noteRemaining = Math.max(0, 6 - note.trim().length);

  // Synthetic future audit id, just for the metadata caption — the
  // real audit_id comes back in the bundle response.
  const auditPlaceholder = `A-${new Date().toISOString().slice(0, 10)}-NEW`;

  return (
    <Modal open={open} onClose={() => !busy && onClose?.()}
      title="Open a change request"
      width={760}
      footer={
        <div style={{display:"flex", alignItems:"center", width:"100%", gap:12}}>
          <span className="t-cap" style={{flex:1}}>
            Routing: <strong>{reviewerLabel}</strong>
          </span>
          <button className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="btn btn-success" disabled={busy || !valid}
            onClick={submit}>
            <Icon name="check" size={14}/>
            {busy ? "Submitting…" : `Create & submit · ${rows.length} change${rows.length === 1 ? "" : "s"}`}
          </button>
        </div>
      }>
      <div className="col gap-4">
        {/* 1) Target strip */}
        <div style={{
          display:"grid", gridTemplateColumns:"1fr 1fr 1fr",
          gap:12, padding:16,
          background:"var(--neutral-50)",
          border:"1px solid var(--neutral-200)", borderRadius:6 }}>
          <label>
            <div className="t-cap">Entity</div>
            <select className="field-select" value={entity}
              onChange={(e) => setEntity(e.target.value)}>
              {ENTITY_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label>
            <div className="t-cap">Change type</div>
            <select className="field-select" value={changeType}
              onChange={(e) => setChangeType(e.target.value)}>
              {CHANGE_TYPE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <div className="t-bodysm muted" style={{marginTop:4, fontSize:12}}>
              {CHANGE_TYPE_OPTIONS.find(o => o.value === changeType)?.hint}
            </div>
          </label>
          <div>
            <div className="t-cap">PMT impact</div>
            <div className="row gap-2" style={{marginTop:2}}>
              {pmtRelevant
                ? <Chip tone="eligibility"><Icon name="target" size={11}/> pmt_relevant</Chip>
                : <Chip tone="neutral">cosmetic</Chip>}
            </div>
            <label style={{display:"flex", alignItems:"center", gap:6, marginTop:6}}>
              <input type="checkbox" checked={pmtRelevant}
                disabled={derivedPmt}
                onChange={(e) => setForcePmt(e.target.checked)}/>
              <span className="t-bodysm" style={{fontSize:12}}>
                Force PMT
              </span>
            </label>
            <div className="t-cap" style={{marginTop:2, fontSize:11}}>
              {derivedPmt
                ? "Auto-derived from a PMT field (locked)."
                : "Tick to force a PMT review."}
            </div>
          </div>
        </div>

        {/* 2) Field changes */}
        <div className="card" style={{padding:0,
          border:"1px solid var(--neutral-200)", borderRadius:6,
          boxShadow:"none"}}>
          <div style={{
            display:"flex", alignItems:"center", gap:8,
            padding:"10px 16px",
            borderBottom:"1px solid var(--neutral-200)",
            background:"white"}}>
            <strong style={{fontSize:13.5}}>Field changes</strong>
            <span className="t-cap">
              {rows.length} field{rows.length === 1 ? "" : "s"}
              {grouped.length > 0 && ` · ${grouped.length} categor${grouped.length === 1 ? "y" : "ies"}`}
            </span>
            <div style={{flex:1}}/>
            {rows.length > 0 && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={clearAll}>
                Clear all
              </button>
            )}
          </div>

          <div style={{padding:16, display:"flex", flexDirection:"column", gap:12}}>
            {rows.length === 0 && (
              <div className="col gap-3">
                <div className="t-bodysm muted" style={{textAlign:"center"}}>
                  No changes yet. Tap a quick-add or use the picker below.
                </div>
                <div style={{display:"flex", flexWrap:"wrap", gap:8,
                              justifyContent:"center"}}>
                  {QUICK_ADDS.map(({ category, field }) => {
                    const meta = FIELDS_FLAT[`${category}:${field}`];
                    if (!meta) return null;
                    return (
                      <button key={`${category}:${field}`} type="button"
                        onClick={() => addRow(category, field)}
                        style={{
                          display:"inline-flex", alignItems:"center", gap:6,
                          padding:"6px 12px", border:"1px solid var(--neutral-200)",
                          borderRadius:999, background:"white", cursor:"pointer",
                          fontSize:13, color:"var(--neutral-700)" }}>
                        <span style={{
                          width:8, height:8, borderRadius:"50%",
                          background:`var(--accent-${meta._tone})` }}/>
                        {meta.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {grouped.map(({ category, rows: groupRows }) => {
              const groupPmt = groupRows.some(r => {
                const meta = FIELDS_FLAT[`${r.category}:${r.field}`];
                return !!meta?.pmt;
              });
              return (
                <div key={category.key}
                  style={{
                    borderLeft: borderLeftAccent
                      ? `3px solid var(--accent-${category.tone})`
                      : "1px solid var(--neutral-200)",
                    background:"white",
                    border:"1px solid var(--neutral-200)",
                    borderLeftWidth: borderLeftAccent ? 3 : 1,
                    borderRadius:6,
                  }}>
                  <div style={{
                    padding:"8px 12px",
                    display:"flex", alignItems:"center", gap:8,
                    borderBottom:"1px solid var(--neutral-200)",
                    background:"var(--neutral-50)"}}>
                    <span style={{ width:8, height:8, borderRadius:"50%",
                                    background:`var(--accent-${category.tone})` }}/>
                    <strong style={{fontSize:13}}>{category.label}</strong>
                    <span className="t-cap">{groupRows.length} field{groupRows.length === 1 ? "" : "s"}</span>
                    {groupPmt && <Chip size="sm" tone="eligibility">PMT</Chip>}
                  </div>
                  <div>
                    {groupRows.map(r => {
                      const meta = FIELDS_FLAT[`${r.category}:${r.field}`];
                      const rowKey = `${r.category}:${r.field}`;
                      return (
                        <div key={rowKey} data-row-key={rowKey}
                          style={{
                            display:"grid",
                            gridTemplateColumns:"1.2fr 1.1fr 16px 1.4fr 28px",
                            gap:10, alignItems:"center",
                            padding:"8px 12px",
                            borderBottom:"1px solid var(--neutral-100)"}}>
                          <div style={{fontSize:13}}>
                            <strong>{meta.label}</strong>
                            <div className="t-mono" style={{fontSize:11, color:"var(--neutral-500)"}}>
                              {r.category}.{r.field}
                            </div>
                          </div>
                          {(() => {
                            const cv = currentValues[`${r.category}.${r.field}`];
                            const formatted = formatCurrent(cv, meta);
                            return formatted
                              ? <Chip size="sm" tone="neutral"
                                      title={String(cv)}
                                      data-testid={`current-${r.category}-${r.field}`}>
                                  current: {formatted}
                                </Chip>
                              : <Chip size="sm" tone="neutral"
                                      data-testid={`current-${r.category}-${r.field}`}>
                                  current —
                                </Chip>;
                          })()}
                          <Icon name="arrowRight" size={14} color="var(--neutral-500)"/>
                          <RowInput meta={meta} value={r.value}
                            autoFocus={focusFieldKey === rowKey}
                            onChange={(v) => updateValue(r.category, r.field, v)}/>
                          <button type="button" className="icon-btn"
                            aria-label={`Remove ${meta.label}`}
                            onClick={() => removeRow(r.category, r.field)}>
                            <Icon name="x" size={14}/>
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {/* Add-row affordance */}
            <div data-testid="add-row-zone">
              {addUx === "picker"
                ? <AddPicker  disabled={busy} addedKeys={addedKeys} onAdd={addRow}/>
                : addUx === "tree"
                ? <AddTree    disabled={busy} addedKeys={addedKeys} onAdd={addRow}/>
                : <AddComposer disabled={busy} addedKeys={addedKeys} onAdd={addRow}/>}
            </div>
          </div>
        </div>

        {/* 3) Requester note */}
        <div>
          <label className="t-cap">Requester note</label>
          <textarea rows={3}
            className="field-input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why this change? Written verbatim to the audit chain."
            style={{ width:"100%", marginTop:2 }}/>
          <div className="t-cap" style={{marginTop:4, fontSize:11}}>
            Written verbatim to the audit chain.
            {noteRemaining > 0 && (
              <span style={{color:"var(--accent-danger)", marginLeft:6}}>
                {noteRemaining} more char{noteRemaining === 1 ? "" : "s"} needed
              </span>
            )}
          </div>
        </div>

        {/* Error banner (post-submit failure) */}
        {error && (
          <div className="t-bodysm" style={{color:"var(--accent-danger)",
            padding:"8px 12px", background:"var(--neutral-50)",
            border:"1px solid var(--accent-danger)", borderRadius:6}}>
            {error}
          </div>
        )}

        {/* Metadata row */}
        <div className="t-cap" style={{fontSize:11}}>
          Requester <strong>{me?.username || "admin"}</strong> · Source <strong>web</strong> ·
          Will be audited as <span className="t-mono">{auditPlaceholder}</span>
        </div>
      </div>
    </Modal>
  );
};

// Export helpers + the component so the test file (and the household
// consumer) can pull them off `window` without a bundler.
Object.assign(window, {
  ChangeRequestModal,
  CR_CATEGORIES: CATEGORIES,
  CR_FIELDS_FLAT: FIELDS_FLAT,
  CR_ROUTING: ROUTING,
  routeFor,
  derivePmt,
});
