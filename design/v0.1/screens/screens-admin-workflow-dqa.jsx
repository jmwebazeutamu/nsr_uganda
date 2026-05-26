/* global React, Icon, Chip, PageHeader, KPI, useApi */
// NSR MIS — Admin · Workflow · DQA Rules
// =========================================================
// Versioned JSON-DSL rule engine. Sprint 0 item 4.
// Lifecycle DRAFT → PENDING_APPROVAL → ACTIVE → RETIRED + REJECTED.
// author != approved_by enforced at service layer.
//
// Maps to:
//   apps.dqa.models.DqaRule          (versioned)
//   apps.dqa.models.DqaRulePreviewRun (audit trail of /preview/ runs)
//   apps.dqa.models.DqaResult        (per-record evaluations)
//   apps.dqa.engine                  (DSL grammar)
//   apps.dqa.services                (submit / approve / retire)

const { useState: useStateDQA, useMemo: useMemoDQA } = React;

// Live overlay — pull active rules from the admin API. Falls back
// to DQA_RULES (mock) when the API is unreachable so the design
// preview keeps rendering. Same pattern as the choice-lists screen.
const _projectDqaRules = (results) => {
  if (!Array.isArray(results) || results.length === 0) return null;
  return results.map(r => ({
    ruleId: r.rule_id,
    latestVersion: r.version,
    severity: r.severity,
    status: r.status,
    applicability: r.applicability || { entity: "household" },
    description: r.description || "",
    failRate7d: typeof r.fail_rate_7d === "number" ? r.fail_rate_7d : null,
    evaluated7d: typeof r.evaluated_7d === "number" ? r.evaluated_7d : null,
    author: r.author || "",
    approvedBy: r.approved_by || null,
    approvedAt: r.approved_at ? String(r.approved_at).slice(0, 10) : null,
    submittedAt: r.submitted_at ? String(r.submitted_at).slice(0, 10) : null,
  }));
};

const DQA_SEVERITY_TONE = { blocking: "danger", warning: "quality", info: "data" };
const DQA_STATUS_TONE = {
  draft: "quality", pending_approval: "update", active: "data",
  retired: "neutral", rejected: "danger",
};

const DQA_RULES = [
  // (rule_id, latest version, severity, status, applicability, fail_rate_last_7d, …)
  { ruleId: "AC-MANDATORY-NIN-HEAD",        latestVersion: 3, severity: "blocking", status: "active", applicability: { entity: "household" }, description: "Head of household must have a NIN value (verified or pending allowed).", failRate7d: 4.2, evaluated7d: 81204, author: "MGLSD Stats", approvedBy: "Director General · UBOS", approvedAt: "12 Mar 2026" },
  { ruleId: "AC-CONSISTENCY-BIRTH-AGE",     latestVersion: 2, severity: "warning",  status: "active", applicability: { entity: "member" },    description: "Date of birth must agree with reported age (±1 year tolerance).",          failRate7d: 1.8, evaluated7d: 322910, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "18 Feb 2026" },
  { ruleId: "AC-PMT-INPUTS-COMPLETE",       latestVersion: 4, severity: "blocking", status: "active", applicability: { entity: "household" }, description: "All 25 PMT v1 inputs must be present (non-null) for household.",             failRate7d: 6.4, evaluated7d: 81204, author: "Nakanwagi · MGLSD", approvedBy: "Director General · UBOS", approvedAt: "12 Mar 2026" },
  { ruleId: "AC-WG-SS-AGE-FLOOR",           latestVersion: 1, severity: "info",     status: "active", applicability: { entity: "member", age_band: "5+" }, description: "WG-SS questions only asked of members aged 5 and over.",                failRate7d: 0.1, evaluated7d: 198431, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "04 Jan 2026" },
  { ruleId: "AC-GEO-COVERAGE-VALID",        latestVersion: 2, severity: "blocking", status: "active", applicability: { entity: "household" }, description: "Parish + sub-county + district codes must form a valid UBOS path.",        failRate7d: 0.4, evaluated7d: 81204, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "12 Mar 2026" },
  { ruleId: "AC-CONSENT-RECORDED",          latestVersion: 1, severity: "blocking", status: "active", applicability: { entity: "household" }, description: "Head must have given consent (consent_given=true) at intake.",              failRate7d: 0.0, evaluated7d: 81204, author: "DPO", approvedBy: "Director General · UBOS", approvedAt: "04 Jan 2026" },
  { ruleId: "AC-DISABILITY-WG-SS-COMPLETE", latestVersion: 1, severity: "warning",  status: "active", applicability: { entity: "member", age_band: "5+" }, description: "All 6 WG-SS domains must be answered for eligible members.",            failRate7d: 2.1, evaluated7d: 198431, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "08 Mar 2026" },
  { ruleId: "AC-EDU-SCHOOL-AGE",            latestVersion: 1, severity: "warning",  status: "active", applicability: { entity: "member", age_band: "5-17" }, description: "School-age members must answer 'currently attending school'.",        failRate7d: 5.8, evaluated7d: 81012, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "08 Mar 2026" },
  { ruleId: "AC-VITAL-MARRIAGE-AGE",        latestVersion: 1, severity: "blocking", status: "active", applicability: { entity: "member" },    description: "Marriage event date must be after member's date of birth (18+).",          failRate7d: 0.0, evaluated7d: 12091, author: "DPO", approvedBy: "Director General · UBOS", approvedAt: "04 Jan 2026" },
  { ruleId: "AC-DWELLING-MATERIALS-VALID",  latestVersion: 2, severity: "warning",  status: "active", applicability: { entity: "household" }, description: "Floor/roof/wall material codes must exist in current choice list.",        failRate7d: 0.2, evaluated7d: 81204, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "08 Mar 2026" },
  { ruleId: "AC-PMT-OUTLIER-DETECTION",     latestVersion: 1, severity: "warning",  status: "pending_approval", applicability: { entity: "household" }, description: "Flags households whose PMT score is >3σ from sub-region mean.",        failRate7d: null, evaluated7d: null, author: "Nakanwagi · MGLSD", approvedBy: null, approvedAt: null, submittedAt: "21 May 2026" },
  { ruleId: "AC-EARNINGS-BAND-PRESENT",     latestVersion: 1, severity: "info",     status: "draft", applicability: { entity: "member", age_band: "15+" }, description: "Members 15+ in wage employment should report an earnings band.",      failRate7d: null, evaluated7d: null, author: "Bahati E. · OPM", approvedBy: null, approvedAt: null },
  { ruleId: "AC-HEAD-AGE-FLOOR-18",         latestVersion: 0, severity: "blocking", status: "retired", applicability: { entity: "household" }, description: "Household head must be 18+. Retired — replaced by AC-CONSENT-AGE-FLOOR.", failRate7d: null, evaluated7d: null, author: "DQA team", approvedBy: "Director General · UBOS", approvedAt: "10 Jan 2026" },
];

const DQA_PREVIEW_RUNS = [
  { ruleId: "AC-PMT-OUTLIER-DETECTION", version: 1, sample: 5000, passCount: 4814, failCount: 186, executedAt: "21 May 2026 · 11:42", executedBy: "Nakanwagi" },
  { ruleId: "AC-PMT-OUTLIER-DETECTION", version: 1, sample: 1000, passCount:  969, failCount:  31, executedAt: "21 May 2026 · 09:58", executedBy: "Nakanwagi" },
  { ruleId: "AC-EARNINGS-BAND-PRESENT", version: 1, sample: 5000, passCount: 3211, failCount:1789, executedAt: "20 May 2026 · 14:12", executedBy: "Bahati E." },
];

const AdminDqaRulesScreen = () => {
  // Live overlay: fetch once on mount, fall back to mocks on error.
  const [resp] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/workflow/dqa/rules/")
    : [null];
  // eslint-disable-next-line no-shadow
  const DQA_RULES_LIVE = _projectDqaRules(resp && resp.results) || DQA_RULES;

  const [q, setQ] = useStateDQA("");
  const [severity, setSeverity] = useStateDQA("");
  const [status, setStatus] = useStateDQA("");
  const [selected, setSelected] = useStateDQA(null);

  const rows = useMemoDQA(() => DQA_RULES_LIVE.filter(r => {
    if (q && !(r.ruleId.toLowerCase().includes(q.toLowerCase()) || (r.description || "").toLowerCase().includes(q.toLowerCase()))) return false;
    if (severity && r.severity !== severity) return false;
    if (status && r.status !== status) return false;
    return true;
  }), [q, severity, status, DQA_RULES_LIVE]);

  // KPIs
  const total = DQA_RULES_LIVE.length;
  const active = DQA_RULES_LIVE.filter(r => r.status === "active").length;
  const pending = DQA_RULES_LIVE.filter(r => r.status === "pending_approval").length;
  const drafts = DQA_RULES_LIVE.filter(r => r.status === "draft").length;

  if (selected) {
    const rule = DQA_RULES_LIVE.find(r => r.ruleId === selected)
      || DQA_RULES.find(r => r.ruleId === selected);
    if (!rule) { setSelected(null); return null; }
    return <DqaRuleDetail rule={rule} onBack={() => setSelected(null)}/>;
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · WORKFLOW · DQA rules"
        title="Data quality rules"
        sub="Versioned JSON-DSL rule engine. Active rules evaluate every intake and UPD. Dual approval — author cannot approve."
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export rules</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> New rule</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Total rules" value={total} foot={`${active} active · ${pending} pending · ${drafts} draft`}/>
        <KPI title="Active blocking" value={DQA_RULES_LIVE.filter(r => r.status === "active" && r.severity === "blocking").length} foot="Hard stops on submit"/>
        <KPI title="Active warnings" value={DQA_RULES_LIVE.filter(r => r.status === "active" && r.severity === "warning").length} foot="Reviewer sees yellow flag"/>
        <KPI title="Preview runs last 7d" value="124" foot="Sandboxed evaluations — no PII persisted" trend="up" trendValue="+18"/>
      </div>

      <div className="card mt-5" style={{ padding: '14px 16px' }}>
        <div className="row gap-3" style={{ flexWrap: 'wrap' }}>
          <div className="search" style={{ maxWidth: 360, height: 34, background: 'var(--neutral-0)' }}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search rule ID or description…"/>
          </div>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 140 }} value={severity} onChange={e => setSeverity(e.target.value)}>
            <option value="">Any severity</option>
            <option value="blocking">Blocking</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 160 }} value={status} onChange={e => setStatus(e.target.value)}>
            <option value="">Any status</option>
            <option value="active">Active</option>
            <option value="pending_approval">Pending approval</option>
            <option value="draft">Draft</option>
            <option value="retired">Retired</option>
            <option value="rejected">Rejected</option>
          </select>
          <div style={{ flex: 1 }}/>
          <span className="t-cap">{rows.length} of {total}</span>
        </div>
      </div>

      <div className="card mt-4">
        <table className="tbl">
          <thead>
            <tr>
              <th>Rule ID · v</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Description</th>
              <th>Applies to</th>
              <th>Fail rate (7d)</th>
              <th>Author</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.ruleId} style={{ cursor: 'pointer' }} onClick={() => setSelected(r.ruleId)}>
                <td>
                  <div className="t-mono" style={{ fontWeight: 600, fontSize: 12.5 }}>{r.ruleId}</div>
                  <div className="t-cap">v{r.latestVersion}</div>
                </td>
                <td><Chip size="sm" tone={DQA_SEVERITY_TONE[r.severity]}>{r.severity}</Chip></td>
                <td><Chip size="sm" tone={DQA_STATUS_TONE[r.status]}>{r.status.replace("_", " ")}</Chip></td>
                <td className="t-bodysm" style={{ maxWidth: 360 }}>{r.description}</td>
                <td>
                  <Chip size="sm">{r.applicability.entity}</Chip>
                  {r.applicability.age_band && <div className="t-cap mt-1">age {r.applicability.age_band}</div>}
                </td>
                <td>
                  {typeof r.failRate7d !== "number"
                    ? <span className="muted t-cap">—</span>
                    : <>
                        <div className="t-num" style={{ fontWeight: 500, color: r.failRate7d > 5 ? 'var(--accent-danger)' : r.failRate7d > 2 ? 'var(--accent-quality)' : 'var(--neutral-700)' }}>
                          {r.failRate7d.toFixed(1)}%
                        </div>
                        <div className="t-cap">{Number(r.evaluated7d ?? 0).toLocaleString()} evals</div>
                      </>}
                </td>
                <td className="t-cap">{r.author}</td>
                <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/* ===========================================================
   DQA Rule Detail
   =========================================================== */
const DqaRuleDetail = ({ rule, onBack }) => {
  const [tab, setTab] = useStateDQA("expression");
  const previewRuns = DQA_PREVIEW_RUNS.filter(p => p.ruleId === rule.ruleId);
  const isEditable = rule.status === "draft";

  // Sample DSL — for AC-PMT-OUTLIER-DETECTION
  const sampleExpression = {
    op: "lt",
    lhs: { op: "abs", arg: { op: "minus", lhs: { var: "household.pmt_score" }, rhs: { aggregate: "mean", group_by: ["sub_region_code"], var: "household.pmt_score" } } },
    rhs: { op: "mul", lhs: { literal: 3 }, rhs: { aggregate: "stddev", group_by: ["sub_region_code"], var: "household.pmt_score" } },
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow={<>ADMIN · WORKFLOW · DQA · <span className="t-mono">{rule.ruleId}</span> · v{rule.latestVersion}</>}
        title={(rule.description || rule.ruleId).slice(0, 60) + ((rule.description || "").length > 60 ? '…' : '')}
        sub={<>Author <strong>{rule.author}</strong> {rule.approvedBy && <>· Approved by <strong>{rule.approvedBy}</strong> on {rule.approvedAt}</>}</>}
        right={<>
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to rules</button>
          {rule.status === "active" && <button className="btn"><Icon name="copy" size={14}/> Clone as draft</button>}
          {isEditable && <button className="btn btn-primary"><Icon name="upload" size={14}/> Submit for approval</button>}
          {rule.status === "pending_approval" && <>
            <button className="btn"><Icon name="x" size={14}/> Reject</button>
            <button className="btn btn-primary"><Icon name="check" size={14}/> Approve & activate</button>
          </>}
        </>}
      />

      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16 }}>
          <div>
            <div className="t-cap">Severity</div>
            <Chip tone={DQA_SEVERITY_TONE[rule.severity]} style={{ marginTop: 4 }}>{rule.severity}</Chip>
          </div>
          <div>
            <div className="t-cap">Status</div>
            <Chip tone={DQA_STATUS_TONE[rule.status]} style={{ marginTop: 4 }}>{rule.status.replace("_", " ")}</Chip>
          </div>
          <div>
            <div className="t-cap">Applies to</div>
            <Chip style={{ marginTop: 4 }}>{rule.applicability.entity}</Chip>
            {rule.applicability.age_band && <div className="t-cap mt-1">age {rule.applicability.age_band}</div>}
          </div>
          <div>
            <div className="t-cap">Version</div>
            <div className="t-num" style={{ fontSize: 18, fontWeight: 600, marginTop: 2 }}>v{rule.latestVersion}</div>
          </div>
        </div>
      </div>

      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid var(--neutral-300)', marginTop: 16, flexWrap: 'wrap' }}>
        {[
          { id: "expression", label: "Expression (DSL)" },
          { id: "preview",    label: "Preview & sample failures" },
          { id: "lifecycle",  label: "Lifecycle & approval" },
          { id: "history",    label: "Version history" },
        ].map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: '10px 16px', border: 0,
              borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
              marginBottom: -1, background: 'transparent',
              color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
              fontWeight: active ? 600 : 500, fontSize: 13.5, cursor: 'pointer',
            }}>{t.label}</button>
          );
        })}
      </div>

      {tab === "expression" && (
        <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 0 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <strong className="t-bodysm">DSL expression</strong>
            <span className="t-cap">grammar: <span className="t-mono">apps.dqa.engine</span></span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm"><Icon name="copy" size={12}/> Copy JSON</button>
            {isEditable && <button className="btn btn-sm"><Icon name="edit" size={12}/> Edit</button>}
          </div>
          <pre style={{
            margin: 0, padding: '16px 20px', fontSize: 12.5,
            background: '#0d1f3b', color: '#e2eaf5',
            overflow: 'auto', whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font-mono)', lineHeight: 1.55,
            borderBottomLeftRadius: 4, borderBottomRightRadius: 4,
          }}>{JSON.stringify(sampleExpression, null, 2)}</pre>
        </div>
      )}

      {tab === "preview" && (
        <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 0 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <strong className="t-bodysm">Preview runs</strong>
            <span className="t-cap">audit log — record values are never persisted, only IDs</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm btn-primary"><Icon name="play" size={12}/> Run preview</button>
          </div>
          {previewRuns.length === 0
            ? <div style={{ padding: 32, textAlign: 'center', color: 'var(--neutral-500)' }}>
                <Icon name="play" size={28} color="var(--neutral-300)"/>
                <div className="t-bodysm mt-2">No preview runs yet — run one to see fail-rate before submission.</div>
              </div>
            : <table className="tbl" style={{ boxShadow: 'none' }}>
                <thead><tr><th>Executed</th><th>Sample size</th><th>Pass</th><th>Fail</th><th>Fail rate</th><th>Executed by</th></tr></thead>
                <tbody>
                  {previewRuns.map((p, i) => {
                    const sample = Number(p.sample ?? 0);
                    const passCount = Number(p.passCount ?? 0);
                    const failCount = Number(p.failCount ?? 0);
                    const failRate = sample > 0 ? failCount / sample : 0;
                    return (
                      <tr key={i}>
                        <td className="t-cap">{p.executedAt}</td>
                        <td className="t-num">{sample.toLocaleString()}</td>
                        <td className="t-num">{passCount.toLocaleString()}</td>
                        <td className="t-num">{failCount.toLocaleString()}</td>
                        <td><Chip size="sm" tone={failRate > 0.05 ? 'danger' : failRate > 0.02 ? 'quality' : 'data'}>{(failRate * 100).toFixed(1)}%</Chip></td>
                        <td className="t-bodysm">{p.executedBy}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>}
        </div>
      )}

      {tab === "lifecycle" && (
        <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
          <h4 className="t-h3" style={{ margin: '0 0 14px' }}>Lifecycle</h4>
          <div className="row gap-1" style={{ alignItems: 'center', marginBottom: 18 }}>
            {[
              { id: "draft", icon: "edit" },
              { id: "pending_approval", icon: "clock" },
              { id: "active", icon: "check" },
              { id: "retired", icon: "archive" },
            ].map((s, i, arr) => {
              const order = ["draft","pending_approval","active","retired"];
              const idx = order.indexOf(rule.status);
              const sIdx = order.indexOf(s.id);
              const reached = sIdx <= idx;
              const current = sIdx === idx;
              return (
                <React.Fragment key={s.id}>
                  <div style={{
                    padding: '10px 14px', borderRadius: 6,
                    border: current ? '2px solid var(--primary-900)' : `1px solid ${reached ? 'var(--accent-data)' : 'var(--neutral-300)'}`,
                    background: current ? 'var(--primary-100)' : reached ? 'var(--accent-data-bg, var(--neutral-50))' : 'var(--neutral-0)',
                    color: current ? 'var(--primary-900)' : reached ? 'var(--accent-data)' : 'var(--neutral-500)',
                    fontWeight: current ? 600 : 500, fontSize: 13,
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                  }}>
                    <Icon name={reached && !current ? 'check' : s.icon} size={12}/>
                    {s.id.replace("_", " ")}
                  </div>
                  {i < arr.length - 1 && <div style={{ flex: 1, height: 1, minWidth: 20, background: reached ? 'var(--accent-data)' : 'var(--neutral-300)' }}/>}
                </React.Fragment>
              );
            })}
          </div>
          <div className="tint-update" style={{ padding: 12, borderRadius: 4, borderLeft: '3px solid var(--accent-update)' }}>
            <div className="row gap-2" style={{ marginBottom: 4 }}>
              <Icon name="shield" size={13} color="var(--accent-update)"/>
              <strong className="t-bodysm">No self-approval (AC-DQA-NO-SELF-APPROVE)</strong>
            </div>
            <div className="t-bodysm muted">
              The rule's author cannot approve their own submission. The constraint is enforced at the
              service layer (<span className="t-mono">apps.dqa.services</span>) — bypassing it
              from the API or admin shell returns 400.
            </div>
          </div>
        </div>
      )}

      {tab === "history" && (
        <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 0 }}>
          <table className="tbl" style={{ boxShadow: 'none' }}>
            <thead><tr><th>Version</th><th>Status</th><th>Author</th><th>Approved</th><th>Approval note</th></tr></thead>
            <tbody>
              <tr><td className="t-num">v{rule.latestVersion}</td><td><Chip size="sm" tone={DQA_STATUS_TONE[rule.status]}>{rule.status.replace('_',' ')}</Chip></td><td>{rule.author}</td><td className="t-cap">{rule.approvedAt || '—'}</td><td className="t-bodysm muted">{rule.status === 'active' ? 'Approved as part of release v1.4' : '—'}</td></tr>
              {rule.latestVersion >= 2 && <tr><td className="t-num">v{rule.latestVersion - 1}</td><td><Chip size="sm">Superseded</Chip></td><td>{rule.author}</td><td className="t-cap">04 Jan 2026</td><td className="t-bodysm muted">Initial release.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

Object.assign(window, { AdminDqaRulesScreen });
