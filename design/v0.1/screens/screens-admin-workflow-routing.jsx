/* global React, Icon, Chip, PageHeader, KPI, Modal, Field, Toast, useApi, nsrApi */
// NSR MIS — Admin · Workflow · UPD routing rules
// =========================================================
// Operations-managed routing for ChangeRequest types. Replaces the
// hardcoded matrix in SAD §4.4.4 — operations can rebalance SLAs
// and required roles without a deploy.
//
// Maps to: apps.update_workflow.models.UpdRoutingRule
//   (change_type, pmt_relevant, required_role, sla_hours, is_active)
// Unique-active constraint per (change_type, pmt_relevant) tuple.

const { useState: useStateRR, useMemo: useMemoRR } = React;

const RR_CHANGE_TYPES = [
  { id: "correction",        label: "Correction",         desc: "Update of an existing field — operator-driven" },
  { id: "addition",          label: "Addition",           desc: "Adds member or household roster row" },
  { id: "removal",           label: "Removal",            desc: "Removes a member or roster row" },
  { id: "vital_event",       label: "Vital event",        desc: "Birth, death, marriage — system-named life event" },
  { id: "programme_state",   label: "Programme state",    desc: "Push from partner MIS — enrolment / exit" },
  { id: "recertification",   label: "Recertification",    desc: "Wave-driven full refresh" },
  { id: "life_event",        label: "Life event",         desc: "Operator-driven counterpart of vital_event" },
  { id: "verification",      label: "Verification",       desc: "Identity / consent reverify" },
  { id: "address_move",      label: "Address move",       desc: "Household geo change" },
  { id: "roster_change",     label: "Roster change",      desc: "Composite roster mutation" },
  { id: "asset_change",      label: "Asset change",       desc: "Asset add / remove / value change" },
];

const RR_ROLES = ["parish_coordinator","cdo","nsr_unit_coordinator","dpo","auto_committed"];
const RR_ROLE_LABEL = {
  parish_coordinator: "Parish Coordinator",
  cdo: "Community Dev't Officer (CDO)",
  nsr_unit_coordinator: "NSR Unit Coordinator",
  dpo: "Data Protection Officer (DPO)",
  auto_committed: "Auto-committed (no human review)",
};
const RR_ROLE_TONE = {
  parish_coordinator: "data",
  cdo: "programme",
  nsr_unit_coordinator: "system",
  dpo: "danger",
  auto_committed: "quality",
};

// Live matrix — pulled from UpdRoutingRule rows
const RR_RULES = [
  // change_type, pmt_relevant, required_role, sla_hours, is_active, updated_at
  { changeType:"correction",      pmtRelevant: false, requiredRole:"parish_coordinator",   slaHours: 72, isActive: true,  updatedAt:"04 Jan 2026", note:"Sprint 0 default" },
  { changeType:"correction",      pmtRelevant: true,  requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"addition",        pmtRelevant: false, requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"12 Mar 2026", note:"Backlog rebalance — was 72h" },
  { changeType:"addition",        pmtRelevant: true,  requiredRole:"nsr_unit_coordinator", slaHours: 24, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"removal",         pmtRelevant: false, requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"removal",         pmtRelevant: true,  requiredRole:"nsr_unit_coordinator", slaHours: 24, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"vital_event",     pmtRelevant: false, requiredRole:"auto_committed",       slaHours:  0, isActive: true,  updatedAt:"04 Jan 2026", note:"1% sample auto-audited" },
  { changeType:"vital_event",     pmtRelevant: true,  requiredRole:"cdo",                  slaHours: 24, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"programme_state", pmtRelevant: false, requiredRole:"auto_committed",       slaHours:  0, isActive: true,  updatedAt:"04 Jan 2026", note:"Partner-pushed; trust DSA" },
  { changeType:"programme_state", pmtRelevant: true,  requiredRole:"nsr_unit_coordinator", slaHours: 48, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"recertification", pmtRelevant: false, requiredRole:"cdo",                  slaHours: 96, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"recertification", pmtRelevant: true,  requiredRole:"nsr_unit_coordinator", slaHours: 72, isActive: true,  updatedAt:"04 Jan 2026", note:"" },
  { changeType:"life_event",      pmtRelevant: false, requiredRole:"parish_coordinator",   slaHours: 72, isActive: true,  updatedAt:"21 May 2026", note:"US-S22-003 — new" },
  { changeType:"life_event",      pmtRelevant: true,  requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"verification",    pmtRelevant: false, requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"verification",    pmtRelevant: true,  requiredRole:"nsr_unit_coordinator", slaHours: 24, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"address_move",    pmtRelevant: false, requiredRole:"cdo",                  slaHours: 72, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"address_move",    pmtRelevant: true,  requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"roster_change",   pmtRelevant: false, requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"roster_change",   pmtRelevant: true,  requiredRole:"nsr_unit_coordinator", slaHours: 24, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"asset_change",    pmtRelevant: false, requiredRole:"parish_coordinator",   slaHours: 72, isActive: true,  updatedAt:"21 May 2026", note:"" },
  { changeType:"asset_change",    pmtRelevant: true,  requiredRole:"cdo",                  slaHours: 48, isActive: true,  updatedAt:"21 May 2026", note:"" },
];

// Volume + breach context per change_type
const RR_VOLUME = {
  correction:      { open: 412,  weeklyAvg: 1820, breachRate: 4.2 },
  addition:        { open: 218,  weeklyAvg:  912, breachRate: 6.8 },
  removal:         { open:  91,  weeklyAvg:  302, breachRate: 2.1 },
  vital_event:     { open:   0,  weeklyAvg: 3140, breachRate: 0   },
  programme_state: { open:   0,  weeklyAvg: 8420, breachRate: 0   },
  recertification: { open:  18,  weeklyAvg:   91, breachRate: 1.1 },
  life_event:      { open:  62,  weeklyAvg:  204, breachRate: 8.9 },
  verification:    { open:  41,  weeklyAvg:  118, breachRate: 3.4 },
  address_move:    { open: 119,  weeklyAvg:  421, breachRate: 5.2 },
  roster_change:   { open:  84,  weeklyAvg:  248, breachRate: 4.1 },
  asset_change:    { open:  72,  weeklyAvg:  202, breachRate: 3.8 },
};

// Live overlay — pull active rules + per-change-type stats from the
// new admin API. Falls back to RR_RULES / RR_VOLUME when the API
// isn't reachable so the prototype keeps rendering.
const _projectRoutingRules = (results) => {
  if (!Array.isArray(results) || results.length === 0) return null;
  return results.map(r => ({
    changeType: r.change_type,
    pmtRelevant: r.pmt_relevant,
    requiredRole: r.required_role,
    slaHours: r.sla_hours,
    note: r.note,
    breachRate: r.breach_rate_30d ?? 0,
    open: r.open_count ?? 0,
  }));
};

const AdminUpdRoutingScreen = () => {
  const [respRules, respMeta] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/workflow/upd-routing/")
    : [null, { refresh: () => {} }];
  // eslint-disable-next-line no-shadow
  const RR_RULES_LIVE = _projectRoutingRules(respRules && respRules.results) || RR_RULES;

  const [search, setSearch] = useStateRR("");
  const [roleFilter, setRoleFilter] = useStateRR("");
  // US-S11-043 — Edit modal target + History drawer target. Both
  // are nullable so the screen renders nothing when neither is open.
  const [editTarget, setEditTarget] = useStateRR(null);
  const [historyTarget, setHistoryTarget] = useStateRR(null);
  const [toast, setToast] = useStateRR("");

  // Export matrix as CSV — flat shape, one row per active rule.
  const exportMatrix = () => {
    const header = [
      "change_type", "pmt_relevant", "required_role",
      "sla_hours", "note",
    ];
    const rows = [header];
    for (const r of RR_RULES_LIVE) {
      rows.push([
        r.changeType, r.pmtRelevant ? "true" : "false",
        r.requiredRole, r.slaHours, r.note || "",
      ]);
    }
    const csv = rows.map(row =>
      row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")
    ).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `nsr-upd-routing-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Build the matrix: rows = change types, columns = (PMT-relevant, non-PMT).
  //
  // `vol` (open / weeklyAvg / breachRate) is a separate concern from routing
  // rules — only the live API projection actually carries open_count /
  // breach_rate_30d. Falling back to RR_RULES (mock) produces rows WITHOUT
  // those fields, so we cannot use "we found a rule" as a proxy for "we
  // have live volume". Compose from RR_VOLUME (mock) as the base and
  // overlay live numbers only when present on the projection.
  const matrix = useMemoRR(() => {
    return RR_CHANGE_TYPES.map(ct => {
      const ruleFalse = RR_RULES_LIVE.find(r => r.changeType === ct.id && r.pmtRelevant === false);
      const ruleTrue  = RR_RULES_LIVE.find(r => r.changeType === ct.id && r.pmtRelevant === true);
      const mockVol = RR_VOLUME[ct.id] || { open: 0, weeklyAvg: 0, breachRate: 0 };
      // Prefer a live-projected row that actually carries open_count.
      // Projection sets open: r.open_count ?? 0 so a missing field
      // surfaces as 0 rather than undefined.
      const liveRule = [ruleFalse, ruleTrue].find(
        r => r && typeof r.open === "number",
      );
      const vol = liveRule
        ? {
            open: liveRule.open,
            weeklyAvg: mockVol.weeklyAvg,
            breachRate: typeof liveRule.breachRate === "number" ? liveRule.breachRate : mockVol.breachRate,
          }
        : mockVol;
      return { ct, ruleFalse, ruleTrue, vol };
    });
  }, [RR_RULES_LIVE]);

  const filtered = matrix.filter(m => {
    if (search && !(m.ct.id.includes(search.toLowerCase()) || m.ct.label.toLowerCase().includes(search.toLowerCase()))) return false;
    if (roleFilter && m.ruleFalse?.requiredRole !== roleFilter && m.ruleTrue?.requiredRole !== roleFilter) return false;
    return true;
  });

  const breachingTypes = matrix.filter(m => (m.vol?.breachRate ?? 0) > 5).length;
  const autoCommitTypes = RR_RULES_LIVE.filter(r => r.requiredRole === "auto_committed").length;

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · WORKFLOW · UPD routing"
        title="Change request routing"
        sub="Maps each (change_type × pmt_relevant) tuple to a required role and SLA. The constraint is unique-active per tuple — edits write a new active row and archive the previous one."
        right={<>
          <button className="btn" onClick={exportMatrix}>
            <Icon name="download" size={14}/> Export matrix
          </button>
          <button className="btn"
                  onClick={() => setHistoryTarget({ changeType: null, pmtRelevant: null })}
                  title="Browse every prior version of every routing rule">
            <Icon name="history" size={14}/> History
          </button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Active rules" value={RR_RULES_LIVE.length} foot={`${RR_CHANGE_TYPES.length} change types × 2 (PMT) = ${RR_CHANGE_TYPES.length * 2} expected`}/>
        <KPI title="Open CRs" value={Object.values(RR_VOLUME).reduce((a,v) => a + Number(v?.open ?? 0), 0).toLocaleString()} foot="Currently in review queues"/>
        <KPI title="Auto-committed" value={autoCommitTypes} foot="No human review · 1% sample audited" trend="flat"/>
        <KPI title="Breaching SLA" value={breachingTypes} foot={`Types with >5% breach rate · ${breachingTypes ? 'review' : 'healthy'}`}/>
      </div>

      <div className="card mt-5" style={{ padding: '14px 16px' }}>
        <div className="row gap-3" style={{ flexWrap: 'wrap' }}>
          <div className="search" style={{ maxWidth: 320, height: 34, background: 'var(--neutral-0)' }}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search change_type…"/>
          </div>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 200 }} value={roleFilter} onChange={e => setRoleFilter(e.target.value)}>
            <option value="">Any required role</option>
            {RR_ROLES.map(r => <option key={r} value={r}>{RR_ROLE_LABEL[r]}</option>)}
          </select>
          <div style={{ flex: 1 }}/>
          <span className="t-cap">{filtered.length} change types</span>
        </div>
      </div>

      {/* Matrix table */}
      <div className="card mt-4" style={{ padding: 0 }}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Change type</th>
              <th>Open / wk avg</th>
              <th>Breach rate</th>
              <th style={{ background: 'var(--neutral-50)' }}>
                <div className="t-cap">PMT-relevant <span style={{ color:'var(--neutral-400)' }}>= false</span></div>
                <div className="t-bodysm" style={{ fontWeight: 600 }}>Routing</div>
              </th>
              <th style={{ background: 'var(--accent-eligibility-bg, var(--neutral-50))' }}>
                <div className="t-cap" style={{ color: 'var(--accent-eligibility)' }}>PMT-relevant <span>= true</span></div>
                <div className="t-bodysm" style={{ fontWeight: 600, color: 'var(--accent-eligibility)' }}>Routing</div>
              </th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(({ ct, ruleFalse, ruleTrue, vol }) => (
              <tr key={ct.id}>
                <td>
                  <div className="t-mono" style={{ fontWeight: 600, fontSize: 12.5 }}>{ct.id}</div>
                  <div className="t-cap">{ct.desc}</div>
                </td>
                <td>
                  <div className="t-num" style={{ fontWeight: 500 }}>{Number(vol?.open ?? 0).toLocaleString()}</div>
                  <div className="t-cap">{Number(vol?.weeklyAvg ?? 0).toLocaleString()} / wk</div>
                </td>
                <td>
                  {!vol?.breachRate
                    ? <span className="muted t-cap">n/a (auto)</span>
                    : <Chip size="sm" tone={vol.breachRate > 5 ? 'danger' : vol.breachRate > 3 ? 'quality' : 'data'}>{Number(vol.breachRate).toFixed(1)}%</Chip>}
                </td>
                <RuleCell rule={ruleFalse}
                  onEdit={() => setEditTarget({
                    changeType: ct.id, pmtRelevant: false, current: ruleFalse,
                  })}/>
                <RuleCell rule={ruleTrue} tint
                  onEdit={() => setEditTarget({
                    changeType: ct.id, pmtRelevant: true, current: ruleTrue,
                  })}/>
                <td className="col-actions">
                  <button className="icon-btn"
                    title={`History for ${ct.id} (both PMT variants)`}
                    onClick={() => setHistoryTarget({
                      changeType: ct.id, pmtRelevant: null,
                    })}>
                    <Icon name="history" size={13}/>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="tint-update mt-4" style={{
        padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)',
      }}>
        <div className="row gap-2" style={{ marginBottom: 4 }}>
          <Icon name="info" size={13} color="var(--accent-update)"/>
          <strong className="t-bodysm">Edits are versioned, not destructive</strong>
        </div>
        <div className="t-bodysm muted">
          Every change creates a new active row and flips the previous one to <span className="t-mono">is_active=false</span>.
          The constraint <span className="t-mono">upd_routing_unique_active_per_tuple</span> means at most one active rule per
          (change_type × pmt_relevant) at any time. Inactive history surfaces under the <strong>History</strong> button.
          If all rows are deleted, the system falls back to the <span className="t-mono">DEFAULT_MATRIX</span> constants in code.
        </div>
      </div>

      {editTarget && (
        <EditRoutingRuleModal
          target={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={(newRow) => {
            setEditTarget(null);
            setToast(
              `Updated ${newRow.changeType}/pmt=${newRow.pmtRelevant} `
              + `→ ${RR_ROLE_LABEL[newRow.requiredRole]} · ${newRow.slaHours}h SLA. `
              + `Previous version archived.`,
            );
            respMeta?.refresh && respMeta.refresh();
          }}
          onError={(msg) => setToast(`Save failed: ${msg}`)}
        />
      )}

      {historyTarget && (
        <RoutingHistoryDrawer
          target={historyTarget}
          onClose={() => setHistoryTarget(null)}
        />
      )}

      <Toast message={toast} onDone={() => setToast("")}/>
    </div>
  );
};

const RuleCell = ({ rule, tint, onEdit }) => {
  if (!rule) {
    return (
      <td style={tint ? { background: 'var(--accent-eligibility-bg, var(--neutral-50))' } : null}>
        <div className="row gap-2">
          <span className="muted t-cap">— no rule (falls back to DEFAULT_MATRIX)</span>
          {onEdit && (
            <button className="icon-btn" title="Create a rule for this tuple" onClick={onEdit}>
              <Icon name="plus" size={12}/>
            </button>
          )}
        </div>
      </td>
    );
  }
  const isAuto = rule.requiredRole === "auto_committed";
  return (
    <td style={tint ? { background: 'var(--accent-eligibility-bg, var(--neutral-50))' } : null}>
      <div className="row gap-2" style={{alignItems:"center"}}>
        <Chip size="sm" tone={RR_ROLE_TONE[rule.requiredRole]}>{RR_ROLE_LABEL[rule.requiredRole]}</Chip>
        {isAuto
          ? <span className="t-cap" style={{ color: 'var(--accent-quality)' }}>auto-commit · 1% sample</span>
          : <span className="t-cap"><strong>{rule.slaHours}h SLA</strong></span>}
        {onEdit && (
          <button className="icon-btn"
            style={{marginLeft:"auto", padding:"2px 4px"}}
            title="Edit this routing rule (versioned — previous row is archived)"
            onClick={onEdit}>
            <Icon name="edit" size={12}/>
          </button>
        )}
      </div>
      {rule.note && <div className="t-cap mt-1" style={{ color: 'var(--neutral-600)' }}>{rule.note}</div>}
    </td>
  );
};


// ── EditRoutingRuleModal (US-S11-043) ─────────────────────────────────
// PATCHes the (change_type, pmt_relevant) tuple. Per the model's
// versioned-write contract, the existing active row is archived and
// a new one becomes active — operators can't accidentally destroy
// version history.
const EditRoutingRuleModal = ({ target, onClose, onSaved, onError }) => {
  const { changeType, pmtRelevant, current } = target;
  const [requiredRole, setRequiredRole] = useStateRR(current?.requiredRole || "cdo");
  const [slaHours, setSlaHours] = useStateRR(String(current?.slaHours ?? 48));
  const [note, setNote] = useStateRR(current?.note || "");
  const [submitting, setSubmitting] = useStateRR(false);

  const ctMeta = RR_CHANGE_TYPES.find(c => c.id === changeType) || {};
  const isAuto = requiredRole === "auto_committed";
  const slaNum = parseInt(slaHours, 10);
  const canSave = !submitting && requiredRole
    && (isAuto || (Number.isFinite(slaNum) && slaNum >= 0));

  const save = async () => {
    if (!canSave) return;
    setSubmitting(true);
    try {
      const url = `/api/v1/admin/workflow/upd-routing/${changeType}/${pmtRelevant ? "true" : "false"}/`;
      const payload = {
        required_role: requiredRole,
        sla_hours: isAuto ? 0 : slaNum,
        note,
      };
      const r = await nsrApi.patch(url, payload);
      setSubmitting(false);
      onSaved({
        changeType: r.change_type,
        pmtRelevant: r.pmt_relevant,
        requiredRole: r.required_role,
        slaHours: r.sla_hours,
        note: r.note,
      });
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || JSON.stringify(err.body))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Edit routing · ${changeType} · PMT=${pmtRelevant}`} size="md">
      <p className="t-bodysm muted" style={{marginTop:0, marginBottom:12}}>
        {ctMeta.desc || ""}
      </p>
      <p className="t-bodysm" style={{
        background:"var(--accent-update-bg)", padding:"8px 12px",
        borderRadius:4, marginBottom:16, fontSize:12,
      }}>
        Versioned write — the current active row stays in the
        history; this submit creates a new active row.
      </p>

      <Field label="Required role">
        <select value={requiredRole} onChange={e => setRequiredRole(e.target.value)}
                disabled={submitting}>
          {RR_ROLES.map(r => (
            <option key={r} value={r}>{RR_ROLE_LABEL[r]}</option>
          ))}
        </select>
      </Field>

      <Field label={isAuto
        ? "SLA hours (auto-committed has SLA=0)"
        : "SLA hours"}>
        <input
          type="number" min={0} max={720}
          value={isAuto ? "0" : slaHours}
          onChange={e => setSlaHours(e.target.value)}
          disabled={submitting || isAuto}
          placeholder="hours (e.g. 24, 48, 72)"
        />
      </Field>

      <Field label="Note (operator visible — captured on the new active row)">
        <textarea
          value={note} onChange={e => setNote(e.target.value)}
          rows={2} disabled={submitting}
          placeholder="e.g. raised from 48h to 72h during Q1 onboarding backlog"
        />
      </Field>

      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!canSave}>
          {submitting ? "Saving…" : "Save (versioned)"}
        </button>
      </div>
    </Modal>
  );
};


// ── RoutingHistoryDrawer (US-S11-043) ─────────────────────────────────
// Read-only timeline of UpdRoutingRule versions. When `target.changeType`
// is set the history is scoped to that tuple; null = all history.
const RoutingHistoryDrawer = ({ target, onClose }) => {
  const [rows, setRows] = useStateRR(null);
  const [error, setError] = useStateRR("");

  React.useEffect(() => {
    const qs = new URLSearchParams();
    if (target.changeType) qs.set("change_type", target.changeType);
    if (target.pmtRelevant !== null && target.pmtRelevant !== undefined) {
      qs.set("pmt_relevant", target.pmtRelevant ? "true" : "false");
    }
    const url = `/api/v1/admin/workflow/upd-routing/history/?${qs.toString()}`;
    nsrApi.get(url)
      .then(body => setRows(body.results || []))
      .catch(err => setError(err.message || String(err)));
  }, [target]);

  const title = target.changeType
    ? `History · ${target.changeType}${target.pmtRelevant !== null ? ` · PMT=${target.pmtRelevant}` : ""}`
    : "Routing matrix · history";

  return (
    <Modal open={true} onClose={onClose} title={title} size="lg">
      {error && (
        <p className="t-bodysm" style={{color:"var(--accent-danger)"}}>{error}</p>
      )}
      {rows === null && !error && (
        <p className="t-bodysm muted">Loading…</p>
      )}
      {rows !== null && rows.length === 0 && (
        <p className="t-bodysm muted">No history rows for this scope.</p>
      )}
      {rows && rows.length > 0 && (
        <table className="tbl">
          <thead>
            <tr>
              <th>Change type</th>
              <th>PMT</th>
              <th>Required role</th>
              <th>SLA</th>
              <th>Active</th>
              <th>Updated</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="t-mono" style={{fontSize:12}}>{r.change_type}</td>
                <td>
                  <Chip size="sm" tone={r.pmt_relevant ? "eligibility" : "neutral"}>
                    {r.pmt_relevant ? "true" : "false"}
                  </Chip>
                </td>
                <td>
                  <Chip size="sm" tone={RR_ROLE_TONE[r.required_role]}>
                    {RR_ROLE_LABEL[r.required_role] || r.required_role}
                  </Chip>
                </td>
                <td className="t-num">{r.sla_hours}h</td>
                <td>
                  {r.is_active
                    ? <Chip size="sm" tone="data">active</Chip>
                    : <Chip size="sm" tone="neutral">archived</Chip>}
                </td>
                <td className="t-cap">
                  {(r.updated_at || "").slice(0, 16).replace("T", " ")}
                </td>
                <td className="t-cap">{r.note || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
};

Object.assign(window, { AdminUpdRoutingScreen });
