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
    { key: "member_name",     label: "Member name",            type: "text",   pmt: false, entity: "member" },
    { key: "member_dob",      label: "Member date of birth",   type: "date",   pmt: false, entity: "member" },
    { key: "member_sex",      label: "Member sex",             type: "select", pmt: false, entity: "member",
      // ADR-0010 seed codes (sex: 1=Male, 2=Female).
      options: ["1","2"] },
    { key: "member_relation", label: "Member relation to head", type: "text",   pmt: false, entity: "member" },
  ]},
  { key: "hd", label: "Health & Disability",   tone: "danger",       fields: [
    { key: "disab",     label: "Disability status",          type: "select", pmt: true, entity: "member",
      options: ["none","mild","moderate","severe"] },
    { key: "chronic",   label: "Chronic illness",            type: "select", pmt: true, entity: "member",
      options: ["yes","no"] },
    { key: "u5_breg",   label: "Under-5 birth registration", type: "select", pmt: false, entity: "member",
      options: ["yes","no","partial"] },
    { key: "preg_lact", label: "Pregnant / lactating",       type: "select", pmt: false, entity: "member",
      options: ["yes","no"] },
  ]},
  { key: "ed", label: "Education",             tone: "programme",    fields: [
    { key: "ever_school", label: "Ever attended school", type: "select", pmt: true, entity: "member",
      options: ["yes","no"] },
    { key: "grade",       label: "Highest grade",        type: "text",   pmt: true, entity: "member" },
    { key: "attending",   label: "Currently attending",  type: "select", pmt: false, entity: "member",
      options: ["yes","no"] },
  ]},
  { key: "emp", label: "Employment",           tone: "system",       fields: [
    { key: "occ",        label: "Primary occupation",  type: "text",   pmt: true, entity: "member" },
    { key: "sector",     label: "Sector",              type: "select", pmt: true, entity: "member",
      options: ["agriculture","trade","services","manufacturing","public","none"] },
    { key: "income_src", label: "Main income source",  type: "text",   pmt: true, entity: "member" },
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
// Live catalog fetch (US-S28-CATALOG)
// ────────────────────────────────────────────────────────────────
// The modal fetches /api/v1/upd/field-catalog/ on mount and uses the
// response as the source of truth for category list, field metadata,
// and SELECT options (resolved against the active ChoiceList version
// for any field tagged `choice_list` in the backend catalog).
//
// On unreachable API (file:// preview, 401, network error) the hook
// silently returns the hardcoded CATEGORIES so the design preview
// keeps working. Same fall-through pattern as every other live-wired
// screen in this codebase.
const _liveCatalogToFlat = (categories) => {
  const out = {};
  for (const c of categories) {
    for (const f of c.fields) {
      out[`${c.key}:${f.key}`] = {
        category: c.key, ...f, _categoryLabel: c.label, _tone: c.tone,
      };
    }
  }
  return out;
};

const useFieldCatalog = () => {
  const [state, setState] = useCR({
    categories: CATEGORIES,
    fieldsFlat: FIELDS_FLAT,
    source: "fallback",  // "fallback" | "live"
  });
  useECR(() => {
    let cancelled = false;
    fetch("/api/v1/upd/field-catalog/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        const cats = Array.isArray(data?.categories) ? data.categories : null;
        if (!cats || cats.length === 0) return;
        setState({
          categories: cats,
          fieldsFlat: _liveCatalogToFlat(cats),
          source: "live",
        });
      })
      .catch(() => { /* keep fallback */ });
    return () => { cancelled = true; };
  }, []);
  return state;
};

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
// `fieldsFlat` defaults to the module-level constant so the existing
// unit tests can call derivePmt(rows) without passing the live
// catalog; the component overrides it with the fetched catalog.
const derivePmt = (rows, fieldsFlat = FIELDS_FLAT) => rows.some(r => {
  const meta = fieldsFlat[`${r.category}:${r.field}`];
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
    // Normalise options so the renderer works for both the legacy
    // fallback shape (["Iron sheets", "Tiles", …]) and the live API
    // shape ([{code: "01", label: "Iron sheets"}, …]). Wire value is
    // always the `code`.
    const options = (meta.options || []).map(o =>
      typeof o === "string" ? { code: o, label: o } : o
    );
    return (
      <select ref={inputRef} className="field-select"
        value={value} onChange={(e) => onChange(e.target.value)}
        style={{ width:"100%" }}>
        <option value="">Select…</option>
        {options.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
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
// `categories` is the visible-by-entity-scope subset (defaults to the
// full catalog for backward-compat).
const AddComposer = ({ disabled, addedKeys, onAdd, categories = CATEGORIES }) => {
  const catByKey = useMCR(
    () => Object.fromEntries(categories.map(c => [c.key, c])),
    [categories],
  );
  const [open, setOpen] = useCR(false);
  const [cat, setCat] = useCR("");
  const [fld, setFld] = useCR("");
  const cancel = () => { setOpen(false); setCat(""); setFld(""); };
  const fields = cat ? (catByKey[cat]?.fields || []) : [];
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
        {categories.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
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
// flat list of every (category, field) row. `fieldsFlat` defaults to
// the global FIELDS_FLAT; the modal passes a filtered subset when the
// entity scope is restricted (member-only flow).
const AddPicker = ({ disabled, addedKeys, onAdd, fieldsFlat = FIELDS_FLAT }) => {
  const [open, setOpen] = useCR(false);
  const [q, setQ] = useCR("");
  const all = useMCR(() => Object.values(fieldsFlat), [fieldsFlat]);
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
// `categories` honors the entity-scope filter passed by the modal.
const AddTree = ({ disabled, addedKeys, onAdd, categories = CATEGORIES }) => {
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
        <span className="t-cap">{categories.length} categories</span>
        <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>Done</button>
      </div>
      <div style={{ maxHeight:300, overflowY:"auto" }}>
        {categories.map(c => {
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
  // Roster for the member picker. Items: {id, name, line, relationship,
  // dob, sex}. The modal needs at least `id` + `name` per row; the
  // rest decorate the member info card.
  members = [],
  // Per-member current values, keyed by member id:
  //   { "01HMEM…": { "hd.chronic": "no", "ed.grade": "P5", … } }
  // Merged with `currentValues` for the selected member when entity
  // = "member". Consumers leave this empty if they don't have it.
  memberValues = {},
  householdId,
  me,
  addUx = "composer", // "composer" | "picker" | "tree"
  borderLeftAccent = true,
  onSubmit,           // (payload) => Promise<{cr_id, audit_id, routed_to, ...}>
  onSuccess,          // (result, payload) => void
}) => {
  const [entity, setEntity]         = useCR("household");
  const [memberId, setMemberId]     = useCR("");
  const [changeType, setChangeType] = useCR("correction");
  const [forcePmt, setForcePmt]     = useCR(false);
  const [rows, setRows]             = useCR([]);
  const [note, setNote]             = useCR("");
  const [busy, setBusy]             = useCR(false);
  const [error, setError]           = useCR("");
  const [focusFieldKey, setFocusFieldKey] = useCR("");
  // Supporting documents — base64-encoded so the bundle endpoint can
  // round-trip them in JSON. Each entry: {filename, content_type,
  // size, data_base64}. Caps mirror the server side (5 MB per file,
  // 15 MB total, 3 files, PDF/JPG/PNG/HEIC/WebP).
  const [documents, setDocuments]   = useCR([]);
  const [docError, setDocError]     = useCR("");

  // Reset every time the modal opens — operators expect a clean
  // sheet, not whatever they typed last time.
  useECR(() => {
    if (!open) return;
    setEntity("household");
    setMemberId("");
    setChangeType("correction");
    setForcePmt(false);
    setRows([]);
    setNote("");
    setBusy(false);
    setError("");
    setFocusFieldKey("");
    setDocuments([]);
    setDocError("");
    setStep(1);
  }, [open]);

  // Drop pending rows when entity scope flips — a household-scope row
  // can't survive a switch to entity=member (and vice versa) since the
  // server rejects mixed-scope payloads. Better to wipe than to let
  // the operator submit an invalid bundle.
  useECR(() => {
    if (!open) return;
    setRows([]);
    setMemberId("");
  }, [entity]);

  // Live catalog from /api/v1/upd/field-catalog/ — falls back to the
  // hardcoded CATEGORIES when the API is unreachable (file:// preview,
  // 401, network error). Each render past mount uses whichever is in
  // state; the fetch happens once per modal mount.
  const liveCatalog = useFieldCatalog();

  // Visible catalog — household scope hides member-only fields and
  // vice versa. Categories that end up with zero fields after the
  // filter are dropped so the composer / tree don't show empty
  // headings.
  const visibleCategories = useMCR(() => {
    const wantMember = entity === "member";
    return liveCatalog.categories
      .map(c => ({
        ...c,
        fields: c.fields.filter(
          f => wantMember ? f.entity === "member" : f.entity !== "member",
        ),
      }))
      .filter(c => c.fields.length > 0);
  }, [entity, liveCatalog.categories]);

  const visibleFieldsFlat = useMCR(() => {
    const out = {};
    for (const c of visibleCategories) {
      for (const f of c.fields) {
        out[`${c.key}:${f.key}`] = liveCatalog.fieldsFlat[`${c.key}:${f.key}`];
      }
    }
    return out;
  }, [visibleCategories, liveCatalog.fieldsFlat]);

  // Effective current values — when a member is selected, merge that
  // member's snapshot on top of the household-level snapshot.
  const effectiveCurrentValues = useMCR(() => {
    if (entity !== "member" || !memberId) return currentValues;
    return { ...currentValues, ...(memberValues[memberId] || {}) };
  }, [entity, memberId, currentValues, memberValues]);

  const selectedMember = useMCR(
    () => (entity === "member" && memberId)
      ? members.find(m => m.id === memberId) || null
      : null,
    [entity, memberId, members],
  );

  const addedKeys = useMCR(
    () => new Set(rows.map(r => `${r.category}:${r.field}`)),
    [rows],
  );

  // Auto-derived PMT-relevance. Force-PMT can raise but not lower:
  // when derivedPmt is true the checkbox is disabled and stays on.
  // Reads the live fieldsFlat so a backend-tagged PMT change picks up
  // without a redeploy.
  const derivedPmt = useMCR(
    () => derivePmt(rows, liveCatalog.fieldsFlat),
    [rows, liveCatalog.fieldsFlat],
  );
  const pmtRelevant = derivedPmt || forcePmt;

  const reviewerLabel = routeFor(changeType, pmtRelevant);

  // ── Wizard ────────────────────────────────────────────────────
  // 4 steps: 1 Target, 2 Fields, 3 Evidence + note, 4 Review.
  // Per-step validation gates the Next button; final submit only
  // fires from step 4. State resets to 1 every open (see effect
  // below). The existing `valid` derivation stays as the final
  // submit gate — the per-step checks are subsets of it.
  const TOTAL_STEPS = 4;
  const STEP_LABELS = ["Target", "Fields", "Evidence", "Review"];
  const [step, setStep] = useCR(1);

  const step1Valid = entity !== "member" || !!memberId;
  const step2Valid =
    rows.length >= 1
    && rows.every(r => (r.value || "").trim().length > 0);
  const step3Valid = true;  // documents are optional; note is gated on step 4
  const step4Valid = note.trim().length >= 6;

  const canAdvance =
    step === 1 ? step1Valid
    : step === 2 ? step2Valid
    : step === 3 ? step3Valid
    : false;

  const valid =
    rows.length >= 1
    && rows.every(r => (r.value || "").trim().length > 0)
    && note.trim().length >= 6
    // When the entity is a member, the operator must pick one before
    // we have a target. The server rejects entity=member without a
    // member_id anyway; this just keeps the bad path off the wire.
    && (entity !== "member" || !!memberId);

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

  // ── Supporting documents ──────────────────────────────────────────
  // Mirrors server caps in apps/update_workflow/evidence_storage.py.
  const DOC_MAX_FILE = 5 * 1024 * 1024;
  const DOC_MAX_TOTAL = 15 * 1024 * 1024;
  const DOC_MAX_COUNT = 3;
  const DOC_ALLOWED_MIME = new Set([
    "application/pdf", "image/jpeg", "image/png", "image/heic", "image/webp",
  ]);

  const readAsBase64 = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      // readAsDataURL prefixes "data:<mime>;base64,..." — strip it.
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsDataURL(file);
  });

  const addDocuments = async (fileList) => {
    setDocError("");
    const files = Array.from(fileList || []);
    if (files.length === 0) return;
    // Client-side validation — server re-validates, but failing here
    // gives instant feedback without a round-trip.
    if (documents.length + files.length > DOC_MAX_COUNT) {
      setDocError(`At most ${DOC_MAX_COUNT} documents.`);
      return;
    }
    let total = documents.reduce((s, d) => s + d.size, 0);
    const next = [];
    for (const f of files) {
      if (!DOC_ALLOWED_MIME.has(f.type)) {
        setDocError(`Unsupported type for ${f.name}. Use PDF, JPG, PNG, HEIC, or WebP.`);
        return;
      }
      if (f.size > DOC_MAX_FILE) {
        setDocError(`${f.name} is over the 5 MB per-file limit.`);
        return;
      }
      total += f.size;
      if (total > DOC_MAX_TOTAL) {
        setDocError(`Total attachment size exceeds 15 MB.`);
        return;
      }
      try {
        const b64 = await readAsBase64(f);
        next.push({
          filename: f.name,
          content_type: f.type,
          size: f.size,
          data_base64: b64,
        });
      } catch (e) {
        setDocError(`Could not read ${f.name}: ${e.message || e}`);
        return;
      }
    }
    setDocuments([...documents, ...next]);
  };

  const removeDocument = (idx) =>
    setDocuments(documents.filter((_, i) => i !== idx));

  const fmtBytes = (n) => {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  };

  // Group rows by category. Order follows CATEGORIES so the rendered
  // layout matches the catalog (Identification first, etc.).
  const grouped = useMCR(() => {
    const map = new Map();
    for (const r of rows) {
      if (!map.has(r.category)) map.set(r.category, []);
      map.get(r.category).push(r);
    }
    return visibleCategories
      .filter(c => map.has(c.key))
      .map(c => ({ category: c, rows: map.get(c.key) }));
  }, [rows, visibleCategories]);

  const submit = async () => {
    if (!valid || !onSubmit) return;
    setBusy(true);
    setError("");
    const payload = {
      household_id: householdId,
      entity,
      // Only sent for entity=member; the bundle serializer ignores it
      // otherwise but enforces it strictly when entity='member'.
      ...(entity === "member" && memberId ? { member_id: memberId } : {}),
      change_type: changeType,
      pmt_relevant: pmtRelevant,
      rows: rows.map(r => ({
        category: r.category, field: r.field, new_value: r.value,
      })),
      ...(documents.length > 0
        ? { documents: documents.map(d => ({
            filename: d.filename,
            content_type: d.content_type,
            data_base64: d.data_base64,
          })) }
        : {}),
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
            Step {step}/{TOTAL_STEPS} · {STEP_LABELS[step - 1]}
            {" · "}Routing: <strong>{reviewerLabel}</strong>
          </span>
          <button className="btn" disabled={busy} onClick={onClose}>Cancel</button>
          {step > 1 && (
            <button className="btn" disabled={busy}
                    onClick={() => setStep(step - 1)}>
              ← Back
            </button>
          )}
          {step < TOTAL_STEPS && (
            <button className="btn btn-primary"
                    disabled={busy || !canAdvance}
                    onClick={() => setStep(step + 1)}>
              Next →
            </button>
          )}
          {step === TOTAL_STEPS && (
            <button className="btn btn-success" disabled={busy || !valid}
              onClick={submit}>
              <Icon name="check" size={14}/>
              {busy ? "Submitting…" : `Create & submit · ${rows.length} change${rows.length === 1 ? "" : "s"}`}
            </button>
          )}
        </div>
      }>
      <div className="col gap-4">
        {/* Step indicator strip */}
        <div data-testid="wizard-step-indicator"
             style={{display:"flex", gap:8, marginBottom:4}}>
          {STEP_LABELS.map((label, i) => {
            const n = i + 1;
            const isActive = n === step;
            const isDone = n < step;
            return (
              <div key={n} style={{
                flex:1, padding:"6px 10px", borderRadius:6,
                fontSize:11.5, fontWeight: isActive ? 600 : 500,
                background: isActive ? "var(--primary-100)"
                          : isDone ? "var(--neutral-100)"
                          : "transparent",
                color: isActive ? "var(--primary-900)"
                      : isDone ? "var(--neutral-700)"
                      : "var(--neutral-500)",
                border: isActive ? "1px solid var(--primary-700)"
                                  : "1px solid var(--neutral-200)",
                display:"flex", alignItems:"center", gap:6,
              }}>
                <span style={{
                  display:"inline-flex", alignItems:"center", justifyContent:"center",
                  width:18, height:18, borderRadius:"50%",
                  background: isActive ? "var(--primary-900)"
                            : isDone ? "var(--neutral-300)"
                            : "var(--neutral-200)",
                  color:"var(--neutral-0)", fontSize:10.5, fontWeight:700,
                }}>
                  {isDone ? "✓" : n}
                </span>
                {label}
              </div>
            );
          })}
        </div>

        {/* Live summary strip — visible on every step. Surfaces the
              PMT-relevance chip, routing label, and pending-state
              counts so the operator never has to step back to check
              what's been selected. */}
        <div data-testid="wizard-live-summary" style={{
          display:"flex", alignItems:"center", gap:10,
          padding:"8px 12px",
          background:"var(--neutral-50)",
          border:"1px solid var(--neutral-200)", borderRadius:6,
          fontSize:12.5,
        }}>
          <span data-testid="summary-target">
            <Icon name={entity === "household" ? "home"
                       : entity === "all_members" ? "users" : "user"} size={12}/>
            {" "}
            {entity === "member"
              ? `${selectedMember?.name || (memberId ? memberId.slice(0, 10) + "…" : "Member (none)")}`
              : entity === "all_members" ? "All members" : "Household"}
          </span>
          <span className="muted">·</span>
          <span data-testid="summary-changes">
            <strong>{rows.length}</strong> field{rows.length === 1 ? "" : "s"}
          </span>
          {documents.length > 0 && (<>
            <span className="muted">·</span>
            <span data-testid="summary-documents">
              <strong>{documents.length}</strong> doc{documents.length === 1 ? "" : "s"}
            </span>
          </>)}
          <span className="muted">·</span>
          <span data-testid="summary-route">
            → <strong>{reviewerLabel}</strong>
          </span>
          <span className="muted">·</span>
          {pmtRelevant
            ? <Chip tone="eligibility" size="sm" data-testid="summary-pmt-chip">
                <Icon name="target" size={11}/> pmt_relevant
              </Chip>
            : <Chip tone="neutral" size="sm" data-testid="summary-pmt-chip">cosmetic</Chip>}
        </div>

        {/* Step 1) Target strip */}
        {step === 1 && (<>
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

        {/* 1b) Member picker — only rendered when entity=member.
              Shows the roster as a select, then renders an info
              card with name/ID/relationship/DOB once a member is
              chosen. The card is the operator's confirmation that
              the right person is being changed. */}
        {entity === "member" && (
          <div data-testid="member-picker-strip" style={{
            padding:16, background:"var(--neutral-50)",
            border:"1px solid var(--neutral-200)", borderRadius:6,
            display:"flex", flexDirection:"column", gap:12,
          }}>
            <div>
              <div className="t-cap">Member</div>
              {members.length === 0 ? (
                <div className="t-bodysm muted" style={{marginTop:4}}>
                  No roster passed to the modal — consumer must supply
                  `members` to enable entity=member submissions.
                </div>
              ) : (
                <select className="field-select"
                  data-testid="member-picker-select"
                  value={memberId}
                  onChange={(e) => setMemberId(e.target.value)}
                  style={{ width:"100%", maxWidth:480 }}>
                  <option value="">Select a member…</option>
                  {members.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.line != null ? `${m.line}. ` : ""}{m.name}
                      {m.relationship ? ` · ${m.relationship}` : ""}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {selectedMember && (
              <div data-testid="member-info-card" style={{
                padding:"10px 12px", background:"white",
                border:"1px solid var(--neutral-200)", borderRadius:6,
                display:"grid", gridTemplateColumns:"repeat(4, 1fr)",
                gap:12, fontSize:13,
              }}>
                <div>
                  <div className="t-cap">Name</div>
                  <strong>{selectedMember.name}</strong>
                </div>
                <div>
                  <div className="t-cap">Member ID</div>
                  <div className="t-mono" style={{fontSize:11.5}}>
                    {selectedMember.id.slice(0, 12)}…
                  </div>
                </div>
                <div>
                  <div className="t-cap">Relation</div>
                  <div>{selectedMember.relationship || "—"}</div>
                </div>
                <div>
                  <div className="t-cap">Date of birth</div>
                  <div>{selectedMember.dob || "—"}</div>
                </div>
              </div>
            )}
          </div>
        )}
        </>)}

        {/* Step 2) Field changes */}
        {step === 2 && (<>
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
                    const meta = liveCatalog.fieldsFlat[`${category}:${field}`];
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
                const meta = liveCatalog.fieldsFlat[`${r.category}:${r.field}`];
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
                      const meta = liveCatalog.fieldsFlat[`${r.category}:${r.field}`];
                      const rowKey = `${r.category}:${r.field}`;
                      const cv = effectiveCurrentValues[`${r.category}.${r.field}`];
                      const cvFormatted = formatCurrent(cv, meta);
                      const hasChanged = (r.value || "").trim() !== "";
                      return (
                        <div key={rowKey} data-row-key={rowKey}
                          style={{
                            padding:"10px 12px",
                            borderBottom:"1px solid var(--neutral-100)",
                            display:"flex", flexDirection:"column", gap:6,
                          }}>
                          {/* Row header — field label, key, remove. */}
                          <div style={{display:"flex", alignItems:"center", gap:8}}>
                            <strong style={{fontSize:13}}>{meta.label}</strong>
                            <span className="t-mono" style={{fontSize:11, color:"var(--neutral-500)"}}>
                              {r.category}.{r.field}
                            </span>
                            {meta.pmt && (
                              <Chip size="sm" tone="eligibility">PMT</Chip>
                            )}
                            <div style={{flex:1}}/>
                            <button type="button" className="icon-btn"
                              aria-label={`Remove ${meta.label}`}
                              onClick={() => removeRow(r.category, r.field)}>
                              <Icon name="x" size={14}/>
                            </button>
                          </div>
                          {/* Before / After diff cards. Two columns side-by-
                              side. Lights up green on the "after" side once
                              the operator has typed a value. */}
                          <div style={{
                            display:"grid",
                            gridTemplateColumns:"1fr 16px 1fr",
                            gap:8, alignItems:"stretch",
                          }}>
                            <div data-testid={`before-${r.category}-${r.field}`}
                                 style={{
                                   padding:"8px 10px",
                                   background:"var(--neutral-50)",
                                   border:"1px solid var(--neutral-200)",
                                   borderRadius:6,
                                   minHeight:38,
                                   display:"flex", flexDirection:"column", gap:2,
                                 }}>
                              <span style={{
                                fontSize:10, fontWeight:600,
                                letterSpacing:"0.06em", textTransform:"uppercase",
                                color:"var(--neutral-500)",
                              }}>Before</span>
                              <span
                                data-testid={`current-${r.category}-${r.field}`}
                                title={cv == null ? "" : String(cv)}
                                style={{
                                  fontSize:13,
                                  color: cvFormatted ? "var(--neutral-900)" : "var(--neutral-500)",
                                  fontStyle: cvFormatted ? "normal" : "italic",
                                  overflow:"hidden", textOverflow:"ellipsis",
                                  whiteSpace:"nowrap",
                                }}>
                                {cvFormatted || "current —"}
                              </span>
                            </div>
                            <div style={{
                              display:"flex", alignItems:"center", justifyContent:"center",
                              color: hasChanged ? "var(--accent-update)" : "var(--neutral-500)",
                            }}>
                              <Icon name="arrowRight" size={14}/>
                            </div>
                            <div data-testid={`after-${r.category}-${r.field}`}
                                 style={{
                                   padding:"8px 10px",
                                   background: hasChanged ? "rgba(34, 139, 34, 0.06)" : "white",
                                   border: hasChanged
                                     ? "1px solid rgba(34, 139, 34, 0.5)"
                                     : "1px solid var(--neutral-200)",
                                   borderRadius:6,
                                   minHeight:38,
                                   display:"flex", flexDirection:"column", gap:2,
                                 }}>
                              <span style={{
                                fontSize:10, fontWeight:600,
                                letterSpacing:"0.06em", textTransform:"uppercase",
                                color: hasChanged ? "rgb(34, 100, 34)" : "var(--neutral-500)",
                              }}>After</span>
                              <RowInput meta={meta} value={r.value}
                                autoFocus={focusFieldKey === rowKey}
                                onChange={(v) => updateValue(r.category, r.field, v)}/>
                            </div>
                          </div>
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
                ? <AddPicker  disabled={busy} addedKeys={addedKeys} onAdd={addRow} fieldsFlat={visibleFieldsFlat}/>
                : addUx === "tree"
                ? <AddTree    disabled={busy} addedKeys={addedKeys} onAdd={addRow} categories={visibleCategories}/>
                : <AddComposer disabled={busy} addedKeys={addedKeys} onAdd={addRow} categories={visibleCategories}/>}
            </div>
          </div>
        </div>
        </>)}

        {/* Step 3) Evidence (documents + requester note) */}
        {step === 3 && (<>
        {/* 2b) Supporting documents — PDF / image upload. Base64-
              encoded into the bundle payload. Server enforces the
              same caps but client-side validation gives instant
              feedback. */}
        <div data-testid="documents-strip">
          <div style={{display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:6}}>
            <label className="t-cap">Supporting documents (optional)</label>
            <span className="t-cap" style={{fontSize:11, color:"var(--neutral-500)"}}>
              {documents.length} of {DOC_MAX_COUNT} · 5 MB each · PDF, JPG, PNG, HEIC, WebP
            </span>
          </div>
          <input type="file"
                 data-testid="documents-input"
                 multiple
                 accept="application/pdf,image/jpeg,image/png,image/heic,image/webp"
                 disabled={documents.length >= DOC_MAX_COUNT || busy}
                 onChange={(e) => {
                   addDocuments(e.target.files);
                   e.target.value = "";  // allow re-selecting the same file
                 }}
                 style={{ fontSize: 12.5 }}/>
          {docError && (
            <div className="t-bodysm" style={{color:"var(--accent-danger)", marginTop:6, fontSize:12}}>
              {docError}
            </div>
          )}
          {documents.length > 0 && (
            <div data-testid="documents-list" style={{
              marginTop:8, display:"flex", flexDirection:"column", gap:6,
            }}>
              {documents.map((d, i) => (
                <div key={i} data-testid={`document-row-${i}`}
                     style={{
                       display:"grid", gridTemplateColumns:"auto 1fr auto auto",
                       gap:10, alignItems:"center",
                       padding:"6px 10px",
                       background:"var(--neutral-50)",
                       border:"1px solid var(--neutral-200)", borderRadius:6,
                       fontSize:12.5,
                     }}>
                  <Icon name="file" size={14} color="var(--neutral-500)"/>
                  <span style={{overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>
                    {d.filename}
                  </span>
                  <span className="t-cap" style={{fontSize:11}}>{fmtBytes(d.size)}</span>
                  <button type="button" className="icon-btn"
                          aria-label={`Remove ${d.filename}`}
                          onClick={() => removeDocument(i)}>
                    <Icon name="x" size={12}/>
                  </button>
                </div>
              ))}
            </div>
          )}
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
        </>)}

        {/* Step 4) Review — read-only summary so the operator
              can confirm before submit. Every field comes from
              state already gathered in earlier steps. */}
        {step === 4 && (
          <div data-testid="wizard-review" style={{
            display:"flex", flexDirection:"column", gap:12,
            padding:16, background:"var(--neutral-50)",
            border:"1px solid var(--neutral-200)", borderRadius:6,
          }}>
            <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12}}>
              <div>
                <div className="t-cap">Target</div>
                <strong>
                  {entity === "member"
                    ? `Member · ${selectedMember?.name || memberId.slice(0, 12) + "…"}`
                    : entity === "all_members" ? "All members" : "Household"}
                </strong>
              </div>
              <div>
                <div className="t-cap">Routing</div>
                <strong>{reviewerLabel}</strong>
                {pmtRelevant && (
                  <Chip tone="eligibility" size="sm" style={{marginLeft:8}}>
                    pmt_relevant
                  </Chip>
                )}
              </div>
              <div>
                <div className="t-cap">Change type</div>
                <strong>
                  {CHANGE_TYPE_OPTIONS.find(o => o.value === changeType)?.label
                    || changeType}
                </strong>
              </div>
              <div>
                <div className="t-cap">Fields changing</div>
                <strong>{rows.length}</strong>
                {documents.length > 0 && (
                  <> · <strong>{documents.length}</strong> document{documents.length === 1 ? "" : "s"}</>
                )}
              </div>
            </div>

            <div>
              <div className="t-cap" style={{marginBottom:4}}>Changes</div>
              {rows.map(r => {
                const meta = liveCatalog.fieldsFlat[`${r.category}:${r.field}`];
                const cv = effectiveCurrentValues[`${r.category}.${r.field}`];
                return (
                  <div key={`${r.category}:${r.field}`} style={{
                    display:"grid", gridTemplateColumns:"1.2fr 1fr 1fr",
                    gap:8, padding:"4px 0", fontSize:13,
                    borderBottom:"1px solid var(--neutral-100)",
                  }}>
                    <strong>{meta.label}</strong>
                    <span className="t-bodysm muted">
                      {formatCurrent(cv, meta) || "—"}
                    </span>
                    <span><strong>{r.value || "(empty)"}</strong></span>
                  </div>
                );
              })}
            </div>

            {documents.length > 0 && (
              <div>
                <div className="t-cap" style={{marginBottom:4}}>Documents</div>
                {documents.map((d, i) => (
                  <div key={i} className="t-bodysm" style={{padding:"2px 0"}}>
                    <Icon name="file" size={11}/> {d.filename} <span className="muted">· {fmtBytes(d.size)}</span>
                  </div>
                ))}
              </div>
            )}

            <div>
              <div className="t-cap" style={{marginBottom:4}}>Requester note</div>
              <div className="t-bodysm" style={{
                padding:"8px 10px", background:"white",
                border:"1px solid var(--neutral-200)", borderRadius:4,
                whiteSpace:"pre-wrap",
              }}>
                {note || <span className="muted">(no note yet — back to step 3)</span>}
              </div>
              {noteRemaining > 0 && (
                <div className="t-bodysm" style={{
                  color:"var(--accent-danger)", marginTop:4, fontSize:12,
                }}>
                  Note must be at least 6 characters — go back to step 3.
                </div>
              )}
            </div>
          </div>
        )}

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
