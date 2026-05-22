/* global React, Icon, Chip, PageHeader, KPI, useApi */
// NSR MIS — PMT Dashboard (Admin · PMT)
// =========================================================
// Operational dashboard for the Proxy Means Test engine.
// The PMT score is the gravity well of the registry — every
// programme eligibility rule, every UPD impact assessment,
// every cohort export references a household's band.
//
// This screen is read-only by design. Editing the model
// (variables, weights, band strategy) lives in PMT Configuration.
//
// Wired from:
//   apps.pmt.models.PMTModelVersion   (active model + history)
//   apps.pmt.models.PMTResult         (per-household score)
//   apps.pmt.models.PMTBandThreshold  (daily empirical thresholds)
//   apps.pmt.tasks                    (recompute jobs)
//   apps.security.audit               (model activations, recomputes)

const { useState: useStatePMT, useMemo: useMemoPMT } = React;

/* ============================================================
   Sample data — mirrors live shape; replace with API reads.
   ============================================================ */
const PMT_ACTIVE = {
  version: 1,
  status: "active",
  description: "Uganda PMT v1 — UNHS 2019/20 + UDHS 2022 calibration. 25-variable model; ADR-0025 DSL.",
  author: "MGLSD Statistics Unit · Dr. Nakanwagi",
  approvedBy: "Director General · UBOS",
  approvedAt: "02 Jan 2026",
  effectiveFrom: "04 Jan 2026",
  bandStrategy: "percentile",
  intercept: 3.0185,
  validationRSquared: 0.642,
  calibrationDataset: "UNHS 2023/24",
  calibrationYearEnd: 2024,
  calibrationStale: false, // ADR-0023: stale if year-end > 3 years ago
  yearsToStale: 1,
  variablesCount: 25,
  bandCutoffsPercentile: { extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100 },
  thresholdsLatest: { extreme_poverty: 2.812, poverty: 3.245, vulnerable: 3.582, not_poor: 7.219 },
  thresholdsComputedAt: "22 May 2026 · 02:00 EAT",
  thresholdsSampleSize: 12108331,
};

const PMT_VARIABLES_TOP = [
  { name: "rooms_per_capita",          weight: +0.292, transform: "identity",      group: "Dwelling",      influence: 0.193 },
  { name: "floor_tiles_terrazzo",      weight: +0.326, transform: "present_as_one", group: "Dwelling",     influence: 0.181 },
  { name: "owns_car_or_van",           weight: +0.294, transform: "present_as_one", group: "Assets",        influence: 0.156 },
  { name: "owns_television",           weight: +0.228, transform: "present_as_one", group: "Assets",        influence: 0.142 },
  { name: "owns_motorcycle",           weight: +0.213, transform: "present_as_one", group: "Assets",        influence: 0.131 },
  { name: "any_cellphone",             weight: +0.185, transform: "present_as_one", group: "Assets",        influence: 0.118 },
  { name: "head_edu_tertiary",         weight: +0.312, transform: "present_as_one", group: "Education",     influence: 0.117 },
  { name: "head_edu_secondary",        weight: +0.154, transform: "present_as_one", group: "Education",     influence: 0.104 },
  { name: "open_defecation",           weight: -0.128, transform: "present_as_one", group: "Sanitation",    influence: 0.092 },
  { name: "share_children_under_15",   weight: -0.117, transform: "identity",      group: "Composition",   influence: 0.089 },
  { name: "owns_refrigerator",         weight: +0.157, transform: "present_as_one", group: "Assets",        influence: 0.083 },
];

// Band distribution — full registry, snapshot 22 May 2026 02:00 EAT
const PMT_BANDS = [
  { band: "extreme_poverty", label: "Extreme poverty",  pct: 10.1, count: 1222942, color: "var(--accent-danger)",    tone: "danger"      },
  { band: "poverty",         label: "Poverty",          pct: 10.0, count: 1210890, color: "var(--accent-quality)",   tone: "quality"     },
  { band: "vulnerable",      label: "Vulnerable",       pct: 10.1, count: 1222942, color: "var(--accent-update)",    tone: "update"      },
  { band: "not_poor",        label: "Not poor",         pct: 69.8, count: 8451557, color: "var(--accent-data)",      tone: "data"        },
];

// Sub-region poverty-rate (% in poverty + extreme_poverty)
const PMT_GEO = [
  { subreg: "Karamoja",        rate: 53.2, hh: 412091, scored: 99.8, pomp: 219400 },
  { subreg: "West Nile",       rate: 38.4, hh: 901232, scored: 99.1, pomp: 345970 },
  { subreg: "Acholi",          rate: 35.8, hh: 698412, scored: 98.4, pomp: 250030 },
  { subreg: "Lango",           rate: 29.1, hh: 712014, scored: 97.6, pomp: 207195 },
  { subreg: "Teso",            rate: 28.4, hh: 658912, scored: 99.0, pomp: 187131 },
  { subreg: "Bukedi",          rate: 26.9, hh: 622109, scored: 96.8, pomp: 167347 },
  { subreg: "Busoga",          rate: 22.4, hh: 1109221, scored: 95.4, pomp: 248466 },
  { subreg: "Bunyoro",         rate: 21.0, hh: 712031, scored: 96.9, pomp: 149526 },
  { subreg: "Sebei",           rate: 19.8, hh: 192040, scored: 99.4, pomp: 38024 },
  { subreg: "Tooro",           rate: 17.6, hh: 821092, scored: 95.1, pomp: 144512 },
  { subreg: "Kigezi",          rate: 16.2, hh: 612091, scored: 97.0, pomp: 99159 },
  { subreg: "Ankole",          rate: 13.4, hh: 988120, scored: 96.2, pomp: 132408 },
  { subreg: "Buganda North",   rate: 11.6, hh: 1322015, scored: 94.3, pomp: 153354 },
  { subreg: "Buganda South",   rate:  9.1, hh: 1448820, scored: 93.0, pomp: 131843 },
];

// Threshold drift — last 6 weeks of empirical band thresholds (percentile model)
const PMT_DRIFT = [
  { wk: "Wk 16", ep: 2.798, p: 3.232, v: 3.569 },
  { wk: "Wk 17", ep: 2.802, p: 3.235, v: 3.572 },
  { wk: "Wk 18", ep: 2.804, p: 3.238, v: 3.575 },
  { wk: "Wk 19", ep: 2.808, p: 3.241, v: 3.578 },
  { wk: "Wk 20", ep: 2.810, p: 3.243, v: 3.580 },
  { wk: "Wk 21", ep: 2.812, p: 3.245, v: 3.582 },
];

// Trigger-source breakdown — where the scores came from (last 90d)
const PMT_TRIGGERS = [
  { code: "initial_registration", label: "Initial registration", count: 87102, share: 38.2, tone: "data" },
  { code: "upd_pmt_relevant",     label: "UPD · pmt_relevant",   count: 64811, share: 28.4, tone: "update" },
  { code: "model_activation",     label: "Model activation",     count: 38241, share: 16.8, tone: "programme" },
  { code: "manual_recompute",     label: "Manual recompute",     count: 21908, share:  9.6, tone: "quality" },
  { code: "ddup_merge",           label: "DDUP merge",           count: 11421, share:  5.0, tone: "identity" },
  { code: "scheduled_batch",      label: "Scheduled batch",      count:  4521, share:  2.0, tone: "neutral" },
];

const PMT_JOB = {
  taskName: "apps.pmt.tasks.recompute_band_thresholds_task",
  schedule: "Daily · 02:00 EAT",
  lastRun: "22 May 2026 · 02:00 EAT",
  durationMs: 84320,
  status: "success",
  bandsWritten: 4,
  modelVersionsProcessed: 1,
  nextRun: "23 May 2026 · 02:00 EAT",
  successRate7d: 100,
  recentRuns: [
    { date: "22 May 2026", status: "success", ms: 84320, sample: 12108331 },
    { date: "21 May 2026", status: "success", ms: 81204, sample: 12107218 },
    { date: "20 May 2026", status: "success", ms: 79892, sample: 12104991 },
    { date: "19 May 2026", status: "success", ms: 81012, sample: 12103442 },
    { date: "18 May 2026", status: "success", ms: 82431, sample: 12101108 },
    { date: "17 May 2026", status: "warn",    ms: 142981, sample: 12098932, note: "Slow — index rebuild on PMTResult.computed_at" },
    { date: "16 May 2026", status: "success", ms: 80201, sample: 12096081 },
  ],
};

const PMT_COVERAGE = {
  totalHouseholds: 12108331,
  scored: 12108331,
  scoredPct: 100.0,
  scoredInLast30d: 11212091,
  scoredInLast30dPct: 92.6,
  scoredInLast90d: 11800042,
  scoredInLast90dPct: 97.5,
  scoredStale: 308289, // older than 12 months
  scoredStalePct: 2.5,
};

const PMT_RECENT_EVENTS = [
  { when: "22 May · 14:02", actor: "System REF",  action: "score.recomputed", entity: "01KRPPW6WRGRJZY0N4XN8R1YC2", detail: "UPD-2026-05-22-00188 · roof material · band poverty→vulnerable", tone: "update" },
  { when: "22 May · 13:55", actor: "System REF",  action: "score.recomputed", entity: "01HXP02CN4QFB7K6FZRWS00111", detail: "UPD-2026-05-22-00184 · land hectares · band unchanged",        tone: "update" },
  { when: "22 May · 09:18", actor: "Akello P.",   action: "score.manual",     entity: "01HY09KRS1P9MN6FB7K6FZRWS84", detail: "UPD review · manual recompute · band vulnerable→poverty",     tone: "user"   },
  { when: "22 May · 02:00", actor: "celery-beat", action: "thresholds.recompute", entity: "PMT-v1",                  detail: "4 bands written · n=12,108,331 · 84.3s",                       tone: "system" },
  { when: "21 May · 16:44", actor: "System REF",  action: "score.recomputed", entity: "01HXZ9MR4N8P2QFB7K6FZRWS33", detail: "DDUP merge · band poverty→poverty",                            tone: "update" },
  { when: "20 May · 11:08", actor: "System REF",  action: "score.recomputed", entity: "(batch · 412 households)",    detail: "Scheduled batch · West Nile · band shifts: 38 ep→p, 71 p→v",   tone: "system" },
];

/* ============================================================
   Local helpers
   ============================================================ */
const PMT_Stat = ({ label, value, sub, tint = "data", action }) => (
  <div style={{
    padding: '14px 16px', borderRadius: 6,
    border: '1px solid var(--neutral-200)',
    borderLeft: `3px solid var(--accent-${tint})`,
    background: 'var(--neutral-0)',
    minWidth: 0,
  }}>
    <div className="t-cap">{label}</div>
    <div style={{ fontSize: 22, fontWeight: 600, marginTop: 4, lineHeight: 1.15 }}>{value}</div>
    {sub && <div className="t-cap mt-2">{sub}</div>}
    {action && <div className="mt-2">{action}</div>}
  </div>
);

const PMT_SectionHead = ({ title, sub, action }) => (
  <div className="row gap-3" style={{ marginBottom: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
    <h3 className="t-h3" style={{ margin: 0 }}>{title}</h3>
    {sub && <span className="t-cap">{sub}</span>}
    <div style={{ flex: 1 }} />
    {action}
  </div>
);

/* Compact band chip */
const BandChip = ({ band }) => {
  const m = {
    extreme_poverty: { label: 'Extreme poverty', tone: 'danger' },
    poverty:         { label: 'Poverty',         tone: 'quality' },
    vulnerable:      { label: 'Vulnerable',      tone: 'update' },
    not_poor:        { label: 'Not poor',        tone: 'data' },
  }[band] || { label: band, tone: 'neutral' };
  return <Chip size="sm" tone={m.tone}>{m.label}</Chip>;
};

/* ============================================================
   PMT DASHBOARD
   ============================================================ */
// Project the live `/api/v1/admin/pmt/dashboard/` response onto the
// existing mock-shaped variables this screen renders against. When
// the live fetch has data, it overrides the module-scope demo arrays;
// when it doesn't yet (loading / 403 / not authenticated), the demo
// constants stay visible so the prototype keeps rendering.
const _projectActive = (raw) => raw ? {
  version: raw.version,
  status: raw.status,
  description: raw.description,
  author: raw.author,
  approvedBy: raw.approved_by,
  approvedAt: (raw.approved_at || "").slice(0, 10),
  effectiveFrom: (raw.effective_from || "").slice(0, 10),
  bandStrategy: raw.band_strategy,
  intercept: raw.intercept,
  validationRSquared: raw.validation_r_squared,
  calibrationDataset: raw.calibration_dataset,
  calibrationYearEnd: raw.calibration_year_end,
  calibrationStale: raw.calibration_stale,
  yearsToStale: raw.years_to_stale,
  variablesCount: raw.variables_count,
  bandCutoffsPercentile: raw.band_cutoffs_percentile,
  thresholdsLatest: raw.thresholds_latest,
  thresholdsComputedAt: raw.thresholds_computed_at,
  thresholdsSampleSize: raw.thresholds_sample_size,
} : PMT_ACTIVE;

const _projectBands = (rows) => Array.isArray(rows) && rows.length ? rows.map(r => ({
  band: r.band,
  label: (r.band || "").replace("_", " ").replace(/\b\w/g, c => c.toUpperCase()),
  pct: r.pct,
  count: r.count,
  color: {
    extreme_poverty: "var(--accent-danger)",
    poverty: "var(--accent-quality)",
    vulnerable: "var(--accent-update)",
    not_poor: "var(--accent-data)",
  }[r.band] || "var(--neutral-300)",
  tone: {
    extreme_poverty: "danger",
    poverty: "quality",
    vulnerable: "update",
    not_poor: "data",
  }[r.band] || "neutral",
})) : PMT_BANDS;

const PmtDashboardScreen = ({ onOpenConfig }) => {
  const [periodFilter, setPeriodFilter] = useStatePMT('30d');
  // Live data overlay — fetched once on mount, falls back to the
  // prototype constants when the endpoint isn't reachable.
  const [resp, meta] = (typeof useApi === 'function')
    ? useApi('/api/v1/admin/pmt/dashboard/')
    : [null, { loading: false, error: null }];
  // Shadow the module-scope mock arrays with the live projections.
  // JSX inside this function picks up the inner consts via lexical
  // scope, so no JSX-level rename is required.
  // eslint-disable-next-line no-shadow
  const PMT_ACTIVE = _projectActive(resp && resp.active);
  // eslint-disable-next-line no-shadow
  const PMT_BANDS = _projectBands(resp && resp.bands);

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · PMT · operational dashboard"
        title="Proxy Means Test"
        sub="Operational health of the Uganda PMT engine — active model, band distribution, recompute job, threshold drift, and score coverage."
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export snapshot</button>
          <button className="btn btn-primary" onClick={onOpenConfig}><Icon name="sliders" size={14}/> Open configuration</button>
        </>}
      />

      {/* Top row — Active model card + headline KPIs */}
      <div className="grid" style={{ gridTemplateColumns: '1.4fr 1fr 1fr 1fr', gap: 16 }}>
        {/* Active model card */}
        <div className="card" style={{
          padding: 0, borderTop: '3px solid var(--accent-eligibility)',
          gridRow: '1 / span 2',
        }}>
          <div className="card-header" style={{ padding: '14px 18px', alignItems: 'flex-start' }}>
            <div>
              <div className="t-cap" style={{ color: 'var(--accent-eligibility)', fontWeight: 600 }}>
                <Icon name="check" size={11}/> ACTIVE MODEL VERSION
              </div>
              <h2 style={{ margin: '4px 0 0', fontSize: 28, fontWeight: 700 }}>
                PMT v{PMT_ACTIVE.version}
              </h2>
              <div className="t-cap mt-1">{PMT_ACTIVE.description}</div>
            </div>
            <Chip tone="data"><Icon name="check" size={10}/> Active</Chip>
          </div>
          <div style={{ padding: '0 18px 14px', display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 8, fontSize: 13 }}>
            <div className="muted">Effective from</div><div>{PMT_ACTIVE.effectiveFrom}</div>
            <div className="muted">Approved by</div><div>{PMT_ACTIVE.approvedBy}</div>
            <div className="muted">Author</div><div>{PMT_ACTIVE.author}</div>
            <div className="muted">Variables</div><div className="t-num">{PMT_ACTIVE.variablesCount}</div>
            <div className="muted">Intercept</div><div className="t-mono">{PMT_ACTIVE.intercept.toFixed(4)}</div>
            <div className="muted">Validation R²</div><div className="t-num">{PMT_ACTIVE.validationRSquared.toFixed(3)}</div>
            <div className="muted">Band strategy</div>
            <div><Chip size="sm" tone="data">{PMT_ACTIVE.bandStrategy}</Chip></div>
            <div className="muted">Calibration dataset</div><div>{PMT_ACTIVE.calibrationDataset}</div>
            <div className="muted">Calibration year</div>
            <div>
              {PMT_ACTIVE.calibrationYearEnd}{' '}
              {PMT_ACTIVE.calibrationStale
                ? <Chip size="sm" tone="danger">stale</Chip>
                : <span className="t-cap">· {PMT_ACTIVE.yearsToStale}y until recalibration window (ADR-0023)</span>}
            </div>
          </div>
          <div style={{
            borderTop: '1px solid var(--neutral-200)',
            padding: '12px 18px',
            background: 'var(--neutral-50)',
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <Icon name="info" size={13} color="var(--neutral-500)"/>
            <span className="t-cap">
              Activation requires dual approval — same workflow as DQA and DDUP. See PMT Configuration.
            </span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm" onClick={onOpenConfig}>Open v{PMT_ACTIVE.version}</button>
          </div>
        </div>

        {/* Coverage KPIs */}
        <PMT_Stat
          label="Households scored"
          value={`${PMT_COVERAGE.scoredPct.toFixed(1)}%`}
          sub={`${PMT_COVERAGE.scored.toLocaleString()} of ${PMT_COVERAGE.totalHouseholds.toLocaleString()}`}
          tint="data"/>
        <PMT_Stat
          label="Scored last 30 days"
          value={`${PMT_COVERAGE.scoredInLast30dPct.toFixed(1)}%`}
          sub={`${PMT_COVERAGE.scoredInLast30d.toLocaleString()} households`}
          tint="programme"/>
        <PMT_Stat
          label="Stale scores (>12mo)"
          value={`${PMT_COVERAGE.scoredStalePct.toFixed(1)}%`}
          sub={`${PMT_COVERAGE.scoredStale.toLocaleString()} households — flag for refresh`}
          tint="quality"/>

        {/* Threshold drift compact */}
        <div className="card" style={{ padding: 14, borderLeft: '3px solid var(--accent-update)' }}>
          <div className="t-cap" style={{ color: 'var(--accent-update)', fontWeight: 600 }}>EMPIRICAL THRESHOLDS · v1</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
            {Object.entries(PMT_ACTIVE.thresholdsLatest).map(([b, t]) => (
              <div key={b}>
                <BandChip band={b}/>
                <div className="t-num" style={{ fontSize: 18, fontWeight: 600, marginTop: 4 }}>≤ {t.toFixed(3)}</div>
              </div>
            ))}
          </div>
          <div className="t-cap mt-3">
            Computed {PMT_ACTIVE.thresholdsComputedAt}<br/>
            n = {PMT_ACTIVE.thresholdsSampleSize.toLocaleString()}
          </div>
        </div>

        <PMT_Stat
          label="Daily recompute job"
          value={PMT_JOB.status === 'success' ? 'Healthy' : 'Degraded'}
          sub={<>last run <strong>{PMT_JOB.lastRun}</strong> · next {PMT_JOB.nextRun}</>}
          tint={PMT_JOB.status === 'success' ? 'data' : 'quality'}/>
      </div>

      {/* Band distribution + Geography */}
      <div className="grid mt-5" style={{ gridTemplateColumns: '1fr 1.6fr', gap: 16 }}>
        <div className="card" style={{ padding: 20 }}>
          <PMT_SectionHead title="Band distribution"
            sub={`Snapshot · ${PMT_ACTIVE.thresholdsSampleSize.toLocaleString()} households`}/>
          {/* Stacked bar */}
          <div style={{
            display: 'flex', height: 14, borderRadius: 7, overflow: 'hidden',
            background: 'var(--neutral-100)',
          }} title="Band distribution">
            {PMT_BANDS.map(b => (
              <div key={b.band} title={`${b.label}: ${b.pct.toFixed(1)}%`}
                style={{ flex: b.pct, background: b.color }}/>
            ))}
          </div>
          {/* Legend */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 18 }}>
            {PMT_BANDS.map(b => (
              <div key={b.band} className="row gap-3" style={{ alignItems: 'center' }}>
                <span style={{ width: 12, height: 12, borderRadius: 3, background: b.color, flex: '0 0 auto' }}/>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="t-bodysm" style={{ fontWeight: 500 }}>{b.label}</div>
                  <div className="t-cap">{b.count.toLocaleString()} households</div>
                </div>
                <div className="t-num" style={{ fontSize: 17, fontWeight: 600, minWidth: 56, textAlign: 'right' }}>
                  {b.pct.toFixed(1)}%
                </div>
              </div>
            ))}
          </div>
          <div className="t-cap mt-4" style={{ paddingTop: 12, borderTop: '1px solid var(--neutral-200)' }}>
            Bands are policy-bound to population percentiles (MGLSD directive 2026-05-21).
            The empirical score-thresholds shift daily as the registry grows — see threshold drift.
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <PMT_SectionHead title="Poverty rate by sub-region"
            sub="% in poverty + extreme poverty"
            action={<button className="btn btn-sm btn-ghost"><Icon name="download" size={12}/> CSV</button>}/>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {PMT_GEO.map(g => {
              const tone = g.rate >= 40 ? 'var(--accent-danger)'
                : g.rate >= 25 ? 'var(--accent-quality)'
                : g.rate >= 15 ? 'var(--accent-update)'
                : 'var(--accent-data)';
              const maxRate = Math.max(...PMT_GEO.map(x => x.rate));
              return (
                <div key={g.subreg} style={{
                  display: 'grid', gridTemplateColumns: '140px 1fr 80px 80px',
                  gap: 12, alignItems: 'center', padding: '6px 0',
                }}>
                  <span className="t-bodysm" style={{ fontWeight: 500 }}>{g.subreg}</span>
                  <div style={{
                    height: 8, background: 'var(--neutral-100)', borderRadius: 4, overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${(g.rate/maxRate)*100}%`, height: '100%', background: tone,
                    }}/>
                  </div>
                  <span className="t-num t-bodysm" style={{ fontWeight: 600, textAlign: 'right' }}>
                    {g.rate.toFixed(1)}%
                  </span>
                  <span className="t-cap" style={{ textAlign: 'right' }}>
                    {g.pomp.toLocaleString()} HH
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Threshold drift + Trigger source breakdown */}
      <div className="grid mt-5" style={{ gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        <div className="card" style={{ padding: 20 }}>
          <PMT_SectionHead title="Band threshold drift"
            sub="empirical score thresholds, last 6 weeks · v1"
            action={<select className="field-select btn-sm" value={periodFilter} onChange={e=>setPeriodFilter(e.target.value)} style={{ height: 28, width: 'auto' }}>
              <option value="30d">Last 30 days</option>
              <option value="6w">Last 6 weeks</option>
              <option value="90d">Last 90 days</option>
              <option value="365d">Last 12 months</option>
            </select>}/>
          {/* SVG line chart — three band thresholds over weeks */}
          <ThresholdDrift data={PMT_DRIFT}/>
          <div className="row gap-3 mt-3" style={{ flexWrap: 'wrap' }}>
            {[
              ['extreme_poverty', 'var(--accent-danger)',  PMT_DRIFT[PMT_DRIFT.length-1].ep - PMT_DRIFT[0].ep],
              ['poverty',         'var(--accent-quality)', PMT_DRIFT[PMT_DRIFT.length-1].p  - PMT_DRIFT[0].p],
              ['vulnerable',      'var(--accent-update)',  PMT_DRIFT[PMT_DRIFT.length-1].v  - PMT_DRIFT[0].v],
            ].map(([b, color, delta]) => (
              <div key={b} className="row gap-2">
                <span style={{ width: 10, height: 10, borderRadius: 2, background: color }}/>
                <BandChip band={b}/>
                <span className="t-cap">Δ {delta >= 0 ? '+' : ''}{delta.toFixed(3)}</span>
              </div>
            ))}
          </div>
          <div className="t-cap mt-3" style={{ paddingTop: 12, borderTop: '1px solid var(--neutral-200)' }}>
            Thresholds drift upward as the registry adds wealthier households or as the model
            picks up newly-completed UPD evidence. A sudden ±0.05 shift fires an alert (see Audit).
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <PMT_SectionHead title="Trigger sources" sub="last 90 days · 228,004 scores"/>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {PMT_TRIGGERS.map(t => {
              const max = Math.max(...PMT_TRIGGERS.map(x => x.share));
              return (
                <div key={t.code}>
                  <div className="row gap-2" style={{ alignItems: 'center' }}>
                    <Chip size="sm" tone={t.tone}>{t.label}</Chip>
                    <div style={{ flex: 1 }}/>
                    <span className="t-num" style={{ fontWeight: 600, fontSize: 13 }}>{t.count.toLocaleString()}</span>
                    <span className="t-cap" style={{ minWidth: 44, textAlign: 'right' }}>{t.share.toFixed(1)}%</span>
                  </div>
                  <div style={{
                    height: 4, background: 'var(--neutral-100)', borderRadius: 2,
                    overflow: 'hidden', marginTop: 4,
                  }}>
                    <div style={{
                      width: `${(t.share/max)*100}%`, height: '100%', background: `var(--accent-${t.tone === 'neutral' ? 'data' : t.tone})`,
                    }}/>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="t-cap mt-4" style={{ paddingTop: 12, borderTop: '1px solid var(--neutral-200)' }}>
            Source codes are ChoiceList <span className="t-mono">pmt_trigger_source</span> (US-PMT-014).
          </div>
        </div>
      </div>

      {/* Recompute job + Top variables */}
      <div className="grid mt-5" style={{ gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:12 }}>
            <h3 className="t-h3" style={{ margin: 0 }}>Recompute job</h3>
            <Chip size="sm" tone="data">{PMT_JOB.successRate7d}% / 7d</Chip>
            <span className="t-cap t-mono">{PMT_JOB.taskName}</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm"><Icon name="refresh" size={12}/> Run now</button>
          </div>
          <div style={{ padding: '12px 20px', display:'grid', gridTemplateColumns:'180px 1fr', rowGap:6, fontSize:13 }}>
            <div className="muted">Schedule</div><div>{PMT_JOB.schedule}</div>
            <div className="muted">Last run</div><div>{PMT_JOB.lastRun} · {(PMT_JOB.durationMs/1000).toFixed(1)}s · {PMT_JOB.bandsWritten} bands written</div>
            <div className="muted">Next run</div><div>{PMT_JOB.nextRun}</div>
          </div>
          <table className="tbl" style={{ boxShadow: 'none' }}>
            <thead><tr><th>Date</th><th>Status</th><th>Duration</th><th>Sample size</th><th>Note</th></tr></thead>
            <tbody>
              {PMT_JOB.recentRuns.map((r, i) => (
                <tr key={i}>
                  <td className="t-cap">{r.date}</td>
                  <td>
                    {r.status === 'success' && <Chip size="sm" tone="data"><Icon name="check" size={10}/> success</Chip>}
                    {r.status === 'warn'    && <Chip size="sm" tone="quality"><Icon name="alert" size={10}/> slow</Chip>}
                    {r.status === 'fail'    && <Chip size="sm" tone="danger">failed</Chip>}
                  </td>
                  <td className="t-num t-bodysm">{(r.ms/1000).toFixed(1)}s</td>
                  <td className="t-num t-bodysm">{r.sample.toLocaleString()}</td>
                  <td className="t-bodysm muted">{r.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <PMT_SectionHead title="Top variables by influence" sub="model v1 · |β × σ| × sample mean"/>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {PMT_VARIABLES_TOP.map(v => {
              const max = Math.max(...PMT_VARIABLES_TOP.map(x => x.influence));
              const isNeg = v.weight < 0;
              return (
                <div key={v.name}>
                  <div className="row gap-2" style={{ alignItems: 'center' }}>
                    <span className="t-mono t-bodysm" style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v.name}</span>
                    <Chip size="sm" tone={isNeg ? 'quality' : 'data'}>{v.weight >= 0 ? '+' : ''}{v.weight.toFixed(3)}</Chip>
                  </div>
                  <div style={{
                    height: 4, background: 'var(--neutral-100)', borderRadius: 2,
                    overflow: 'hidden', marginTop: 4,
                  }}>
                    <div style={{
                      width: `${(v.influence/max)*100}%`, height: '100%',
                      background: isNeg ? 'var(--accent-quality)' : 'var(--accent-data)',
                    }}/>
                  </div>
                </div>
              );
            })}
          </div>
          <button className="btn btn-sm mt-4" style={{ width: '100%' }} onClick={onOpenConfig}>
            <Icon name="sliders" size={13}/> Open variable editor
          </button>
        </div>
      </div>

      {/* Recent events */}
      <div className="card mt-5" style={{ padding: 0 }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:12 }}>
          <h3 className="t-h3" style={{ margin: 0 }}>Recent score events</h3>
          <span className="t-cap">most recent 6 from the audit chain · feed: <span className="t-mono">apps.security.audit</span></span>
          <div style={{ flex: 1 }}/>
          <button className="btn btn-sm btn-ghost"><Icon name="download" size={12}/> Export</button>
        </div>
        {PMT_RECENT_EVENTS.map((e, i) => (
          <div key={i} style={{
            padding: '12px 20px',
            display: 'flex', gap: 14, alignItems: 'flex-start',
            borderBottom: i < PMT_RECENT_EVENTS.length-1 ? '1px solid var(--neutral-200)' : 0,
          }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: e.tone === 'system' ? 'var(--neutral-200)'
                : e.tone === 'update' ? 'var(--accent-update-bg, var(--neutral-100))'
                : 'var(--primary-100)',
              color: e.tone === 'system' ? 'var(--neutral-700)'
                : e.tone === 'update' ? 'var(--accent-update)'
                : 'var(--primary-900)',
              display: 'grid', placeItems: 'center',
              fontSize: 10, fontWeight: 600, flex: '0 0 auto',
            }}>
              {e.actor.split(' ').map(w => w[0]).slice(0, 2).join('')}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row gap-2" style={{ alignItems: 'baseline', flexWrap: 'wrap' }}>
                <strong className="t-bodysm">{e.actor}</strong>
                <span className="t-mono t-cap">{e.action}</span>
                <span className="t-cap">·</span>
                <span className="t-mono t-cap" style={{ color: 'var(--accent-system)' }}>{e.entity}</span>
              </div>
              <div className="t-cap mt-1" style={{ color: 'var(--neutral-600)' }}>{e.detail}</div>
            </div>
            <div className="t-cap" style={{ flex: '0 0 auto', whiteSpace: 'nowrap' }}>{e.when}</div>
          </div>
        ))}
      </div>

      <div className="t-cap mt-4" style={{ textAlign: 'center' }}>
        Read-only operational dashboard. Editing the model — variables, weights, band strategy — happens in PMT Configuration.
      </div>
    </div>
  );
};

/* ============================================================
   Inline SVG line chart for threshold drift
   ============================================================ */
const ThresholdDrift = ({ data }) => {
  const w = 640, h = 200, pad = { t: 12, r: 12, b: 24, l: 44 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;

  const allVals = data.flatMap(d => [d.ep, d.p, d.v]);
  const yMin = Math.floor(Math.min(...allVals) * 100) / 100 - 0.02;
  const yMax = Math.ceil(Math.max(...allVals) * 100) / 100 + 0.02;
  const xStep = innerW / (data.length - 1);

  const path = (key, color) => {
    const d = data.map((row, i) => {
      const x = pad.l + i * xStep;
      const y = pad.t + ((yMax - row[key]) / (yMax - yMin)) * innerH;
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(' ');
    return <path d={d} fill="none" stroke={color} strokeWidth={2}/>;
  };

  const yTicks = [];
  for (let i = 0; i <= 4; i++) {
    const v = yMin + (i / 4) * (yMax - yMin);
    const y = pad.t + ((yMax - v) / (yMax - yMin)) * innerH;
    yTicks.push(
      <g key={i}>
        <line x1={pad.l} y1={y} x2={w - pad.r} y2={y} stroke="var(--neutral-200)" strokeWidth={1}/>
        <text x={pad.l - 6} y={y + 3} fontSize="10" textAnchor="end" fill="var(--neutral-500)">{v.toFixed(2)}</text>
      </g>
    );
  }

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: 'auto', maxHeight: 260 }} role="img" aria-label="Threshold drift chart">
      {yTicks}
      {path('v',  'var(--accent-update)')}
      {path('p',  'var(--accent-quality)')}
      {path('ep', 'var(--accent-danger)')}
      {data.map((d, i) => (
        <g key={d.wk}>
          <text x={pad.l + i * xStep} y={h - pad.b + 14}
            fontSize="10" textAnchor="middle" fill="var(--neutral-500)">{d.wk}</text>
          {['ep', 'p', 'v'].map(key => {
            const color = key === 'ep' ? 'var(--accent-danger)' : key === 'p' ? 'var(--accent-quality)' : 'var(--accent-update)';
            const y = pad.t + ((yMax - d[key]) / (yMax - yMin)) * innerH;
            return <circle key={key} cx={pad.l + i * xStep} cy={y} r={3} fill="var(--neutral-0)" stroke={color} strokeWidth={2}/>;
          })}
        </g>
      ))}
    </svg>
  );
};

Object.assign(window, {
  PmtDashboardScreen,
  PMT_ACTIVE, PMT_BANDS, PMT_VARIABLES_TOP, PMT_GEO, PMT_DRIFT, PMT_JOB, PMT_COVERAGE,
});
