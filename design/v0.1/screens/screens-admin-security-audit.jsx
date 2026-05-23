/* global React, Icon, Chip, PageHeader, KPI */
// NSR MIS — Admin · Security · Audit Chain
// =========================================================
// Browse the append-only, hash-chained audit log.
// Maps to: apps.security.models.AuditEvent
//   (actor_id, action, entity_type/entity_id, field_changes,
//    prev_hash, self_hash, ip_address, user_agent, occurred_at)
//
// The hash chain is computed by a DB trigger so application bugs
// cannot break it (migration 0002). This screen surfaces:
//   - paginated event browser with filters
//   - one event detail with chain verification status
//   - global chain health (verified to head)

const { useState: useStateAUD, useMemo: useMemoAUD } = React;

const AUD_ACTIONS = ["create","read","update","soft_delete","hard_delete","merge","unmerge","promote","reject"];
const AUD_ENTITY_TYPES = ["household","member","pmt_model_version","pmt_result","dqa_rule","ddup_match_pair","change_request","choice_list","partner","programme","data_request"];

const AUD_EVENTS = [
  { id:"01HXP4M8N1K6FB7K6FZRWS2201", occurred:"22 May 2026 · 14:08:21", actor:"akello.p", actorKind:"user", action:"update", entityType:"household", entityId:"01KRPPW6WRGRJZY0N4XN8R1YC2", reason:"Approved UPD-2026-05-22-00188", ip:"196.43.221.18", changes:{"roof_material":{"old":"thatch","new":"metal"}}, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2200", occurred:"22 May 2026 · 14:02:18", actor:"system-ref", actorKind:"system", action:"update", entityType:"programme", entityId:"OPM-PDM", reason:"enrolment.activated batch wh-2026-05-22-088", ip:"10.0.0.42", changes:{"enrolled":{"old":1486807,"new":1487219}}, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2199", occurred:"22 May 2026 · 02:00:04", actor:"celery-beat", actorKind:"system", action:"create", entityType:"pmt_band_threshold", entityId:"01HXP4M8N1K6FB7K6FZRWS00", reason:"daily recompute · v1 · 4 bands · n=12,108,331", ip:"10.0.0.51", changes:null, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2198", occurred:"21 May 2026 · 16:44:02", actor:"otieno.j", actorKind:"user", action:"promote", entityType:"pmt_model_version", entityId:"01HXM12Z4F7N6P0V8K9TB2QXJK", reason:"Signed step 3/3 — activation of v2", ip:"196.43.221.32", changes:null, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2197", occurred:"21 May 2026 · 14:18:51", actor:"nakanwagi.d", actorKind:"user", action:"create", entityType:"pmt_model_version", entityId:"01HXM12Z4F7N6P0V8K9TB2QXJK", reason:"Submitted v2 for approval", ip:"196.43.221.40", changes:null, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2196", occurred:"21 May 2026 · 11:08:14", actor:"adong.f", actorKind:"user", action:"merge", entityType:"member", entityId:"01HXR9P2K7N6FB7K6FZRWS01", reason:"Manual merge — same NIN match", ip:"41.78.12.4", changes:{"surviving":"M-01KRPPW6WR-002","losing":"M-01KRPPW6WR-099"}, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2195", occurred:"21 May 2026 · 09:58:01", actor:"akello.p", actorKind:"user", action:"read", entityType:"member", entityId:"M-01KRPPW6WR-002", reason:"PII reveal · NIN value", ip:"196.43.221.18", changes:null, chainOk: true, piiReveal: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2194", occurred:"20 May 2026 · 22:14:50", actor:"system-nira", actorKind:"system", action:"update", entityType:"member", entityId:"M-01HXP02CN4-002", reason:"NIN verified · match score 0.98", ip:"10.0.0.62", changes:{"nin_verification_status":{"old":"pending","new":"verified"}}, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2193", occurred:"20 May 2026 · 14:48:21", actor:"bahati.e", actorKind:"user", action:"create", entityType:"data_request", entityId:"DR-2026-05-20-00041", reason:"Submitted DRS request — DSA-OPM-PDM-2026", ip:"41.78.12.18", changes:null, chainOk: true },
  { id:"01HXP4M8N1K6FB7K6FZRWS2192", occurred:"20 May 2026 · 11:08:22", actor:"otieno.j", actorKind:"user", action:"reject", entityType:"change_request", entityId:"UPD-2026-05-20-00211", reason:"Insufficient evidence — photo blurry", ip:"196.43.221.32", changes:null, chainOk: true },
];

const AUD_ACTION_TONE = {
  create: "data", read: "system", update: "update", soft_delete: "quality",
  hard_delete: "danger", merge: "programme", unmerge: "quality", promote: "data", reject: "danger",
};

const AdminAuditScreen = () => {
  const [q, setQ] = useStateAUD("");
  const [actorFilter, setActorFilter] = useStateAUD("");
  const [actionFilter, setActionFilter] = useStateAUD("");
  const [entityFilter, setEntityFilter] = useStateAUD("");
  const [selected, setSelected] = useStateAUD(null);

  const events = useMemoAUD(() => AUD_EVENTS.filter(e => {
    if (q && !(e.actor.includes(q.toLowerCase()) || e.entityId.toLowerCase().includes(q.toLowerCase()) || (e.reason || "").toLowerCase().includes(q.toLowerCase()))) return false;
    if (actorFilter && e.actorKind !== actorFilter) return false;
    if (actionFilter && e.action !== actionFilter) return false;
    if (entityFilter && e.entityType !== entityFilter) return false;
    return true;
  }), [q, actorFilter, actionFilter, entityFilter]);

  const totalEvents = "412,890,221";
  const last24h = "1,408,221";
  const piiReveals7d = 38;
  const chainHead = AUD_EVENTS[0];

  if (selected) {
    const e = AUD_EVENTS.find(x => x.id === selected);
    return <AuditEventDetail event={e} onBack={() => setSelected(null)}/>;
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · SECURITY · audit chain"
        title="Audit chain"
        sub="Append-only, hash-chained. The chain is computed by a database trigger so application bugs cannot break it. 10-year retention (SAD §8.4)."
        right={<>
          <button className="btn"><Icon name="shield" size={14}/> Verify chain</button>
          <button className="btn"><Icon name="download" size={14}/> Export window</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Events in chain" value={totalEvents} foot="Since 04 Jan 2026 · 10-year retention"/>
        <KPI title="Last 24 hours" value={last24h} foot="Average 16.3k/hour" spark={[1.2,1.3,1.3,1.4,1.4,1.4,1.4,1.4]}/>
        <KPI title="PII reveals (7d)" value={piiReveals7d} foot="NIN / DoB / photo unmask" trend="up" trendValue="+8 from 7d prior"/>
        <KPI title="Chain integrity" value="✓ verified" foot={`Verified to head ${chainHead.id.slice(0,16)}…`}/>
      </div>

      <div className="card mt-5" style={{ padding: '14px 16px' }}>
        <div className="row gap-3" style={{ flexWrap: 'wrap' }}>
          <div className="search" style={{ maxWidth: 360, height: 34, background: 'var(--neutral-0)' }}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search actor, entity ID, or reason…"/>
          </div>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 140 }} value={actorFilter} onChange={e => setActorFilter(e.target.value)}>
            <option value="">Any actor</option>
            <option value="user">User</option>
            <option value="system">System</option>
          </select>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 160 }} value={actionFilter} onChange={e => setActionFilter(e.target.value)}>
            <option value="">Any action</option>
            {AUD_ACTIONS.map(a => <option key={a}>{a}</option>)}
          </select>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 180 }} value={entityFilter} onChange={e => setEntityFilter(e.target.value)}>
            <option value="">Any entity type</option>
            {AUD_ENTITY_TYPES.map(e => <option key={e}>{e}</option>)}
          </select>
          <div style={{ flex: 1 }}/>
          <span className="t-cap">{events.length} of {AUD_EVENTS.length}</span>
        </div>
      </div>

      <div className="card mt-4">
        <table className="tbl">
          <thead>
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Reason</th>
              <th>IP</th>
              <th>Chain</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {events.map(e => (
              <tr key={e.id} style={{ cursor: 'pointer' }} onClick={() => setSelected(e.id)}>
                <td className="t-cap" style={{ whiteSpace: 'nowrap' }}>{e.occurred}</td>
                <td>
                  <div className="row gap-2">
                    <Chip size="sm" tone={e.actorKind === "user" ? "data" : "neutral"}>{e.actorKind}</Chip>
                    <span className="t-mono t-bodysm">{e.actor}</span>
                  </div>
                </td>
                <td><Chip size="sm" tone={AUD_ACTION_TONE[e.action]}>{e.action}</Chip></td>
                <td>
                  <div className="t-mono t-cap">{e.entityType}</div>
                  <div className="t-mono t-cap" style={{ color: 'var(--accent-system)', whiteSpace:'nowrap' }}>{e.entityId.slice(0, 20)}{e.entityId.length > 20 ? '…' : ''}</div>
                </td>
                <td className="t-bodysm" style={{ maxWidth: 280 }}>
                  {e.piiReveal && <Chip size="sm" tone="danger" style={{ marginRight: 6 }}><Icon name="shield" size={9}/> PII</Chip>}
                  {e.reason}
                </td>
                <td className="t-mono t-cap">{e.ip}</td>
                <td>
                  {e.chainOk
                    ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> ok</Chip>
                    : <Chip size="sm" tone="danger">broken</Chip>}
                </td>
                <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="tint-update mt-4" style={{ padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)' }}>
        <div className="row gap-2" style={{ marginBottom: 4 }}>
          <Icon name="shield" size={13} color="var(--accent-update)"/>
          <strong className="t-bodysm">Hash chain</strong>
        </div>
        <div className="t-bodysm muted">
          Each row carries <span className="t-mono">self_hash = sha256(prev_hash || canonical(this_row))</span> computed
          by a DB trigger on insert (migration <span className="t-mono">apps/security/migrations/0002</span>).
          <strong> Verify chain </strong> walks the chain from genesis to head and reports the first row, if any, whose
          stored hash doesn't match its recomputation — that detects tampering and accidental deletes.
        </div>
      </div>
    </div>
  );
};

const AuditEventDetail = ({ event, onBack }) => {
  return (
    <div className="page">
      <PageHeader
        eyebrow={<>ADMIN · SECURITY · AUDIT · <span className="t-mono">{event.id}</span></>}
        title={`${event.action.toUpperCase()} on ${event.entityType}:${event.entityId.slice(0, 20)}…`}
        sub={<>{event.occurred} · actor <strong>{event.actor}</strong></>}
        right={<button className="btn" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to audit</button>}
      />

      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 8, fontSize: 13 }}>
          <div className="muted">Event ID</div><div className="t-mono">{event.id}</div>
          <div className="muted">Occurred at</div><div>{event.occurred}</div>
          <div className="muted">Actor</div>
          <div>
            <Chip size="sm" tone={event.actorKind === "user" ? "data" : "neutral"}>{event.actorKind}</Chip>
            <span className="t-mono" style={{ marginLeft: 8 }}>{event.actor}</span>
          </div>
          <div className="muted">Action</div><div><Chip size="sm" tone={AUD_ACTION_TONE[event.action]}>{event.action}</Chip></div>
          <div className="muted">Entity</div>
          <div>
            <span className="t-mono">{event.entityType}</span>
            <span className="t-mono" style={{ marginLeft: 8, color: 'var(--accent-system)' }}>{event.entityId}</span>
          </div>
          <div className="muted">Reason</div>
          <div className="t-bodysm">
            {event.piiReveal && <Chip size="sm" tone="danger" style={{ marginRight: 6 }}><Icon name="shield" size={9}/> PII reveal</Chip>}
            {event.reason}
          </div>
          <div className="muted">Source IP</div><div className="t-mono">{event.ip}</div>
        </div>
      </div>

      {event.changes && (
        <div className="card mt-4" style={{ padding: 0 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Field changes</strong>
            <div className="t-cap">JSON dict of old → new values. PII-classified fields are redacted unless the viewer has scope.</div>
          </div>
          <pre style={{ margin: 0, padding: 16, fontSize: 12.5, background: '#0d1f3b', color: '#e2eaf5', overflow: 'auto', fontFamily: 'var(--font-mono)', lineHeight: 1.55 }}>{JSON.stringify(event.changes, null, 2)}</pre>
        </div>
      )}

      <div className="card mt-4" style={{ padding: 0 }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)' }}>
          <strong>Chain integrity</strong>
          <div className="t-cap">SHA-256, computed by a DB trigger. Tamper-evident.</div>
        </div>
        <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 8, fontSize: 13 }}>
          <div className="muted">prev_hash</div><div className="t-mono" style={{ fontSize: 11, wordBreak: 'break-all' }}>0x{"e8d2c7a4f12e9a47b3c4d8e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b"}</div>
          <div className="muted">self_hash</div><div className="t-mono" style={{ fontSize: 11, wordBreak: 'break-all' }}>0x{"a1b2c3d4e5f6789012345678abcdef9012345678abcdef0123456789abcdef0123"}</div>
          <div className="muted">Verified</div>
          <div>
            {event.chainOk
              ? <Chip tone="data"><Icon name="check" size={11}/> hash matches</Chip>
              : <Chip tone="danger">chain broken</Chip>}
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { AdminAuditScreen });
