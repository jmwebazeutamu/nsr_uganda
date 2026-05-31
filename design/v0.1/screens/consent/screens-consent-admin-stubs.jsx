/* global React,
   Icon, Chip, KPI, PageHeader,
   PURPOSES, BasisChip, LifecycleChip, ConsentStateChip */
// NSR MIS — Consent admin stub screens (US-CONSENT-01, -02, -17)
// =====================================================
// Module family: SEC. These are the S27 stubs the build prompt asks for —
// the Purposes catalogue, Statement-version editor, and DPO Coverage
// dashboard. They render the live vocabulary + KPI shape against the
// /api/v1/consent/ surface; the rich editors land in S28. The DPO
// Withdrawal Queue is the fully-built Screen 4 (screens-consent-dpo-queue).

const { useState: useStateCA } = React;

/* ---------- US-CONSENT-01 — Purpose catalogue (stub) ---------- */
const ConsentPurposesScreen = () => (
  <div style={{ padding: 24 }}>
    <PageHeader
      title="Consent purposes"
      subtitle="Catalogue · dual-approved (author ≠ approver) · US-CONSENT-01"
    />
    <table className="t-bodysm" style={{ width: "100%", borderCollapse: "collapse", marginTop: 16 }}>
      <thead>
        <tr style={{ textAlign: "left", color: "var(--neutral-500)" }}>
          <th style={{ padding: "8px 12px" }}>Code</th>
          <th style={{ padding: "8px 12px" }}>Name</th>
          <th style={{ padding: "8px 12px" }}>Lawful basis</th>
          <th style={{ padding: "8px 12px" }}>Withdrawable</th>
          <th style={{ padding: "8px 12px" }}>Status</th>
        </tr>
      </thead>
      <tbody>
        {PURPOSES.map(p => (
          <tr key={p.code} style={{ borderTop: "1px solid var(--neutral-200)" }}>
            <td style={{ padding: "8px 12px", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{p.code}</td>
            <td style={{ padding: "8px 12px" }}>{p.name}</td>
            <td style={{ padding: "8px 12px" }}><BasisChip basis={p.basis} title={p.basisNote || p.basis}/></td>
            <td style={{ padding: "8px 12px" }}>
              <Icon name={p.withdrawable ? "check" : "lock"} size={14}
                    color={p.withdrawable ? "var(--accent-data)" : "var(--neutral-500)"}/>
            </td>
            <td style={{ padding: "8px 12px" }}><LifecycleChip state="Active" size="sm"/></td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

/* ---------- US-CONSENT-02 — Statement version editor (stub) ---------- */
const ConsentStatementsScreen = () => (
  <div style={{ padding: 24 }}>
    <PageHeader
      title="Statement versions"
      subtitle="Versioned statement text · one ACTIVE per purpose · US-CONSENT-02"
    />
    <div className="t-bodysm muted" style={{ marginTop: 16 }}>
      The v3 English statement is seeded ACTIVE on REGISTRATION; the six
      Ugandan languages carry placeholder bodies. Activating a statement
      marked <b>material</b> flags every GRANTED record <ConsentStateChip
      state="Pending re-consent" size="sm"/> and shows the count before
      commit. The full i18n editor lands in S28.
    </div>
  </div>
);

/* ---------- US-CONSENT-17 — DPO coverage dashboard (stub) ---------- */
const ConsentCoverageScreen = () => {
  const [data, setData] = useStateCA(null);
  React.useEffect(() => {
    let live = true;
    fetch("/api/v1/consent/coverage", { credentials: "same-origin" })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (live) setData(d); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  const byState = (data && data.consent_records_by_state) || {};
  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="Consent coverage"
        subtitle="DPO dashboard · KPI cards live · charts deferred · US-CONSENT-17"
      />
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 16 }}>
        <KPI label="Active purposes" value={data ? data.active_purposes : "—"}/>
        <KPI label="Granted" value={byState.GRANTED || 0}/>
        <KPI label="Withdrawn" value={byState.WITHDRAWN || 0}/>
        <KPI label="Open withdrawals" value={data ? data.open_withdrawal_tickets : "—"}/>
        <KPI label="SLA breached" value={data ? data.sla_breached : "—"}
             tone={data && data.sla_breached ? "danger" : "neutral"}/>
      </div>
      <div className="t-bodysm muted" style={{ marginTop: 24 }}>
        Production charting (coverage-by-sub-region, withdrawal trend) is
        deferred to a later sprint.
      </div>
    </div>
  );
};

Object.assign(window, {
  ConsentPurposesScreen, ConsentStatementsScreen, ConsentCoverageScreen,
});
