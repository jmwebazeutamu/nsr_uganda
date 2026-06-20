/* global React, Icon, Chip, PageHeader, KPI, useApi */
// NSR MIS — Admin · Workflow · DDUP Model
// =========================================================
// Versioned deduplication model + live MatchPair queue.
//
// Live wiring (Cat 2.3): the KPI strip, the version list/detail,
// the match queue, and the Decisions-tab tiles all read off the
// admin-console workflow API. The hardcoded mock arrays below are
// the fallback for file:// previews where no Django session exists;
// when the API returns rows they take precedence.
//
// Maps to:
//   apps.ddup.models.DdupModelVersion  (versioned: tier 1 deterministic,
//                                       tier 3 probabilistic weights + thresholds)
//   apps.ddup.models.MatchPair         (pending / merged / rejected / on_hold / cross_household)
//   apps.ddup.models.MergeDecision     (immutable decision; 30-day un-merge window)
//
// Endpoints:
//   GET /api/v1/admin/workflow/ddup/versions/
//   GET /api/v1/admin/workflow/ddup/queue-stats/
//   GET /api/v1/admin/workflow/ddup/pairs/?status=pending

const { useState: useStateDDUP, useMemo: useMemoDDUP } = React;

// ────────────────────────────────────────────────────────────────
// Mock fallback — kept only so the design preview at file:// keeps
// rendering when no Django session is present. Anything that lands
// in the live API responses overrides these.
// ────────────────────────────────────────────────────────────────

const _DDUP_VERSIONS_MOCK = [
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
];

const _DDUP_QUEUE_STATS_MOCK = {
  pending: 0, mergedThisWeek: 0, rejectedThisWeek: 0, onHold: 0, crossHousehold: 0,
  autoMergedToday: 0, manualMergedToday: 0,
  activeThreshold: null, activeAutoReverseRate: null, activeVersion: null,
};

const _DDUP_RECENT_PAIRS_MOCK = [];

// ────────────────────────────────────────────────────────────────
// Projectors — API row → JSX view-model. Keep null-safe so a
// partial payload (e.g. a fresh draft with no merge decisions yet)
// doesn't crash the render tree.
// ────────────────────────────────────────────────────────────────

const _projectVersion = (r) => {
  if (!r) return null;
  const cfg = r.config || {};
  const tier3 = (cfg.tier3 && typeof cfg.tier3 === "object") ? cfg.tier3 : {};
  // Tier-enabled flags. The live config typically only carries
  // tier3.auto_merge_threshold; assume tier-1 always on (it's the
  // deterministic baseline) and read tier2/tier3 explicitly when
  // present.
  const tier1 = cfg.tier1 !== undefined ? !!cfg.tier1 : true;
  const tier2 = cfg.tier2 !== undefined ? !!cfg.tier2 : !!(cfg.tier2_phone_enabled);
  const tier3On = cfg.tier3 !== undefined
    ? (typeof cfg.tier3 === "boolean" ? cfg.tier3 : true)
    : (r.threshold != null);
  const tier3Fields = Array.isArray(tier3.fields)
    ? tier3.fields
    : (Array.isArray(cfg.tier3Fields) ? cfg.tier3Fields : []);
  const threshold = r.threshold != null
    ? Number(r.threshold)
    : (tier3.auto_merge_threshold != null ? Number(tier3.auto_merge_threshold) : 0);
  return {
    id: r.id,
    version: r.version,
    status: r.status,
    description: r.description || `v${r.version} — ${r.status}`,
    author: r.author || "",
    approvedBy: r.approved_by || null,
    approvedAt: r.approved_at ? String(r.approved_at).slice(0, 10) : null,
    effectiveFrom: r.effective_from ? String(r.effective_from).slice(0, 10) : null,
    updatedAt: r.created_at ? String(r.created_at).slice(0, 10) : null,
    config: { autoMergeThreshold: threshold, tier1, tier2, tier3: tier3On, tier3Fields },
    autoMergeCount: Number(r.auto_merge_count ?? 0),
    manualMergeCount: Number(r.manual_merge_count ?? 0),
    autoReverseRate: typeof r.auto_reverse_rate === "number" ? r.auto_reverse_rate : null,
  };
};

const _projectStats = (s) => {
  if (!s || typeof s !== "object") return null;
  // pairs_by_status is a {status: count} map; pending/on_hold/
  // cross_household are also surfaced at the top level by the new
  // endpoint, but the legacy map stays for back-compat.
  const byStatus = s.pairs_by_status || {};
  return {
    pending:           Number(s.pending ?? byStatus.pending ?? 0),
    onHold:            Number(s.on_hold ?? byStatus.on_hold ?? 0),
    crossHousehold:    Number(s.cross_household ?? byStatus.cross_household ?? 0),
    autoMergedToday:   Number(s.auto_merged_today ?? 0),
    manualMergedToday: Number(s.manual_merged_today ?? 0),
    mergedThisWeek:    Number(s.merged_this_week ?? 0),
    rejectedThisWeek:  Number(s.rejected_this_week ?? 0),
    activeThreshold:        typeof s.active_threshold === "number" ? s.active_threshold : null,
    activeAutoReverseRate:  typeof s.active_auto_reverse_rate === "number" ? s.active_auto_reverse_rate : null,
    activeVersion:          s.active_version ?? null,
  };
};

// Live MatchPair → table row. Composite score is a Decimal serialised
// to string sometimes — coerce. record_a/b are ULIDs not display
// strings (member name/household id lookup is a follow-up slice;
// today we show the truncated ULID).
const _projectPair = (r) => {
  if (!r) return null;
  const created = r.created_at ? Date.parse(r.created_at) : null;
  const ageHours = created
    ? Math.max(0, Math.floor((Date.now() - created) / 36e5))
    : null;
  return {
    id: r.id,
    type: r.record_type || "member",
    a: r.record_a_id ? `${String(r.record_a_id).slice(0, 12)}…` : "—",
    b: r.record_b_id ? `${String(r.record_b_id).slice(0, 12)}…` : "—",
    tier: Number(r.tier ?? 0),
    score: r.composite_score != null ? Number(r.composite_score) : 0,
    status: r.status || "pending",
    ageHours,
    reason: r.match_reason || "",
  };
};

const DDUP_STATUS_TONE = { draft: "quality", pending_approval: "update", active: "data", retired: "neutral" };
const DDUP_PAIR_STATUS_TONE = { pending:"quality", merged:"data", rejected:"danger", on_hold:"update", cross_household:"programme" };

const AdminDdupScreen = () => {
  // Live overlay — falls back to the mock arrays at file:// preview
  // time when useApi is unavailable or returns nothing. Errors
  // surface as the empty state below (no crash, just zero rows).
  const [versionsResp] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/workflow/ddup/versions/")
    : [null];
  const [statsResp] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/workflow/ddup/queue-stats/")
    : [null];
  const [pairsResp] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/workflow/ddup/pairs/?status=pending")
    : [null];

  const DDUP_VERSIONS = useMemoDDUP(() => {
    const live = Array.isArray(versionsResp?.results)
      ? versionsResp.results.map(_projectVersion).filter(Boolean)
      : null;
    return (live && live.length > 0) ? live : _DDUP_VERSIONS_MOCK;
  }, [versionsResp]);

  const DDUP_QUEUE_STATS = useMemoDDUP(() => {
    return _projectStats(statsResp) || _DDUP_QUEUE_STATS_MOCK;
  }, [statsResp]);

  const DDUP_RECENT_PAIRS = useMemoDDUP(() => {
    const live = Array.isArray(pairsResp?.results)
      ? pairsResp.results.map(_projectPair).filter(Boolean)
      : null;
    return (live && live.length > 0) ? live : _DDUP_RECENT_PAIRS_MOCK;
  }, [pairsResp]);

  const [tab, setTab] = useStateDDUP("versions");
  // Default-select the active version when the list resolves; fall
  // back to the first available if nothing's active.
  const defaultId = useMemoDDUP(() => {
    const active = DDUP_VERSIONS.find(v => v.status === "active");
    return (active || DDUP_VERSIONS[0])?.id || null;
  }, [DDUP_VERSIONS]);
  const [selectedId, setSelectedId] = useStateDDUP(defaultId);
  const selected = DDUP_VERSIONS.find(v => v.id === selectedId)
    || DDUP_VERSIONS.find(v => v.id === defaultId)
    || DDUP_VERSIONS[0];
  // Guard: if the live list is empty AND the mock is empty we cannot
  // render anything. Shouldn't happen in practice (mock always has 1).
  if (!selected) {
    return <div className="page"><div className="t-cap muted" style={{ padding: 24 }}>No DDUP model versions available.</div></div>;
  }
  const cfg = selected.config || {};
  const autoMergeThreshold = Number(cfg.autoMergeThreshold ?? 0);
  const autoMergeCount = Number(selected.autoMergeCount ?? 0);
  const manualMergeCount = Number(selected.manualMergeCount ?? 0);
  // KPI "Active threshold" reads the live active version, not the
  // currently-selected detail. Falls back to the selected version's
  // threshold when the API hasn't responded.
  const activeThreshold = DDUP_QUEUE_STATS.activeThreshold != null
    ? DDUP_QUEUE_STATS.activeThreshold
    : autoMergeThreshold;
  const activeVersionLabel = DDUP_QUEUE_STATS.activeVersion != null
    ? `v${DDUP_QUEUE_STATS.activeVersion}`
    : (DDUP_VERSIONS.find(v => v.status === "active")
        ? `v${DDUP_VERSIONS.find(v => v.status === "active").version}`
        : "—");
  // KPI "Auto-reverse rate" — also active-version-scoped.
  const refRate = DDUP_VERSIONS.find(v => v.status === "active");
  const liveAutoReverseRate = DDUP_QUEUE_STATS.activeAutoReverseRate;
  const refAutoReverseRate = liveAutoReverseRate != null
    ? liveAutoReverseRate
    : (refRate && typeof refRate.autoReverseRate === "number" ? refRate.autoReverseRate : null);

  // Pending-pairs trend caption is informational only — the API
  // doesn't supply a 24h delta yet, so we omit the +N today caption
  // when running live. Keep the up-arrow on mock for layout parity.
  const pendingTrendCaption = (versionsResp || statsResp)
    ? undefined
    : "+34 today";

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
        <KPI title="Pending pairs"
             value={DDUP_QUEUE_STATS.pending.toLocaleString()}
             foot={`${DDUP_QUEUE_STATS.onHold.toLocaleString()} on hold · ${DDUP_QUEUE_STATS.crossHousehold.toLocaleString()} cross-household`}
             trend={pendingTrendCaption ? "up" : undefined}
             trendValue={pendingTrendCaption}/>
        <KPI title="Auto-merge today"
             value={DDUP_QUEUE_STATS.autoMergedToday.toLocaleString()}
             foot={`${DDUP_QUEUE_STATS.manualMergedToday.toLocaleString()} manual merges`}/>
        <KPI title="Active threshold"
             value={Number(activeThreshold).toFixed(2)}
             foot={`Score ≥ this → auto-merge · ${activeVersionLabel}`}/>
        <KPI title="Auto-reverse rate"
             value={refAutoReverseRate === null ? "—" : `${(refAutoReverseRate * 100).toFixed(2)}%`}
             foot="of auto-merges reversed within 30d window"
             trend="flat"/>
      </div>

      {/* Sub-tabs: Model versions · Match queue · Decisions */}
      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid var(--neutral-300)', marginTop: 24, flexWrap: 'wrap' }}>
        {[
          { id: "versions", label: "Model versions" },
          { id: "queue",    label: `Match queue (${DDUP_QUEUE_STATS.pending.toLocaleString()})` },
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
              const active = v.id === selected.id;
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
                  <div className="t-cap mt-1">{(v.description || "").slice(0, 56)}{(v.description || "").length > 56 ? "…" : ""}</div>
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
                  <div className="t-cap mt-2">Author: <strong>{selected.author || "—"}</strong>{selected.approvedBy && <> · Approved by <strong>{selected.approvedBy}</strong> on {selected.approvedAt}</>}</div>
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
                <Stat k="Auto-merge threshold" v={autoMergeThreshold.toFixed(2)} sub="composite score cut" first/>
                <Stat k="Auto-merges" v={autoMergeCount.toLocaleString()} sub="tier-3 confident"/>
                <Stat k="Manual merges" v={manualMergeCount.toLocaleString()} sub="operator decisions"/>
                <Stat k="Auto-reverse rate" v={typeof selected.autoReverseRate === "number" ? `${(selected.autoReverseRate*100).toFixed(2)}%` : '—'} sub="reversed within 30d window" last/>
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
                    <td>{cfg.tier1 ? <Chip size="sm" tone="data">enabled</Chip> : <Chip size="sm">disabled</Chip>}</td>
                  </tr>
                  <tr>
                    <td><Chip tone="update">Tier 2</Chip></td>
                    <td className="t-bodysm">Deterministic-soft</td>
                    <td className="t-mono t-bodysm">Phone match (Soundex-normalised) · name similarity ≥ 0.85</td>
                    <td className="t-mono">0.85+</td>
                    <td>{cfg.tier2 ? <Chip size="sm" tone="data">enabled</Chip> : <Chip size="sm">disabled</Chip>}</td>
                  </tr>
                  <tr>
                    <td><Chip tone="quality">Tier 3</Chip></td>
                    <td className="t-bodysm">Probabilistic composite</td>
                    <td className="t-mono t-bodysm">{(Array.isArray(cfg.tier3Fields) && cfg.tier3Fields.length > 0) ? cfg.tier3Fields.join(' + ') : <span className="muted">—</span>}</td>
                    <td className="t-mono">{autoMergeThreshold.toFixed(2)}+</td>
                    <td>{cfg.tier3 ? <Chip size="sm" tone="data">enabled</Chip> : <Chip size="sm">disabled</Chip>}</td>
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
            <span className="t-cap">{DDUP_QUEUE_STATS.pending.toLocaleString()} awaiting decision</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm">Auto-resolve high-confidence</button>
          </div>
          {DDUP_RECENT_PAIRS.length === 0 ? (
            <div className="t-cap muted" style={{ padding: 32, textAlign: "center" }}>
              No pending pairs in the queue.
            </div>
          ) : (
            <table className="tbl" style={{ boxShadow: 'none' }}>
              <thead>
                <tr><th>Pair ID</th><th>Type</th><th>Record A</th><th>Record B</th><th>Tier</th><th>Score</th><th>Reason</th><th>Status</th><th>Age</th><th className="col-actions"></th></tr>
              </thead>
              <tbody>
                {DDUP_RECENT_PAIRS.map(p => (
                  <tr key={p.id} style={{ cursor: 'pointer' }}>
                    <td className="col-id">{String(p.id).slice(0, 16)}…</td>
                    <td><Chip size="sm">{p.type}</Chip></td>
                    <td className="t-bodysm t-mono">{p.a}</td>
                    <td className="t-bodysm t-mono">{p.b}</td>
                    <td><Chip size="sm" tone={p.tier === 1 ? 'data' : p.tier === 2 ? 'update' : 'quality'}>Tier {p.tier}</Chip></td>
                    <td className="t-num">{Number(p.score ?? 0).toFixed(2)}</td>
                    <td className="t-cap">{p.reason}</td>
                    <td><Chip size="sm" tone={DDUP_PAIR_STATUS_TONE[p.status]}>{String(p.status).replace('_',' ')}</Chip></td>
                    <td className="t-cap">{p.ageHours != null ? `${p.ageHours}h` : '—'}</td>
                    <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
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
                <div className="t-num" style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>{Number(s.value ?? 0).toLocaleString()}</div>
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
