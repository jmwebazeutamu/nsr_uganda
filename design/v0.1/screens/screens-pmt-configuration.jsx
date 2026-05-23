/* global React, Icon, Chip, PageHeader,
   PMT_ACTIVE, PMT_VARIABLES_TOP, BandChip */
// NSR MIS — PMT Configuration (Admin · PMT)
// =========================================================
// Manage PMT model versions: registry of all versions, variable
// + weight editor for drafts, band strategy + cutoffs editor,
// activation workflow (dual approval per AC-PMT-MODEL-VERSION).
//
// Maps to:
//   apps.pmt.models.PMTModelVersion (status DRAFT → PENDING_APPROVAL → ACTIVE → RETIRED)
//   apps.pmt.services.activate_model_version
//   apps.security.audit (model.create, model.submit, model.activate)

const { useState: useStatePCfg, useMemo: useMemoPCfg } = React;

/* ============================================================
   Sample data — mirrors PMTModelVersion shape; replace with API
   ============================================================ */
const PCFG_VERSIONS = [
  {
    id: "01HXM12Z4F7N6P0V8K9TB2QXJK",
    version: 2,
    status: "draft",
    description: "v2 calibration — UDHS 2024 spike-in. Adds livestock & cooking-fuel variables.",
    author: "Dr. Nakanwagi · MGLSD Statistics",
    approvedBy: null, approvedAt: null,
    effectiveFrom: null,
    variablesCount: 27,
    intercept: 2.9842,
    validationRSquared: 0.668,
    bandStrategy: "percentile",
    bandCutoffs: { extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100 },
    calibrationDataset: "UNHS 2023/24 + UDHS 2024 spike-in",
    calibrationYearEnd: 2024,
    createdAt: "12 May 2026",
    updatedAt: "21 May 2026 · 11:08 EAT",
  },
  {
    id: "01HX91KPNRMQ0F2B7K6FZRWS01",
    version: 1,
    status: "active",
    description: "Uganda PMT v1 — UNHS 2019/20 + UDHS 2022 calibration. 25-variable model; ADR-0025 DSL.",
    author: "MGLSD Statistics Unit · Dr. Nakanwagi",
    approvedBy: "Director General · UBOS",
    approvedAt: "02 Jan 2026",
    effectiveFrom: "04 Jan 2026",
    variablesCount: 25,
    intercept: 3.0185,
    validationRSquared: 0.642,
    bandStrategy: "percentile",
    bandCutoffs: { extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100 },
    calibrationDataset: "UNHS 2023/24",
    calibrationYearEnd: 2024,
    createdAt: "02 Dec 2025",
    updatedAt: "04 Jan 2026 · 09:14 EAT",
  },
  {
    id: "01H8M9QR4N1P0V8B7K6FZRWS00",
    version: 0,
    status: "retired",
    description: "Legacy PMT (UNHS 2016/17). Retired on v1 activation.",
    author: "MGLSD legacy",
    approvedBy: "Director General · UBOS",
    approvedAt: "10 Aug 2023",
    effectiveFrom: "01 Sep 2023",
    variablesCount: 22,
    intercept: 2.9100,
    validationRSquared: 0.582,
    bandStrategy: "threshold",
    bandCutoffs: { extreme_poverty: 0, poverty: 30, vulnerable: 50, not_poor: 100 },
    calibrationDataset: "UNHS 2016/17",
    calibrationYearEnd: 2017,
    createdAt: "20 Jul 2023",
    updatedAt: "04 Jan 2026 · 09:14 EAT",
  },
];

// Full 25-variable list of the active v1 model (and stub for v2 draft)
const PCFG_VARIABLES_V1 = [
  { name: "member_count",                 weight: -0.077, transform: "identity",        group: "Composition" },
  { name: "share_children_under_15",      weight: -0.117, transform: "identity",        group: "Composition" },
  { name: "head_is_female",               weight: +0.038, transform: "present_as_one",  group: "Head" },
  { name: "head_edu_completed_primary",   weight: +0.099, transform: "present_as_one",  group: "Education" },
  { name: "head_edu_secondary",           weight: +0.154, transform: "present_as_one",  group: "Education" },
  { name: "head_edu_tertiary",            weight: +0.312, transform: "present_as_one",  group: "Education" },
  { name: "floor_tiles_terrazzo",         weight: +0.326, transform: "present_as_one",  group: "Dwelling" },
  { name: "floor_cement_or_brick",        weight: +0.130, transform: "present_as_one",  group: "Dwelling" },
  { name: "roof_metal_or_tile",           weight: +0.138, transform: "present_as_one",  group: "Dwelling" },
  { name: "wall_uncovered_adobe",         weight: +0.052, transform: "present_as_one",  group: "Dwelling" },
  { name: "wall_stone_lime_cement",       weight: +0.099, transform: "present_as_one",  group: "Dwelling" },
  { name: "wall_other_finished",          weight: +0.050, transform: "present_as_one",  group: "Dwelling" },
  { name: "rooms_per_capita",             weight: +0.292, transform: "identity",        group: "Dwelling" },
  { name: "electricity_for_lighting",     weight: +0.112, transform: "present_as_one",  group: "Utilities" },
  { name: "piped_water_to_premises",      weight: +0.075, transform: "present_as_one",  group: "Utilities" },
  { name: "lighting_kerosene",            weight: -0.034, transform: "present_as_one",  group: "Utilities" },
  { name: "open_defecation",              weight: -0.128, transform: "present_as_one",  group: "Sanitation" },
  { name: "owns_car_or_van",              weight: +0.294, transform: "present_as_one",  group: "Assets" },
  { name: "owns_television",              weight: +0.228, transform: "present_as_one",  group: "Assets" },
  { name: "owns_motorcycle",              weight: +0.213, transform: "present_as_one",  group: "Assets" },
  { name: "any_cellphone",                weight: +0.185, transform: "present_as_one",  group: "Assets" },
  { name: "owns_refrigerator",            weight: +0.157, transform: "present_as_one",  group: "Assets" },
  { name: "owns_computer",                weight: +0.141, transform: "present_as_one",  group: "Assets" },
  { name: "owns_radio",                   weight: +0.107, transform: "present_as_one",  group: "Assets" },
  { name: "is_renting",                   weight: +0.108, transform: "present_as_one",  group: "Tenure" },
];

const PCFG_TRANSFORMS = [
  { id: "identity",       label: "identity",       desc: "Pass-through — multiply value × weight" },
  { id: "present_as_one", label: "present_as_one", desc: "Binary — 1 if present, 0 otherwise" },
  { id: "log1p",          label: "log1p",          desc: "log(1 + value) — for asset counts" },
  { id: "zscore",         label: "zscore",         desc: "Standardised to dataset mean / σ" },
];

const STATUS_TONE = {
  draft: "quality",
  pending_approval: "update",
  active: "data",
  retired: "neutral",
};
const STATUS_LABEL = {
  draft: "Draft",
  pending_approval: "Pending approval",
  active: "Active",
  retired: "Retired",
};

/* ============================================================
   PCfgSection — small content shell
   ============================================================ */
const PCfgSection = ({ title, sub, action, children }) => (
  <div className="card mt-4" style={{ padding: 0 }}>
    <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <div>
        <h3 className="t-h3" style={{ margin: 0 }}>{title}</h3>
        {sub && <div className="t-cap mt-1">{sub}</div>}
      </div>
      <div style={{ flex: 1 }}/>
      {action}
    </div>
    {children}
  </div>
);

/* ============================================================
   PMT Configuration
   ============================================================ */
const PmtConfigurationScreen = ({ onBack }) => {
  // Which version is selected in the right pane.
  const [selectedId, setSelectedId] = useStatePCfg(PCFG_VERSIONS[0].id);
  const [tab, setTab] = useStatePCfg("variables");
  const [varSearch, setVarSearch] = useStatePCfg("");
  const [varGroupFilter, setVarGroupFilter] = useStatePCfg("All");

  const selected = useMemoPCfg(
    () => PCFG_VERSIONS.find(v => v.id === selectedId) || PCFG_VERSIONS[0],
    [selectedId]
  );
  const variables = selected.version === 1 ? PCFG_VARIABLES_V1
    : selected.version === 2 ? PCFG_VARIABLES_V1 // would diff in real data; use same for sample
    : PCFG_VARIABLES_V1.slice(0, 22);

  const filteredVariables = useMemoPCfg(() => {
    const q = varSearch.trim().toLowerCase();
    return variables.filter(v => {
      if (varGroupFilter !== "All" && v.group !== varGroupFilter) return false;
      if (q && !v.name.includes(q)) return false;
      return true;
    });
  }, [variables, varSearch, varGroupFilter]);

  const groups = [...new Set(variables.map(v => v.group))];

  const isEditable = selected.status === "draft";
  const totalAbsWeight = variables.reduce((a, v) => a + Math.abs(v.weight), 0);

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · PMT · configuration"
        title="PMT Configuration"
        sub="Model registry — draft, calibrate, and activate PMT model versions. Activation requires dual approval (AC-PMT-MODEL-VERSION)."
        right={<>
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to dashboard</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> New model version</button>
        </>}
      />

      {/* Two-pane: version list + version editor */}
      <div className="grid" style={{ gridTemplateColumns: '320px 1fr', gap: 16 }}>
        {/* Version registry */}
        <div className="card" style={{ padding: 0, alignSelf: 'start' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong className="t-bodysm">Model versions</strong>
            <div className="t-cap">3 in registry · {PCFG_VERSIONS.filter(v => v.status === 'active').length} active</div>
          </div>
          {PCFG_VERSIONS.map(v => {
            const active = v.id === selectedId;
            return (
              <div key={v.id}
                onClick={() => setSelectedId(v.id)}
                style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--neutral-200)',
                  borderLeft: active ? '3px solid var(--accent-eligibility)' : '3px solid transparent',
                  background: active ? 'var(--neutral-50)' : 'transparent',
                  cursor: 'pointer',
                }}>
                <div className="row gap-2" style={{ alignItems: 'baseline' }}>
                  <strong style={{ fontSize: 15 }}>v{v.version}</strong>
                  <Chip size="sm" tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Chip>
                  {v.status === 'active' && <Icon name="check" size={12} color="var(--accent-data)"/>}
                </div>
                <div className="t-cap mt-1" style={{ color: 'var(--neutral-600)' }}>{v.description.slice(0, 60)}{v.description.length > 60 ? '…' : ''}</div>
                <div className="t-cap mt-2 row gap-2">
                  <span>{v.variablesCount} vars</span>
                  {v.validationRSquared && <span>· R² {v.validationRSquared.toFixed(3)}</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* Version editor */}
        <div>
          {/* Version header card */}
          <div className="card" style={{ padding: 0 }}>
            <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '64px 1fr auto', gap: 16, alignItems: 'flex-start' }}>
              <div style={{
                width: 64, height: 64, borderRadius: 8,
                background: 'var(--accent-eligibility-bg, var(--neutral-100))',
                color: 'var(--accent-eligibility)',
                display: 'grid', placeItems: 'center',
                fontSize: 22, fontWeight: 700,
              }}>v{selected.version}</div>
              <div style={{ minWidth: 0 }}>
                <div className="row gap-2" style={{ marginBottom: 4, alignItems: 'baseline' }}>
                  <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>PMT v{selected.version}</h2>
                  <Chip tone={STATUS_TONE[selected.status]}>{STATUS_LABEL[selected.status]}</Chip>
                </div>
                <div className="t-bodysm" style={{ color: 'var(--neutral-700)' }}>{selected.description}</div>
                <div className="t-cap mt-2">
                  Author: <strong>{selected.author}</strong>
                  {selected.approvedBy && <> · Approved by <strong>{selected.approvedBy}</strong> on {selected.approvedAt}</>}
                </div>
              </div>
              <div className="row gap-2">
                {selected.status === 'draft' && <>
                  <button className="btn"><Icon name="copy" size={13}/> Clone</button>
                  <button className="btn btn-primary"><Icon name="upload" size={13}/> Submit for approval</button>
                </>}
                {selected.status === 'pending_approval' && <>
                  <button className="btn"><Icon name="x" size={13}/> Reject</button>
                  <button className="btn btn-primary"><Icon name="check" size={13}/> Approve & activate</button>
                </>}
                {selected.status === 'active' && <>
                  <button className="btn"><Icon name="copy" size={13}/> Clone as draft</button>
                </>}
                {selected.status === 'retired' && <>
                  <button className="btn"><Icon name="copy" size={13}/> Clone as draft</button>
                </>}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', borderTop: '1px solid var(--neutral-200)' }}>
              {[
                ['Variables',          selected.variablesCount],
                ['Intercept',          selected.intercept.toFixed(4)],
                ['Validation R²',      selected.validationRSquared.toFixed(3)],
                ['Calibration year',   selected.calibrationYearEnd],
              ].map(([k, v], i) => (
                <div key={k} style={{
                  padding: '10px 16px',
                  borderRight: i < 3 ? '1px solid var(--neutral-200)' : 0,
                }}>
                  <div className="t-cap">{k}</div>
                  <div className="t-num" style={{ fontSize: 18, fontWeight: 600, marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>

            {selected.status === 'draft' && (
              <div className="tint-update" style={{
                padding: '10px 20px',
                borderTop: '1px solid var(--neutral-200)',
                borderLeft: '3px solid var(--accent-update)',
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <Icon name="info" size={13} color="var(--accent-update)"/>
                <span className="t-bodysm">
                  This draft is editable. <strong>Submit for approval</strong> to lock variables/weights and start the dual-approval workflow.
                </span>
              </div>
            )}
            {selected.status === 'active' && (
              <div className="tint-update" style={{
                padding: '10px 20px',
                borderTop: '1px solid var(--neutral-200)',
                borderLeft: '3px solid var(--accent-data)',
                background: 'var(--accent-data-bg, var(--neutral-50))',
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <Icon name="check" size={13} color="var(--accent-data)"/>
                <span className="t-bodysm">
                  Active model — read-only. To change variables or weights, clone as draft.
                </span>
              </div>
            )}
          </div>

          {/* Tabs */}
          <div role="tablist" style={{
            display: 'flex', gap: 0,
            borderBottom: '1px solid var(--neutral-300)',
            marginTop: 16, flexWrap: 'wrap',
          }}>
            {[
              { id: 'variables', label: 'Variables & weights' },
              { id: 'bands',     label: 'Bands & strategy' },
              { id: 'calib',     label: 'Calibration' },
              { id: 'workflow',  label: 'Approval & lifecycle' },
              { id: 'sim',       label: 'Simulator' },
            ].map(t => {
              const active = t.id === tab;
              return (
                <button key={t.id} onClick={() => setTab(t.id)} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '10px 16px', border: 0, marginBottom: -1,
                  borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
                  background: 'transparent', cursor: 'pointer',
                  color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
                  fontWeight: active ? 600 : 500, fontSize: 13.5,
                }}>{t.label}</button>
              );
            })}
          </div>

          {/* Tab content */}
          {tab === 'variables' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 0 }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div className="search" style={{ maxWidth: 300, height: 32, background: 'var(--neutral-0)' }}>
                  <Icon name="search" size={14} color="var(--neutral-500)"/>
                  <input value={varSearch} onChange={e => setVarSearch(e.target.value)} placeholder="Search variable name…"/>
                </div>
                <select className="field-select" value={varGroupFilter} onChange={e => setVarGroupFilter(e.target.value)} style={{ height: 32, width: 'auto', minWidth: 140 }}>
                  <option value="All">All groups</option>
                  {groups.map(g => <option key={g}>{g}</option>)}
                </select>
                <span className="t-cap">{filteredVariables.length} of {variables.length}</span>
                <div style={{ flex: 1 }}/>
                {isEditable && <>
                  <button className="btn btn-sm"><Icon name="upload" size={12}/> Import CSV</button>
                  <button className="btn btn-sm"><Icon name="plus" size={12}/> Add variable</button>
                </>}
              </div>
              <table className="tbl" style={{ boxShadow: 'none' }}>
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Group</th>
                    <th>Transform</th>
                    <th style={{ textAlign: 'right' }}>Weight (β)</th>
                    <th style={{ width: '20%' }}>Magnitude</th>
                    {isEditable && <th className="col-actions"></th>}
                  </tr>
                </thead>
                <tbody>
                  {filteredVariables.map(v => {
                    const max = Math.max(...variables.map(x => Math.abs(x.weight)));
                    const isNeg = v.weight < 0;
                    return (
                      <tr key={v.name}>
                        <td className="t-mono" style={{ fontSize: 12.5 }}>{v.name}</td>
                        <td><Chip size="sm">{v.group}</Chip></td>
                        <td className="t-mono t-cap">{v.transform}</td>
                        <td className="t-num t-bodysm" style={{ textAlign: 'right', fontWeight: 600, color: isNeg ? 'var(--accent-quality)' : 'var(--accent-data)' }}>
                          {v.weight >= 0 ? '+' : ''}{v.weight.toFixed(3)}
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <div style={{
                              flex: 1, height: 6, background: 'var(--neutral-100)', borderRadius: 3, overflow: 'hidden',
                              position: 'relative',
                            }}>
                              <div style={{
                                position: 'absolute', left: '50%',
                                width: '1px', height: '100%', background: 'var(--neutral-300)',
                              }}/>
                              <div style={{
                                position: 'absolute',
                                left: isNeg ? `${50 - (Math.abs(v.weight)/max)*50}%` : '50%',
                                width: `${(Math.abs(v.weight)/max)*50}%`, height: '100%',
                                background: isNeg ? 'var(--accent-quality)' : 'var(--accent-data)',
                              }}/>
                            </div>
                          </div>
                        </td>
                        {isEditable && <td className="col-actions">
                          <button className="icon-btn" title="Edit"><Icon name="edit" size={12}/></button>
                        </td>}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{
                padding: '12px 16px',
                borderTop: '1px solid var(--neutral-200)',
                background: 'var(--neutral-50)',
                display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
              }}>
                <span className="t-cap">Intercept</span>
                <span className="t-mono" style={{ fontWeight: 600 }}>{selected.intercept.toFixed(4)}</span>
                <span style={{ width: 1, height: 16, background: 'var(--neutral-200)' }}/>
                <span className="t-cap">Σ |β|</span>
                <span className="t-num" style={{ fontWeight: 600 }}>{totalAbsWeight.toFixed(3)}</span>
                <div style={{ flex: 1 }}/>
                <span className="t-cap">
                  Engine: <span className="t-mono">apps.pmt.engine.compute_pmt</span> ·
                  Feature evaluator: <span className="t-mono">apps.pmt.feature_evaluator</span>
                </span>
              </div>
            </div>
          )}

          {tab === 'bands' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
              <div className="row gap-3 mb-3" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div style={{ flex: '1 1 320px' }}>
                  <strong>Band strategy</strong>
                  <div className="t-cap mt-1">
                    How a household's <code className="t-mono">score</code> maps to a band.
                    Switching strategies requires resubmitting the model for approval.
                  </div>
                </div>
                <div className="row gap-2">
                  {[
                    ['threshold',  'Fixed score thresholds', 'Cut on score values declared on the model'],
                    ['percentile', 'Population percentiles', 'Cut on population percentile ranks; thresholds recompute daily'],
                  ].map(([id, label, desc]) => {
                    const active = selected.bandStrategy === id;
                    return (
                      <div key={id} style={{
                        padding: 12, borderRadius: 6, width: 220,
                        border: `2px solid ${active ? 'var(--accent-eligibility)' : 'var(--neutral-200)'}`,
                        background: active ? 'var(--accent-eligibility-bg, var(--neutral-50))' : 'var(--neutral-0)',
                        cursor: isEditable ? 'pointer' : 'default',
                        opacity: isEditable || active ? 1 : 0.7,
                      }}>
                        <div className="row gap-2" style={{ alignItems: 'center' }}>
                          <span style={{
                            width: 14, height: 14, borderRadius: '50%',
                            border: `2px solid ${active ? 'var(--accent-eligibility)' : 'var(--neutral-400)'}`,
                            background: active ? 'var(--accent-eligibility)' : 'transparent',
                          }}/>
                          <strong className="t-bodysm">{label}</strong>
                        </div>
                        <div className="t-cap mt-2">{desc}</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div style={{
                marginTop: 18, padding: 16, borderRadius: 6,
                border: '1px solid var(--neutral-200)',
              }}>
                <div className="row gap-2 mb-3">
                  <strong>Band cutoffs</strong>
                  <Chip size="sm" tone="data">{selected.bandStrategy}</Chip>
                  <span className="t-cap">— {selected.bandStrategy === 'percentile' ? 'population percentile ranks (0–100)' : 'score thresholds'}</span>
                </div>
                <table className="tbl" style={{ boxShadow: 'none' }}>
                  <thead><tr><th>Band</th><th>{selected.bandStrategy === 'percentile' ? 'Upper percentile rank' : 'Upper score threshold'}</th><th>Daily empirical threshold</th><th>Notes</th></tr></thead>
                  <tbody>
                    {Object.entries(selected.bandCutoffs).map(([band, cutoff]) => (
                      <tr key={band}>
                        <td><BandChip band={band}/></td>
                        <td className="t-num">{cutoff}{selected.bandStrategy === 'percentile' ? '%' : ''}</td>
                        <td className="t-mono t-bodysm">
                          {selected.status === 'active' && PMT_ACTIVE.thresholdsLatest[band]
                            ? `≤ ${PMT_ACTIVE.thresholdsLatest[band].toFixed(3)}`
                            : <span className="muted">—</span>}
                        </td>
                        <td className="t-cap">
                          {band === 'extreme_poverty' && 'MGLSD floor — SCG eligibility'}
                          {band === 'poverty'         && 'OPM-PDM primary cohort'}
                          {band === 'vulnerable'      && 'Programme co-targeting cohort'}
                          {band === 'not_poor'        && 'Default — excluded from targeted programmes'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {selected.bandStrategy === 'percentile' && (
                  <div className="tint-update" style={{
                    marginTop: 14, padding: 12, borderRadius: 4,
                    borderLeft: '3px solid var(--accent-update)',
                  }}>
                    <div className="row gap-2" style={{ marginBottom: 4 }}>
                      <Icon name="info" size={13} color="var(--accent-update)"/>
                      <strong className="t-bodysm">Percentile band thresholds</strong>
                    </div>
                    <div className="t-bodysm muted">
                      The score-thresholds shown in the third column are recomputed daily by{' '}
                      <span className="t-mono">apps.pmt.tasks.recompute_band_thresholds_task</span>{' '}
                      against the full PMTResult population. The cutoffs above are policy values — the
                      empirical thresholds drift as the registry grows.
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === 'calib' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20, display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
              <div>
                <h4 className="t-h3" style={{ margin: '0 0 10px' }}>Calibration provenance</h4>
                <table className="tbl" style={{ boxShadow: 'none' }}>
                  <tbody>
                    <tr><td className="muted" style={{ width: 200 }}>Calibration dataset</td><td>{selected.calibrationDataset}</td></tr>
                    <tr><td className="muted">Latest year of dataset</td><td className="t-num">{selected.calibrationYearEnd}</td></tr>
                    <tr><td className="muted">Sample size</td><td className="t-num">{(34091).toLocaleString()} households</td></tr>
                    <tr><td className="muted">Validation R²</td><td className="t-num">{selected.validationRSquared.toFixed(3)}</td></tr>
                    <tr><td className="muted">Mean absolute error</td><td className="t-num">0.412</td></tr>
                    <tr><td className="muted">Targeting accuracy (bottom-30%)</td><td className="t-num">82.4%</td></tr>
                    <tr><td className="muted">Calibration method</td><td>OLS · ADR-0025 DSL</td></tr>
                  </tbody>
                </table>
              </div>
              <div className="tint-update" style={{
                padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)',
                alignSelf: 'start',
              }}>
                <div className="row gap-2" style={{ marginBottom: 6 }}>
                  <Icon name="info" size={13} color="var(--accent-update)"/>
                  <strong className="t-bodysm">Recalibration cadence (ADR-0023)</strong>
                </div>
                <div className="t-bodysm muted" style={{ lineHeight: 1.55 }}>
                  PMT models recalibrate every 3 years after the latest year of the source dataset.
                  Calibration year-end <strong>{selected.calibrationYearEnd}</strong> means recalibration is due in{' '}
                  <strong>{2027 - selected.calibrationYearEnd} year{2027 - selected.calibrationYearEnd === 1 ? '' : 's'}</strong>{' '}
                  ({selected.calibrationYearEnd + 3}).
                </div>
                <div style={{
                  marginTop: 12, padding: '8px 12px',
                  background: 'var(--neutral-0)', borderRadius: 4,
                  border: '1px solid var(--neutral-200)',
                  fontSize: 12, fontFamily: 'var(--font-mono)',
                }}>
                  Trigger: <span style={{ color: 'var(--accent-quality)' }}>year_now - calibration_year_end ≥ 3</span>
                </div>
              </div>
            </div>
          )}

          {tab === 'workflow' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
              <h4 className="t-h3" style={{ margin: '0 0 14px' }}>Approval & lifecycle</h4>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '14px 0', overflowX: 'auto',
              }}>
                {[
                  { id: 'draft',            label: 'Draft',            icon: 'edit'  },
                  { id: 'pending_approval', label: 'Pending approval', icon: 'clock' },
                  { id: 'active',           label: 'Active',           icon: 'check' },
                  { id: 'retired',          label: 'Retired',          icon: 'archive' },
                ].map((s, i, arr) => {
                  const reached = ['draft','pending_approval','active','retired'].indexOf(selected.status) >= i;
                  const current = selected.status === s.id;
                  return (
                    <React.Fragment key={s.id}>
                      <div style={{
                        padding: '10px 14px',
                        borderRadius: 6,
                        border: current ? '2px solid var(--primary-900)' : `1px solid ${reached ? 'var(--accent-data)' : 'var(--neutral-300)'}`,
                        background: current ? 'var(--primary-100)' : reached ? 'var(--accent-data-bg, var(--neutral-50))' : 'var(--neutral-0)',
                        color: current ? 'var(--primary-900)' : reached ? 'var(--accent-data)' : 'var(--neutral-500)',
                        fontWeight: current ? 600 : 500, fontSize: 13,
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                        flex: '0 0 auto',
                      }}>
                        <Icon name={reached && !current ? 'check' : s.icon} size={12}/>
                        {s.label}
                      </div>
                      {i < arr.length - 1 && (
                        <div style={{ flex: 1, height: 1, minWidth: 24, background: reached ? 'var(--accent-data)' : 'var(--neutral-300)' }}/>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>

              {/* Dual approval chain */}
              <div className="mt-4">
                <strong className="t-bodysm">Dual approval chain (AC-PMT-MODEL-VERSION)</strong>
                <div className="row gap-3 mt-3" style={{ flexWrap: 'wrap' }}>
                  {[
                    { step: 1, role: 'Author', who: selected.author, status: 'signed', at: selected.createdAt },
                    { step: 2, role: 'MGLSD Data Steward', who: selected.status !== 'draft' ? 'Statistics review · MGLSD' : 'awaiting submission', status: selected.status === 'draft' ? 'pending' : 'signed', at: selected.approvedAt },
                    { step: 3, role: 'Director General · UBOS', who: selected.approvedBy || 'awaiting steward sign-off', status: selected.status === 'active' || selected.status === 'retired' ? 'signed' : 'pending', at: selected.approvedAt },
                  ].map(s => (
                    <div key={s.step} style={{
                      flex: '1 1 240px', minWidth: 220,
                      padding: 14, borderRadius: 6,
                      border: '1px solid var(--neutral-200)',
                      borderLeft: `3px solid ${s.status === 'signed' ? 'var(--accent-data)' : 'var(--accent-quality)'}`,
                      background: 'var(--neutral-0)',
                    }}>
                      <div className="row gap-2" style={{ marginBottom: 6 }}>
                        <div style={{
                          width: 22, height: 22, borderRadius: '50%',
                          background: s.status === 'signed' ? 'var(--accent-data-bg, var(--neutral-100))' : 'var(--neutral-100)',
                          color: s.status === 'signed' ? 'var(--accent-data)' : 'var(--neutral-500)',
                          display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 600,
                        }}>{s.step}</div>
                        {s.status === 'signed'
                          ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> signed</Chip>
                          : <Chip size="sm" tone="quality"><Icon name="clock" size={10}/> pending</Chip>}
                      </div>
                      <div className="t-bodysm" style={{ fontWeight: 600 }}>{s.role}</div>
                      <div className="t-cap mt-1">{s.who}</div>
                      {s.at && <div className="t-cap mt-1">{s.at}</div>}
                    </div>
                  ))}
                </div>
              </div>

              <div className="tint-update mt-4" style={{
                padding: 12, borderRadius: 4, borderLeft: '3px solid var(--accent-update)',
              }}>
                <div className="row gap-2" style={{ marginBottom: 4 }}>
                  <Icon name="shield" size={13} color="var(--accent-update)"/>
                  <strong className="t-bodysm">No self-approval (AC-PMT-NO-SELF-APPROVE)</strong>
                </div>
                <div className="t-bodysm muted">
                  The model's author cannot sign off the steward or director steps. Activation atomically
                  retires the previous active version and writes an audit row (<span className="t-mono">apps.pmt.services.activate_model_version</span>).
                </div>
              </div>
            </div>
          )}

          {tab === 'sim' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
              <h4 className="t-h3" style={{ margin: '0 0 4px' }}>Score simulator</h4>
              <div className="t-cap mb-3">Plug in a household input set, see the score + band this model would assign.</div>

              <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'flex-start' }}>
                <div style={{
                  padding: 16, borderRadius: 6, border: '1px solid var(--neutral-200)',
                  background: 'var(--neutral-50)',
                }}>
                  <strong className="t-bodysm">Household inputs</strong>
                  <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {[
                      ['Member count',          '6'],
                      ['Rooms',                 '2'],
                      ['Floor material',        'Earth'],
                      ['Roof material',         'Metal'],
                      ['Has electricity',       'No'],
                      ['Owns motorcycle',       'No'],
                      ['Owns television',       'No'],
                      ['Has cellphone',         'Yes'],
                      ['Head education',        'Primary completed'],
                      ['Open defecation',       'Yes'],
                    ].map(([k, v]) => (
                      <label key={k} style={{ display: 'flex', flexDirection: 'column', fontSize: 12, gap: 4 }}>
                        <span className="muted">{k}</span>
                        <input className="field-input" defaultValue={v} style={{ padding: '4px 6px', height: 28, fontSize: 13 }}/>
                      </label>
                    ))}
                  </div>
                  <button className="btn btn-primary mt-3"><Icon name="play" size={13}/> Recompute</button>
                </div>

                <div style={{
                  padding: 16, borderRadius: 6,
                  border: '1px solid var(--neutral-200)',
                  borderLeft: '3px solid var(--accent-eligibility)',
                  background: 'var(--neutral-0)',
                }}>
                  <div className="t-cap" style={{ color: 'var(--accent-eligibility)', fontWeight: 600 }}>SIMULATED SCORE</div>
                  <div style={{ fontSize: 36, fontWeight: 700, marginTop: 6 }}>2.84</div>
                  <div className="row gap-2 mt-2">
                    <BandChip band="extreme_poverty"/>
                    <span className="t-cap">band at percentile 8.2%</span>
                  </div>
                  <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--neutral-50)', borderRadius: 4 }}>
                    <div className="t-cap">Contributing variables (top 5)</div>
                    {[
                      ['open_defecation',         -0.128, -0.128],
                      ['share_children_under_15', -0.117, -0.094],
                      ['rooms_per_capita',        +0.292, +0.097],
                      ['head_edu_completed_primary', +0.099, +0.099],
                      ['any_cellphone',           +0.185, +0.185],
                    ].map(([n, w, c]) => (
                      <div key={n} className="row gap-2 mt-2" style={{ alignItems: 'baseline' }}>
                        <span className="t-mono" style={{ fontSize: 12, flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{n}</span>
                        <span className="t-cap">β {w >= 0 ? '+' : ''}{w.toFixed(3)}</span>
                        <Chip size="sm" tone={c >= 0 ? 'data' : 'quality'}>{c >= 0 ? '+' : ''}{c.toFixed(3)}</Chip>
                      </div>
                    ))}
                  </div>
                  <div className="t-cap mt-3">Simulator is sandboxed — it does not write a PMTResult row.</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="t-cap mt-4" style={{ textAlign: 'center' }}>
        Configuration changes are audit-logged. Activation atomically retires the prior active version
        and queues a population-wide rescore (<span className="t-mono">apps.pmt.tasks</span>).
      </div>
    </div>
  );
};

Object.assign(window, { PmtConfigurationScreen, PCFG_VERSIONS });
