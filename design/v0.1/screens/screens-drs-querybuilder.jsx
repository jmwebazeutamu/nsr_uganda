/* global React, Icon, Chip, PageHeader, Field */
// NSR MIS — DRS Wizard, Step 2 (Build) — Query Builder
// =====================================================
// Drop-in replacement for the current BuildStep in
// `screens-drs.jsx`. Exposes <BuildStepV2 .../> which renders the
// full nestable rule + group builder, an estimated-match rail,
// the DSA card and a saved-queries rail.
//
// To wire into the existing wizard:
//   1. Save this file at /design/v0.1/screens/screens-drs-querybuilder.jsx
//   2. Add it to `nsr-mis-console.html` AFTER components.jsx and
//      BEFORE screens-drs.jsx, e.g.:
//        <script type="text/babel" src="v0.1/screens/screens-drs-querybuilder.jsx"></script>
//        <script type="text/babel" src="v0.1/screens/screens-drs.jsx"></script>
//   3. In screens-drs.jsx, swap the {step === 'build' && <BuildStep .../>}
//      line for <BuildStepV2 .../> and feed it the wizard's `tree` +
//      `maxRows` state (replace the previous `subRegionCodes / programmeCodes`
//      flat sets — the tree subsumes both).
//   4. The submit payload now ships `request_payload.criteria` (the
//      tree) plus `request_payload.max_rows`. validate_against_dsa
//      still walks the leaf rules to extract `fields` + the sub-region
//      and programme code sets it currently understands; nothing on
//      the server changes until the criteria evaluator lands.
//
// The expression compiles to a JSON payload the backend
// (apps.data_requests.validate_against_dsa) can evaluate:
//   {
//     combinator: "AND",
//     rules: [
//       { field: "household.sub_region_code", op: "in",
//         value: ["SR-BUGANDA-SOUTH"] },
//       { combinator: "OR", rules: [...] },
//     ],
//     limit: 10000,
//   }
// The dotted field keys mirror the BuilderSchema response so the
// existing submit flow keeps working — same field whitelist, same
// DSA-clause guard, same audit hash on the criteria tree.
//
// All colour, spacing and typography references go through the
// v0.1/tokens.css `--*` variables — no hard-coded hex / px outside
// those tokens, per /design/README.md §"How to add a new screen".

const {
  useState: useStateQB, useMemo: useMemoQB,
  useRef: useRefQB, useEffect: useEffectQB,
  useContext: useContextQB, createContext: createContextQB,
} = React;

// US-S27-013 — the live catalogue arrives from
// /api/v1/drs/requests/builder-schema/ via BuildStepV2's `fields`
// prop. We thread it through the recursive tree via context so
// QBRule + QBFieldPicker can resolve a rule's field by key and
// list the available choices. The inline QB_FIELDS below is the
// offline-preview fallback only.
const QBFieldsContext = createContextQB(null);
const useQBFields = () => useContextQB(QBFieldsContext);

/* ----------------------------------------------------------------
   Field catalogue (mirrors /api/v1/drs/requests/builder-schema/).
   In production this comes from the schema response; left inline
   here so the design preview is representative offline.
   ---------------------------------------------------------------- */

const QB_SUB_REGIONS = [
  { code: "SR-BUGANDA-SOUTH", name: "Buganda South" },
  { code: "SR-BUGANDA-NORTH", name: "Buganda North" },
  { code: "SR-BUSOGA",        name: "Busoga" },
  { code: "SR-BUNYORO",       name: "Bunyoro" },
  { code: "SR-TORO",          name: "Tooro" },
  { code: "SR-ANKOLE",        name: "Ankole" },
  { code: "SR-KIGEZI",        name: "Kigezi" },
  { code: "SR-ACHOLI",        name: "Acholi" },
  { code: "SR-KARAMOJA",      name: "Karamoja" },
];

const QB_PROGRAMMES = [
  { code: "OPM-PDM",     name: "Parish Development Model" },
  { code: "OPM-NUSAF4",  name: "NUSAF 4" },
  { code: "MGLSD-SCG",   name: "Senior Citizens' Grant" },
  { code: "MGLSD-DRDIP", name: "DRDIP" },
  { code: "MoH-eMTCT",   name: "eMTCT Vouchers" },
];

const QB_FIELDS = [
  // Identifiers
  { group: "Identifiers", key: "household.registry_id",       label: "Registry ID",        type: "text" },
  { group: "Identifiers", key: "household.household_number",  label: "Household number",   type: "text" },

  // Geography
  { group: "Geography",   key: "household.sub_region_code",   label: "Sub-region",         type: "enum",  options: QB_SUB_REGIONS.map(s => ({value:s.code, label:s.name})) },
  { group: "Geography",   key: "household.district_code",     label: "District",           type: "enum",  options: [
      {value:"DST-WAKISO", label:"Wakiso"}, {value:"DST-MUKONO", label:"Mukono"},
      {value:"DST-MOROTO", label:"Moroto"}, {value:"DST-GULU",   label:"Gulu"},
      {value:"DST-ARUA",   label:"Arua"},   {value:"DST-KAMPALA",label:"Kampala"},
    ]},
  { group: "Geography",   key: "household.parish_name",       label: "Parish (name)",      type: "text" },
  { group: "Geography",   key: "household.gps_lat",           label: "GPS latitude",       type: "number",
    disabled: true, disabled_reason: "DSA clause 4.2.b — sensitive coordinate." },

  // Programmes
  { group: "Programmes",  key: "household.programme_codes",   label: "Programme enrolment", type: "enum-multi",
    options: QB_PROGRAMMES.map(p => ({value:p.code, label:p.name})) },
  { group: "Programmes",  key: "household.enrolment_status",  label: "Enrolment status",    type: "enum",
    options: [
      {value:"active",label:"Active"}, {value:"pending",label:"Pending"},
      {value:"suspended",label:"Suspended"}, {value:"exited",label:"Exited"},
    ]},

  // PMT / vulnerability
  { group: "PMT",         key: "household.pmt_score",         label: "PMT score",           type: "number" },
  { group: "PMT",         key: "household.pmt_band",          label: "PMT band",            type: "enum",
    options: ["Poorest 20%","Poorest 40%","Middle 40%","Wealthiest 20%"]
      .map(v => ({value:v,label:v})) },
  { group: "PMT",         key: "household.vulnerability_band",label: "Vulnerability band",  type: "enum",
    options: ["Extremely vulnerable","Vulnerable","Resilient"].map(v => ({value:v,label:v})) },

  // Household composition
  { group: "Household",   key: "household.size",              label: "Household size",      type: "number" },
  { group: "Household",   key: "household.dependency_ratio",  label: "Dependency ratio",    type: "number" },
  { group: "Household",   key: "household.head_sex",          label: "Head sex",            type: "enum",
    options: [{value:"F",label:"Female"},{value:"M",label:"Male"}] },
  { group: "Household",   key: "household.head_age_band",     label: "Head age band",       type: "enum",
    options: ["18–29","30–39","40–49","50–59","60+"].map(v => ({value:v,label:v})) },
  { group: "Household",   key: "household.head_education",    label: "Head education",      type: "enum",
    options: ["None","Primary","Secondary","Tertiary"].map(v => ({value:v,label:v})) },
  { group: "Household",   key: "household.head_disability_flag", label: "Head has disability", type: "bool" },

  // Housing
  { group: "Housing",     key: "household.roof_material",     label: "Roof material",       type: "enum",
    options: ["Iron sheets","Thatch","Tiles","Concrete","Other"].map(v => ({value:v,label:v})) },
  { group: "Housing",     key: "household.walls_material",    label: "Walls material",      type: "enum",
    options: ["Brick","Mud","Wood","Iron sheets","Other"].map(v => ({value:v,label:v})) },
  { group: "Housing",     key: "household.toilet_type",       label: "Toilet type",         type: "enum",
    options: ["Flush","VIP latrine","Pit latrine","None"].map(v => ({value:v,label:v})) },
  { group: "Housing",     key: "household.water_source",      label: "Water source",        type: "enum",
    options: ["Piped","Borehole","Protected spring","Open source"].map(v => ({value:v,label:v})) },

  // Temporal
  { group: "Temporal",    key: "household.captured_date",     label: "Captured date",       type: "date" },
  { group: "Temporal",    key: "household.updated_at",        label: "Last updated",        type: "date" },
];

const QB_FIELD_BY_KEY = QB_FIELDS.reduce((a,f) => (a[f.key]=f, a), {});

/* Operator lists per type. Labels are user-facing; `id` is what
   ships in the JSON payload. */
const QB_OPS = {
  text: [
    {id:"eq",       label:"equals"},
    {id:"neq",      label:"does not equal"},
    {id:"contains", label:"contains"},
    {id:"starts",   label:"starts with"},
    {id:"set",      label:"is set"},
    {id:"unset",    label:"is blank"},
  ],
  enum: [
    {id:"eq",   label:"is"},
    {id:"neq",  label:"is not"},
    {id:"in",   label:"is any of"},
    {id:"nin",  label:"is none of"},
    {id:"set",  label:"is set"},
    {id:"unset",label:"is blank"},
  ],
  "enum-multi": [
    {id:"any", label:"includes any of"},
    {id:"all", label:"includes all of"},
    {id:"none",label:"includes none of"},
    {id:"set", label:"is set"},
    {id:"unset",label:"is blank"},
  ],
  number: [
    {id:"eq",  label:"="},
    {id:"neq", label:"≠"},
    {id:"gt",  label:">"},
    {id:"gte", label:"≥"},
    {id:"lt",  label:"<"},
    {id:"lte", label:"≤"},
    {id:"between", label:"between"},
    {id:"set",  label:"is set"},
    {id:"unset",label:"is blank"},
  ],
  date: [
    {id:"on",     label:"on"},
    {id:"before", label:"before"},
    {id:"after",  label:"after"},
    {id:"between",label:"between"},
    {id:"lastN",  label:"in the last"},
    {id:"set",    label:"is set"},
    {id:"unset",  label:"is blank"},
  ],
  bool: [
    {id:"true", label:"is true"},
    {id:"false",label:"is false"},
  ],
};

/* Two-input operators */
const QB_BETWEEN = new Set(["between"]);
/* Operators that take no value */
const QB_NO_VALUE = new Set(["set","unset","true","false"]);

/* ----------------------------------------------------------------
   ID factory + tree helpers
   ---------------------------------------------------------------- */
let _qbSeq = 0;
const qbId = () => `n${++_qbSeq}`;

// `catalogue` is the live FIELD_CATALOGUE from /builder-schema/.
// Falls back to the inline QB_FIELDS so offline preview still works.
const qbNewRule = (field, catalogue) => {
  const list = (catalogue && catalogue.length > 0) ? catalogue : QB_FIELDS;
  const f = field || list.find(x => !x.disabled) || list[0];
  const ops = QB_OPS[f.type] || QB_OPS.text;
  const op = ops[0].id;
  return { id: qbId(), kind: "rule", field: f.key, op, value: defaultValue(f, op) };
};
const qbNewGroup = (combinator = "AND", catalogue) => ({
  id: qbId(), kind: "group", combinator,
  rules: [qbNewRule(null, catalogue)],
});

const defaultValue = (f, op) => {
  if (QB_NO_VALUE.has(op)) return null;
  if (op === "between") return ["",""];
  if (op === "lastN")   return { n: 30, unit: "days" };
  if (f.type === "enum-multi" || op === "in" || op === "nin" || op === "any" || op === "all" || op === "none") return [];
  if (f.type === "bool") return true;
  return "";
};

/* Recursively walk the tree applying `fn` to the matching node id. */
const qbMutate = (node, id, fn) => {
  if (node.id === id) return fn(node);
  if (node.kind !== "group") return node;
  return { ...node, rules: node.rules.map(r => qbMutate(r, id, fn)) };
};
const qbRemove = (node, id) => {
  if (node.kind !== "group") return node;
  return {
    ...node,
    rules: node.rules
      .filter(r => r.id !== id)
      .map(r => qbRemove(r, id)),
  };
};
const qbCountRules = (node) => {
  if (node.kind === "rule") return 1;
  return node.rules.reduce((a,r) => a + qbCountRules(r), 0);
};

/* Compile to a SQL-ish preview string */
const qbToSQL = (node, indent = 0) => {
  const pad = "  ".repeat(indent);
  if (node.kind === "rule") {
    const f = QB_FIELD_BY_KEY[node.field];
    const col = node.field.split(".").pop();
    const fmtV = (v) => {
      if (v == null || v === "") return "?";
      if (typeof v === "number") return v;
      if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
      return `'${v}'`;
    };
    const v = node.value;
    switch (node.op) {
      case "eq":       return `${col} = ${fmtV(v)}`;
      case "neq":      return `${col} <> ${fmtV(v)}`;
      case "gt":       return `${col} > ${fmtV(v)}`;
      case "gte":      return `${col} >= ${fmtV(v)}`;
      case "lt":       return `${col} < ${fmtV(v)}`;
      case "lte":      return `${col} <= ${fmtV(v)}`;
      case "in":
      case "any":      return `${col} IN (${(v||[]).map(fmtV).join(", ") || "?"})`;
      case "nin":
      case "none":     return `${col} NOT IN (${(v||[]).map(fmtV).join(", ") || "?"})`;
      case "all":      return `${col} @> ARRAY[${(v||[]).map(fmtV).join(", ") || "?"}]`;
      case "between":  return `${col} BETWEEN ${fmtV(v?.[0])} AND ${fmtV(v?.[1])}`;
      case "contains": return `${col} ILIKE '%${v||""}%'`;
      case "starts":   return `${col} ILIKE '${v||""}%'`;
      case "on":       return `${col}::date = ${fmtV(v)}`;
      case "before":   return `${col} < ${fmtV(v)}`;
      case "after":    return `${col} > ${fmtV(v)}`;
      case "lastN":    return `${col} >= NOW() - INTERVAL '${v?.n || 0} ${v?.unit || "days"}'`;
      case "set":      return `${col} IS NOT NULL`;
      case "unset":    return `${col} IS NULL`;
      case "true":     return `${col} = TRUE`;
      case "false":    return `${col} = FALSE`;
      default:         return `${col} ${node.op} ?`;
    }
  }
  // group
  const parts = node.rules.map(r => qbToSQL(r, indent + 1));
  const joiner = `\n${pad}  ${node.combinator} `;
  return `(\n${pad}  ${parts.join(joiner)}\n${pad})`;
};

/* ----------------------------------------------------------------
   Field picker popover
   ---------------------------------------------------------------- */
const QBFieldPicker = ({ value, onPick, onClose }) => {
  const [q, setQ] = useStateQB("");
  const ref = useRefQB(null);
  const ctx = useQBFields();
  const activeFields = (ctx && ctx.fields) || QB_FIELDS;
  useEffectQB(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);
  const ql = q.trim().toLowerCase();
  const groups = activeFields
    .filter(f => !ql || (f.label || f.key).toLowerCase().includes(ql) || f.key.toLowerCase().includes(ql))
    .reduce((acc, f) => ((acc[f.group] = acc[f.group] || []).push(f), acc), {});
  return (
    <div ref={ref} style={{
      position:"absolute", top:"calc(100% + 4px)", left:0, zIndex:40,
      width:340, background:"var(--neutral-0)",
      border:"1px solid var(--neutral-300)", borderRadius:6,
      boxShadow:"0 8px 24px rgba(0,0,0,0.12)", overflow:"hidden",
    }}>
      <div style={{padding:10, borderBottom:"1px solid var(--neutral-200)"}}>
        <div className="search" style={{padding:"4px 8px", background:"var(--neutral-50)"}}>
          <Icon name="search" size={14}/>
          <input autoFocus value={q} onChange={e=>setQ(e.target.value)} placeholder="Search fields…"/>
        </div>
      </div>
      <div style={{maxHeight:340, overflowY:"auto"}}>
        {Object.entries(groups).map(([g, fields]) => (
          <div key={g}>
            <div style={{
              padding:"8px 12px 4px", fontSize:11, fontWeight:600,
              letterSpacing:"0.06em", textTransform:"uppercase",
              color:"var(--neutral-500)", background:"var(--neutral-50)",
            }}>{g}</div>
            {fields.map(f => {
              const blocked = !!f.disabled;
              const active = value === f.key;
              return (
                <button key={f.key}
                  disabled={blocked}
                  onClick={() => { onPick(f); onClose(); }}
                  style={{
                    width:"100%", textAlign:"left", padding:"8px 12px",
                    border:0, background: active ? "var(--accent-system-bg)" : "transparent",
                    cursor: blocked ? "not-allowed" : "pointer",
                    display:"flex", alignItems:"center", gap:8,
                    color: blocked ? "var(--neutral-500)" : "var(--neutral-900)",
                  }}
                  onMouseEnter={e => !blocked && (e.currentTarget.style.background = active ? "var(--accent-system-bg)" : "var(--neutral-50)")}
                  onMouseLeave={e => !blocked && (e.currentTarget.style.background = active ? "var(--accent-system-bg)" : "transparent")}
                >
                  <div style={{flex:1}}>
                    <div className="t-bodysm" style={{fontWeight: active ? 600 : 500}}>{f.label}</div>
                    <div className="t-cap t-mono" style={{color:"var(--neutral-500)"}}>{f.key}</div>
                  </div>
                  <span className="t-cap" style={{
                    padding:"1px 6px", borderRadius:3, background:"var(--neutral-100)",
                    color:"var(--neutral-700)", fontSize:10, textTransform:"uppercase",
                    letterSpacing:"0.04em",
                  }}>{f.type === "enum-multi" ? "list" : f.type}</span>
                  {blocked && <Icon name="lock" size={12} color="var(--accent-danger)"/>}
                </button>
              );
            })}
          </div>
        ))}
        {Object.keys(groups).length === 0 && (
          <div style={{padding:24, textAlign:"center", color:"var(--neutral-500)"}} className="t-bodysm">
            No fields match “{q}”.
          </div>
        )}
      </div>
    </div>
  );
};

/* ----------------------------------------------------------------
   Value editor — adapts to field type + operator
   ---------------------------------------------------------------- */
const QBValueEditor = ({ field, op, value, onChange }) => {
  if (QB_NO_VALUE.has(op)) {
    return <div className="t-cap" style={{padding:"7px 10px", color:"var(--neutral-500)", fontStyle:"italic"}}>
      no value needed
    </div>;
  }
  if (op === "between") {
    const [a, b] = value || ["",""];
    const t = field.type === "date" ? "date" : "number";
    return (
      <div style={{display:"flex", gap:6, alignItems:"center"}}>
        <input className="field-input" type={t} value={a||""}
          onChange={e => onChange([e.target.value, b])} style={{flex:1, minWidth:0}}/>
        <span className="t-cap">and</span>
        <input className="field-input" type={t} value={b||""}
          onChange={e => onChange([a, e.target.value])} style={{flex:1, minWidth:0}}/>
      </div>
    );
  }
  if (op === "lastN") {
    const v = value || { n: 30, unit: "days" };
    return (
      <div style={{display:"flex", gap:6, alignItems:"center"}}>
        <input className="field-input" type="number" min={1} value={v.n}
          onChange={e => onChange({ ...v, n: Number(e.target.value)||0 })}
          style={{width:90}}/>
        <select className="field-select" value={v.unit}
          onChange={e => onChange({ ...v, unit: e.target.value })}
          style={{flex:1}}>
          <option value="days">days</option>
          <option value="weeks">weeks</option>
          <option value="months">months</option>
          <option value="years">years</option>
        </select>
      </div>
    );
  }
  if (op === "in" || op === "nin" || op === "any" || op === "all" || op === "none"
      || field.type === "enum-multi") {
    return <QBMultiSelect field={field} value={value||[]} onChange={onChange}/>;
  }
  if (field.type === "enum") {
    return (
      <select className="field-select" value={value||""} onChange={e => onChange(e.target.value)}>
        <option value="">Select…</option>
        {field.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  if (field.type === "number") {
    return <input className="field-input" type="number" value={value||""}
      placeholder="0" onChange={e => onChange(e.target.value)}/>;
  }
  if (field.type === "date") {
    return <input className="field-input" type="date" value={value||""}
      onChange={e => onChange(e.target.value)}/>;
  }
  if (field.type === "bool") {
    return (
      <select className="field-select" value={String(value)} onChange={e => onChange(e.target.value === "true")}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  // text
  return <input className="field-input" value={value||""}
    placeholder={field.label} onChange={e => onChange(e.target.value)}/>;
};

const QBMultiSelect = ({ field, value, onChange }) => {
  const [open, setOpen] = useStateQB(false);
  const ref = useRefQB(null);
  useEffectQB(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const options = field.options || [];
  const labelFor = v => (options.find(o => o.value === v)?.label) || v;
  const toggle = v => onChange(value.includes(v) ? value.filter(x => x!==v) : [...value, v]);
  return (
    <div ref={ref} style={{position:"relative", flex:1, minWidth:0}}>
      <button onClick={() => setOpen(o => !o)} className="field-input" style={{
        textAlign:"left", display:"flex", alignItems:"center", gap:6,
        flexWrap:"wrap", padding:"4px 8px", minHeight:32, cursor:"pointer",
        background:"var(--neutral-0)",
      }}>
        {value.length === 0
          ? <span className="t-cap" style={{color:"var(--neutral-500)"}}>Pick one or more…</span>
          : value.map(v => (
              <span key={v} style={{
                display:"inline-flex", alignItems:"center", gap:4,
                background:"var(--accent-system-bg)", color:"var(--accent-system)",
                padding:"2px 6px 2px 8px", borderRadius:3, fontSize:12, fontWeight:500,
              }}>
                {labelFor(v)}
                <span role="button" tabIndex={-1}
                  onClick={e => { e.stopPropagation(); toggle(v); }}
                  style={{cursor:"pointer", opacity:0.7, paddingLeft:2}}><Icon name="x" size={10}/></span>
              </span>
            ))}
        <span style={{flex:1}}/>
        <Icon name="chevronDown" size={14} color="var(--neutral-500)"/>
      </button>
      {open && (
        <div style={{
          position:"absolute", top:"calc(100% + 4px)", left:0, right:0, zIndex:30,
          background:"var(--neutral-0)", border:"1px solid var(--neutral-300)",
          borderRadius:6, boxShadow:"0 8px 24px rgba(0,0,0,0.12)",
          maxHeight:240, overflowY:"auto",
        }}>
          {options.map(o => {
            const on = value.includes(o.value);
            return (
              <label key={o.value} style={{
                display:"flex", alignItems:"center", gap:8, padding:"7px 12px",
                cursor:"pointer", background: on ? "var(--accent-system-bg)" : "transparent",
              }} onMouseEnter={e => !on && (e.currentTarget.style.background = "var(--neutral-50)")}
                 onMouseLeave={e => !on && (e.currentTarget.style.background = "transparent")}>
                <input type="checkbox" checked={on} onChange={() => toggle(o.value)}/>
                <span className="t-bodysm">{o.label}</span>
                <span style={{flex:1}}/>
                <span className="t-cap t-mono" style={{color:"var(--neutral-500)", fontSize:10}}>{o.value}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
};

/* ----------------------------------------------------------------
   Combinator pill — toggles AND/OR for a group
   ---------------------------------------------------------------- */
const QBCombinator = ({ value, onChange }) => (
  <div style={{
    display:"inline-flex", alignItems:"center",
    border:"1px solid var(--neutral-300)", borderRadius:4,
    overflow:"hidden", fontSize:12, fontWeight:600,
  }}>
    {["AND","OR"].map(c => (
      <button key={c} onClick={() => onChange(c)} style={{
        border:0, padding:"4px 10px", cursor:"pointer",
        background: value === c ? "var(--accent-system)" : "var(--neutral-0)",
        color: value === c ? "var(--neutral-0)" : "var(--neutral-700)",
        letterSpacing:"0.04em",
      }}>{c}</button>
    ))}
  </div>
);

/* ----------------------------------------------------------------
   Single Rule row
   ---------------------------------------------------------------- */
const QBRule = ({ rule, onChange, onRemove, onDuplicate }) => {
  const [pickerOpen, setPickerOpen] = useStateQB(false);
  const ctx = useQBFields();
  const byKey = (ctx && ctx.byKey) || QB_FIELD_BY_KEY;
  const fallback = (ctx && ctx.fields) || QB_FIELDS;
  const field = byKey[rule.field] || fallback[0];
  const ops = QB_OPS[field.type] || QB_OPS.text;
  const blocked = field.disabled;

  const setField = (f) => {
    const op = (QB_OPS[f.type] || QB_OPS.text)[0].id;
    onChange({ ...rule, field: f.key, op, value: defaultValue(f, op) });
  };
  const setOp = (op) => {
    onChange({ ...rule, op, value: defaultValue(field, op) });
  };
  const setValue = (value) => onChange({ ...rule, value });

  return (
    <div style={{
      display:"grid",
      gridTemplateColumns:"minmax(180px, 220px) minmax(140px, 160px) minmax(200px, 1fr) 32px 32px",
      alignItems:"center", gap:8, padding:"8px 0",
    }}>
      {/* Field picker */}
      <div style={{position:"relative"}}>
        <button onClick={() => setPickerOpen(o => !o)} className="field-input" style={{
          textAlign:"left", display:"flex", alignItems:"center", gap:6,
          background: blocked ? "var(--accent-danger-bg)" : "var(--neutral-0)",
          borderColor: blocked ? "var(--accent-danger)" : "var(--neutral-300)",
          cursor:"pointer",
        }}>
          {blocked && <Icon name="lock" size={12} color="var(--accent-danger)"/>}
          <div style={{flex:1, minWidth:0, overflow:"hidden"}}>
            <div className="t-bodysm" style={{
              fontWeight:500, whiteSpace:"nowrap", overflow:"hidden",
              textOverflow:"ellipsis", color: blocked ? "var(--accent-danger)" : "var(--neutral-900)",
            }}>{field.label}</div>
            <div className="t-cap t-mono" style={{
              color:"var(--neutral-500)", fontSize:10, lineHeight:1.2,
              whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis",
            }}>{field.key}</div>
          </div>
          <Icon name="chevronDown" size={12} color="var(--neutral-500)"/>
        </button>
        {pickerOpen && (
          <QBFieldPicker value={rule.field}
            onPick={setField} onClose={() => setPickerOpen(false)}/>
        )}
      </div>

      {/* Operator */}
      <select className="field-select" value={rule.op} onChange={e => setOp(e.target.value)}>
        {ops.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>

      {/* Value */}
      <div style={{minWidth:0}}>
        <QBValueEditor field={field} op={rule.op} value={rule.value} onChange={setValue}/>
      </div>

      {/* Actions */}
      <button className="icon-btn" onClick={onDuplicate} title="Duplicate"
        style={{width:28, height:28}}><Icon name="duplicate" size={14}/></button>
      <button className="icon-btn" onClick={onRemove} title="Remove rule"
        style={{width:28, height:28, color:"var(--accent-danger)"}}><Icon name="x" size={14}/></button>

      {/* DSA hint row */}
      {blocked && (
        <div style={{gridColumn:"1 / -1", paddingLeft:0}}>
          <div className="t-cap" style={{color:"var(--accent-danger)", display:"flex", alignItems:"center", gap:4}}>
            <Icon name="lock" size={11}/> {field.disabled_reason} — pick another field or request a DSA expansion.
          </div>
        </div>
      )}
    </div>
  );
};

/* ----------------------------------------------------------------
   Group — recursive
   ---------------------------------------------------------------- */
const QBGroup = ({ node, depth, onChange, onRemove, isRoot }) => {
  const ctx = useQBFields();
  const catalogue = (ctx && ctx.fields) || QB_FIELDS;
  // Colour the group's left bar by depth so nested logic is legible.
  const tones = [
    "var(--accent-system)",     // depth 0 — root
    "var(--accent-update)",     // depth 1
    "var(--accent-programme)",  // depth 2
    "var(--accent-identity)",   // depth 3
  ];
  const tone = tones[Math.min(depth, tones.length-1)];
  const tonesBg = [
    "transparent",
    "var(--accent-update-bg)",
    "var(--accent-programme-bg)",
    "var(--accent-identity-bg)",
  ];
  const bg = tonesBg[Math.min(depth, tonesBg.length-1)];

  const setCombinator = (c) => onChange({ ...node, combinator: c });

  const replaceChild = (id, next) => {
    onChange({
      ...node,
      rules: node.rules.map(r => r.id === id ? next : r),
    });
  };
  const removeChild = (id) => {
    onChange({ ...node, rules: node.rules.filter(r => r.id !== id) });
  };
  const duplicateChild = (id) => {
    const i = node.rules.findIndex(r => r.id === id);
    if (i < 0) return;
    const src = node.rules[i];
    const copy = JSON.parse(JSON.stringify(src));
    const restamp = (n) => { n.id = qbId(); if (n.kind === "group") n.rules.forEach(restamp); };
    restamp(copy);
    const next = [...node.rules];
    next.splice(i + 1, 0, copy);
    onChange({ ...node, rules: next });
  };

  const addRule = () => onChange({ ...node, rules: [...node.rules, qbNewRule(null, catalogue)] });
  const addGroup = () => onChange({
    ...node, rules: [...node.rules, qbNewGroup(node.combinator === "AND" ? "OR" : "AND", catalogue)],
  });

  return (
    <div style={{
      position:"relative",
      borderLeft: `3px solid ${tone}`,
      background: bg,
      borderRadius: isRoot ? 0 : 4,
      padding: isRoot ? "0 0 0 16px" : "8px 12px 12px 16px",
      marginLeft: isRoot ? 0 : 8,
    }}>
      {/* Group header */}
      <div style={{
        display:"flex", alignItems:"center", gap:10,
        padding: isRoot ? "12px 0 4px" : "0 0 8px",
      }}>
        <span className="t-cap" style={{
          fontWeight:600, color:tone, letterSpacing:"0.04em",
          textTransform:"uppercase",
        }}>
          {isRoot ? "Match" : "Nested · match"}
        </span>
        <QBCombinator value={node.combinator} onChange={setCombinator}/>
        <span className="t-cap">
          of the following {node.rules.length === 1 ? "criterion" : "criteria"}
        </span>
        <span style={{flex:1}}/>
        <button className="btn btn-sm" onClick={addRule}>
          <Icon name="plus" size={12}/> Add rule
        </button>
        <button className="btn btn-sm btn-ghost" onClick={addGroup}>
          <Icon name="plus" size={12}/> Add group
        </button>
        {!isRoot && (
          <button className="icon-btn" onClick={onRemove} title="Remove group"
            style={{width:28, height:28, color:"var(--accent-danger)"}}>
            <Icon name="x" size={14}/>
          </button>
        )}
      </div>

      {/* Children with AND/OR vertical badges between them */}
      <div>
        {node.rules.map((child, i) => (
          <div key={child.id} style={{position:"relative"}}>
            {i > 0 && (
              <div style={{
                display:"flex", alignItems:"center", gap:8, padding:"2px 0",
                marginLeft: child.kind === "group" ? 0 : 4,
              }}>
                <div style={{flex:"0 0 auto"}}>
                  <span style={{
                    display:"inline-block",
                    padding:"1px 8px", borderRadius:10,
                    background:tone, color:"var(--neutral-0)",
                    fontSize:10, fontWeight:700, letterSpacing:"0.06em",
                  }}>{node.combinator}</span>
                </div>
                <div style={{flex:1, height:1, background:"var(--neutral-200)"}}/>
              </div>
            )}
            {child.kind === "rule" ? (
              <QBRule rule={child}
                onChange={n => replaceChild(child.id, n)}
                onRemove={() => removeChild(child.id)}
                onDuplicate={() => duplicateChild(child.id)}/>
            ) : (
              <QBGroup node={child} depth={depth+1}
                onChange={n => replaceChild(child.id, n)}
                onRemove={() => removeChild(child.id)}/>
            )}
          </div>
        ))}
        {node.rules.length === 0 && (
          <div className="t-bodysm" style={{padding:"12px 0", color:"var(--neutral-500)", fontStyle:"italic"}}>
            Empty group — add a rule or remove the group.
          </div>
        )}
      </div>
    </div>
  );
};

/* ----------------------------------------------------------------
   Recipes / quick-start presets
   ---------------------------------------------------------------- */
const QB_RECIPES = [
  {
    id: "blank", label: "Blank query", icon: "file",
    note: "Start with one rule on Sub-region.",
    build: () => ({ id: qbId(), kind:"group", combinator:"AND",
      rules: [qbNewRule(QB_FIELD_BY_KEY["household.sub_region_code"])] }),
  },
  {
    id: "karamoja-poorest", label: "Karamoja · poorest 40%", icon: "target",
    note: "Households in Karamoja sub-region with PMT band Poorest 40% or Poorest 20%.",
    build: () => ({
      id: qbId(), kind:"group", combinator:"AND",
      rules: [
        { id: qbId(), kind:"rule", field:"household.sub_region_code", op:"eq", value:"SR-KARAMOJA" },
        { id: qbId(), kind:"rule", field:"household.pmt_band", op:"in", value:["Poorest 20%","Poorest 40%"] },
      ],
    }),
  },
  {
    id: "women-headed-pdm", label: "Women-headed · PDM enrolled", icon: "users",
    note: "Active PDM enrolees with female household head.",
    build: () => ({
      id: qbId(), kind:"group", combinator:"AND",
      rules: [
        { id: qbId(), kind:"rule", field:"household.head_sex", op:"eq", value:"F" },
        { id: qbId(), kind:"rule", field:"household.programme_codes", op:"any", value:["OPM-PDM"] },
        { id: qbId(), kind:"rule", field:"household.enrolment_status", op:"eq", value:"active" },
      ],
    }),
  },
  {
    id: "elderly-or-disability", label: "Elderly head OR disability", icon: "shield",
    note: "Head 60+ OR household head has a registered disability.",
    build: () => ({
      id: qbId(), kind:"group", combinator:"AND",
      rules: [
        { id: qbId(), kind:"rule", field:"household.sub_region_code", op:"in",
          value:["SR-ACHOLI","SR-KARAMOJA","SR-BUSOGA"] },
        { id: qbId(), kind:"group", combinator:"OR",
          rules: [
            { id: qbId(), kind:"rule", field:"household.head_age_band", op:"eq", value:"60+" },
            { id: qbId(), kind:"rule", field:"household.head_disability_flag", op:"true", value:null },
          ],
        },
      ],
    }),
  },
];

/* ----------------------------------------------------------------
   Build Step — top-level
   ---------------------------------------------------------------- */
const BuildStepV2 = ({
  tree, onChange, maxRows, onMaxRows,
  fields,
  recipes = QB_RECIPES,
  showSQL = true, dsaReference = "DSA-OPM-PDM-2026",
}) => {
  // Resolve the active catalogue: prefer the live `fields` prop
  // (US-S27-013 — comes from /builder-schema/), fall back to the
  // inline QB_FIELDS for offline preview. The byKey map is shared
  // via React context so every QBRule / QBFieldPicker can resolve
  // a rule's field without prop-drilling.
  const ctx = useMemoQB(() => {
    const list = (fields && fields.length > 0) ? fields : QB_FIELDS;
    const byKey = list.reduce((a, f) => (a[f.key] = f, a), {});
    return { fields: list, byKey };
  }, [fields]);

  // Estimated match count — fake numeric model derived from rule
  // count, just to give the surface a believable "live" feel.
  const estimate = useMemoQB(() => {
    const ruleCount = qbCountRules(tree);
    if (ruleCount === 0) return 12_089_442;
    const base = 12_089_442;
    // Each rule cuts ~62%, capped — pure design-time mock.
    const factor = Math.pow(0.38, Math.min(ruleCount, 8));
    return Math.max(120, Math.round(base * factor));
  }, [tree]);

  const sql = useMemoQB(() => qbToSQL(tree, 0), [tree]);

  return (
    <QBFieldsContext.Provider value={ctx}>
    <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
      <div className="col gap-4">
        {/* Recipes strip — hidden when no recipes are supplied (e.g. live wizard mode) */}
        {recipes.length > 0 && (
          <div className="card" style={{padding:14}}>
            <div className="row gap-3" style={{flexWrap:"wrap"}}>
              <div style={{display:"flex", flexDirection:"column", gap:2, marginRight:8}}>
                <span className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)"}}>START FROM</span>
                <span className="t-cap">Recipes load a pre-built criteria tree</span>
              </div>
              {recipes.map(r => (
                <button key={r.id} onClick={() => onChange(r.build(ctx.byKey, ctx.fields))}
                  title={r.note}
                  className="btn btn-sm" style={{
                    background:"var(--neutral-0)", borderColor:"var(--neutral-300)",
                  }}>
                  <Icon name={r.icon} size={12}/> {r.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Builder card */}
        <div className="card" style={{borderTop:"3px solid var(--accent-system)"}}>
          <div className="card-header">
            <div>
              <h3 className="t-h3" style={{margin:0}}>Query builder</h3>
              <div className="t-cap">
                Compose criteria for data selection. Compiles to a JSON
                payload validated against {dsaReference} on submit.
              </div>
            </div>
            <div className="row gap-2">
              <Chip tone="system">{qbCountRules(tree)} rule{qbCountRules(tree)===1?"":"s"}</Chip>
              <button className="btn btn-sm btn-ghost"
                onClick={() => onChange(qbNewGroup("AND", ctx.fields))}>
                <Icon name="refresh" size={12}/> Reset
              </button>
            </div>
          </div>
          <div style={{padding:"4px 16px 16px"}}>
            <QBGroup node={tree} depth={0} isRoot
              onChange={onChange}
              onRemove={() => {}}/>
          </div>
        </div>

        {/* Row cap */}
        <div className="card">
          <div className="card-header">
            <div>
              <h3 className="t-h3" style={{margin:0}}>Row cap</h3>
              <div className="t-cap">
                Hard ceiling on the result set. The DSA monthly budget applies
                even when this is unset.
              </div>
            </div>
          </div>
          <div style={{padding:16, display:"flex", alignItems:"center", gap:16}}>
            <input className="field-input" type="number" min={1} step={1000}
              placeholder="Unbounded — DSA budget applies"
              value={maxRows}
              onChange={e => onMaxRows(e.target.value.replace(/[^0-9]/g, ""))}
              style={{maxWidth:260}}/>
            <div className="row gap-2" style={{flexWrap:"wrap"}}>
              {[1000, 5000, 10000, 50000].map(n => (
                <button key={n} className="btn btn-sm" onClick={() => onMaxRows(String(n))}>
                  {n.toLocaleString()}
                </button>
              ))}
              <button className="btn btn-sm btn-ghost" onClick={() => onMaxRows("")}>
                Unbounded
              </button>
            </div>
          </div>
        </div>

        {/* Expression preview */}
        {showSQL && (
          <div className="card">
            <div className="card-header">
              <div>
                <h3 className="t-h3" style={{margin:0}}>Expression preview</h3>
                <div className="t-cap">
                  Read-only — the server runs validation + SQL generation. Question
                  marks mean an unfilled value.
                </div>
              </div>
              <button className="btn btn-sm btn-ghost"
                onClick={() => navigator.clipboard?.writeText(sql)}>
                <Icon name="duplicate" size={12}/> Copy
              </button>
            </div>
            <pre className="t-mono" style={{
              margin:0, padding:16, fontSize:12, lineHeight:1.55,
              background:"var(--neutral-50)",
              borderTop:"1px solid var(--neutral-200)",
              color:"var(--neutral-900)", whiteSpace:"pre-wrap",
              borderBottomLeftRadius:"var(--radius-card)",
              borderBottomRightRadius:"var(--radius-card)",
            }}>
{`SELECT *
FROM nsr.household
WHERE ${sql.replace(/^\(\n  /, "").replace(/\n\)$/, "").replace(/\n  /g, "\n  ")}${maxRows ? `\nLIMIT ${Number(maxRows).toLocaleString()}` : ""};`}
            </pre>
          </div>
        )}
      </div>

      {/* Right rail */}
      <div className="col gap-3">
        {/* Estimated match card */}
        <div className="card" style={{borderTop:"3px solid var(--accent-data)"}}>
          <div style={{padding:16}}>
            <div className="t-cap" style={{color:"var(--accent-data)", fontWeight:600}}>
              <Icon name="target" size={11}/> ESTIMATED MATCHES
            </div>
            <div className="t-num" style={{
              fontSize:32, fontWeight:700, letterSpacing:"-0.01em",
              marginTop:4, color:"var(--neutral-900)",
            }}>{estimate.toLocaleString()}</div>
            <div className="t-cap">
              of 12,089,442 households · {(estimate/12089442*100).toFixed(2)}% of registry
            </div>
            <div style={{
              height:6, background:"var(--neutral-200)", borderRadius:3,
              marginTop:10, overflow:"hidden",
            }}>
              <div style={{
                width:`${Math.max(0.5, estimate/12089442*100)}%`, height:"100%",
                background:"var(--accent-data)",
              }}/>
            </div>
            <button className="btn btn-sm mt-3" style={{width:"100%"}}>
              <Icon name="refresh" size={12}/> Recount
            </button>
            <div className="t-cap mt-2" style={{color:"var(--neutral-500)"}}>
              Estimate runs against an anonymised sample. Final row count
              is computed at delivery time.
            </div>
          </div>
        </div>

        {/* DSA card */}
        <div className="card" style={{borderTop:'3px solid var(--accent-system)'}}>
          <div className="card-header" style={{padding:'12px 16px'}}>
            <div>
              <div className="t-cap" style={{color:'var(--accent-system)'}}>ACTIVE DSA</div>
              <h3 className="t-h3" style={{margin:'2px 0 0'}}>{dsaReference}</h3>
            </div>
            <Chip tone="data">Active</Chip>
          </div>
          <div style={{padding:16}}>
            <div style={{display:'grid', gridTemplateColumns:'110px 1fr', rowGap:6, fontSize:13}}>
              <div className="muted">Partner</div><div>Office of the Prime Minister</div>
              <div className="muted">Programme</div><div>OPM-PDM 2026</div>
              <div className="muted">Valid to</div>
                <div>31 Dec 2026 <Chip size="sm" tone="data">8 months left</Chip></div>
              <div className="muted">Row budget</div><div>2,500,000 / month</div>
              <div className="muted">Used</div><div>1,824,317 (73%)</div>
            </div>
            <div style={{
              height:6, background:'var(--neutral-200)', borderRadius:3,
              marginTop:10, overflow:'hidden',
            }}>
              <div style={{width:'73%', height:'100%', background:'var(--accent-system)'}}/>
            </div>
            <div className="t-cap mt-3">
              Sensitive fields: <strong>4 disabled</strong> by clause 4.2.b.
            </div>
          </div>
        </div>

        {/* Saved queries */}
        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}>
            <div>
              <div className="t-cap">RECENT QUERIES</div>
              <h3 className="t-h3" style={{margin:'2px 0 0'}}>Saved</h3>
            </div>
            <button className="icon-btn" title="Save current"><Icon name="save" size={14}/></button>
          </div>
          <div>
            {[
              { name:"Karamoja · q1 vulnerability", rules:5, when:"yesterday" },
              { name:"PDM Buganda renewals",       rules:3, when:"3 days ago" },
              { name:"SCG · 60+ heads",             rules:2, when:"last week" },
            ].map(q => (
              <div key={q.name} style={{
                padding:"10px 16px", borderTop:"1px solid var(--neutral-200)",
                display:"flex", alignItems:"center", gap:8, cursor:"pointer",
              }}>
                <Icon name="history" size={14} color="var(--neutral-500)"/>
                <div style={{flex:1, minWidth:0}}>
                  <div className="t-bodysm" style={{
                    fontWeight:500, whiteSpace:"nowrap", overflow:"hidden",
                    textOverflow:"ellipsis",
                  }}>{q.name}</div>
                  <div className="t-cap">{q.rules} rules · {q.when}</div>
                </div>
                <Icon name="chevronRight" size={14} color="var(--neutral-500)"/>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
    </QBFieldsContext.Provider>
  );
};

Object.assign(window, {
  BuildStepV2,
  qbNewGroup, qbNewRule, qbId,
  QB_FIELDS, QB_FIELD_BY_KEY, QB_RECIPES,
});
