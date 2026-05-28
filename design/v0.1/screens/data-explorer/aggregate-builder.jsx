/* global React, Icon, Chip, PageHeader, DataExplorerPrivacyChip, useDataExplorerCatalogue */
// NSR MIS — Data Explorer · Aggregate builder (US-DATA-EXP-001)
// =========================================================
// Core analytics surface. The user picks an entity + projection
// variables + filters + a geographic scope; the screen POSTs to
// /aggregate; the response renders as a chart + table with the
// k-anonymity suppression rules honoured visually.
//
// Architecture: ADR-0023 §D3 (k-anonymity), §D4 (geographic floor),
// §D6 (per-class throttle), §D8 (Suppressed badge token).
//
// Wired from (Coder-owned backend):
//   POST /api/v1/data-explorer/aggregate                 — run query
//   GET  /api/v1/data-explorer/datasets                  — entity picker
//   GET  /api/v1/data-explorer/datasets/{id}/variables   — variable picker
//   GET  /api/v1/data-explorer/privacy-classes           — class catalogue
//   GET  /api/v1/data-explorer/suppression-vocabulary    — Suppressed token

const { useState: useStateAGG, useEffect: useEffectAGG, useMemo: useMemoAGG, useCallback: useCallbackAGG } = React;

const AGG_I18N = {
  "data_explorer.aggregate.eyebrow": "DATA EXPLORER · AGGREGATE BUILDER",
  "data_explorer.aggregate.title": "Aggregate query",
  "data_explorer.aggregate.sub":
    "Build a counts-only query against the registry. Cells below the k-anonymity floor are suppressed automatically.",
  "data_explorer.aggregate.pane.query": "Query",
  "data_explorer.aggregate.pane.results": "Results",
  "data_explorer.aggregate.pane.metadata": "Metadata",
  "data_explorer.aggregate.entity.label": "Dataset",
  "data_explorer.aggregate.entity.placeholder": "Select a dataset…",
  "data_explorer.aggregate.variables.title": "Variables",
  "data_explorer.aggregate.variables.empty": "Pick a dataset to see its variables.",
  "data_explorer.aggregate.projection.title": "Projection axes",
  "data_explorer.aggregate.projection.hint":
    "Drop or click 1–2 variables. Group-by axes drive the chart and table rows.",
  "data_explorer.aggregate.projection.empty": "No projection axes yet.",
  "data_explorer.aggregate.filters.title": "Filters",
  "data_explorer.aggregate.filters.hint":
    "Optional filters narrow the cohort. Operators reflect the variable's type.",
  "data_explorer.aggregate.filters.empty": "No filters applied.",
  "data_explorer.aggregate.geography.title": "Geographic scope",
  "data_explorer.aggregate.geography.hint_floor":
    "Aggregate not available below sub-county; use 'Request record-level data' on this dataset for parish/village access.",
  "data_explorer.aggregate.geography.level.sub_region": "Sub-region",
  "data_explorer.aggregate.geography.level.district": "District",
  "data_explorer.aggregate.geography.level.sub_county": "Sub-county",
  "data_explorer.aggregate.geography.level.parish": "Parish",
  "data_explorer.aggregate.geography.level.village": "Village",
  "data_explorer.aggregate.run": "Run aggregate",
  "data_explorer.aggregate.running": "Running…",
  "data_explorer.aggregate.cell.suppressed_tooltip":
    "Count below privacy floor — see ADR-0023 for details.",
  "data_explorer.aggregate.suppressed_caption":
    "{suppressed} of {total} cells suppressed (count below k={k} floor)",
  "data_explorer.aggregate.results.empty":
    "Run the query to see results. Cells below the k-anonymity floor render as — with the Suppressed chip.",
  "data_explorer.aggregate.results.col.count": "Count",
  "data_explorer.aggregate.error.throttle":
    "Daily query cap reached for {class}. Try again in {retry}.",
  "data_explorer.aggregate.error.floor.title":
    "Aggregate below the sub-county floor is not available.",
  "data_explorer.aggregate.error.floor.cta":
    "Request record-level data — {scope} → parish level",
  "data_explorer.aggregate.error.stale.title":
    "Aggregate temporarily unavailable while data refreshes.",
  "data_explorer.aggregate.error.stale.body":
    "Last refresh: {refreshed}. Try again in a few minutes.",
  "data_explorer.aggregate.metadata.matview": "Matview",
  "data_explorer.aggregate.metadata.refreshed_at": "Refreshed",
  "data_explorer.aggregate.metadata.suppressed_cell_count": "Suppressed cells",
  "data_explorer.aggregate.metadata.strictest_class": "Strictest class",
  "data_explorer.aggregate.metadata.empty": "Run the query to see metadata.",
};
const ti = (key, vars = {}) => {
  let s = AGG_I18N[key] || key;
  for (const [k, v] of Object.entries(vars)) {
    s = s.replaceAll(`{${k}}`, String(v));
  }
  return s;
};

/* ============================================================
   Operators by type — type-aware operator dropdown. Keys mirror the
   query DSL the Coder accepts. New types add operators here, not in
   the JSX (no inline ternary lists).
   ============================================================ */
const AGG_OPERATORS_BY_TYPE = {
  text:    [{ op: "eq", label: "is" }, { op: "in", label: "is one of" }],
  integer: [
    { op: "eq", label: "is" }, { op: "gte", label: "≥" },
    { op: "lte", label: "≤" }, { op: "between", label: "between" },
  ],
  number: [
    { op: "eq", label: "is" }, { op: "gte", label: "≥" },
    { op: "lte", label: "≤" }, { op: "between", label: "between" },
  ],
  enum:    [{ op: "eq", label: "is" }, { op: "in", label: "is one of" }],
  boolean: [{ op: "eq", label: "is" }],
  date:    [
    { op: "eq", label: "is" }, { op: "gte", label: "on or after" },
    { op: "lte", label: "on or before" }, { op: "between", label: "between" },
  ],
};
const operatorsFor = (type) => AGG_OPERATORS_BY_TYPE[type] || [{ op: "eq", label: "is" }];

/* ============================================================
   Suppression vocabulary — fetched from the API at mount. Mock
   fallback covers file:// preview. Token + label per ADR-0023 §D8.
   ============================================================ */
const AGG_SUPPRESSED_BADGE_MOCK = {
  code: "SUPPRESSED",
  label: "Suppressed",
  token_fg: "var(--neutral-700)",
  token_bg: "var(--neutral-100)",
};

/* ============================================================
   Mock fallback — sample aggregate result so the chart + table render
   under file://. The shape mirrors what the Coder's /aggregate
   endpoint will return.
   ============================================================ */
const AGG_RESULT_MOCK = {
  rows: [
    { group_keys: { sub_region: "Karamoja",      head_sex: "F" }, count: 41212, suppressed: false },
    { group_keys: { sub_region: "Karamoja",      head_sex: "M" }, count: 28814, suppressed: false },
    { group_keys: { sub_region: "West Nile",     head_sex: "F" }, count: 102341, suppressed: false },
    { group_keys: { sub_region: "West Nile",     head_sex: "M" }, count: 88011, suppressed: false },
    { group_keys: { sub_region: "Acholi",        head_sex: "F" }, count: 64412, suppressed: false },
    { group_keys: { sub_region: "Acholi",        head_sex: "M" }, count: 51109, suppressed: false },
    { group_keys: { sub_region: "Sebei",         head_sex: "F" }, count: null,  suppressed: true  },
    { group_keys: { sub_region: "Sebei",         head_sex: "M" }, count: null,  suppressed: true  },
  ],
  metadata: {
    matview: "mv_explorer_household_by_subcounty_demographics",
    refreshed_at: "2026-05-27T02:00:00+03:00",
    suppressed_cell_count: 2,
    strictest_class: "Internal",
    k_floor: 5,
    total_cells: 8,
  },
};

const _fmtTimestamp = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const m = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d.getDate().toString().padStart(2,"0")} ${m[d.getMonth()]} ${d.getFullYear()} · ${d.getHours().toString().padStart(2,"0")}:${d.getMinutes().toString().padStart(2,"0")} EAT`;
};

const _csrf = () => {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

/* ============================================================
   Hook: load datasets + their variables on demand, and the
   suppression-vocabulary entry.
   ============================================================ */
const useAggregateBuilderData = (selectedDatasetId) => {
  const [datasets, setDatasets] = useStateAGG(window.DXC_DATASETS_MOCK || []);
  const [variables, setVariables] = useStateAGG([]);
  const [suppressedBadge, setSuppressedBadge] = useStateAGG(AGG_SUPPRESSED_BADGE_MOCK);
  const [source, setSource] = useStateAGG("loading");

  useEffectAGG(() => {
    let cancelled = false;
    const fetchJson = (url) => fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

    Promise.all([
      fetchJson("/api/v1/data-explorer/datasets"),
      fetchJson("/api/v1/data-explorer/suppression-vocabulary").catch(() => null),
    ])
      .then(([ds, vocab]) => {
        if (cancelled) return;
        const rows = (ds && Array.isArray(ds.results)) ? ds.results
          : Array.isArray(ds) ? ds : (window.DXC_DATASETS_MOCK || []);
        setDatasets(rows);
        if (vocab?.suppressed) setSuppressedBadge(vocab.suppressed);
        setSource("live");
      })
      .catch(() => {
        if (cancelled) return;
        setSource("fallback");
      });
    return () => { cancelled = true; };
  }, []);

  useEffectAGG(() => {
    let cancelled = false;
    if (!selectedDatasetId) {
      setVariables([]);
      return;
    }
    fetch(`/api/v1/data-explorer/datasets/${selectedDatasetId}/variables`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((v) => {
        if (cancelled) return;
        const rows = (v && Array.isArray(v.results)) ? v.results
          : Array.isArray(v) ? v : (window.DXD_VARIABLES_MOCK || []);
        setVariables(rows);
      })
      .catch(() => {
        if (cancelled) return;
        setVariables(window.DXD_VARIABLES_MOCK || []);
      });
    return () => { cancelled = true; };
  }, [selectedDatasetId]);

  return { datasets, variables, suppressedBadge, source };
};

/* ============================================================
   ChartBars — simple inline-SVG bar chart, modelled after the
   ThresholdDrift pattern in screens-pmt-dashboard.jsx. Suppressed
   cells render with a hatched fill so the empty rendering reads as
   "suppressed", not "missing".
   ============================================================ */
const ChartBars = ({ rows, labelFor }) => {
  const w = 720, h = 240, pad = { t: 16, r: 16, b: 56, l: 56 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;

  if (!rows || rows.length === 0) {
    return (
      <svg
        viewBox={`0 0 ${w} ${h}`}
        style={{ width: "100%", height: "auto", maxHeight: 300 }}
        role="img"
        aria-label="Aggregate result chart (no data)"
      >
        <text x={w/2} y={h/2} fontSize="12" textAnchor="middle" fill="var(--neutral-500)">
          No data yet — run the query
        </text>
      </svg>
    );
  }

  const visibleCounts = rows
    .map((r) => (r.suppressed ? 0 : Number(r.count ?? 0)))
    .filter((n) => Number.isFinite(n));
  const max = Math.max(1, ...visibleCounts);
  const barW = innerW / rows.length;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: "auto", maxHeight: 300 }}
      role="img"
      aria-label="Aggregate result chart"
    >
      <defs>
        <pattern
          id="agg-hatch"
          patternUnits="userSpaceOnUse"
          width="6" height="6"
          patternTransform="rotate(45)"
        >
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--neutral-500)" strokeWidth="1"/>
        </pattern>
      </defs>
      {/* y-axis ticks */}
      {[0, 0.25, 0.5, 0.75, 1].map((t, i) => {
        const v = max * t;
        const y = pad.t + (1 - t) * innerH;
        return (
          <g key={i}>
            <line
              x1={pad.l} y1={y} x2={w - pad.r} y2={y}
              stroke="var(--neutral-200)" strokeWidth={1}
            />
            <text
              x={pad.l - 6} y={y + 3}
              fontSize="10" textAnchor="end" fill="var(--neutral-500)"
            >{Math.round(v).toLocaleString()}</text>
          </g>
        );
      })}
      {/* bars */}
      {rows.map((r, i) => {
        const x = pad.l + i * barW + barW * 0.15;
        const bw = barW * 0.7;
        if (r.suppressed) {
          // Hatched outline only — no fill height. Communicates the
          // cell exists but the value is suppressed.
          return (
            <g key={i}>
              <rect
                x={x} y={pad.t}
                width={bw} height={innerH}
                fill="url(#agg-hatch)"
                stroke="var(--neutral-400)"
                strokeWidth="1"
                strokeDasharray="3 3"
                aria-label={`${labelFor(r) || ""} suppressed`}
              />
              <text
                x={x + bw/2} y={h - pad.b + 16}
                fontSize="10" textAnchor="middle"
                fill="var(--neutral-500)"
              >{labelFor(r)}</text>
            </g>
          );
        }
        const v = Number(r.count ?? 0);
        const bh = (v / max) * innerH;
        return (
          <g key={i}>
            <rect
              x={x} y={pad.t + (innerH - bh)}
              width={bw} height={bh}
              fill="var(--accent-system)"
              rx="2"
              aria-label={`${labelFor(r) || ""} ${v.toLocaleString()}`}
            />
            <text
              x={x + bw/2} y={pad.t + (innerH - bh) - 4}
              fontSize="10" textAnchor="middle"
              fill="var(--neutral-700)"
            >{v.toLocaleString()}</text>
            <text
              x={x + bw/2} y={h - pad.b + 16}
              fontSize="10" textAnchor="middle"
              fill="var(--neutral-700)"
            >{labelFor(r)}</text>
          </g>
        );
      })}
    </svg>
  );
};

/* ============================================================
   SuppressedChip — pulls token from /suppression-vocabulary
   ============================================================ */
const SuppressedChip = ({ badge }) => {
  if (!badge) return null;
  return (
    <span
      className="chip chip-sm"
      style={{
        color: badge.token_fg,
        background: badge.token_bg,
        border: `1px solid ${badge.token_fg}`,
      }}
      title={ti("data_explorer.aggregate.cell.suppressed_tooltip")}
      aria-label={`${badge.label}: ${ti("data_explorer.aggregate.cell.suppressed_tooltip")}`}
    >
      <Icon name="lock" size={11}/>
      {badge.label}
    </span>
  );
};

/* ============================================================
   AggregateBuilderScreen — primary export
   ============================================================ */
const AggregateBuilderScreen = ({
  initialDatasetId,
  initialProjectionVariable,
  onRequestRecords,
} = {}) => {
  const { privacyClasses } = useDataExplorerCatalogue();

  const [datasetId, setDatasetId] = useStateAGG(initialDatasetId || "");
  const [projection, setProjection] = useStateAGG(
    initialProjectionVariable ? [initialProjectionVariable] : [],
  );
  const [filters, setFilters] = useStateAGG([]);
  const [geoLevel, setGeoLevel] = useStateAGG("sub_county");
  const [running, setRunning] = useStateAGG(false);
  const [result, setResult] = useStateAGG(null);
  const [error, setError] = useStateAGG(null);

  const { datasets, variables, suppressedBadge, source } =
    useAggregateBuilderData(datasetId);

  // Auto-pick the first dataset on first render so the screen renders
  // a populated variable list under file:// preview.
  useEffectAGG(() => {
    if (!datasetId && datasets.length > 0) {
      setDatasetId(datasets[0].id);
    }
  }, [datasets, datasetId]);

  const currentDataset = useMemoAGG(
    () => datasets.find((d) => d.id === datasetId) || null,
    [datasets, datasetId],
  );

  const canRun = !running && projection.length >= 1 && datasetId;

  const addProjection = (code) => {
    if (projection.includes(code) || projection.length >= 2) return;
    setProjection([...projection, code]);
  };
  const removeProjection = (code) =>
    setProjection(projection.filter((c) => c !== code));
  const addFilter = (variable) => {
    if (filters.find((f) => f.variable_code === variable.code)) return;
    const ops = operatorsFor(variable.type);
    setFilters([...filters, {
      variable_code: variable.code,
      variable_label: variable.label,
      variable_type: variable.type,
      op: ops[0].op,
      value: "",
    }]);
  };
  const updateFilter = (idx, patch) =>
    setFilters(filters.map((f, i) => i === idx ? { ...f, ...patch } : f));
  const removeFilter = (idx) =>
    setFilters(filters.filter((_, i) => i !== idx));

  const runAggregate = useCallbackAGG(() => {
    if (!canRun) return;
    setRunning(true);
    setError(null);
    setResult(null);

    const payload = {
      dataset_id: datasetId,
      projection_variables: projection,
      filters: filters.map((f) => ({
        variable_code: f.variable_code,
        op: f.op, value: f.value,
      })),
      geographic_scope: { level: geoLevel },
    };

    fetch("/api/v1/data-explorer/aggregate", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": _csrf(),
      },
      body: JSON.stringify(payload),
    })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (r.status === 429) {
          throw { kind: "throttle", body, retryAfter: r.headers.get("Retry-After") };
        }
        if (r.status === 422 && body?.error === "geographic_floor_violation") {
          throw { kind: "floor", body };
        }
        if (r.status === 503 && body?.error === "matview_stale") {
          throw { kind: "stale", body };
        }
        if (!r.ok) throw { kind: "other", body };
        return body;
      })
      .then((body) => setResult(body))
      .catch((e) => {
        // Live API unreachable in preview — show the mock result so
        // the chart + table still render rather than dead-ending on
        // an error toast.
        if (!e || !e.kind) {
          setResult(AGG_RESULT_MOCK);
          return;
        }
        setError(e);
      })
      .finally(() => setRunning(false));
  }, [canRun, datasetId, projection, filters, geoLevel]);

  // Project the result rows into chart-friendly labels.
  const chartRows = useMemoAGG(() => {
    if (!result?.rows) return [];
    return result.rows.map((r) => ({
      ...r,
      _label: Object.values(r.group_keys || {}).join(" · "),
    }));
  }, [result]);

  const projectionVars = useMemoAGG(
    () => projection.map((code) => variables.find((v) => v.code === code)).filter(Boolean),
    [projection, variables],
  );

  const eyebrowSuffix = source === "live" ? " · LIVE"
    : source === "fallback" ? " · MOCK PREVIEW" : " · loading…";

  return (
    <div className="page">
      <PageHeader
        eyebrow={ti("data_explorer.aggregate.eyebrow") + eyebrowSuffix}
        title={ti("data_explorer.aggregate.title")}
        sub={ti("data_explorer.aggregate.sub")}
      />

      {/* 3-pane layout: query | results | metadata */}
      <div
        className="grid"
        style={{ gridTemplateColumns: "minmax(300px, 380px) 1fr 280px", gap: 16 }}
      >
        {/* ============================ QUERY PANE ============================ */}
        <section className="card" style={{ padding: 0 }} aria-label="Query builder">
          <header
            style={{
              padding: "14px 18px",
              borderBottom: "1px solid var(--neutral-200)",
            }}
          >
            <h3 className="t-h3" style={{ margin: 0, fontSize: 15 }}>
              {ti("data_explorer.aggregate.pane.query")}
            </h3>
          </header>

          <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Entity picker */}
            <div className="field">
              <label className="field-label" htmlFor="agg-dataset">
                {ti("data_explorer.aggregate.entity.label")}
              </label>
              <select
                id="agg-dataset"
                className="field-select"
                value={datasetId}
                onChange={(e) => {
                  setDatasetId(e.target.value);
                  setProjection([]);
                  setFilters([]);
                  setResult(null);
                  setError(null);
                }}
              >
                <option value="">{ti("data_explorer.aggregate.entity.placeholder")}</option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>{d.title}</option>
                ))}
              </select>
            </div>

            {/* Variable picker — clickable chips, click to add to projection */}
            <div>
              <div
                className="t-cap"
                style={{ fontWeight: 600, marginBottom: 6 }}
              >
                {ti("data_explorer.aggregate.variables.title")}
              </div>
              {variables.length === 0 ? (
                <div className="t-cap muted">
                  {ti("data_explorer.aggregate.variables.empty")}
                </div>
              ) : (
                <div
                  className="row gap-1"
                  style={{ flexWrap: "wrap", maxHeight: 180, overflowY: "auto" }}
                  role="list"
                >
                  {variables.map((v) => (
                    <button
                      key={v.code}
                      type="button"
                      role="listitem"
                      onClick={() => addProjection(v.code)}
                      disabled={projection.includes(v.code) || projection.length >= 2}
                      title={v.label}
                      aria-label={`Add ${v.label} to projection`}
                      style={{
                        padding: "4px 8px", borderRadius: 4, fontSize: 12,
                        border: "1px solid var(--neutral-300)",
                        background: projection.includes(v.code)
                          ? "var(--accent-system-bg)" : "white",
                        cursor: projection.length >= 2 && !projection.includes(v.code)
                          ? "not-allowed" : "pointer",
                        opacity: projection.length >= 2 && !projection.includes(v.code)
                          ? 0.5 : 1,
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}
                    >
                      <span className="t-mono">{v.code}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Projection axes drop zone */}
            <div
              role="region"
              aria-label="Projection axes"
              style={{
                padding: 12,
                border: "1px dashed var(--neutral-300)",
                borderRadius: 6,
                background: "var(--accent-system-bg)",
              }}
            >
              <div
                className="t-cap"
                style={{ fontWeight: 600, marginBottom: 6 }}
              >
                {ti("data_explorer.aggregate.projection.title")}
              </div>
              {projectionVars.length === 0 ? (
                <div className="t-cap muted">
                  {ti("data_explorer.aggregate.projection.empty")}
                </div>
              ) : (
                <div className="row gap-2" style={{ flexWrap: "wrap" }}>
                  {projectionVars.map((v) => (
                    <span
                      key={v.code}
                      className="chip chip-sm"
                      style={{
                        color: "var(--accent-system)",
                        background: "white",
                        border: "1px solid var(--accent-system)",
                      }}
                    >
                      {v.label}
                      <button
                        type="button"
                        onClick={() => removeProjection(v.code)}
                        aria-label={`Remove ${v.label}`}
                        style={{
                          background: "none", border: 0, padding: 0,
                          marginLeft: 4, cursor: "pointer",
                          color: "var(--neutral-600)",
                        }}
                      >
                        <Icon name="x" size={11}/>
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="t-cap mt-2" style={{ color: "var(--neutral-600)" }}>
                {ti("data_explorer.aggregate.projection.hint")}
              </div>
            </div>

            {/* Filters */}
            <div>
              <div
                className="t-cap"
                style={{ fontWeight: 600, marginBottom: 6 }}
              >
                {ti("data_explorer.aggregate.filters.title")}
              </div>
              {filters.length === 0 ? (
                <div className="t-cap muted">
                  {ti("data_explorer.aggregate.filters.empty")}
                </div>
              ) : (
                <div
                  className="col gap-2"
                  role="list"
                  aria-label="Active filters"
                >
                  {filters.map((f, i) => {
                    const ops = operatorsFor(f.variable_type);
                    return (
                      <div
                        key={i}
                        role="listitem"
                        className="row gap-2"
                        style={{
                          padding: 8,
                          borderRadius: 4,
                          background: "var(--neutral-50, #f7f8fa)",
                          alignItems: "center",
                        }}
                      >
                        <span className="t-bodysm" style={{ flex: 1, minWidth: 0 }}>
                          {f.variable_label}
                        </span>
                        <select
                          className="field-select"
                          style={{ height: 28, width: "auto", minWidth: 90 }}
                          value={f.op}
                          onChange={(e) => updateFilter(i, { op: e.target.value })}
                          aria-label={`Operator for ${f.variable_label}`}
                        >
                          {ops.map((o) => (
                            <option key={o.op} value={o.op}>{o.label}</option>
                          ))}
                        </select>
                        <input
                          className="field-input"
                          style={{ height: 28, width: 90 }}
                          value={f.value}
                          onChange={(e) => updateFilter(i, { value: e.target.value })}
                          placeholder="value"
                          aria-label={`Value for ${f.variable_label}`}
                        />
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => removeFilter(i)}
                          aria-label={`Remove filter ${f.variable_label}`}
                        >
                          <Icon name="x" size={12}/>
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="t-cap mt-2" style={{ color: "var(--neutral-600)" }}>
                {ti("data_explorer.aggregate.filters.hint")}
              </div>
              {variables.length > 0 && filters.length < 4 && (
                <details style={{ marginTop: 8 }}>
                  <summary
                    className="t-cap"
                    style={{ cursor: "pointer", color: "var(--accent-system)" }}
                  >
                    + Add filter
                  </summary>
                  <div
                    className="row gap-1"
                    style={{ flexWrap: "wrap", marginTop: 6 }}
                  >
                    {variables
                      .filter((v) => !filters.find((f) => f.variable_code === v.code))
                      .map((v) => (
                        <button
                          key={v.code}
                          type="button"
                          onClick={() => addFilter(v)}
                          style={{
                            padding: "3px 6px", borderRadius: 4,
                            fontSize: 11, border: "1px solid var(--neutral-300)",
                            background: "white", cursor: "pointer",
                          }}
                          aria-label={`Add filter on ${v.label}`}
                        >
                          {v.label}
                        </button>
                      ))}
                  </div>
                </details>
              )}
            </div>

            {/* Geographic scope */}
            <fieldset
              style={{
                border: "1px solid var(--neutral-200)",
                borderRadius: 4, padding: 12, margin: 0,
              }}
            >
              <legend
                className="t-cap"
                style={{ fontWeight: 600, padding: "0 6px" }}
              >
                {ti("data_explorer.aggregate.geography.title")}
              </legend>
              <div className="col gap-1">
                {["sub_region", "district", "sub_county", "parish", "village"].map((lvl) => {
                  const belowFloor = lvl === "parish" || lvl === "village";
                  return (
                    <label
                      key={lvl}
                      className="row gap-2"
                      style={{
                        alignItems: "center",
                        opacity: belowFloor ? 0.5 : 1,
                        cursor: belowFloor ? "not-allowed" : "pointer",
                      }}
                    >
                      <input
                        type="radio"
                        name="agg-geo-level"
                        value={lvl}
                        checked={geoLevel === lvl}
                        onChange={(e) => setGeoLevel(e.target.value)}
                        disabled={belowFloor}
                        aria-describedby={belowFloor ? "agg-geo-floor-hint" : undefined}
                      />
                      <span className="t-bodysm">
                        {ti(`data_explorer.aggregate.geography.level.${lvl}`)}
                      </span>
                    </label>
                  );
                })}
              </div>
              <div
                id="agg-geo-floor-hint"
                className="t-cap"
                style={{ marginTop: 8, color: "var(--neutral-600)" }}
              >
                {ti("data_explorer.aggregate.geography.hint_floor")}
              </div>
            </fieldset>

            {/* Run button */}
            <button
              type="button"
              className="btn btn-primary"
              onClick={runAggregate}
              disabled={!canRun}
              aria-disabled={!canRun}
            >
              <Icon name="play" size={14}/>
              {running ? ti("data_explorer.aggregate.running") : ti("data_explorer.aggregate.run")}
            </button>
          </div>
        </section>

        {/* ============================ RESULTS PANE ============================ */}
        <section className="card" style={{ padding: 0 }} aria-label="Results">
          <header
            style={{
              padding: "14px 18px",
              borderBottom: "1px solid var(--neutral-200)",
              display: "flex", alignItems: "center", gap: 12,
            }}
          >
            <h3 className="t-h3" style={{ margin: 0, fontSize: 15 }}>
              {ti("data_explorer.aggregate.pane.results")}
            </h3>
            {result && (
              <span className="t-cap">
                {ti("data_explorer.aggregate.suppressed_caption", {
                  suppressed: result.metadata?.suppressed_cell_count ?? 0,
                  total: result.metadata?.total_cells ?? (result.rows || []).length,
                  k: result.metadata?.k_floor ?? "?",
                })}
              </span>
            )}
          </header>

          <div style={{ padding: 18 }}>
            {/* Error paths first — they replace the chart + table */}
            {error?.kind === "throttle" && (
              <div
                role="alert"
                className="card"
                style={{
                  padding: 16,
                  borderLeft: "3px solid var(--accent-danger)",
                  background: "var(--accent-danger-bg)",
                }}
              >
                <strong>{ti("data_explorer.aggregate.error.throttle", {
                  class: error.body?.privacy_class || "—",
                  retry: error.retryAfter ? `${error.retryAfter}s` : "tomorrow",
                })}</strong>
              </div>
            )}

            {error?.kind === "floor" && (
              <div
                role="alert"
                className="card"
                style={{
                  padding: 16,
                  borderLeft: "3px solid var(--accent-quality)",
                  background: "var(--accent-quality-bg)",
                }}
              >
                <h4 className="t-h3" style={{ margin: "0 0 6px", fontSize: 15 }}>
                  {ti("data_explorer.aggregate.error.floor.title")}
                </h4>
                <p className="t-bodysm" style={{ margin: "0 0 12px" }}>
                  {ti("data_explorer.aggregate.geography.hint_floor")}
                </p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => onRequestRecords?.({
                    dataset_id: datasetId,
                    projection_variables: projection,
                    filters,
                    geographic_scope: {
                      level: error.body?.requested_level || "parish",
                      codes: error.body?.requested_codes || [],
                    },
                  })}
                >
                  <Icon name="download" size={13}/>
                  {ti("data_explorer.aggregate.error.floor.cta", {
                    scope: error.body?.scope_label || currentDataset?.title || "this dataset",
                  })}
                </button>
              </div>
            )}

            {error?.kind === "stale" && (
              <div
                role="alert"
                className="card"
                style={{
                  padding: 16,
                  borderLeft: "3px solid var(--accent-update)",
                  background: "var(--accent-update-bg)",
                }}
              >
                <h4 className="t-h3" style={{ margin: "0 0 6px", fontSize: 15 }}>
                  {ti("data_explorer.aggregate.error.stale.title")}
                </h4>
                <p className="t-bodysm" style={{ margin: 0 }}>
                  {ti("data_explorer.aggregate.error.stale.body", {
                    refreshed: _fmtTimestamp(error.body?.refreshed_at) || "—",
                  })}
                </p>
              </div>
            )}

            {/* Result render */}
            {!error && result && (
              <>
                <div style={{ marginBottom: 18 }}>
                  <ChartBars rows={chartRows} labelFor={(r) => r._label}/>
                </div>
                <table className="tbl" style={{ boxShadow: "none" }}>
                  <thead>
                    <tr>
                      {projection.map((p) => (
                        <th key={p} scope="col">{p}</th>
                      ))}
                      {!projection.includes(geoLevel) && (
                        <th scope="col">{ti(`data_explorer.aggregate.geography.level.${geoLevel}`)}</th>
                      )}
                      <th scope="col" style={{ textAlign: "right" }}>
                        {ti("data_explorer.aggregate.results.col.count")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.rows || []).map((row, i) => {
                      const keys = row.group_keys || {};
                      return (
                        <tr key={i}>
                          {projection.map((p) => (
                            <td key={p}>{keys[p] ?? "—"}</td>
                          ))}
                          {!projection.includes(geoLevel) && (
                            <td>{keys[geoLevel] ?? keys.sub_region ?? "—"}</td>
                          )}
                          <td
                            style={{ textAlign: "right" }}
                            aria-label={row.suppressed
                              ? `Suppressed — ${ti("data_explorer.aggregate.cell.suppressed_tooltip")}`
                              : `${Number(row.count).toLocaleString()}`}
                          >
                            {row.suppressed ? (
                              <span className="row gap-1" style={{
                                justifyContent: "flex-end", alignItems: "center",
                              }}>
                                <span aria-hidden="true">—</span>
                                <SuppressedChip badge={suppressedBadge}/>
                              </span>
                            ) : (
                              <span className="t-num">
                                {Number(row.count).toLocaleString()}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}

            {!error && !result && (
              <div
                role="status"
                style={{
                  padding: 32, textAlign: "center",
                  color: "var(--neutral-600)",
                }}
              >
                {ti("data_explorer.aggregate.results.empty")}
              </div>
            )}
          </div>
        </section>

        {/* ============================ METADATA PANE ============================ */}
        <aside className="card" style={{ padding: 18 }} aria-label="Metadata">
          <h3 className="t-h3" style={{ margin: "0 0 12px", fontSize: 15 }}>
            {ti("data_explorer.aggregate.pane.metadata")}
          </h3>
          {result?.metadata ? (
            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "1fr",
                rowGap: 10, margin: 0,
              }}
            >
              <div>
                <dt className="t-cap" style={{ fontWeight: 600 }}>
                  {ti("data_explorer.aggregate.metadata.matview")}
                </dt>
                <dd className="t-mono t-bodysm" style={{ margin: 0, wordBreak: "break-all" }}>
                  {result.metadata.matview || "—"}
                </dd>
              </div>
              <div>
                <dt className="t-cap" style={{ fontWeight: 600 }}>
                  {ti("data_explorer.aggregate.metadata.refreshed_at")}
                </dt>
                <dd className="t-bodysm" style={{ margin: 0 }}>
                  {_fmtTimestamp(result.metadata.refreshed_at) || "—"}
                </dd>
              </div>
              <div>
                <dt className="t-cap" style={{ fontWeight: 600 }}>
                  {ti("data_explorer.aggregate.metadata.suppressed_cell_count")}
                </dt>
                <dd className="t-bodysm" style={{ margin: 0 }}>
                  <span className="t-num">{result.metadata.suppressed_cell_count ?? 0}</span>
                  {result.metadata.total_cells != null && (
                    <span className="t-cap" style={{ color: "var(--neutral-500)", marginLeft: 4 }}>
                      / {result.metadata.total_cells}
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="t-cap" style={{ fontWeight: 600 }}>
                  {ti("data_explorer.aggregate.metadata.strictest_class")}
                </dt>
                <dd style={{ margin: 0 }}>
                  {window.DataExplorerPrivacyChip ? (
                    <window.DataExplorerPrivacyChip
                      classCode={result.metadata.strictest_class}
                      classes={privacyClasses}
                      size="sm"
                    />
                  ) : (
                    <span className="t-bodysm">{result.metadata.strictest_class || "—"}</span>
                  )}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="t-cap" style={{ margin: 0, color: "var(--neutral-600)" }}>
              {ti("data_explorer.aggregate.metadata.empty")}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
};

Object.assign(window, {
  AggregateBuilderScreen,
  useAggregateBuilderData,
  AGG_RESULT_MOCK,
  AGG_SUPPRESSED_BADGE_MOCK,
  AGG_I18N,
});
