/* global React, Icon, Chip, PageHeader, DataExplorerPrivacyChip, DataExplorerAggregatedOnlyBadge, DataExplorerFacetChips, useDataExplorerCatalogue, DXC_DATASETS_MOCK */
// NSR MIS — Data Explorer · Dataset detail (US-DATA-EXP-001)
// =========================================================
// One-dataset view: variable dictionary, coverage panel, synthetic
// sample preview, and the "Request record-level data" handoff CTA.
//
// Architecture: ADR-0023 §D1 (module boundary), §D2 (matview shape +
// coverage), §D3 (k-anonymity + Sensitive blocking), §D4 (geographic
// floor), §D8 (Aggregated-only badge).
//
// Wired from (Coder-owned backend):
//   GET /api/v1/data-explorer/datasets/{id}            — dataset meta
//   GET /api/v1/data-explorer/datasets/{id}/variables  — variable table
//   GET /api/v1/data-explorer/coverage/{id}            — sub-region coverage
//   GET /api/v1/data-explorer/synthetic-sample/{id}    — synthetic rows
//   GET /api/v1/data-explorer/privacy-classes          — class catalogue

const { useState: useStateDXD, useEffect: useEffectDXD, useMemo: useMemoDXD } = React;

const DXD_I18N = {
  "data_explorer.dataset.eyebrow": "DATA EXPLORER · DATASET",
  "data_explorer.dataset.back": "Back to catalogue",
  "data_explorer.dataset.cta.request_records": "Request record-level data",
  "data_explorer.dataset.cta.use_in_aggregate": "Use in aggregate",
  "data_explorer.dataset.cta.tip_sensitive":
    "Record-level access requires DSA. Contact your DPO.",
  "data_explorer.dataset.variables.title": "Variable dictionary",
  "data_explorer.dataset.variables.sub":
    "Each row maps to a model field. Click a row to open its full data-dictionary entry.",
  "data_explorer.dataset.variables.facet.privacy": "Sensitivity",
  "data_explorer.dataset.variables.facet.completeness": "Has completeness baseline",
  "data_explorer.dataset.variables.completeness.with": "With baseline",
  "data_explorer.dataset.variables.completeness.without": "Without",
  "data_explorer.dataset.variables.col.code": "Code",
  "data_explorer.dataset.variables.col.label": "Label",
  "data_explorer.dataset.variables.col.type": "Type",
  "data_explorer.dataset.variables.col.privacy": "Sensitivity",
  "data_explorer.dataset.variables.col.completeness": "Completeness",
  "data_explorer.dataset.variables.col.cadence": "Refresh",
  "data_explorer.dataset.variables.col.action": "",
  "data_explorer.dataset.variables.empty": "No variables match this filter.",
  "data_explorer.dataset.variables.view": "View",
  "data_explorer.dataset.coverage.title": "Coverage",
  "data_explorer.dataset.coverage.sub": "% completeness across sub-regions",
  "data_explorer.dataset.coverage.empty": "No coverage snapshot recorded yet.",
  "data_explorer.dataset.sample.title": "Synthetic sample",
  "data_explorer.dataset.sample.caption_warn":
    "Synthetic sample — not real records. Shape only; never matches a household.",
  "data_explorer.dataset.sample.toggle.show": "Show synthetic sample",
  "data_explorer.dataset.sample.toggle.hide": "Hide synthetic sample",
  "data_explorer.dataset.sample.empty":
    "No synthetic sample published for this dataset.",
  "data_explorer.dataset.meta.refresh_cadence": "Refresh cadence",
  "data_explorer.dataset.meta.last_refreshed": "Last refreshed",
  "data_explorer.dataset.meta.coverage_floor": "Geographic floor",
  "data_explorer.dataset.meta.variables_count": "Variables",
};
const tt = (k) => DXD_I18N[k] || k;

/* ============================================================
   Mock fallbacks — only used when fetch() fails. Loosely mirror the
   shapes the Data Analyst's YAML produces.
   ============================================================ */
const DXD_VARIABLES_MOCK = [
  { code: "household_count",     label: "Households (count)",            type: "integer",
    privacy_class: "Internal",   completeness: 100.0, refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "head_sex",            label: "Head of household sex",         type: "enum",
    privacy_class: "Internal",   completeness: 99.7,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "head_age_band",       label: "Head of household age band",    type: "enum",
    privacy_class: "Internal",   completeness: 99.2,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "household_size_band", label: "Household size (band)",         type: "enum",
    privacy_class: "Internal",   completeness: 99.9,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "elderly_headed",      label: "Elderly-headed (60+)",          type: "boolean",
    privacy_class: "Internal",   completeness: 99.7,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "female_headed",       label: "Female-headed",                 type: "boolean",
    privacy_class: "Internal",   completeness: 99.7,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "child_headed",        label: "Child-headed (<18)",            type: "boolean",
    privacy_class: "Internal",   completeness: 99.7,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "members_under_5",     label: "Members under 5 (count band)",  type: "enum",
    privacy_class: "Internal",   completeness: 96.4,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "members_over_60",     label: "Members 60+ (count band)",      type: "enum",
    privacy_class: "Internal",   completeness: 96.4,  refresh_cadence: "daily",
    has_completeness_baseline: true },
  { code: "any_disability",      label: "Any disability (WG-SS positive)", type: "boolean",
    privacy_class: "Personal",   completeness: 92.1,  refresh_cadence: "weekly",
    has_completeness_baseline: true },
  { code: "sub_county_code",     label: "Sub-county code (UBOS)",        type: "text",
    privacy_class: "Public",     completeness: 100.0, refresh_cadence: "daily",
    has_completeness_baseline: false },
  { code: "district_code",       label: "District code (UBOS)",          type: "text",
    privacy_class: "Public",     completeness: 100.0, refresh_cadence: "daily",
    has_completeness_baseline: false },
];

const DXD_COVERAGE_MOCK = {
  generated_at: "2026-05-27T02:00:00+03:00",
  by_sub_region: [
    { sub_region_code: "SR-KARAMOJA",      sub_region_name: "Karamoja",      completeness_pct: 98.4 },
    { sub_region_code: "SR-WEST-NILE",     sub_region_name: "West Nile",     completeness_pct: 97.1 },
    { sub_region_code: "SR-ACHOLI",        sub_region_name: "Acholi",        completeness_pct: 96.8 },
    { sub_region_code: "SR-LANGO",         sub_region_name: "Lango",         completeness_pct: 95.2 },
    { sub_region_code: "SR-TESO",          sub_region_name: "Teso",          completeness_pct: 97.8 },
    { sub_region_code: "SR-BUKEDI",        sub_region_name: "Bukedi",        completeness_pct: 94.6 },
    { sub_region_code: "SR-BUSOGA",        sub_region_name: "Busoga",        completeness_pct: 93.4 },
    { sub_region_code: "SR-BUNYORO",       sub_region_name: "Bunyoro",       completeness_pct: 95.9 },
    { sub_region_code: "SR-TOORO",         sub_region_name: "Tooro",         completeness_pct: 92.7 },
    { sub_region_code: "SR-ANKOLE",        sub_region_name: "Ankole",        completeness_pct: 96.0 },
    { sub_region_code: "SR-KIGEZI",        sub_region_name: "Kigezi",        completeness_pct: 97.0 },
    { sub_region_code: "SR-BUGANDA-NORTH", sub_region_name: "Buganda North", completeness_pct: 91.2 },
    { sub_region_code: "SR-BUGANDA-SOUTH", sub_region_name: "Buganda South", completeness_pct: 89.8 },
    { sub_region_code: "SR-SEBEI",         sub_region_name: "Sebei",         completeness_pct: 98.0 },
  ],
};

const DXD_SAMPLE_MOCK = {
  warning: "synthetic — not real records",
  rows: [
    { sub_county_code: "STC-070101", household_count: 412, head_sex: "F", head_age_band: "30-44", household_size_band: "4-6",  elderly_headed: false, female_headed: true,  child_headed: false, members_under_5: "1",   members_over_60: "0",   any_disability: false },
    { sub_county_code: "STC-070102", household_count: 1241, head_sex: "M", head_age_band: "45-59", household_size_band: "7-9",  elderly_headed: false, female_headed: false, child_headed: false, members_under_5: "2",   members_over_60: "1",   any_disability: true  },
    { sub_county_code: "STC-070103", household_count: 89,   head_sex: "F", head_age_band: "60+",   household_size_band: "1-3",  elderly_headed: true,  female_headed: true,  child_headed: false, members_under_5: "0",   members_over_60: "1",   any_disability: false },
  ],
};

const _formatTs = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const m = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d.getDate().toString().padStart(2, "0")} ${m[d.getMonth()]} ${d.getFullYear()} · ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")} EAT`;
};

/* ============================================================
   Hook — load the dataset detail bundle
   ============================================================ */
const useDatasetDetail = (datasetId) => {
  const [state, setState] = useStateDXD({
    dataset: null,
    variables: DXD_VARIABLES_MOCK,
    coverage: DXD_COVERAGE_MOCK,
    sample: DXD_SAMPLE_MOCK,
    source: "loading",
  });

  useEffectDXD(() => {
    let cancelled = false;
    if (!datasetId) {
      // No id wired (preview-only). Render with the first mock.
      const fallback = (window.DXC_DATASETS_MOCK || [])[0] || null;
      setState((s) => ({ ...s, dataset: fallback, source: "fallback" }));
      return;
    }
    const fetchJson = (url) => fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

    Promise.all([
      fetchJson(`/api/v1/data-explorer/datasets/${datasetId}`),
      fetchJson(`/api/v1/data-explorer/datasets/${datasetId}/variables`),
      fetchJson(`/api/v1/data-explorer/coverage/${datasetId}`).catch(() => null),
      fetchJson(`/api/v1/data-explorer/synthetic-sample/${datasetId}`).catch(() => null),
    ])
      .then(([ds, vars, cov, sample]) => {
        if (cancelled) return;
        const variables = (vars && Array.isArray(vars.results))
          ? vars.results
          : Array.isArray(vars) ? vars : DXD_VARIABLES_MOCK;
        setState({
          dataset: ds || null,
          variables,
          coverage: cov || DXD_COVERAGE_MOCK,
          sample: sample || DXD_SAMPLE_MOCK,
          source: "live",
        });
      })
      .catch(() => {
        if (cancelled) return;
        const fallback = (window.DXC_DATASETS_MOCK || []).find((d) => d.id === datasetId)
          || (window.DXC_DATASETS_MOCK || [])[0] || null;
        setState((s) => ({ ...s, dataset: fallback, source: "fallback" }));
      });
    return () => { cancelled = true; };
  }, [datasetId]);

  return state;
};

/* ============================================================
   CoverageBars — sub-region completeness bars, mirrors the
   "Poverty rate by sub-region" pattern from screens-pmt-dashboard.
   ============================================================ */
const CoverageBars = ({ coverage }) => {
  const rows = (coverage && coverage.by_sub_region) || [];
  if (rows.length === 0) {
    return (
      <div className="t-cap muted" style={{ padding: 8 }}>
        {tt("data_explorer.dataset.coverage.empty")}
      </div>
    );
  }
  const max = Math.max(1, ...rows.map((r) => r.completeness_pct || 0));
  return (
    <div role="list" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r) => {
        const tone = r.completeness_pct >= 97 ? "var(--accent-data)"
          : r.completeness_pct >= 93 ? "var(--accent-update)"
            : r.completeness_pct >= 88 ? "var(--accent-quality)"
              : "var(--accent-danger)";
        return (
          <div
            key={r.sub_region_code}
            role="listitem"
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr 60px",
              gap: 12, alignItems: "center", padding: "4px 0",
            }}
          >
            <span className="t-bodysm" style={{ fontWeight: 500 }}>
              {r.sub_region_name}
            </span>
            <div
              role="progressbar"
              aria-valuenow={r.completeness_pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${r.sub_region_name} completeness ${r.completeness_pct.toFixed(1)}%`}
              style={{
                height: 8, background: "var(--neutral-100)",
                borderRadius: 4, overflow: "hidden",
              }}
            >
              <div style={{
                width: `${(r.completeness_pct / max) * 100}%`,
                height: "100%", background: tone,
              }}/>
            </div>
            <span className="t-num t-bodysm" style={{
              fontWeight: 600, textAlign: "right",
            }}>{r.completeness_pct.toFixed(1)}%</span>
          </div>
        );
      })}
    </div>
  );
};

/* ============================================================
   CompletenessCell — inline bar in the variable table
   ============================================================ */
const CompletenessCell = ({ pct }) => {
  if (pct == null) return <span className="t-cap muted">—</span>;
  const tone = pct >= 95 ? "var(--accent-data)"
    : pct >= 85 ? "var(--accent-update)"
      : pct >= 70 ? "var(--accent-quality)"
        : "var(--accent-danger)";
  return (
    <div className="row gap-2" style={{ alignItems: "center", minWidth: 120 }}>
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Completeness ${pct.toFixed(1)}%`}
        style={{
          flex: 1, height: 6,
          background: "var(--neutral-100)", borderRadius: 3, overflow: "hidden",
        }}
      >
        <div style={{ width: `${pct}%`, height: "100%", background: tone }}/>
      </div>
      <span className="t-num t-bodysm" style={{ minWidth: 44, textAlign: "right" }}>
        {pct.toFixed(1)}%
      </span>
    </div>
  );
};

/* ============================================================
   DatasetDetailScreen — primary export
   ============================================================ */
const DatasetDetailScreen = ({ datasetId, onBack, onOpenVariable, onOpenAggregate, onRequestRecords } = {}) => {
  // Pull privacy classes + badge from the shared catalogue hook so the
  // class chips render identically to the catalogue screen.
  const { privacyClasses, aggregatedOnlyBadge } = useDataExplorerCatalogue();
  const { dataset, variables, coverage, sample, source } = useDatasetDetail(datasetId);

  const [privacyFilter, setPrivacyFilter] = useStateDXD("");
  const [completenessFilter, setCompletenessFilter] = useStateDXD("");
  const [showSample, setShowSample] = useStateDXD(false);

  const privacyFacets = useMemoDXD(
    () => privacyClasses.map((c) => ({
      code: c.code, label: c.label,
      token_fg: c.token_fg, token_bg: c.token_bg,
    })),
    [privacyClasses],
  );

  const completenessFacets = [
    { code: "with",    label: tt("data_explorer.dataset.variables.completeness.with") },
    { code: "without", label: tt("data_explorer.dataset.variables.completeness.without") },
  ];

  const filteredVars = useMemoDXD(() => variables.filter((v) => {
    if (privacyFilter && v.privacy_class !== privacyFilter) return false;
    if (completenessFilter === "with" && !v.has_completeness_baseline) return false;
    if (completenessFilter === "without" && v.has_completeness_baseline) return false;
    return true;
  }), [variables, privacyFilter, completenessFilter]);

  const dsClass = privacyClasses.find((c) => c.code === dataset?.privacy_class);
  const canRequestRecords = dataset && dsClass && dsClass.allows_record_level_discovery
    && !dsClass.blocked;

  const eyebrowSuffix = source === "live" ? " · LIVE"
    : source === "fallback" ? " · MOCK PREVIEW"
      : " · loading…";

  if (!dataset) {
    return (
      <div className="page">
        <PageHeader
          eyebrow={tt("data_explorer.dataset.eyebrow") + eyebrowSuffix}
          title="Dataset"
          sub="Loading…"
        />
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow={tt("data_explorer.dataset.eyebrow") + eyebrowSuffix}
        title={dataset.title}
        sub={dataset.description}
        right={<>
          {onBack && (
            <button type="button" className="btn" onClick={onBack}>
              <Icon name="chevronLeft" size={14}/>
              {tt("data_explorer.dataset.back")}
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canRequestRecords}
            title={canRequestRecords ? undefined : tt("data_explorer.dataset.cta.tip_sensitive")}
            aria-disabled={!canRequestRecords}
            onClick={() => onRequestRecords?.(dataset)}
          >
            <Icon name="download" size={14}/>
            {tt("data_explorer.dataset.cta.request_records")}
          </button>
        </>}
      />

      {/* Header strip — chips + meta */}
      <div
        className="card"
        style={{ padding: "14px 18px", marginBottom: 16 }}
      >
        <div className="row gap-3" style={{ flexWrap: "wrap", alignItems: "center" }}>
          {window.DataExplorerPrivacyChip && (
            <window.DataExplorerPrivacyChip
              classCode={dataset.privacy_class}
              classes={privacyClasses}
              size=""
            />
          )}
          {dataset.aggregated_only && window.DataExplorerAggregatedOnlyBadge && (
            <window.DataExplorerAggregatedOnlyBadge badge={aggregatedOnlyBadge}/>
          )}
          <span className="t-cap">·</span>
          <span className="t-bodysm">
            <strong>{tt("data_explorer.dataset.meta.refresh_cadence")}:</strong>{" "}
            {dataset.refresh_cadence}
          </span>
          <span className="t-bodysm">
            <strong>{tt("data_explorer.dataset.meta.last_refreshed")}:</strong>{" "}
            {_formatTs(dataset.last_refreshed_at) || "—"}
          </span>
          <span className="t-bodysm">
            <strong>{tt("data_explorer.dataset.meta.coverage_floor")}:</strong>{" "}
            {dataset.coverage_floor || "—"}
          </span>
          <span className="t-bodysm">
            <strong>{tt("data_explorer.dataset.meta.variables_count")}:</strong>{" "}
            {dataset.variables_count}
          </span>
        </div>
      </div>

      <div
        className="grid"
        style={{ gridTemplateColumns: "1.7fr 1fr", gap: 16 }}
      >
        {/* Variables table */}
        <div className="card" style={{ padding: 0 }}>
          <div
            style={{
              padding: "14px 18px",
              borderBottom: "1px solid var(--neutral-200)",
            }}
          >
            <div className="row gap-3" style={{ alignItems: "baseline", flexWrap: "wrap" }}>
              <h3 className="t-h3" style={{ margin: 0 }}>
                {tt("data_explorer.dataset.variables.title")}
              </h3>
              <span className="t-cap">
                {filteredVars.length} of {variables.length}
              </span>
              <div style={{ flex: 1 }}/>
            </div>
            <p
              className="t-cap"
              style={{ margin: "4px 0 12px", color: "var(--neutral-600)" }}
            >
              {tt("data_explorer.dataset.variables.sub")}
            </p>
            <div className="row gap-4" style={{ flexWrap: "wrap" }}>
              {window.DataExplorerFacetChips && (
                <window.DataExplorerFacetChips
                  label={tt("data_explorer.dataset.variables.facet.privacy")}
                  options={privacyFacets}
                  value={privacyFilter}
                  onChange={setPrivacyFilter}
                  idPrefix="dxd-pc"
                />
              )}
              {window.DataExplorerFacetChips && (
                <window.DataExplorerFacetChips
                  label={tt("data_explorer.dataset.variables.facet.completeness")}
                  options={completenessFacets}
                  value={completenessFilter}
                  onChange={setCompletenessFilter}
                  idPrefix="dxd-cb"
                />
              )}
            </div>
          </div>

          {filteredVars.length === 0 ? (
            <div
              role="status"
              style={{ padding: 32, textAlign: "center", color: "var(--neutral-600)" }}
            >
              {tt("data_explorer.dataset.variables.empty")}
            </div>
          ) : (
            <table className="tbl" style={{ boxShadow: "none" }}>
              <thead>
                <tr>
                  <th scope="col">{tt("data_explorer.dataset.variables.col.code")}</th>
                  <th scope="col">{tt("data_explorer.dataset.variables.col.label")}</th>
                  <th scope="col">{tt("data_explorer.dataset.variables.col.type")}</th>
                  <th scope="col">{tt("data_explorer.dataset.variables.col.privacy")}</th>
                  <th scope="col">{tt("data_explorer.dataset.variables.col.completeness")}</th>
                  <th scope="col">{tt("data_explorer.dataset.variables.col.cadence")}</th>
                  <th scope="col" className="col-actions"/>
                </tr>
              </thead>
              <tbody>
                {filteredVars.map((v) => (
                  <tr key={v.code}>
                    <td>
                      <span className="t-mono t-bodysm">{v.code}</span>
                    </td>
                    <td>{v.label}</td>
                    <td>
                      <span className="t-cap">{v.type}</span>
                    </td>
                    <td>
                      {window.DataExplorerPrivacyChip && (
                        <window.DataExplorerPrivacyChip
                          classCode={v.privacy_class}
                          classes={privacyClasses}
                          size="sm"
                        />
                      )}
                    </td>
                    <td>
                      <CompletenessCell pct={v.completeness}/>
                    </td>
                    <td>
                      <span className="t-cap">{v.refresh_cadence}</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => onOpenVariable?.(dataset.id, v.code)}
                        aria-label={`View variable ${v.label}`}
                      >
                        {tt("data_explorer.dataset.variables.view")}
                        <Icon name="chevronRight" size={12}/>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="col gap-3" style={{ minWidth: 0 }}>
          {/* Coverage panel */}
          <div className="card" style={{ padding: 18 }}>
            <h3 className="t-h3" style={{ margin: "0 0 4px" }}>
              {tt("data_explorer.dataset.coverage.title")}
            </h3>
            <p className="t-cap" style={{ margin: "0 0 12px", color: "var(--neutral-600)" }}>
              {tt("data_explorer.dataset.coverage.sub")}
            </p>
            <CoverageBars coverage={coverage}/>
            {coverage?.generated_at && (
              <div className="t-cap mt-3" style={{ color: "var(--neutral-500)" }}>
                Generated {_formatTs(coverage.generated_at)}
              </div>
            )}
          </div>

          {/* Synthetic sample */}
          <div className="card" style={{ padding: 0 }}>
            <button
              type="button"
              onClick={() => setShowSample((s) => !s)}
              aria-expanded={showSample}
              aria-controls="dxd-sample-panel"
              style={{
                width: "100%", background: "transparent",
                border: 0, padding: "14px 18px", cursor: "pointer",
                display: "flex", alignItems: "center", gap: 10,
                textAlign: "left",
              }}
            >
              <Icon name={showSample ? "chevronDown" : "chevronRight"} size={14}/>
              <h3 className="t-h3" style={{ margin: 0, fontSize: 15 }}>
                {tt("data_explorer.dataset.sample.title")}
              </h3>
              <span
                className="chip chip-sm"
                style={{
                  color: "var(--accent-quality)",
                  background: "var(--accent-quality-bg)",
                  border: "1px solid var(--accent-quality)",
                }}
              >
                <Icon name="alert" size={11}/>
                {tt("data_explorer.dataset.sample.caption_warn")}
              </span>
            </button>
            {showSample && (
              <div
                id="dxd-sample-panel"
                style={{
                  padding: "0 18px 18px",
                  borderTop: "1px solid var(--neutral-200)",
                }}
              >
                {sample?.rows?.length ? (
                  <div style={{ overflowX: "auto", marginTop: 12 }}>
                    <table className="tbl" style={{ boxShadow: "none", fontSize: 12 }}>
                      <thead>
                        <tr>
                          {Object.keys(sample.rows[0]).map((k) => (
                            <th key={k} scope="col" className="t-mono">{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sample.rows.map((row, i) => (
                          <tr key={i}>
                            {Object.keys(sample.rows[0]).map((k) => (
                              <td key={k} className="t-mono">{String(row[k])}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="t-cap muted" style={{ marginTop: 12 }}>
                    {tt("data_explorer.dataset.sample.empty")}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Use in aggregate CTA */}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onOpenAggregate?.(dataset.id)}
            aria-label={tt("data_explorer.dataset.cta.use_in_aggregate")}
          >
            <Icon name="sliders" size={14}/>
            {tt("data_explorer.dataset.cta.use_in_aggregate")}
          </button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {
  DatasetDetailScreen,
  useDatasetDetail,
  DXD_VARIABLES_MOCK,
  DXD_COVERAGE_MOCK,
  DXD_SAMPLE_MOCK,
});
