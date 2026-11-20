/* global React, Chip, PageHeader, KPI, useApi */
// NSR MIS — Admin · AI oversight
// =========================================================
// Read-only. Where each AI feature stands, which model drives it, how it
// measures against reviewer decisions, and what it last scored (ADR-0045).
//
// This is the view for the people who decide whether a feature leaves
// SHADOW, so it lists suggestions in every state and says, per feature,
// whether reviewers can see them. It never decides anything:
//   - state labels and tones arrive from the server (`ui_tone` codes);
//   - "who may see a suggestion" is the server's `shown_to_reviewers`;
//   - there is no write control. Changing a feature's state is
//     `manage.py ai_feature` until open item AI-O-06 names who may.
//
// Endpoints:
//   GET /api/v1/admin/ai/overview/
//   GET /api/v1/admin/ai/suggestions/?feature=<code>&limit=50

const { useState: useStateAi } = React;

// Africa/Kampala is EAT (UTC+3). Stored UTC, rendered EAT (CLAUDE.md).
const _aiWhen = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Kampala", day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(d) + " EAT";
};

const _aiPct = (v) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—");

// One line saying what drove the score. The server owns the keys; this
// only lays them out.
const _aiWhy = (row) => {
  const d = row.details || {};
  const parts = d.contributions || d.z;
  if (!parts) return "—";
  return Object.entries(parts).map(([k, v]) => `${k} ${v}`).join(" · ");
};

const AiStateChip = ({ state }) => (
  <Chip size="sm" tone={state.tone}>{state.label}</Chip>
);

const AiFeatureCard = ({ feature, selected, onSelect }) => {
  const m = feature.model;
  const ev = feature.evaluation;
  const run = feature.last_run;
  return (
    <div className="card" role="button" tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}
      style={{
        padding: 16, cursor: "pointer",
        borderLeft: selected ? "3px solid var(--accent-system)" : "3px solid transparent",
      }}>
      <div className="row gap-2" style={{ alignItems: "baseline", justifyContent: "space-between" }}>
        <strong>{feature.label}</strong>
        <AiStateChip state={feature.effective_state}/>
      </div>
      {feature.stored_state.code !== feature.effective_state.code && (
        <div className="t-cap mt-1">
          Set to {feature.stored_state.label}, running as {feature.effective_state.label}.
        </div>
      )}
      <div className="t-cap mt-2">
        {m
          ? <>Model <strong>{m.name} v{m.version}</strong> · owner {m.owner} · validated {m.validated_on || "never"}</>
          : "No model attached."}
      </div>
      <div className="t-cap mt-1">
        Reviewers {feature.shown_to_reviewers ? "can" : "cannot"} see its suggestions.
      </div>
      <div className="t-cap mt-2">
        Measured against reviewers: <strong>{ev.labelled}</strong> decisions · precision <strong>{_aiPct(ev.precision)}</strong>
        {" · "}{ev.meets_gate ? "gate met" : "gate not met"}
      </div>
      {!ev.meets_gate && ev.reasons.length > 0 && (
        <ul className="t-cap" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          {ev.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <div className="t-cap mt-2">
        {run
          ? <>Last run {_aiWhen(run.started_at)} · {run.scored.toLocaleString()} scored · {run.skipped.toLocaleString()} skipped · {run.state}</>
          : "Never run."}
      </div>
    </div>
  );
};

const AiSuggestionsTable = ({ feature }) => {
  const [resp, meta] = (typeof useApi === "function")
    ? useApi(`/api/v1/admin/ai/suggestions/?feature=${encodeURIComponent(feature.code)}&limit=50`)
    : [null, { loading: false, error: null }];
  if (meta && meta.loading) return <div className="t-cap muted" style={{ padding: 16 }}>Loading suggestions…</div>;
  if (meta && meta.error) {
    return <div className="t-cap" role="alert" style={{ padding: 16, color: "var(--danger-700)" }}>
      Suggestions could not be loaded ({meta.error}).
    </div>;
  }
  const rows = (resp && resp.results) || [];
  if (!rows.length) {
    return <div className="t-cap muted" style={{ padding: 16 }}>
      No suggestions yet. Nothing has been scored for {feature.label}.
    </div>;
  }
  return (
    <>
      <div className="t-cap" style={{ padding: "8px 16px" }}>
        Newest run, highest score first — {rows.length.toLocaleString()} of {resp.total.toLocaleString()}.
        {resp.shown_to_reviewers
          ? " Reviewers can see these."
          : " Reviewers cannot see these; they exist so the feature can be measured."}
      </div>
      <table className="tbl" style={{ boxShadow: "none" }}>
        <thead>
          <tr><th>Subject</th><th>Score</th><th>What drove it</th><th>Reviewer decided</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><span className="t-mono">{r.subject_type}:{r.subject_id}</span></td>
              <td>{Number(r.score).toFixed(3)}{r.details && r.details.flagged ? " · flagged" : ""}</td>
              <td className="t-cap">{_aiWhy(r)}</td>
              <td>{r.reviewer_outcome ? r.reviewer_outcome.label : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
};

const AdminAiScreen = () => {
  const [overview, meta] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/ai/overview/")
    : [null, { loading: false, error: null }];
  const [picked, setPicked] = useStateAi(null);

  const header = (
    <PageHeader
      eyebrow="ADMIN · AI OVERSIGHT"
      title="AI suggestions"
      sub="Advisory only. A model never changes a record; reviewers decide. Features start in shadow so they can be measured before anyone sees them."
    />
  );

  if (meta && meta.loading) return <div className="page">{header}<div className="t-cap muted">Loading…</div></div>;
  if (meta && meta.error) {
    return <div className="page">{header}
      <div className="t-cap" role="alert" style={{ color: "var(--danger-700)" }}>
        AI status could not be loaded ({meta.error}).
      </div></div>;
  }
  const features = (overview && overview.features) || [];
  const selected = features.find((f) => f.code === picked) || features[0] || null;
  const live = features.filter((f) => f.effective_state.code !== "off").length;

  return (
    <div className="page">
      {header}
      {!overview.master_enabled && (
        <div className="card" role="status" style={{ padding: 12, marginBottom: 16 }}>
          <strong>AI services are switched off.</strong>{" "}
          <span className="t-cap">The master switch (AI_SERVICES_ENABLED) is off, so no feature runs and no suggestion is produced, whatever the rows below say.</span>
        </div>
      )}
      <div className="grid grid-4">
        <KPI title="Features" value={features.length} foot="registered AI features"/>
        <KPI title="Running" value={live} foot="in shadow or advisory"/>
        <KPI title="Visible to reviewers"
             value={features.filter((f) => f.shown_to_reviewers).length}
             foot="advisory features only"/>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "360px 1fr", gap: 16, marginTop: 16 }}>
        <div style={{ display: "grid", gap: 12, alignSelf: "start" }}>
          {features.map((f) => (
            <AiFeatureCard key={f.code} feature={f}
              selected={selected && selected.code === f.code}
              onSelect={() => setPicked(f.code)}/>
          ))}
          <div className="t-cap">
            To change a feature's state, an operator runs <span className="t-mono">manage.py ai_feature set</span>.
            Turning one off needs no approval and takes effect on the next call.
          </div>
        </div>
        <div className="card" style={{ padding: 0, alignSelf: "start" }}>
          {selected
            ? <AiSuggestionsTable key={selected.code} feature={selected}/>
            : <div className="t-cap muted" style={{ padding: 16 }}>No AI features are registered.</div>}
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { AdminAiScreen });
