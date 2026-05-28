/* global React, Icon, Chip, PageHeader, DataExplorerPrivacyChip, useDataExplorerCatalogue */
// NSR MIS — Data Explorer · Variable detail (US-DATA-EXP-001)
// =========================================================
// Full data-dictionary entry for one variable: definition list,
// value-domain chip-cloud for coded fields, lineage stub, related
// variables, and the "Use in aggregate" CTA.
//
// Architecture: ADR-0023 §D5 (metadata loader reuses
// apps.update_workflow.field_catalog), §D8 (Aggregated-only badge).
//
// Wired from (Coder-owned backend):
//   GET /api/v1/data-explorer/datasets/{ds}/variables/{code}        — full entry
//   GET /api/v1/data-explorer/datasets/{ds}/variables/{code}/related — siblings
//   GET /api/v1/data-explorer/privacy-classes                       — class catalogue

const { useState: useStateDXV, useEffect: useEffectDXV } = React;

const DXV_I18N = {
  "data_explorer.variable.eyebrow": "DATA EXPLORER · VARIABLE",
  "data_explorer.variable.back": "Back to dataset",
  "data_explorer.variable.cta.use_in_aggregate": "Use in aggregate",
  "data_explorer.variable.definition.title": "Definition",
  "data_explorer.variable.def.source_module": "Source module",
  "data_explorer.variable.def.source_model": "Source model.field",
  "data_explorer.variable.def.source_questionnaire": "Source questionnaire path",
  "data_explorer.variable.def.unit": "Unit",
  "data_explorer.variable.def.baseline": "Expected completeness baseline",
  "data_explorer.variable.def.geo_floor": "Geographic minimum aggregation level",
  "data_explorer.variable.def.cadence": "Refresh cadence",
  "data_explorer.variable.def.notes": "Notes",
  "data_explorer.variable.value_domain.title": "Allowed values",
  "data_explorer.variable.value_domain.sub":
    "Coded values backed by an active ChoiceList. Click a chip to filter the catalogue by that value (Phase 2).",
  "data_explorer.variable.value_domain.empty":
    "This variable is not coded — values follow the data type.",
  "data_explorer.variable.lineage.title": "Lineage",
  "data_explorer.variable.lineage.sub_phase2":
    "Full lineage tracking is Phase 2 (ADR-0023 OPEN-2). For now: see source mapping below.",
  "data_explorer.variable.related.title": "Related variables",
  "data_explorer.variable.related.sub":
    "Other variables from the same source model. Sibling discovery — same parent table.",
  "data_explorer.variable.related.empty": "No related variables.",
};
const tv = (k) => DXV_I18N[k] || k;

/* ============================================================
   Mock fallbacks — only used when fetch() fails (file:// preview).
   The shape mirrors what the metadata loader will return; see
   ADR-0023 §D5 + apps/update_workflow/field_catalog.py.
   ============================================================ */
const DXV_VARIABLE_MOCK = {
  code: "head_age_band",
  label: "Head of household age band",
  definition:
    "Age of the head of household, bucketed into 5-year bands for k-anonymity. " +
    "Computed from Member.date_of_birth where Member.relationship_to_head = 'head'.",
  privacy_class: "Internal",
  type: "enum",
  source_module: "data_management",
  source_model: "Household.head_age_band",
  source_questionnaire_path: "section.identification.head_age",
  unit: "—",
  expected_completeness_baseline: 99.5,
  geographic_minimum_aggregation_level: "sub_county",
  refresh_cadence: "daily",
  notes:
    "Banded at ingest from Member.date_of_birth to avoid storing the raw age " +
    "anywhere in the Explorer matview path. Reconstructable from Member at " +
    "record level via a DSA only.",
  value_domain: [
    { code: "0-14",  label: "0–14 (child-headed)" },
    { code: "15-29", label: "15–29" },
    { code: "30-44", label: "30–44" },
    { code: "45-59", label: "45–59" },
    { code: "60+",   label: "60+ (elderly-headed)" },
  ],
};

const DXV_RELATED_MOCK = [
  { code: "head_sex",              label: "Head of household sex",            privacy_class: "Internal" },
  { code: "household_size_band",   label: "Household size (band)",            privacy_class: "Internal" },
  { code: "elderly_headed",        label: "Elderly-headed (60+)",             privacy_class: "Internal" },
  { code: "female_headed",         label: "Female-headed",                    privacy_class: "Internal" },
  { code: "child_headed",          label: "Child-headed (<18)",               privacy_class: "Internal" },
  { code: "members_under_5",       label: "Members under 5 (count band)",     privacy_class: "Internal" },
  { code: "members_over_60",       label: "Members 60+ (count band)",         privacy_class: "Internal" },
];

/* ============================================================
   Hook
   ============================================================ */
const useVariableDetail = (datasetId, variableCode) => {
  const [state, setState] = useStateDXV({
    variable: DXV_VARIABLE_MOCK,
    related: DXV_RELATED_MOCK,
    source: "loading",
  });

  useEffectDXV(() => {
    let cancelled = false;
    if (!datasetId || !variableCode) {
      setState((s) => ({ ...s, source: "fallback" }));
      return;
    }
    const fetchJson = (url) => fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

    Promise.all([
      fetchJson(`/api/v1/data-explorer/datasets/${datasetId}/variables/${variableCode}`),
      fetchJson(`/api/v1/data-explorer/datasets/${datasetId}/variables/${variableCode}/related`)
        .catch(() => null),
    ])
      .then(([v, related]) => {
        if (cancelled) return;
        const relatedRows = (related && Array.isArray(related.results))
          ? related.results
          : Array.isArray(related) ? related : DXV_RELATED_MOCK;
        setState({
          variable: v || DXV_VARIABLE_MOCK,
          related: relatedRows,
          source: "live",
        });
      })
      .catch(() => {
        if (cancelled) return;
        setState((s) => ({ ...s, source: "fallback" }));
      });
    return () => { cancelled = true; };
  }, [datasetId, variableCode]);

  return state;
};

/* ============================================================
   DefRow — one row of the definition list
   ============================================================ */
const DefRow = ({ label, value, mono }) => (
  <>
    <dt className="t-cap" style={{ fontWeight: 600, color: "var(--neutral-700)" }}>
      {label}
    </dt>
    <dd
      className={mono ? "t-mono t-bodysm" : "t-bodysm"}
      style={{ margin: 0, color: "var(--neutral-900)" }}
    >
      {value || "—"}
    </dd>
  </>
);

/* ============================================================
   VariableDetailScreen — primary export
   ============================================================ */
const VariableDetailScreen = ({
  datasetId,
  variableCode,
  onBack,
  onOpenVariable,
  onOpenAggregate,
} = {}) => {
  const { privacyClasses } = useDataExplorerCatalogue();
  const { variable, related, source } = useVariableDetail(datasetId, variableCode);

  const eyebrowSuffix = source === "live" ? " · LIVE"
    : source === "fallback" ? " · MOCK PREVIEW"
      : " · loading…";

  if (!variable) {
    return (
      <div className="page">
        <PageHeader
          eyebrow={tv("data_explorer.variable.eyebrow") + eyebrowSuffix}
          title="Variable"
          sub="Loading…"
        />
      </div>
    );
  }

  const valueDomain = variable.value_domain || [];

  return (
    <div className="page">
      <PageHeader
        eyebrow={tv("data_explorer.variable.eyebrow") + eyebrowSuffix}
        title={<>
          {variable.label}{" "}
          <span
            className="t-mono"
            style={{
              fontSize: 14, color: "var(--neutral-600)",
              fontWeight: 400, marginLeft: 8,
            }}
          >
            {variable.code}
          </span>
        </>}
        sub={variable.definition}
        right={<>
          {onBack && (
            <button type="button" className="btn" onClick={onBack}>
              <Icon name="chevronLeft" size={14}/>
              {tv("data_explorer.variable.back")}
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onOpenAggregate?.(datasetId, variable.code)}
            aria-label={tv("data_explorer.variable.cta.use_in_aggregate")}
          >
            <Icon name="sliders" size={14}/>
            {tv("data_explorer.variable.cta.use_in_aggregate")}
          </button>
        </>}
      />

      {/* Privacy chip + meta strip */}
      <div className="row gap-3" style={{ flexWrap: "wrap", marginBottom: 16 }}>
        {window.DataExplorerPrivacyChip && (
          <window.DataExplorerPrivacyChip
            classCode={variable.privacy_class}
            classes={privacyClasses}
            size=""
          />
        )}
        <span className="chip chip-sm chip-neutral">
          <Icon name="database" size={11}/> type {variable.type}
        </span>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1.5fr 1fr", gap: 16 }}>
        {/* Definition list */}
        <div className="card" style={{ padding: 20 }}>
          <h3 className="t-h3" style={{ margin: "0 0 14px" }}>
            {tv("data_explorer.variable.definition.title")}
          </h3>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "200px 1fr",
              rowGap: 10, columnGap: 16, margin: 0,
            }}
          >
            <DefRow
              label={tv("data_explorer.variable.def.source_module")}
              value={variable.source_module}
              mono
            />
            <DefRow
              label={tv("data_explorer.variable.def.source_model")}
              value={variable.source_model}
              mono
            />
            <DefRow
              label={tv("data_explorer.variable.def.source_questionnaire")}
              value={variable.source_questionnaire_path}
              mono
            />
            <DefRow
              label={tv("data_explorer.variable.def.unit")}
              value={variable.unit}
            />
            <DefRow
              label={tv("data_explorer.variable.def.baseline")}
              value={variable.expected_completeness_baseline != null
                ? `${Number(variable.expected_completeness_baseline).toFixed(1)}%`
                : "—"}
            />
            <DefRow
              label={tv("data_explorer.variable.def.geo_floor")}
              value={variable.geographic_minimum_aggregation_level}
            />
            <DefRow
              label={tv("data_explorer.variable.def.cadence")}
              value={variable.refresh_cadence}
            />
            <DefRow
              label={tv("data_explorer.variable.def.notes")}
              value={variable.notes}
            />
          </dl>

          {/* Lineage stub */}
          <div
            style={{
              marginTop: 18, paddingTop: 14,
              borderTop: "1px solid var(--neutral-200)",
            }}
          >
            <h4
              className="t-h3"
              style={{ margin: "0 0 4px", fontSize: 14 }}
            >
              {tv("data_explorer.variable.lineage.title")}
            </h4>
            <p
              className="t-cap"
              style={{ margin: 0, color: "var(--neutral-600)" }}
            >
              {tv("data_explorer.variable.lineage.sub_phase2")}
            </p>
            <p className="t-bodysm" style={{ marginTop: 8 }}>
              Sourced from{" "}
              <span className="t-mono" style={{ color: "var(--accent-system)" }}>
                {variable.source_module}.{variable.source_model}
              </span>
              {variable.source_questionnaire_path && (
                <>
                  {" · questionnaire "}
                  <span className="t-mono" style={{ color: "var(--accent-system)" }}>
                    {variable.source_questionnaire_path}
                  </span>
                </>
              )}
            </p>
          </div>
        </div>

        {/* Side cards */}
        <div className="col gap-3" style={{ minWidth: 0 }}>
          {/* Value domain card */}
          <div className="card" style={{ padding: 18 }}>
            <h3 className="t-h3" style={{ margin: "0 0 4px", fontSize: 15 }}>
              {tv("data_explorer.variable.value_domain.title")}
            </h3>
            {valueDomain.length > 0 ? (
              <>
                <p className="t-cap" style={{ margin: "0 0 12px", color: "var(--neutral-600)" }}>
                  {tv("data_explorer.variable.value_domain.sub")}
                </p>
                <div className="row gap-2" style={{ flexWrap: "wrap" }}>
                  {valueDomain.map((opt) => (
                    <span
                      key={opt.code}
                      className="chip chip-sm"
                      style={{
                        color: "var(--accent-reference)",
                        background: "var(--accent-reference-bg)",
                        border: "1px solid var(--accent-reference)",
                      }}
                      title={opt.code}
                    >
                      <span className="t-mono">{opt.code}</span>
                      {opt.label && opt.label !== opt.code ? ` · ${opt.label}` : ""}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="t-cap" style={{ margin: "8px 0 0", color: "var(--neutral-600)" }}>
                {tv("data_explorer.variable.value_domain.empty")}
              </p>
            )}
          </div>

          {/* Related variables */}
          <div className="card" style={{ padding: 18 }}>
            <h3 className="t-h3" style={{ margin: "0 0 4px", fontSize: 15 }}>
              {tv("data_explorer.variable.related.title")}
            </h3>
            <p className="t-cap" style={{ margin: "0 0 12px", color: "var(--neutral-600)" }}>
              {tv("data_explorer.variable.related.sub")}
            </p>
            {related.length === 0 ? (
              <p className="t-cap" style={{ margin: 0, color: "var(--neutral-600)" }}>
                {tv("data_explorer.variable.related.empty")}
              </p>
            ) : (
              <ul
                style={{
                  margin: 0, padding: 0, listStyle: "none",
                  display: "flex", flexDirection: "column", gap: 6,
                }}
              >
                {related.slice(0, 10).map((r) => (
                  <li key={r.code}>
                    <button
                      type="button"
                      onClick={() => onOpenVariable?.(datasetId, r.code)}
                      style={{
                        background: "none", border: 0, padding: "6px 0",
                        textAlign: "left", cursor: "pointer", width: "100%",
                        display: "flex", alignItems: "center", gap: 8,
                        borderBottom: "1px solid var(--neutral-100)",
                      }}
                      aria-label={`Open related variable ${r.label}`}
                    >
                      <span
                        className="t-mono"
                        style={{ fontSize: 12, color: "var(--neutral-700)" }}
                      >
                        {r.code}
                      </span>
                      <span className="t-bodysm" style={{ flex: 1 }}>{r.label}</span>
                      {window.DataExplorerPrivacyChip && (
                        <window.DataExplorerPrivacyChip
                          classCode={r.privacy_class}
                          classes={privacyClasses}
                          size="sm"
                        />
                      )}
                      <Icon name="chevronRight" size={12}/>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {
  VariableDetailScreen,
  useVariableDetail,
  DXV_VARIABLE_MOCK,
  DXV_RELATED_MOCK,
});
