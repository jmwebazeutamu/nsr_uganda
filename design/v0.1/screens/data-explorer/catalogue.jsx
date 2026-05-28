/* global React, Icon, Chip, PageHeader */
// NSR MIS — Data Explorer · Catalogue (US-DATA-EXP-001)
// =========================================================
// Discovery surface for the registry. Lists datasets the user is
// authorised to see, scoped by ABAC + their EXPLORER realm role.
//
// Architecture: ADR-0023 §D1 — DATA-EXP owns discovery + aggregate;
// API-DRS owns record-level; RPT owns operational dashboards. This
// screen is the front door.
//
// Wired from (Coder-owned backend):
//   GET /api/v1/data-explorer/datasets              — list of datasets
//   GET /api/v1/data-explorer/privacy-classes       — class catalogue
//
// Hardcoded labels and colours are forbidden. PrivacyClass chips,
// the "Aggregated-only" badge, and the refresh-cadence vocabulary
// all flow from the API so a fifth PrivacyClass can be added by the
// architect without a UI deploy (ADR-0023 §D5 + §D8).

const { useState: useStateDXC, useEffect: useEffectDXC, useMemo: useMemoDXC } = React;

/* ============================================================
   i18n keys — every user-facing string carries a stable key so the
   Django translation framework can swap them at render time.
   Mirrors the pattern used in screens-drs.jsx + screens-chatbot.
   ============================================================ */
const DXC_I18N = {
  "data_explorer.catalogue.eyebrow": "DATA REQUESTS · DATA EXPLORER",
  "data_explorer.catalogue.title": "Data Explorer",
  "data_explorer.catalogue.sub":
    "Discover the data the registry holds. Aggregate counts only; " +
    "record-level data flows through Data Requests.",
  "data_explorer.catalogue.search.placeholder":
    "Search datasets by name, description, or variable…",
  "data_explorer.catalogue.facet.privacy.label": "Sensitivity",
  "data_explorer.catalogue.facet.cadence.label": "Refresh cadence",
  "data_explorer.catalogue.facet.any": "Any",
  "data_explorer.catalogue.empty.title": "No datasets match this filter.",
  "data_explorer.catalogue.empty.body":
    "Clear the filters above, or contact your data steward if you " +
    "expected to see a dataset here.",
  "data_explorer.catalogue.card.variables": "variables",
  "data_explorer.catalogue.card.last_refreshed": "Data current as of",
  "data_explorer.catalogue.card.never_refreshed": "Not yet refreshed",
  "data_explorer.catalogue.card.cta": "View dataset",
  "data_explorer.catalogue.source.live": "LIVE",
  "data_explorer.catalogue.source.fallback": "MOCK PREVIEW",
  "data_explorer.catalogue.source.loading": "loading…",
  "data_explorer.catalogue.tip.aggregated_only":
    "Record-level access requires a Data Sharing Agreement. " +
    "Aggregate counts are available here.",
  "data_explorer.catalogue.tip.sensitive_blocked":
    "Aggregate queries on Sensitive data are blocked by ADR-0023 §D3. " +
    "Contact your DPO.",
};
const t = (key) => DXC_I18N[key] || key;

/* ============================================================
   Mock fallback — only shown when fetch() fails (file:// preview or
   the API isn't reachable). Loosely mirrors the YAML shape the Data
   Analyst owns; concrete fixtures live in /scripts/data_explorer/.
   ============================================================ */
const DXC_PRIVACY_CLASSES_MOCK = [
  { code: "Public",    label: "Public",
    token_fg: "var(--accent-system)",  token_bg: "var(--accent-system-bg)",
    k_floor: 0,  allows_record_level_discovery: true,  daily_cap: null },
  { code: "Internal",  label: "Internal",
    token_fg: "var(--accent-programme)", token_bg: "var(--accent-programme-bg)",
    k_floor: 5,  allows_record_level_discovery: true,  daily_cap: 100 },
  { code: "Personal",  label: "Personal",
    token_fg: "var(--accent-eligibility)", token_bg: "var(--accent-eligibility-bg)",
    k_floor: 10, allows_record_level_discovery: false, daily_cap: 25 },
  { code: "Sensitive", label: "Sensitive",
    token_fg: "var(--accent-danger)", token_bg: "var(--accent-danger-bg)",
    k_floor: null, allows_record_level_discovery: false, daily_cap: 0,
    blocked: true },
];

const DXC_AGGREGATED_ONLY_BADGE_MOCK = {
  code: "AGGREGATED_ONLY",
  label: "Aggregated-only",
  token_fg: "var(--accent-system)",
  token_bg: "var(--accent-system-bg)",
};

const DXC_DATASETS_MOCK = [
  {
    id: "01HXPZDXP01HOUSEHOLDDEMOG000",
    code: "mv_explorer_household_by_subcounty_demographics",
    title: "Household demographics by sub-county",
    description:
      "Counts of households by sub-county broken down by head-of-household " +
      "sex, age band, and household size. Sourced from Member + Household.",
    privacy_class: "Internal",
    refresh_cadence: "daily",
    variables_count: 18,
    last_refreshed_at: "2026-05-27T02:00:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_county",
  },
  {
    id: "01HXPZDXP02HOUSEHOLDPMT000",
    code: "mv_explorer_household_by_subcounty_pmt",
    title: "PMT band distribution by sub-county",
    description:
      "Household counts by PMT band (Extreme poverty → Not poor) across " +
      "sub-counties. Joins Household with the active PMTResult.",
    privacy_class: "Internal",
    refresh_cadence: "daily",
    variables_count: 9,
    last_refreshed_at: "2026-05-27T02:30:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_county",
  },
  {
    id: "01HXPZDXP03MEMBEREDU0000",
    code: "mv_explorer_member_by_subcounty_education",
    title: "Education attainment by sub-county",
    description:
      "Member-level education attainment aggregated to sub-county. Uses " +
      "the active education_level ChoiceList (v4).",
    privacy_class: "Internal",
    refresh_cadence: "weekly",
    variables_count: 12,
    last_refreshed_at: "2026-05-24T03:00:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_county",
  },
  {
    id: "01HXPZDXP04MEMBEREMP0000",
    code: "mv_explorer_member_by_subcounty_employment",
    title: "Employment + livelihood by sub-county",
    description:
      "ISCO-08 occupation + ISIC rev.4 industry codes aggregated by " +
      "sub-county. Excludes income amounts (Personal).",
    privacy_class: "Internal",
    refresh_cadence: "weekly",
    variables_count: 14,
    last_refreshed_at: "2026-05-24T03:30:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_county",
  },
  {
    id: "01HXPZDXP05SHOCKSREG0000",
    code: "mv_explorer_household_shocks_subregion",
    title: "Shocks reported by sub-region",
    description:
      "Self-reported shocks (drought, flood, illness, etc.) aggregated " +
      "to sub-region. Public-class — open browsing.",
    privacy_class: "Public",
    refresh_cadence: "weekly",
    variables_count: 8,
    last_refreshed_at: "2026-05-24T04:00:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_region",
  },
  {
    id: "01HXPZDXP06REFERRALS0000",
    code: "mv_explorer_referrals_subcounty",
    title: "Programme referrals by sub-county",
    description:
      "Counts of referrals issued, accepted, and rejected by destination " +
      "programme. Joins Referral × Household.",
    privacy_class: "Internal",
    refresh_cadence: "daily",
    variables_count: 11,
    last_refreshed_at: "2026-05-27T02:45:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_county",
  },
  {
    id: "01HXPZDXP07GRIEVANCE0000",
    code: "mv_explorer_grievances_subcounty",
    title: "Grievances by sub-county",
    description:
      "GRM case counts by L1/L2/L3 path, resolution outcome, and SLA band.",
    privacy_class: "Internal",
    refresh_cadence: "daily",
    variables_count: 10,
    last_refreshed_at: "2026-05-27T03:00:00+03:00",
    aggregated_only: false,
    coverage_floor: "sub_county",
  },
  {
    id: "01HXPZDXP08HEALTHCHR0000",
    code: "mv_explorer_health_chronic_subregion",
    title: "Chronic-illness prevalence by sub-region",
    description:
      "Self-reported chronic-illness prevalence aggregated to sub-region. " +
      "Personal class — no sub-county view; record-level via DSA only.",
    privacy_class: "Personal",
    refresh_cadence: "weekly",
    variables_count: 6,
    last_refreshed_at: "2026-05-24T04:30:00+03:00",
    aggregated_only: true,
    coverage_floor: "sub_region",
  },
];

/* ============================================================
   Data hook — fetches the privacy-classes catalogue and the dataset
   list on mount. Falls back to mocks on failure so the design preview
   keeps rendering under file://.
   ============================================================ */
const useDataExplorerCatalogue = () => {
  const [state, setState] = useStateDXC({
    datasets: DXC_DATASETS_MOCK,
    privacyClasses: DXC_PRIVACY_CLASSES_MOCK,
    aggregatedOnlyBadge: DXC_AGGREGATED_ONLY_BADGE_MOCK,
    cadences: [],
    source: "loading",
  });

  useEffectDXC(() => {
    let cancelled = false;

    const fetchJson = (url) => fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

    Promise.all([
      fetchJson("/api/v1/data-explorer/datasets"),
      fetchJson("/api/v1/data-explorer/privacy-classes"),
    ])
      .then(([ds, pc]) => {
        if (cancelled) return;
        const datasets = (ds && Array.isArray(ds.results))
          ? ds.results
          : Array.isArray(ds) ? ds : DXC_DATASETS_MOCK;
        const classes = (pc && Array.isArray(pc.results)) ? pc.results
          : Array.isArray(pc) ? pc
          : pc?.classes || DXC_PRIVACY_CLASSES_MOCK;
        const badge = pc?.aggregated_only_badge
          || pc?.badges?.aggregated_only
          || DXC_AGGREGATED_ONLY_BADGE_MOCK;
        const cadences = Array.from(new Set(datasets.map((d) => d.refresh_cadence)))
          .filter(Boolean).sort();
        setState({
          datasets, privacyClasses: classes,
          aggregatedOnlyBadge: badge, cadences,
          source: "live",
        });
      })
      .catch(() => {
        if (cancelled) return;
        const cadences = Array.from(new Set(
          DXC_DATASETS_MOCK.map((d) => d.refresh_cadence)
        )).filter(Boolean).sort();
        setState((s) => ({ ...s, cadences, source: "fallback" }));
      });
    return () => { cancelled = true; };
  }, []);

  return state;
};

/* ============================================================
   PrivacyClassChip — renders a class chip with its colour token +
   label from the API. No hardcoded class strings; new classes
   render correctly without code changes.
   ============================================================ */
const PrivacyClassChip = ({ classCode, classes, size = "sm" }) => {
  const cls = (classes || []).find((c) => c.code === classCode);
  if (!cls) {
    return (
      <span className={`chip chip-neutral ${size === "sm" ? "chip-sm" : ""}`}>
        {classCode || "—"}
      </span>
    );
  }
  return (
    <span
      className={`chip ${size === "sm" ? "chip-sm" : ""}`}
      style={{
        color: cls.token_fg, background: cls.token_bg,
        border: `1px solid ${cls.token_fg}`,
      }}
      aria-label={`Sensitivity: ${cls.label}`}
      title={cls.label}
    >
      {cls.blocked && <Icon name="lock" size={11}/>}
      {cls.label}
    </span>
  );
};

/* ============================================================
   AggregatedOnlyBadge — same vocabulary as PrivacyClassChip but
   pulled from /privacy-classes to keep the token + label centrally
   managed (ADR-0023 §D8).
   ============================================================ */
const AggregatedOnlyBadge = ({ badge }) => {
  if (!badge) return null;
  return (
    <span
      className="chip chip-sm"
      style={{
        color: badge.token_fg, background: badge.token_bg,
        border: `1px solid ${badge.token_fg}`,
      }}
      aria-label={`${badge.label} — record-level discovery is not available from the Explorer`}
      title={t("data_explorer.catalogue.tip.aggregated_only")}
    >
      <Icon name="lock" size={11}/>
      {badge.label}
    </span>
  );
};

/* ============================================================
   FacetChips — generic faceted-filter strip. Receives `options`
   from the API; never hardcodes the values.
   ============================================================ */
const FacetChips = ({ label, options, value, onChange, idPrefix }) => (
  <fieldset
    className="row gap-2"
    style={{
      border: 0, padding: 0, margin: 0, flexWrap: "wrap",
      alignItems: "center",
    }}
  >
    <legend
      className="t-cap"
      style={{ fontWeight: 600, padding: 0, marginRight: 4 }}
    >
      {label}
    </legend>
    <button
      type="button"
      className={`chip-btn ${!value ? "active" : ""}`}
      id={`${idPrefix}-any`}
      aria-pressed={!value}
      onClick={() => onChange("")}
      style={{
        padding: "4px 10px", borderRadius: 6, fontSize: 12,
        border: !value
          ? "1px solid var(--accent-system)"
          : "1px solid var(--neutral-300)",
        background: !value ? "var(--accent-system-bg)" : "white",
        cursor: "pointer",
      }}
    >
      {t("data_explorer.catalogue.facet.any")}
    </button>
    {options.map((opt) => {
      const active = value === opt.code;
      return (
        <button
          type="button"
          key={opt.code}
          id={`${idPrefix}-${opt.code}`}
          className={`chip-btn ${active ? "active" : ""}`}
          aria-pressed={active}
          onClick={() => onChange(active ? "" : opt.code)}
          style={{
            padding: "4px 10px", borderRadius: 6, fontSize: 12,
            border: active
              ? `1px solid ${opt.token_fg || "var(--accent-system)"}`
              : "1px solid var(--neutral-300)",
            background: active
              ? (opt.token_bg || "var(--accent-system-bg)") : "white",
            color: active
              ? (opt.token_fg || "var(--neutral-900)") : "var(--neutral-700)",
            cursor: "pointer",
          }}
        >
          {opt.label}
        </button>
      );
    })}
  </fieldset>
);

/* ============================================================
   DatasetCard — one dataset in the grid
   ============================================================ */
const _formatRefreshedAt = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const hh = d.getHours().toString().padStart(2, "0");
  const mm = d.getMinutes().toString().padStart(2, "0");
  return `${d.getDate().toString().padStart(2, "0")} ${months[d.getMonth()]} ${d.getFullYear()} · ${hh}:${mm} EAT`;
};

const DatasetCard = ({ dataset, classes, badge, cadences, onOpen }) => {
  const cadenceOpt = (cadences || []).find((c) => c.code === dataset.refresh_cadence);
  return (
    <article
      className="card"
      style={{
        padding: 18, display: "flex", flexDirection: "column",
        gap: 10, minHeight: 220,
      }}
      aria-labelledby={`ds-title-${dataset.id}`}
    >
      <div className="row gap-2" style={{ flexWrap: "wrap", alignItems: "center" }}>
        <PrivacyClassChip classCode={dataset.privacy_class} classes={classes}/>
        {dataset.aggregated_only && <AggregatedOnlyBadge badge={badge}/>}
        <span
          className="chip chip-sm chip-neutral"
          aria-label={`Refresh cadence: ${cadenceOpt?.label || dataset.refresh_cadence}`}
        >
          <Icon name="refresh" size={11}/>
          {cadenceOpt?.label || dataset.refresh_cadence}
        </span>
      </div>
      <h3
        id={`ds-title-${dataset.id}`}
        className="t-h3"
        style={{ margin: "4px 0 0", fontSize: 16 }}
      >
        {dataset.title}
      </h3>
      <p className="t-bodysm" style={{ margin: 0, color: "var(--neutral-700)" }}>
        {dataset.description}
      </p>
      <div style={{ flex: 1 }}/>
      <div
        className="row gap-3"
        style={{
          alignItems: "center", paddingTop: 10,
          borderTop: "1px solid var(--neutral-200)",
        }}
      >
        <span className="t-cap" style={{ fontWeight: 500 }}>
          {dataset.variables_count} {t("data_explorer.catalogue.card.variables")}
        </span>
        <span className="t-cap" style={{ color: "var(--neutral-500)" }}>·</span>
        <span className="t-cap" style={{ color: "var(--neutral-600)" }}>
          {dataset.last_refreshed_at
            ? `${t("data_explorer.catalogue.card.last_refreshed")} ${_formatRefreshedAt(dataset.last_refreshed_at)}`
            : t("data_explorer.catalogue.card.never_refreshed")}
        </span>
        <div style={{ flex: 1 }}/>
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={() => onOpen?.(dataset.id)}
          aria-label={`Open dataset ${dataset.title}`}
        >
          {t("data_explorer.catalogue.card.cta")} <Icon name="chevronRight" size={13}/>
        </button>
      </div>
    </article>
  );
};

/* ============================================================
   CatalogueScreen — primary export
   ============================================================ */
const CatalogueScreen = ({ onOpenDataset } = {}) => {
  const {
    datasets, privacyClasses, aggregatedOnlyBadge, cadences, source,
  } = useDataExplorerCatalogue();

  const [q, setQ] = useStateDXC("");
  const [privacyFilter, setPrivacyFilter] = useStateDXC("");
  const [cadenceFilter, setCadenceFilter] = useStateDXC("");

  // Cadence facet options — built from the dataset list so a new
  // refresh cadence introduced by the architect (e.g. "monthly")
  // shows up automatically.
  const cadenceFacets = useMemoDXC(
    () => cadences.map((c) => ({
      code: c, label: c.charAt(0).toUpperCase() + c.slice(1),
    })),
    [cadences],
  );

  // Privacy facets — flow from /privacy-classes, including blocked
  // ones. The grid renders nothing for Sensitive matches (none in the
  // fallback) but the facet stays toggleable so the user sees the gate.
  const privacyFacets = useMemoDXC(
    () => privacyClasses.map((c) => ({
      code: c.code, label: c.label,
      token_fg: c.token_fg, token_bg: c.token_bg,
    })),
    [privacyClasses],
  );

  const filtered = useMemoDXC(() => {
    const needle = q.trim().toLowerCase();
    return datasets.filter((d) => {
      if (privacyFilter && d.privacy_class !== privacyFilter) return false;
      if (cadenceFilter && d.refresh_cadence !== cadenceFilter) return false;
      if (!needle) return true;
      const hay = [d.title, d.description, d.code].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }, [datasets, q, privacyFilter, cadenceFilter]);

  const eyebrowSuffix = source === "live"
    ? ` · ${t("data_explorer.catalogue.source.live")}`
    : source === "fallback"
      ? ` · ${t("data_explorer.catalogue.source.fallback")}`
      : ` · ${t("data_explorer.catalogue.source.loading")}`;

  return (
    <div className="page">
      <PageHeader
        eyebrow={t("data_explorer.catalogue.eyebrow") + eyebrowSuffix}
        title={t("data_explorer.catalogue.title")}
        sub={t("data_explorer.catalogue.sub")}
      />

      {/* Filter bar */}
      <div
        className="card"
        style={{ padding: "14px 16px", marginBottom: 16 }}
      >
        <div className="row gap-3" style={{ flexWrap: "wrap", alignItems: "center" }}>
          <label
            className="search"
            style={{ maxWidth: 380, height: 34, background: "var(--neutral-0)" }}
          >
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("data_explorer.catalogue.search.placeholder")}
              aria-label={t("data_explorer.catalogue.search.placeholder")}
            />
          </label>
          <div style={{ flex: 1 }}/>
          <span className="t-cap">
            {filtered.length} of {datasets.length}
          </span>
        </div>
        <div className="row gap-4" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <FacetChips
            label={t("data_explorer.catalogue.facet.privacy.label")}
            options={privacyFacets}
            value={privacyFilter}
            onChange={setPrivacyFilter}
            idPrefix="dxc-pc"
          />
          <FacetChips
            label={t("data_explorer.catalogue.facet.cadence.label")}
            options={cadenceFacets}
            value={cadenceFilter}
            onChange={setCadenceFilter}
            idPrefix="dxc-rc"
          />
        </div>
      </div>

      {/* Dataset grid — 2 cols desktop, 1 col mobile via the CSS grid
          tokens already present in styles.css */}
      {filtered.length > 0 ? (
        <div
          className="grid"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))",
            gap: 16,
          }}
        >
          {filtered.map((d) => (
            <DatasetCard
              key={d.id}
              dataset={d}
              classes={privacyClasses}
              badge={aggregatedOnlyBadge}
              cadences={cadenceFacets}
              onOpen={onOpenDataset}
            />
          ))}
        </div>
      ) : (
        <div
          className="card"
          style={{
            padding: 48, textAlign: "center",
            color: "var(--neutral-600)",
          }}
          role="status"
        >
          <Icon name="inbox" size={32} color="var(--neutral-300)"/>
          <h3 className="t-h3" style={{ margin: "12px 0 4px" }}>
            {t("data_explorer.catalogue.empty.title")}
          </h3>
          <p className="t-bodysm" style={{ margin: 0 }}>
            {t("data_explorer.catalogue.empty.body")}
          </p>
        </div>
      )}
    </div>
  );
};

Object.assign(window, {
  CatalogueScreen,
  // Re-exported so the dataset-detail + variable-detail screens can
  // reuse the same chip + badge components and keep the vocabulary
  // single-sourced from /privacy-classes.
  DataExplorerPrivacyChip: PrivacyClassChip,
  DataExplorerAggregatedOnlyBadge: AggregatedOnlyBadge,
  DataExplorerFacetChips: FacetChips,
  useDataExplorerCatalogue,
  DXC_PRIVACY_CLASSES_MOCK,
  DXC_AGGREGATED_ONLY_BADGE_MOCK,
  DXC_DATASETS_MOCK,
  DXC_I18N,
});
