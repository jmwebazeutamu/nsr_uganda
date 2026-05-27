/* global React, Icon, Chip */
// NSR MIS — Wizard DQA validation panel (US-S11-044)
// =====================================================
// Live intra-household DQA panel. Calls POST /api/v1/dqa/evaluate/household
// on every field-edit batch and renders per-rule pass / fail / error with
// the severity vocabulary returned by GET /api/v1/dqa/severity-vocabulary.
//
// Contract from /docs/04 + the US-S11-044 spec:
//   - No localStorage / sessionStorage caching of rule definitions or
//     evaluation results. The wizard pulls live from the API on mount
//     and refreshes on field change. (The registry must be
//     reconstructable from the audit chain.)
//   - Severity tokens come from the API (blocks_save flag drives Save /
//     Next gating, per /docs/04 § status palette).
//   - The panel renders nothing while waiting for the first response so
//     enumerators don't see a flash-of-blocking false positive.
//   - The panel is collapsible — empty pass-state shows a one-line "All
//     rules passing" footer, not a full table.
//
// Inputs:
//   payload          household dict (questionnaire shape) — the source of
//                    truth for what the panel just asked the API to
//                    evaluate against
//   stage            one of dih_ingest / dih_promote / registry_post_promote
//   focusField       (optional) "members.relationship_to_head", "household.
//                    reported_household_size", etc. When provided, the
//                    panel filters to rules whose applies_to overlaps the
//                    field — the spec's "subscribe only to rules whose
//                    watched fields overlap" pattern.
//   evaluate         async fn (payload, stage) → response. Defaults to
//                    fetch against /api/v1/dqa/evaluate/household. Tests
//                    inject a fake to avoid network.
//   vocabulary       optional pre-fetched severity vocabulary; falls back
//                    to /api/v1/dqa/severity-vocabulary on mount.
//
// Output:
//   onChange?(result) — fired whenever a new evaluation comes back so the
//                       wizard can update its Save gate.

const { useState: useStateDQAv, useEffect: useEffectDQAv, useMemo: useMemoDQAv } = React;

const _DEFAULT_TONE_BY_TOKEN = {
  "status-danger": "danger",
  "status-danger-soft": "danger",
  "status-warning": "quality",
  "status-info": "data",
};

// Fallback vocabulary used until the API responds. Matches the values
// served by GET /api/v1/dqa/severity-vocabulary.
const _DEFAULT_VOCAB = {
  severities: [
    { value: "block",                label: "Block",               token: "status-danger",      blocks_save: true,  description: "" },
    { value: "reject_with_override", label: "Reject (override)",   token: "status-danger-soft", blocks_save: true,  description: "" },
    { value: "flag",                 label: "Flag",                token: "status-warning",     blocks_save: false, description: "" },
    { value: "info",                 label: "Info",                token: "status-info",        blocks_save: false, description: "" },
  ],
};

const _STAGE_DEFAULT = "dih_ingest";

const _watched = (rule) => {
  // applies_to: { household: [...], members: [...] } — flatten into
  // a flat array of "household.<field>" / "members.<field>" tokens for
  // overlap comparison against focusField.
  const out = [];
  const obj = rule.appliesTo || rule.applies_to || {};
  for (const [bucket, fields] of Object.entries(obj || {})) {
    if (!Array.isArray(fields)) continue;
    for (const f of fields) out.push(`${bucket}.${f}`);
  }
  return out;
};

const DqaValidationPanel = ({
  payload, stage = _STAGE_DEFAULT, focusField = null,
  evaluate, vocabulary,
  onChange,
}) => {
  const [vocab, setVocab] = useStateDQAv(vocabulary || _DEFAULT_VOCAB);
  const [result, setResult] = useStateDQAv(null);
  const [loading, setLoading] = useStateDQAv(false);
  const [error, setError] = useStateDQAv(null);

  // Vocabulary fetch — once on mount unless prop supplied.
  useEffectDQAv(() => {
    if (vocabulary) { setVocab(vocabulary); return; }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/v1/dqa/severity-vocabulary", {
          credentials: "include",
        });
        if (!r.ok) return;
        const body = await r.json();
        if (!cancelled) setVocab(body);
      } catch (_e) { /* keep default vocab */ }
    })();
    return () => { cancelled = true; };
  }, [vocabulary]);

  // Per-payload evaluation. The dependency on JSON.stringify(payload)
  // is intentional — every field-edit batch should refetch since the
  // spec forbids stale/cached evaluation results.
  const payloadJson = JSON.stringify(payload || {});
  useEffectDQAv(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const run = evaluate || (async (p, s) => {
      const r = await fetch("/api/v1/dqa/evaluate/household", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: p, stage: s }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
    (async () => {
      try {
        const body = await run(JSON.parse(payloadJson), stage);
        if (cancelled) return;
        setResult(body);
        // onChange is fired once below in the blocking-failures
        // effect so the wizard always sees a payload that carries
        // _wizard_blocks_save. Firing it here too would leave the
        // last call without the flag.
      } catch (e) {
        if (!cancelled) setError(String(e.message || e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payloadJson, stage]);

  const severityIndex = useMemoDQAv(() => {
    const map = {};
    for (const s of (vocab.severities || [])) map[s.value] = s;
    return map;
  }, [vocab]);

  const filteredResults = useMemoDQAv(() => {
    const rows = (result && result.results) || [];
    if (!focusField) return rows;
    // When the wizard tells us which field the operator just touched,
    // narrow to rules whose applies_to overlaps that field. The
    // results payload doesn't carry applies_to — but in the live API
    // we pass the rule directly. To avoid an extra request, the
    // wizard supplies focusField as advisory and we keep the full
    // list when the result rows don't have watched-field metadata.
    return rows.filter(r => {
      const watched = _watched(r);
      if (watched.length === 0) return true;
      return watched.includes(focusField);
    });
  }, [result, focusField]);

  const blockingFailures = useMemoDQAv(() => {
    return filteredResults.filter(r => {
      if (r.status === "pass") return false;
      const sev = severityIndex[r.severity];
      return sev && sev.blocks_save;
    });
  }, [filteredResults, severityIndex]);

  // Expose the boolean for the wizard's Save gate.
  useEffectDQAv(() => {
    if (typeof onChange === "function") {
      onChange({ ...result, _wizard_blocks_save: blockingFailures.length > 0 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockingFailures.length]);

  if (loading && !result) {
    return (
      <div className="card" data-testid="dqa-panel-loading" style={{ padding: 12 }}>
        <Icon name="clock" size={12}/> <span className="t-bodysm muted">Validating household…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" data-testid="dqa-panel-error" style={{ padding: 12, borderLeft: '3px solid var(--accent-danger)' }}>
        <Icon name="alert" size={12}/> <span className="t-bodysm">DQA validation unavailable: {error}</span>
      </div>
    );
  }

  if (!result) return null;

  const failures = filteredResults.filter(r => r.status !== "pass");
  if (failures.length === 0) {
    return (
      <div className="card" data-testid="dqa-panel-pass" style={{ padding: 10, borderLeft: '3px solid var(--accent-data)' }}>
        <Icon name="check" size={12} color="var(--accent-data)"/>{' '}
        <span className="t-bodysm">All intra-household rules passing.</span>
        {result.rules_evaluated !== undefined && (
          <span className="t-cap" style={{ marginLeft: 8 }}>
            {result.rules_evaluated} rule{result.rules_evaluated === 1 ? '' : 's'} checked
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="card" data-testid="dqa-panel" style={{ padding: 0 }}>
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <Icon name="alert" size={14} color={blockingFailures.length > 0 ? 'var(--accent-danger)' : 'var(--accent-warning, var(--accent-quality))'}/>
        <strong className="t-bodysm">
          {failures.length} intra-household issue{failures.length === 1 ? '' : 's'}
        </strong>
        {blockingFailures.length > 0 && (
          <Chip size="sm" tone="danger">{blockingFailures.length} blocking save</Chip>
        )}
        <div style={{ flex: 1 }}/>
        {result.evaluator_service_version && (
          <span className="t-cap">evaluator v{result.evaluator_service_version}</span>
        )}
      </div>
      <table className="tbl" data-testid="dqa-panel-table" style={{ boxShadow: 'none' }}>
        <thead><tr><th>Rule</th><th>Severity</th><th>Message</th><th>Members</th></tr></thead>
        <tbody>
          {failures.map((r, i) => {
            const sev = severityIndex[r.severity] || { label: r.severity, token: "status-info" };
            const tone = _DEFAULT_TONE_BY_TOKEN[sev.token] || "data";
            return (
              <tr key={`${r.rule_code}:${i}`} data-testid={`dqa-row-${r.rule_code}`}>
                <td className="t-mono t-bodysm">{r.rule_code} v{r.rule_version}</td>
                <td><Chip size="sm" tone={tone}>{sev.label}</Chip></td>
                <td className="t-bodysm">{r.message || '—'}</td>
                <td className="t-cap">
                  {(r.offending_member_ids || []).length === 0 ? '—'
                    : (r.offending_member_ids || []).join(", ")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

// Harness exposes the component on globalThis so the design preview +
// Vitest specs can pick it up without an ES-module build step (same
// pattern as scope-edit-modal).
if (typeof globalThis !== "undefined") {
  globalThis.DqaValidationPanel = DqaValidationPanel;
}
