/* global React, Icon, Chip, KPI, Field, PageHeader */
// NSR MIS - Reporting dashboards

const { useEffect: useEffectReporting, useMemo: useMemoReporting, useState: useStateReporting } = React;

const REPORT_GROUPS = [
  {
    group: "Registry Coverage",
    reports: [
      {
        id: "households-by-sub-region",
        title: "Households",
        endpoint: "/api/v1/rpt/dashboards/households-by-sub-region/",
        chart: "bar",
        tone: "data",
      },
      {
        id: "households-by-pmt-band",
        title: "Households by PMT band",
        endpoint: "/api/v1/rpt/dashboards/households-by-pmt-band/",
        chart: "bar",
        tone: "eligibility",
      },
      {
        id: "households-by-urban-rural",
        title: "Households by urban/rural",
        endpoint: "/api/v1/rpt/dashboards/households-by-urban-rural/",
        tone: "data",
      },
      {
        id: "households-by-intake-source",
        title: "Households by intake source",
        endpoint: "/api/v1/rpt/dashboards/households-by-intake-source/",
        tone: "programme",
      },
      {
        id: "weekly-household-registrations",
        title: "Weekly household registrations",
        endpoint: "/api/v1/rpt/dashboards/weekly-household-registrations/",
        chart: "trend",
        tone: "update",
      },
      {
        id: "submissions-per-day",
        title: "Submissions per day",
        endpoint: "/api/v1/rpt/dashboards/submissions-per-day/",
        chart: "trend",
        tone: "update",
      },
    ],
  },
  {
    group: "Pipeline and Quality",
    reports: [
      {
        id: "dih-stages-by-state",
        title: "DIH stages by state",
        endpoint: "/api/v1/rpt/dashboards/dih-stages-by-state/",
        chart: "funnel",
        tone: "update",
      },
      {
        id: "connector-runs-by-status",
        title: "Connector runs by status",
        endpoint: "/api/v1/rpt/dashboards/connector-runs-by-status/",
        tone: "system",
      },
      {
        id: "promotion-latency-by-connector",
        title: "Promotion latency by connector",
        endpoint: "/api/v1/rpt/dashboards/promotion-latency-by-connector/",
        tone: "quality",
      },
      {
        id: "dqa-violations",
        title: "DQA violations",
        endpoint: "/api/v1/rpt/dashboards/dqa-violations/",
        recordEndpoint: "/api/v1/rpt/dashboards/dqa-violations/records/",
        tone: "danger",
      },
      {
        id: "pending-dedup-pairs-by-tier",
        title: "Pending duplicate pairs by tier",
        endpoint: "/api/v1/rpt/dashboards/pending-dedup-pairs-by-tier/",
        recordEndpoint: "/api/v1/rpt/dashboards/dedup-pairs/records/",
        recordParams: { status: "pending" },
        tone: "identity",
      },
      {
        id: "dedup-pairs-by-status",
        title: "Duplicate pairs by status",
        endpoint: "/api/v1/rpt/dashboards/dedup-pairs-by-status/",
        recordEndpoint: "/api/v1/rpt/dashboards/dedup-pairs/records/",
        chart: "bar",
        tone: "identity",
      },
      {
        id: "idv-attempts-by-status",
        title: "NIRA attempts by status",
        endpoint: "/api/v1/rpt/dashboards/idv-attempts-by-status/",
        recordEndpoint: "/api/v1/rpt/dashboards/idv-attempts/records/",
        tone: "identity",
      },
    ],
  },
  {
    group: "Case Management",
    reports: [
      {
        id: "change-requests-by-status",
        title: "Change requests by status",
        endpoint: "/api/v1/rpt/dashboards/change-requests-by-status/",
        recordEndpoint: "/api/v1/rpt/dashboards/change-requests/records/",
        tone: "update",
      },
      {
        id: "open-grievances-by-tier",
        title: "Open grievances by tier",
        endpoint: "/api/v1/rpt/dashboards/open-grievances-by-tier/",
        recordEndpoint: "/api/v1/rpt/dashboards/grievances/records/",
        recordParams: { status: "active" },
        tone: "grm",
      },
      {
        id: "overdue-grievances-by-tier",
        title: "Overdue grievances by tier",
        endpoint: "/api/v1/rpt/dashboards/overdue-grievances-by-tier/",
        recordEndpoint: "/api/v1/rpt/dashboards/grievances/records/",
        recordParams: { overdue: "true" },
        tone: "danger",
      },
      {
        id: "grievances-by-category",
        title: "Grievances by category",
        endpoint: "/api/v1/rpt/dashboards/grievances-by-category/",
        recordEndpoint: "/api/v1/rpt/dashboards/grievances/records/",
        recordParams: { status: "active" },
        tone: "grm",
      },
      {
        id: "referrals-by-programme-status",
        title: "Referrals by programme/status",
        endpoint: "/api/v1/rpt/dashboards/referrals-by-programme-status/",
        tone: "programme",
      },
    ],
  },
  {
    group: "Governance",
    reports: [
      {
        id: "data-requests-by-status",
        title: "Data requests by status",
        endpoint: "/api/v1/rpt/dashboards/data-requests-by-status/",
        recordEndpoint: "/api/v1/rpt/dashboards/data-requests/records/",
        chart: "bar",
        tone: "system",
      },
      {
        id: "audit-events-by-action",
        title: "Audit events by action",
        endpoint: "/api/v1/rpt/dashboards/audit-events-by-action/",
        tone: "system",
      },
    ],
  },
];

const ALL_REPORTS = REPORT_GROUPS.flatMap((g) => g.reports.map((r) => ({ ...r, group: g.group })));

const withQuery = (endpoint, params = {}) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const suffix = query.toString();
  if (!suffix) return endpoint;
  return `${endpoint}${endpoint.includes("?") ? "&" : "?"}${suffix}`;
};

const csvUrl = (endpoint, params = {}) => withQuery(endpoint, { ...params, export: "csv" });

const formatReportKey = (value) => String(value || "(unset)").replaceAll("_", " ");
const formatBucket = (row, index) => formatReportKey(row.label || row.key || row.rule_id || row.metric || `row-${index + 1}`);

const dqaParams = (filters, ruleId = "") => ({
  window: filters.window === "7d" ? "" : filters.window,
  severity: filters.severity === "all" ? "" : filters.severity,
  sub_region_code: filters.subRegionCode,
  rule_id: ruleId || filters.ruleId,
});

const householdParams = (filters) => ({
  group_by: filters.groupBy === "region" ? "region" : filters.groupBy,
  region: filters.region.startsWith("__parent:") ? "" : filters.region,
  sub_region: filters.subRegion,
  district: filters.district,
});

const dqaViolationRecordsUrl = (filters, ruleId = "", exportCsv = false) => (
  withQuery(
    "/api/v1/rpt/dashboards/dqa-violations/records/",
    { ...dqaParams(filters, ruleId), export: exportCsv ? "csv" : "" },
  )
);

const selectedRecordCsvUrl = (report, filters) => {
  if (!report.recordEndpoint) return "";
  if (report.id === "dqa-violations") {
    return dqaViolationRecordsUrl(filters, "", true);
  }
  return csvUrl(report.recordEndpoint, report.recordParams || {});
};

const fetchHouseholdBuckets = (params = {}) => (
  fetch(withQuery("/api/v1/rpt/dashboards/households-by-sub-region/", params), { credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const payload = await response.json();
      return Array.isArray(payload.results) ? payload.results : Array.isArray(payload) ? payload : [];
    })
);

const rowCount = (row) => Number(row.count ?? row.fail_count ?? 0);

const chartColor = (tone) => ({
  data: "var(--accent-data)",
  eligibility: "var(--accent-eligibility)",
  update: "var(--accent-update)",
  quality: "var(--accent-quality)",
  danger: "var(--accent-danger)",
  identity: "var(--accent-identity)",
  grm: "var(--accent-grm)",
  programme: "var(--accent-programme)",
  system: "var(--accent-system)",
}[tone] || "var(--primary-700)");

const roleEmptyCopy = (role, report) => {
  if (role === "partner-analyst") return "No rows are visible under your partner scope.";
  if (role === "dpo") return "No visible rows for the current governance scope.";
  if (["parish", "cdo"].includes(role)) return "No rows are visible in your assigned sub-region scope.";
  return `No ${report.title.toLowerCase()} rows are available for the current filters.`;
};

const roleAuthCopy = (role) => (
  role === "partner-analyst"
    ? "Sign in with your partner account to view scoped reports."
    : "Sign in with your NSR operator account to view live reports."
);

function HorizontalBarChart({ rows, tone }) {
  const max = Math.max(...rows.map(rowCount), 1);
  return (
    <div className="col gap-3" style={{minHeight: 220}}>
      {rows.map((row, index) => {
        const value = rowCount(row);
        const key = row.key || row.rule_id || `row-${index + 1}`;
        return (
          <div key={`${key}-${index}`} className="grid" style={{gridTemplateColumns: "180px 1fr 64px", alignItems: "center", gap: 12}}>
            <div className="t-bodysm" style={{fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}>
              {formatBucket(row, index)}
            </div>
            <div style={{height: 18, background: "var(--neutral-100)", borderRadius: 4, overflow: "hidden"}}>
              <div style={{width: `${Math.max((value / max) * 100, value ? 3 : 0)}%`, height: "100%", background: chartColor(tone)}}/>
            </div>
            <div className="t-mono" style={{textAlign: "right"}}>{value.toLocaleString()}</div>
          </div>
        );
      })}
    </div>
  );
}

function TrendChart({ rows, tone }) {
  const values = rows.map(rowCount);
  const max = Math.max(...values, 1);
  const width = 720;
  const height = 220;
  const pad = 18;
  const span = Math.max(rows.length - 1, 1);
  const points = rows.map((row, index) => {
    const x = pad + index * (width - pad * 2) / span;
    const y = height - pad - (rowCount(row) / max) * (height - pad * 2);
    return { x, y, value: rowCount(row), key: row.key };
  });
  const path = points.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  return (
    <div style={{minHeight: 250}}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{width: "100%", height: 220, display: "block"}}>
        <path d={`M${pad} ${height - pad}H${width - pad}`} stroke="var(--neutral-300)" strokeWidth="1"/>
        <path d={path} fill="none" stroke={chartColor(tone)} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
        {points.map((p, index) => (
          <g key={`${p.key}-${index}`}>
            <circle cx={p.x} cy={p.y} r="4" fill="var(--neutral-0)" stroke={chartColor(tone)} strokeWidth="2"/>
            {index === points.length - 1 && (
              <text x={p.x - 6} y={p.y - 10} textAnchor="end" fontSize="12" fill="var(--neutral-700)">{p.value}</text>
            )}
          </g>
        ))}
      </svg>
      <div className="row" style={{justifyContent: "space-between"}}>
        <span className="t-cap">{rows[0]?.key || "Start"}</span>
        <span className="t-cap">{rows[rows.length - 1]?.key || "End"}</span>
      </div>
    </div>
  );
}

function FunnelChart({ rows, tone }) {
  const max = Math.max(...rows.map(rowCount), 1);
  return (
    <div className="col gap-3" style={{minHeight: 220}}>
      {rows.map((row, index) => {
        const value = rowCount(row);
        const width = Math.max((value / max) * 100, value ? 8 : 0);
        return (
          <div key={`${row.key}-${index}`} className="center">
            <div
              style={{
                width: `${width}%`,
                minWidth: value ? 96 : 0,
                height: 38,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "0 12px",
                background: chartColor(tone),
                color: "var(--neutral-0)",
                borderRadius: 4,
              }}
            >
              <span className="t-bodysm" style={{fontWeight: 700}}>{formatReportKey(row.key)}</span>
              <span className="t-mono">{value.toLocaleString()}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ReportChart({ report, rows }) {
  if (!rows.length || !report.chart) return null;
  return (
    <div className="card">
      <div className="card-header">
        <h3 className="t-h2" style={{margin: 0}}>Chart</h3>
        <Chip tone={report.tone}>{report.chart === "trend" ? "Trend" : report.chart === "funnel" ? "Funnel" : "Distribution"}</Chip>
      </div>
      <div className="card-body">
        {report.chart === "trend" && <TrendChart rows={rows} tone={report.tone}/>}
        {report.chart === "funnel" && <FunnelChart rows={rows} tone={report.tone}/>}
        {report.chart === "bar" && <HorizontalBarChart rows={rows} tone={report.tone}/>}
      </div>
    </div>
  );
}

function ReportsScreen({ role = "nsr-unit" }) {
  const [selectedId, setSelectedId] = useStateReporting("households-by-sub-region");
  const [rows, setRows] = useStateReporting([]);
  const [status, setStatus] = useStateReporting("idle");
  const [error, setError] = useStateReporting("");
  const [dqaRuleId, setDqaRuleId] = useStateReporting("");
  const [dqaRecords, setDqaRecords] = useStateReporting([]);
  const [dqaRecordsStatus, setDqaRecordsStatus] = useStateReporting("idle");
  const [dqaRecordsError, setDqaRecordsError] = useStateReporting("");
  const [dqaFilters, setDqaFilters] = useStateReporting({
    window: "7d",
    severity: "all",
    subRegionCode: "",
    ruleId: "",
  });
  const [householdFilters, setHouseholdFilters] = useStateReporting({
    groupBy: "region",
    region: "",
    subRegion: "",
    district: "",
  });
  const [geoOptions, setGeoOptions] = useStateReporting({
    regions: [],
    subRegions: [],
    districts: [],
  });

  const selected = useMemoReporting(
    () => ALL_REPORTS.find((report) => report.id === selectedId) || ALL_REPORTS[0],
    [selectedId],
  );
  const isDqaReport = selected.id === "dqa-violations";
  const isHouseholdReport = selected.id === "households-by-sub-region";
  const recordCsv = selectedRecordCsvUrl(selected, dqaFilters);
  const selectedEndpoint = isDqaReport
    ? withQuery(selected.endpoint, dqaParams(dqaFilters))
    : isHouseholdReport
      ? withQuery(selected.endpoint, householdParams(householdFilters))
    : selected.endpoint;

  useEffectReporting(() => {
    let cancelled = false;
    setStatus("loading");
    setError("");
    setDqaRuleId("");
    setDqaRecords([]);
    setDqaRecordsStatus("idle");
    setDqaRecordsError("");
    fetch(selectedEndpoint, { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      })
      .then((payload) => {
        if (cancelled) return;
        setRows(Array.isArray(payload) ? payload : []);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setRows([]);
        setError(err.message || "Report request failed");
        setStatus("error");
      });
    return () => { cancelled = true; };
  }, [selectedEndpoint]);

  useEffectReporting(() => {
    let cancelled = false;
    fetchHouseholdBuckets({ group_by: "region" })
      .then((regionRows) => {
        if (!cancelled) setGeoOptions((options) => ({ ...options, regions: regionRows }));
      })
      .catch(() => {
        if (!cancelled) setGeoOptions((options) => ({ ...options, regions: [] }));
      });
    return () => { cancelled = true; };
  }, []);

  useEffectReporting(() => {
    let cancelled = false;
    if (!householdFilters.region) {
      setGeoOptions((options) => ({ ...options, subRegions: [], districts: [] }));
      return () => { cancelled = true; };
    }
    fetchHouseholdBuckets({ group_by: "sub_region", region: householdFilters.region })
      .then((subRegionRows) => {
        if (!cancelled) setGeoOptions((options) => ({ ...options, subRegions: subRegionRows, districts: [] }));
      })
      .catch(() => {
        if (!cancelled) setGeoOptions((options) => ({ ...options, subRegions: [], districts: [] }));
      });
    return () => { cancelled = true; };
  }, [householdFilters.region]);

  useEffectReporting(() => {
    let cancelled = false;
    if (!householdFilters.subRegion) {
      setGeoOptions((options) => ({ ...options, districts: [] }));
      return () => { cancelled = true; };
    }
    fetchHouseholdBuckets({
      group_by: "district",
      region: householdFilters.region,
      sub_region: householdFilters.subRegion,
    })
      .then((districtRows) => {
        if (!cancelled) setGeoOptions((options) => ({ ...options, districts: districtRows }));
      })
      .catch(() => {
        if (!cancelled) setGeoOptions((options) => ({ ...options, districts: [] }));
      });
    return () => { cancelled = true; };
  }, [householdFilters.region, householdFilters.subRegion]);

  const total = rows.reduce((sum, row) => sum + Number(row.count || row.fail_count || 0), 0);
  const reportNeedsLogin = error.includes("403");
  const recordsNeedLogin = dqaRecordsError.includes("403");
  const regions = geoOptions.regions;
  const subRegions = geoOptions.subRegions;
  const districts = geoOptions.districts;

  const loadDqaRecords = (ruleId) => {
    setDqaRuleId(ruleId);
    setDqaRecords([]);
    setDqaRecordsStatus("loading");
    setDqaRecordsError("");
    fetch(dqaViolationRecordsUrl(dqaFilters, ruleId), { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json();
      })
      .then((payload) => {
        setDqaRecords(Array.isArray(payload) ? payload : []);
        setDqaRecordsStatus("ready");
      })
      .catch((err) => {
        setDqaRecords([]);
        setDqaRecordsError(err.message || "Record request failed");
        setDqaRecordsStatus("error");
      });
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="REPORTING"
        title="Reports"
        sub="Live aggregate dashboards from the reporting API."
        right={<>
          <a className="btn" href={selectedEndpoint} target="_blank" rel="noreferrer">
            <Icon name="eye" size={15}/> JSON
          </a>
          <a
            className="btn"
            href={csvUrl(
              selected.endpoint,
              isDqaReport ? dqaParams(dqaFilters) : isHouseholdReport ? householdParams(householdFilters) : {},
            )}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="download" size={15}/> CSV
          </a>
          {recordCsv && (
            <a className="btn" href={recordCsv} target="_blank" rel="noreferrer">
              <Icon name="file" size={15}/> Records
            </a>
          )}
        </>}
      />

      <div className="grid" style={{gridTemplateColumns: "320px 1fr", alignItems: "start"}}>
        <aside className="card card-pad">
          <div className="col gap-4">
            {REPORT_GROUPS.map((group) => (
              <div key={group.group}>
                <div className="t-cap" style={{marginBottom: 8}}>{group.group}</div>
                <div className="col gap-2">
                  {group.reports.map((report) => (
                    <button
                      key={report.id}
                      className={`btn ${selected.id === report.id ? "btn-primary" : ""}`}
                      style={{justifyContent: "flex-start", width: "100%", height: 34}}
                      onClick={() => setSelectedId(report.id)}
                    >
                      <Icon name="barchart" size={15}/>
                      <span style={{overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}>
                        {report.title}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </aside>

        <section className="col gap-4">
          {isHouseholdReport && (
            <div className="card card-pad">
              <div className="grid" style={{gridTemplateColumns: "repeat(4, minmax(0, 1fr)) auto", alignItems: "end"}}>
                <Field label="Region">
                  <select
                    data-testid="household-region-filter"
                    className="field-select"
                    value={householdFilters.region}
                    onChange={(e) => setHouseholdFilters((f) => ({ ...f, region: e.target.value, subRegion: "", district: "" }))}
                  >
                    <option value="">All regions</option>
                    {regions.map((row) => (
                      <option key={row.key} value={row.key}>{row.label || row.key}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Sub-Region">
                  <select
                    data-testid="household-sub-region-filter"
                    className="field-select"
                    value={householdFilters.subRegion}
                    disabled={!householdFilters.region}
                    onChange={(e) => setHouseholdFilters((f) => ({ ...f, subRegion: e.target.value, district: "" }))}
                  >
                    <option value="">All sub-regions</option>
                    {subRegions.map((row) => (
                      <option key={row.key} value={row.key}>{row.label || row.key}</option>
                    ))}
                  </select>
                </Field>
                <Field label="District">
                  <select
                    data-testid="household-district-filter"
                    className="field-select"
                    value={householdFilters.district}
                    disabled={!householdFilters.subRegion}
                    onChange={(e) => setHouseholdFilters((f) => ({ ...f, district: e.target.value }))}
                  >
                    <option value="">All districts</option>
                    {districts.map((row) => (
                      <option key={row.key} value={row.key}>{row.label || row.key}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Group households by">
                  <select
                    data-testid="household-group-by-filter"
                    className="field-select"
                    value={householdFilters.groupBy}
                    onChange={(e) => setHouseholdFilters((f) => ({ ...f, groupBy: e.target.value }))}
                  >
                    <option value="region">Region</option>
                    <option value="sub_region">Sub-Region</option>
                    <option value="district">District</option>
                  </select>
                </Field>
                <button
                  className="btn"
                  onClick={() => setHouseholdFilters({ groupBy: "region", region: "", subRegion: "", district: "" })}
                >
                  <Icon name="refresh" size={15}/> Reset
                </button>
              </div>
              {householdFilters.groupBy === "district" && householdFilters.subRegion && districts.length > 0 && (
                <div className="t-bodysm muted mt-3">
                  District distribution is filtered to {districts.length} district reference record{districts.length === 1 ? "" : "s"} in the selected sub-region.
                </div>
              )}
            </div>
          )}

          {isDqaReport && (
            <div className="card card-pad">
              <div className="grid" style={{gridTemplateColumns: "repeat(4, minmax(0, 1fr)) auto", alignItems: "end"}}>
                <Field label="Window">
                  <select
                    className="field-select"
                    value={dqaFilters.window}
                    onChange={(e) => setDqaFilters((f) => ({ ...f, window: e.target.value }))}
                  >
                    <option value="7d">Last 7 days</option>
                    <option value="30d">Last 30 days</option>
                    <option value="all">All time</option>
                  </select>
                </Field>
                <Field label="Severity">
                  <select
                    className="field-select"
                    value={dqaFilters.severity}
                    onChange={(e) => setDqaFilters((f) => ({ ...f, severity: e.target.value }))}
                  >
                    <option value="all">All severities</option>
                    <option value="blocking">Blocking</option>
                    <option value="warning">Warning</option>
                    <option value="info">Info</option>
                  </select>
                </Field>
                <Field label="Sub-region code">
                  <input
                    className="field-input"
                    value={dqaFilters.subRegionCode}
                    onChange={(e) => setDqaFilters((f) => ({ ...f, subRegionCode: e.target.value.trim() }))}
                    placeholder="SR-BUGANDA"
                  />
                </Field>
                <Field label="Rule ID">
                  <input
                    className="field-input"
                    value={dqaFilters.ruleId}
                    onChange={(e) => setDqaFilters((f) => ({ ...f, ruleId: e.target.value.trim() }))}
                    placeholder="AC-MEM-SURNAME"
                  />
                </Field>
                <button
                  className="btn"
                  onClick={() => setDqaFilters({ window: "7d", severity: "all", subRegionCode: "", ruleId: "" })}
                >
                  <Icon name="refresh" size={15}/> Reset
                </button>
              </div>
            </div>
          )}

          <div className="grid grid-3">
            <KPI title="Report" value={rows.length} foot="buckets"/>
            <KPI title="Total count" value={total.toLocaleString()}/>
            <KPI title="Export" value={recordCsv ? "3" : "2"} foot={recordCsv ? "JSON, CSV, records" : "JSON and CSV"}/>
          </div>

          <div className="card card-pad">
            <div className="row-wrap">
              <a className="btn" href={selectedEndpoint} target="_blank" rel="noreferrer">
                <Icon name="eye" size={15}/> Open JSON
              </a>
              <a
                className="btn"
                href={csvUrl(
                  selected.endpoint,
                  isDqaReport ? dqaParams(dqaFilters) : isHouseholdReport ? householdParams(householdFilters) : {},
                )}
                target="_blank"
                rel="noreferrer"
              >
                <Icon name="download" size={15}/> Download aggregate CSV
              </a>
              {recordCsv && (
                <a className="btn" href={recordCsv} target="_blank" rel="noreferrer">
                  <Icon name="file" size={15}/> Download record CSV
                </a>
              )}
              <Chip tone="system">ABAC scoped</Chip>
            </div>
          </div>

          {status === "ready" && rows.length > 0 && (
            <ReportChart report={selected} rows={rows}/>
          )}

          <div className="card">
            <div className="card-header">
              <div>
                <h3 className="t-h2">{selected.title}</h3>
                <div className="t-bodysm muted t-mono" style={{marginTop: 3}}>{selectedEndpoint}</div>
              </div>
              <Chip tone={selected.tone}>{selected.group}</Chip>
            </div>
            <div className="card-body">
              {status === "loading" && (
                <div className="center" style={{height: 180}}>
                  <div className="row"><Icon name="refresh" size={16}/> Loading report...</div>
                </div>
              )}
              {status === "error" && (
                <div className="center" style={{height: 180}}>
                  <div className="col center gap-3">
                    <Chip tone={reportNeedsLogin ? "quality" : "danger"}>
                      {reportNeedsLogin ? "Login required" : "Unavailable"}
                    </Chip>
                    <div className="t-bodysm muted">{error}</div>
                    {reportNeedsLogin && <div className="t-bodysm muted">{roleAuthCopy(role)}</div>}
                    {reportNeedsLogin && (
                      <a className="btn btn-primary" href="/admin/login/?next=/console/">
                        <Icon name="lock" size={15}/> Sign in
                      </a>
                    )}
                  </div>
                </div>
              )}
              {status === "ready" && rows.length === 0 && (
                <div className="center" style={{height: 180}}>
                  <div className="col center gap-3">
                    <Chip tone="neutral">No rows</Chip>
                    <div className="t-bodysm muted">{roleEmptyCopy(role, selected)}</div>
                  </div>
                </div>
              )}
              {status === "ready" && rows.length > 0 && (
                <div className="table-wrap" style={{boxShadow: "none"}}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Bucket</th>
                        <th style={{textAlign: "right"}}>Count</th>
                        {isDqaReport && <th className="col-actions">Records</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, index) => {
                        const count = Number(row.count ?? row.fail_count ?? 0);
                        const key = row.key || row.rule_id || row.metric || `row-${index + 1}`;
                        return (
                          <tr key={`${key}-${index}`}>
                            <td>
                              <div className="t-bodysm" style={{fontWeight: 600}}>
                                {formatBucket(row, index)}
                              </div>
                              {row.label && row.label !== row.key && (
                                <div className="t-bodysm muted t-mono" style={{marginTop: 2}}>{row.key}</div>
                              )}
                              {row.rule_label && (
                                <div className="t-bodysm muted" style={{marginTop: 2}}>{row.rule_label}</div>
                              )}
                            </td>
                            <td style={{textAlign: "right", fontVariantNumeric: "tabular-nums"}}>
                              {count.toLocaleString()}
                            </td>
                            {isDqaReport && (
                              <td className="col-actions">
                                <button className="btn btn-sm" onClick={() => loadDqaRecords(row.rule_id)}>
                                  <Icon name="eye" size={13}/> View
                                </button>
                                <a
                                  className="btn btn-sm"
                                  href={dqaViolationRecordsUrl(dqaFilters, row.rule_id, true)}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{marginLeft: 6}}
                                >
                                  <Icon name="download" size={13}/> CSV
                                </a>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {isDqaReport && dqaRuleId && (
            <div className="card">
              <div className="card-header">
                <div>
                  <h3 className="t-h2">Violation records</h3>
                  <div className="t-bodysm muted" style={{marginTop: 3}}>
                    Specific failed records for <span className="t-mono">{dqaRuleId}</span>
                  </div>
                </div>
                <a className="btn" href={dqaViolationRecordsUrl(dqaFilters, dqaRuleId, true)} target="_blank" rel="noreferrer">
                  <Icon name="download" size={15}/> Download CSV
                </a>
              </div>
              <div className="card-body">
                {dqaRecordsStatus === "loading" && (
                  <div className="center" style={{height: 120}}>
                    <div className="row"><Icon name="refresh" size={16}/> Loading records...</div>
                  </div>
                )}
                {dqaRecordsStatus === "error" && (
                  <div className="center" style={{height: 120}}>
                    <div className="col center gap-3">
                      <Chip tone={recordsNeedLogin ? "quality" : "danger"}>
                        {recordsNeedLogin ? "Login required" : "Unavailable"}
                      </Chip>
                      <div className="t-bodysm muted">{dqaRecordsError}</div>
                      {recordsNeedLogin && <div className="t-bodysm muted">{roleAuthCopy(role)}</div>}
                      {recordsNeedLogin && (
                        <a className="btn btn-primary" href="/admin/login/?next=/console/">
                          <Icon name="lock" size={15}/> Sign in
                        </a>
                      )}
                    </div>
                  </div>
                )}
                {dqaRecordsStatus === "ready" && dqaRecords.length === 0 && (
                  <div className="center" style={{height: 120}}>
                    <Chip tone="neutral">No matching records</Chip>
                  </div>
                )}
                {dqaRecordsStatus === "ready" && dqaRecords.length > 0 && (
                  <div className="table-wrap" style={{boxShadow: "none"}}>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Record</th>
                          <th>Household</th>
                          <th>Member</th>
                          <th>Sub-region</th>
                          <th>Source</th>
                          <th>Reason</th>
                          <th>Seen</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dqaRecords.map((record) => (
                          <tr key={record.result_id}>
                            <td>
                              <div className="t-mono">{record.record_id}</div>
                              <div className="t-bodysm muted" style={{marginTop: 2}}>
                                {record.record_type}{record.member_line_number ? ` · line ${record.member_line_number}` : ""}
                              </div>
                            </td>
                            <td>
                              <div className="t-mono">{record.household_id || "—"}</div>
                              {record.household_label && (
                                <div className="t-bodysm muted" style={{marginTop: 2}}>{record.household_label}</div>
                              )}
                            </td>
                            <td>{record.member_name || "—"}</td>
                            <td>{formatReportKey(record.sub_region_code || "—")}</td>
                            <td>
                              {record.source_system_code || "—"}
                              {record.connector_name && (
                                <div className="t-bodysm muted" style={{marginTop: 2}}>{record.connector_name}</div>
                              )}
                            </td>
                            <td>{record.reason || "—"}</td>
                            <td className="t-mono">{String(record.executed_at || "").slice(0, 19)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

Object.assign(window, { ReportsScreen });
