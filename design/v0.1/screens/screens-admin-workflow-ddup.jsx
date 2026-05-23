/* global React, Icon, Chip, PageHeader, KPI, useApi */
// NSR MIS — Admin · Workflow · DDUP Model
// =========================================================
// Versioned deduplication model + live MatchPair queue.
//
// Maps to:
//   apps.ddup.models.DdupModelVersion  (versioned: tier 1 deterministic,
//                                       tier 3 probabilistic weights + thresholds)
//   apps.ddup.models.MatchPair         (pending / merged / rejected / on_hold / cross_household)
//   apps.ddup.models.MergeDecision     (immutable decision; 30-day un-merge window)

const { useState: useStateDDUP } = React;

const DDUP_VERSIONS = [
  {
    id: "01HXM2N8KP9Q3RFB7K6FZRWS01",
    version: 3, status: "draft",
    description: "v3 — adds phone-number tier with Soundex normalisation. Awaiting calibration.",
    author: "Bahati E. · DDUP team",
    approvedBy: null, approvedAt: null, effectiveFrom: null,
    updatedAt: "20 May 2026",
    config: { autoMergeThreshold: 0.92, tier1: true, tier2: true, tier3: true, tier3Fields: ["full_name","dob","sex","village_code","phone"] },
    autoMergeCount: 0, manualMergeCount: 0, autoReverseRate: null,
  },
  {
    id: "01HX91KPNRMQ0F2B7K6FZRWS50",
    version: 2, status: "active",
    description: "v2 — relaxed name-similarity threshold to 0.84 after WG-SS roll-out; auto-reverse rate dropped from 2.1% to 0.8%.",
    author: "Bahati E. · DDUP team",
    approvedBy: "Director General · UBOS", approvedAt: "08 Mar 2026", effectiveFrom: "12 Mar 2026",
    updatedAt: "12 Mar 2026",
    config: { autoMergeThreshold: 0.90, tier1: true, tier2: false, tier3: true, tier3Fields: ["full_name","dob","sex","village_code"] },
    autoMergeCount: 18421, manualMergeCount: 4218, autoReverseRate: 0.008,
  },
  {
    id: "01HX2P0Q4N1RFB7K6FZRWS02",
    version: 1, status: "retired",
    description: "v1 initial — deterministic NIN tier only.",
    author: "DDUP team",
    approvedBy: "Director General · UBOS", approvedAt: "02 Jan 2026", effectiveFrom: "04 Jan 2026",
    updatedAt: "12 Mar 2026",
    config: { autoMergeThreshold: 1.0, tier1: true, tier2: false, tier3: false, tier3Fields: [] },
    autoMergeCount: 3128, manualMergeCount: 891, autoReverseRate: 0.021,
  },
];

const DDUP_QUEUE_STATS = {
  pending: 412, mergedThisWeek: 891, rejectedThisWeek: 218, onHold: 38, crossHousehold: 121,
  autoMergedToday: 47, manualMergedToday: 23,
};

const DDUP_RECENT_PAIRS = [
  { id: "01HXR9P2K7N6FB7K6FZRWS01", type:"member", a:"Lokol Naume",        b:"Lokol Naome",        tier:3, score:0.94, status:"pending",  ageHours:2,  reason:"name + village + DoB" },
  { id: "01HXR9P2K7N6FB7K6FZRWS02", type:"member", a:"Mukasa Patrick",     b:"Mukasa P.",          tier:1, score:1.00, status:"pending",  ageHours:4,  reason:"NIN match (CM75081401RSTU)" },
  { id: "01HXR9P2K7N6FB7K6FZRWS03", type:"member", a:"Acheng Rose",        b:"Acheng Rose",        tier:2, score:0.88, status:"on_hold",  ageHours:18, reason:"phone match · names match" },
  { id: "01HXR9P2K7N6FB7K6FZRWS04", type:"household", a:"01HXP02CN4…",     b:"01HXP02CN5…",        tier:3, score:0.86, status:"cross_household", ageHours:22, reason:"head NIN match · different villages" },
  { id: "01HXR9P2K7N6FB7K6FZRWS05", type:"member", a:"Apio Joyce",         b:"Apio Joice",         tier:3, score:0.93, status:"merged",   ageHours:6,  reason:"name + DoB + village" },
];

const DDUP_STATUS_TONE = { draft: "quality", pending_approval: "update", active: "data", retired: "neutral" };
const DDUP_PAIR_STATUS_TONE = { pending:"quality", merged:"data", rejected:"danger", on_hold:"update", cross_household:"programme" };

const AdminDdupScreen = () => {
  const [tab, setTab] = useStateDDUP("versions");
  const [selectedId, setSelectedId] = useStateDDUP(DDUP_VERSIONS[1].id);
  const selected = DDUP_VERSIONS.find(v => v.id === selectedId);

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · WORKFLOW · DDUP"
        title="Deduplication & merge"
        sub="3-tier match strategy — deterministic NIN, phone-Soundex, probabilistic composite. Auto-merge gates on the active model's confidence threshold."
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export decisions</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> New model version</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Pending pairs" value={DDUP_QUEUE_STATS.pending} foot={`${DDUP_QUEUE_STATS.onHold} on hold · ${DDUP_QUEUE_STATS.crossHousehold} cross-household`} trend="up" trendValue="+34 today"/>
        <KPI title="Auto-merge today" value={DDUP_QUEUE_STATS.autoMergedToday} foot={`${DDUP_QUEUE_STATS.manualMergedToday} manual merges`}/>
        <KPI title="Active threshold" value={selected.config.autoMergeThreshold.toFixed(2)} foot="Score ≥ this → auto-merge · v2"/>
        <KPI title="Auto-reverse rate" value={`${(DDUP_VERSIONS[1].autoReverseRate * 100).toFixed(2)}%`} foot="of auto-merges reversed within 30d window" trend="flat"/>
      </div>

      {/* Sub-tabs: Model versions · Match queue · Decisions */}
      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid var(--neutral-300)', marginTop: 24, flexWrap: 'wrap' }}>
        {[
          { id: "versions", label: "Model versions" },
          { id: "queue",    label: `Match queue (${DDUP_QUEUE_STATS.pending})` },
          { id: "decisions",label: "Decisions" },
        ].map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: '10px 16px', border: 0, background: 'transparent', cursor: 'pointer',
              borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
              marginBottom: -1,
              color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
              fontWeight: active ? 600 : 500, fontSize: 13.5,
            }}>{t.label}</button>
          );
        })}
      </div>

      {tab === "versions" && (
        <div className="grid" style={{ gridTemplateColumns: '300px 1fr', gap: 16, marginTop: 16 }}>
          <div className="card" style={{ padding: 0, alignSelf: 'start' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--neutral-200)' }}>
              <strong className="t-bodysm">Versions</strong>
              <div className="t-cap">{DDUP_VERSIONS.length} in registry</div>
            </div>
            {DDUP_VERSIONS.map(v => {
              const active = v.id === selectedId;
              return (
                <div key={v.id} onClick={() => setSelectedId(v.id)} style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--neutral-200)',
                  borderLeft: active ? '3px solid var(--accent-system)' : '3px solid transparent',
                  background: active ? 'var(--neutral-50)' : 'transparent', cursor: 'pointer',
                }}>
                  <div className="row gap-2" style={{ alignItems: 'baseline' }}>
                    <strong>v{v.version}</strong>
                    <Chip size="sm" tone={DDUP_STATUS_TONE[v.status]}>{v.status}</Chip>
                  </div>
                  <div className="t-cap mt-1">{v.description.slice(0, 56)}…</div>
                </div>
              );
            })}
          </div>

          <div>
            <div className="card" style={{ padding: 0 }}>
              <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '64px 1fr auto', gap: 16, alignItems: 'flex-start' }}>
                <div style={{
                  width: 64, height: 64, borderRadius: 8,
                  background: 'var(--accent-system-bg, var(--neutral-100))',
                  color: 'var(--accent-system)',
                  display: 'grid', placeItems: 'center',
                  fontSize: 22, fontWeight: 700,
                }}>v{selected.version}</div>
                <div>
                  <div className="row gap-2" style={{ alignItems: 'baseline' }}>
                    <h2 style={{ margin: 0, fontSize: 20 }}>DDUP v{selected.version}</h2>
                    <Chip tone={DDUP_STATUS_TONE[selected.status]}>{selected.status.replace("_", " ")}</Chip>
                  </div>
                  <div className="t-bodysm mt-1">{selected.description}</div>
                  <div className="t-cap mt-2">Author: <strong>{selected.author}</strong>{selected.approvedBy && <> · Approved by <strong>{selected.approvedBy}</strong> on {selected.approvedAt}</>}</div>
                </div>
                <div className="row gap-2">
                  {selected.status === "draft" && <>
                    <button className="btn"><Icon name="copy" size={13}/> Clone</button>
                    <button className="btn btn-primary"><Icon name="upload" size={13}/> Submit for approval</button>
                  </>}
                  {selected.status === "active" && <button className="btn"><Icon name="copy" size={13}/> Clone as draft</button>}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', borderTop: '1px solid var(--neutral-200)' }}>
                <Stat k="Auto-merge threshold" v={selected.config.autoMergeThreshold.toFixed(2)} sub="composite score cut" first/>
                <Stat k="Auto-merges" v={selected.autoMergeCount.toLocaleString()} sub="tier-3 confident"/>
                <Stat k="Manual merges" v={selected.manualMergeCount.toLocaleString()} sub="operator decisions"/>
                <Stat k="Auto-reverse rate" v={selected.autoReverseRate !== null ? `${(selected.autoReverseRate*100).toFixed(2)}%` : '—'} sub="reversed within 30d window" last/>
              </div>
            </div>

            {/* Tier configuration */}
            <div className="card mt-4" style={{ padding: 0 }}>
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)' }}>
                <strong>Tier configuration</strong>
                <div className="t-cap">Each tier defines a match strategy. Composite score combines per-field similarity scores via the model weights.</div>
              </div>
              <table className="tbl" style={{ boxShadow: 'none' }}>
                <thead><tr><th>Tier</th><th>Strategy</th><th>Match basis</th><th>Threshold</th><th>Status</th></tr></thead>
                <tbody>
                  <tr>
                    <td><Chip tone="data">Tier 1</Chip></td>
                    <td className="t-bodysm">Deterministic</td>
                    <td className="t-mono t-bodysm">NIN exact match · same village</td>
                    <td className="t-mono">1.00</td>
                    <td>{selected.config.tier1 ? <Chip size="sm" tone="data">enabled</Chip> : <Chip size="sm">disabled</Chip>}</td>
                  </tr>
                  <tr>
                    <td><Chip tone="update">Tier 2</Chip></td>
                    <td className="t-bodysm">Deterministic-soft</td>
                    <td className="t-mono t-bodysm">Phone match (Soundex-normalised) · name similarity ≥ 0.85</td>
                    <td className="t-mono">0.85+</td>
                    <td>{selected.config.tier2 ? <Chip size="sm" tone="data">enabled</Chip> : <Chip size="sm">disabled</Chip>}</td>
                  </tr>
                  <tr>
                    <td><Chip tone="quality">Tier 3</Chip></td>
                    <td className="t-bodysm">Probabilistic composite</td>
                    <td className="t-mono t-bodysm">{selected.config.tier3Fields.join(' + ')}</td>
                    <td className="t-mono">{selected.config.autoMergeThreshold.toFixed(2)}+</td>
                    <td>{selected.config.tier3 ? <Chip size="sm" tone="data">enabled</Chip> : <Chip size="sm">disabled</Chip>}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="tint-update mt-4" style={{ padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)' }}>
              <div className="row gap-2" style={{ marginBottom: 4 }}>
                <Icon name="shield" size={13} color="var(--accent-update)"/>
                <strong className="t-bodysm">30-day un-merge window</strong>
              </div>
              <div className="t-bodysm muted">
                Every merge decision records a <span className="t-mono">pre_merge_snapshot</span> and a{' '}
                <span className="t-mono">reverse_window_until</span> 30 days out. Inside that window any operator with
                <span className="t-mono"> ddup.reverse_merge</span> scope can un-merge — the loser record is restored and any
                household head re-points fire. After 30 days the decision is permanent (DDUP-O-02 considers extending).
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === "queue" && (
        <div className="card mt-4" style={{ padding: 0 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', gap: 10, alignItems: 'center' }}>
            <strong>Pending match pairs</strong>
            <span className="t-cap">{DDUP_QUEUE_STATS.pending} awaiting decision</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm">Auto-resolve high-confidence</button>
          </div>
          <table className="tbl" style={{ boxShadow: 'none' }}>
            <thead>
              <tr><th>Pair ID</th><th>Type</th><th>Record A</th><th>Record B</th><th>Tier</th><th>Score</th><th>Reason</th><th>Status</th><th>Age</th><th className="col-actions"></th></tr>
            </thead>
            <tbody>
              {DDUP_RECENT_PAIRS.map(p => (
                <tr key={p.id} style={{ cursor: 'pointer' }}>
                  <td className="col-id">{p.id.slice(0, 16)}…</td>
                  <td><Chip size="sm">{p.type}</Chip></td>
                  <td className="t-bodysm">{p.a}</td>
                  <td className="t-bodysm">{p.b}</td>
                  <td><Chip size="sm" tone={p.tier === 1 ? 'data' : p.tier === 2 ? 'update' : 'quality'}>Tier {p.tier}</Chip></td>
                  <td className="t-num">{p.score.toFixed(2)}</td>
                  <td className="t-cap">{p.reason}</td>
                  <td><Chip size="sm" tone={DDUP_PAIR_STATUS_TONE[p.status]}>{p.status.replace('_',' ')}</Chip></td>
                  <td className="t-cap">{p.ageHours}h</td>
                  <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "decisions" && (
        <div className="card mt-4" style={{ padding: 20 }}>
          <strong>Decision history</strong>
          <div className="t-cap">Immutable — every merge, reject, hold, cross-household decision is recorded with the operator and reason. Reversals are tracked separately on the same row.</div>
          <div className="row gap-3 mt-3" style={{ flexWrap: 'wrap' }}>
            {[
              { label: "Merged this week",        value: DDUP_QUEUE_STATS.mergedThisWeek,    tone: "data" },
              { label: "Rejected this week",      value: DDUP_QUEUE_STATS.rejectedThisWeek,  tone: "danger" },
              { label: "On hold",                 value: DDUP_QUEUE_STATS.onHold,            tone: "quality" },
              { label: "Cross-household pending", value: DDUP_QUEUE_STATS.crossHousehold,    tone: "programme" },
            ].map(s => (
              <div key={s.label} style={{
                flex: '1 1 200px', padding: 14, borderRadius: 6,
                border: '1px solid var(--neutral-200)',
                borderLeft: `3px solid var(--accent-${s.tone})`,
                background: 'var(--neutral-0)',
              }}>
                <div className="t-cap">{s.label}</div>
                <div className="t-num" style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>{s.value.toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const Stat = ({ k, v, sub, first, last }) => (
  <div style={{ padding: '10px 16px', borderRight: last ? 0 : '1px solid var(--neutral-200)' }}>
    <div className="t-cap">{k}</div>
    <div className="t-num" style={{ fontSize: 18, fontWeight: 600, marginTop: 2 }}>{v}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

Object.assign(window, { AdminDdupScreen });
