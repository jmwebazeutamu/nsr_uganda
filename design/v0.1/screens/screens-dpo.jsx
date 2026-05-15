/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — 11.8 DPO cumulative volume console (US-103)
// AC-DRS-CUMULATIVE: cumulative 7d/30d/90d shown per requester vs DSA budget.
// UI-DPO-1..3 per acceptance.md.

const { useState: useStateDPO } = React;

const DEMO_REQUESTERS = [
  {
    id: "REQ-OPM-001", name: "OPM PDM programme", tier: "MDA",
    dsa: "DSA-OPM-2026-001", budget30d: 250000,
    used7d: 8200, used30d: 41500, used90d: 95000, anomaly: false,
  },
  {
    id: "REQ-NUSAF-001", name: "OPM NUSAF", tier: "MDA",
    dsa: "DSA-OPM-2026-002", budget30d: 250000,
    used7d: 22000, used30d: 287500, used90d: 510000, anomaly: true,
    anomaly_reason: "30d exceeds budget by 15%",
  },
  {
    id: "REQ-WB-RES", name: "World Bank shock-response study", tier: "research",
    dsa: "DSA-WB-2026-007", budget30d: 50000,
    used7d: 4100, used30d: 28000, used90d: 42000, anomaly: false,
  },
  {
    id: "REQ-NGO-FH", name: "Food for the Hungry — Karamoja pilot", tier: "NGO",
    dsa: "DSA-FH-2026-003", budget30d: 20000,
    used7d: 0, used30d: 0, used90d: 0, anomaly: false,
  },
  {
    id: "REQ-UNICEF-N", name: "UNICEF nutrition survey", tier: "research",
    dsa: "DSA-UNICEF-2026-001", budget30d: 50000,
    used7d: 3500, used30d: 90000, used90d: 110000, anomaly: true,
    anomaly_reason: "day-over-day acceleration >50%",
  },
];

const DPOScreen = () => {
  const [active, setActive] = useStateDPO(null);
  const totalActive = DEMO_REQUESTERS.length;
  const rows7d = DEMO_REQUESTERS.reduce((acc, r) => acc + r.used7d, 0);
  const rows30d = DEMO_REQUESTERS.reduce((acc, r) => acc + r.used30d, 0);
  const anomalies = DEMO_REQUESTERS.filter(r => r.anomaly).length;

  return (
    <div className="page">
      <PageHeader
        title="DPO cumulative volume console"
        breadcrumb={["Operator console", "DPO", "Cumulative volume"]}
        tone="system"
      >
        <Chip tone="sec" size="sm">US-103</Chip>
      </PageHeader>

      <div className="row gap-4 mt-3">
        <KPI label="Active requesters" value={totalActive}/>
        <KPI label="Rows shipped (7d)" value={rows7d.toLocaleString()}/>
        <KPI label="Rows shipped (30d)" value={rows30d.toLocaleString()}/>
        <KPI label="Anomaly alerts" value={anomalies} tone={anomalies ? 'danger' : 'data'}/>
      </div>

      <div className="card mt-4">
        <div className="card-header">
          <span>Requesters by cumulative volume</span>
          <span className="t-cap muted">DPPA 2019 · DSA-scoped</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Requester</th>
              <th>Tier</th>
              <th>DSA</th>
              <th className="num">7d</th>
              <th className="num">30d</th>
              <th className="num">90d</th>
              <th className="num">30d budget</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {DEMO_REQUESTERS.map(r => {
              const pct = Math.round((r.used30d / r.budget30d) * 100);
              return (
                <tr key={r.id} onClick={() => setActive(r)} style={{cursor:'pointer'}}>
                  <td>
                    <div style={{fontWeight:500}}>{r.name}</div>
                    <div className="t-cap muted">{r.id}</div>
                  </td>
                  <td><Chip size="sm" tone="api">{r.tier}</Chip></td>
                  <td className="t-mono">{r.dsa}</td>
                  <td className="num">{r.used7d.toLocaleString()}</td>
                  <td className="num">{r.used30d.toLocaleString()} <span className="t-cap muted">({pct}%)</span></td>
                  <td className="num">{r.used90d.toLocaleString()}</td>
                  <td className="num">{r.budget30d.toLocaleString()}</td>
                  <td>
                    {r.anomaly ? (
                      <Chip tone="danger" size="sm">▲ {r.anomaly_reason}</Chip>
                    ) : (
                      <Chip tone="data" size="sm">Within budget</Chip>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {active && <RequesterDrawer requester={active} onClose={() => setActive(null)}/>}
    </div>
  );
};

const RequesterDrawer = ({ requester, onClose }) => {
  // Per UI-DPO-2: drill into requester shows full extract history with query
  // hashes. Per UI-DPO-3: pause / force re-approval / revoke download links.
  return (
    <div className="drawer">
      <div className="drawer-header">
        <div>
          <div className="t-h2">{requester.name}</div>
          <div className="t-cap muted">{requester.id} · {requester.dsa}</div>
        </div>
        <button className="btn btn-ghost" onClick={onClose} aria-label="Close drawer">
          <Icon name="x" size={16}/>
        </button>
      </div>

      <div className="drawer-body">
        <div className="t-h3">Extract history (last 30d)</div>
        <table className="data-table">
          <thead>
            <tr><th>When</th><th>Rows</th><th>Query hash</th><th>State</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>2026-05-14 08:21 EAT</td><td className="num">25,000</td>
              <td className="t-mono">8e7c…1d2f</td><td><Chip size="sm" tone="data">delivered</Chip></td>
            </tr>
            <tr>
              <td>2026-05-12 14:09 EAT</td><td className="num">10,000</td>
              <td className="t-mono">3a9b…dd07</td><td><Chip size="sm" tone="data">delivered</Chip></td>
            </tr>
            <tr>
              <td>2026-05-09 11:50 EAT</td><td className="num">6,500</td>
              <td className="t-mono">f04c…112a</td><td><Chip size="sm" tone="quality">expired</Chip></td>
            </tr>
          </tbody>
        </table>

        <div className="row gap-2 mt-4">
          <button className="btn btn-warn"><Icon name="pause" size={14}/> Pause requester</button>
          <button className="btn"><Icon name="rotateCcw" size={14}/> Force re-approval</button>
          <button className="btn btn-danger"><Icon name="xCircle" size={14}/> Revoke active download links</button>
        </div>
        <div className="t-cap muted mt-3">
          Every action opens a reason modal. The audit chain receives the
          actor, reason, and decision timestamp.
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { DPOScreen });
