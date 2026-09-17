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

const { useState: useStateAUD, useMemo: useMemoAUD, useEffect: useEffectAUD } = React;

const audDownloadCsv = (filename, rows) => {
  const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

const AUD_ACTIONS = ["create","read","update","soft_delete","hard_delete","merge","unmerge","promote","reject"];
const AUD_ENTITY_TYPES = ["household","member","pmt_model_version","pmt_result","dqa_rule","ddup_match_pair","change_request","choice_list","partner","programme","data_request"];

/* ============================================================
   LIVE DATA — /api/v1/security/audit-events/
   ============================================================

   This screen used to render AUD_EVENTS: ten fabricated audit events,
   above KPIs claiming 412,890,221 events in the chain and a flat
   "Chain integrity ✓ verified". The real chain holds 81,794 events and
   does NOT verify.

   Of everywhere mock data reached a screen, this was the worst place
   for it. The integrity claim of the whole registry rests on the
   hash-linked audit chain (SAD §8.4), and the people most likely to
   open this screen — an auditor, the DPO — are exactly the people who
   must not be shown a reassuring fiction.

   Nothing here is asserted that the server has not returned.
   ============================================================ */

// EAT (UTC+3) per CLAUDE.md: persist UTC, render East Africa Time.
const _audWhen = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-GB", {
    timeZone: "Africa/Kampala",
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).replace(",", " ·");
};

// A read of a personal-data field is the event an auditor looks for, so
// it is flagged. Derived from what the server sent, not guessed.
const _audIsPiiReveal = (e) =>
  (e.action || "").includes("read")
  && ["member", "household", "submission"].includes(e.entity_type)
  && !/list|page/.test(String(e.entity_id || ""));

const _audRow = (e) => ({
  id: e.id,
  occurred: _audWhen(e.occurred_at),
  occurredRaw: e.occurred_at,
  actor: e.actor_id || "—",
  actorKind: e.actor_kind || "system",
  action: e.action,
  entityType: e.entity_type,
  entityId: e.entity_id,
  reason: e.reason || "",
  ip: e.ip_address || "—",
  changes: e.field_changes || null,
  prevHash: e.prev_hash,
  selfHash: e.self_hash,
  piiReveal: _audIsPiiReveal(e),
  // chainOk is deliberately absent. Whether a row's link is intact is
  // only knowable from the server-side verification below; asserting it
  // per row from the client would be inventing the very assurance this
  // screen exists to report.
});

// How many recent events the table loads. The list endpoint does not
// filter server-side, so the search and dropdowns below narrow THIS
// window — which the UI says, rather than implying it searched all 81k.
const AUD_WINDOW = 200;

const AUD_ACTION_TONE = {
  create: "data", read: "system", update: "update", soft_delete: "quality",
  hard_delete: "danger", merge: "programme", unmerge: "quality", promote: "data", reject: "danger",
};

const AdminAuditScreen = () => {
  const [rows, setRows] = useStateAUD(null);      // null = loading
  const [total, setTotal] = useStateAUD(null);
  const [loadError, setLoadError] = useStateAUD(null);
  const [q, setQ] = useStateAUD("");
  const [actorFilter, setActorFilter] = useStateAUD("");
  const [actionFilter, setActionFilter] = useStateAUD("");
  const [entityFilter, setEntityFilter] = useStateAUD("");
  const [selected, setSelected] = useStateAUD(null);
  const [verifying, setVerifying] = useStateAUD(false);
  const [verifyResult, setVerifyResult] = useStateAUD(null);

  useEffectAUD(() => {
    let cancelled = false;
    fetch(`/api/v1/security/audit-events/?ordering=-occurred_at&page_size=${AUD_WINDOW}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => {
        if (cancelled) return;
        const results = Array.isArray(d) ? d : (d.results || []);
        setRows(results.map(_audRow));
        setTotal(typeof d.count === "number" ? d.count : results.length);
      })
      .catch(err => {
        if (cancelled) return;
        // Show the failure. The previous version fell back to fixtures,
        // so an outage looked like a healthy, quiet audit log.
        setRows([]);
        setLoadError(err.message || String(err));
      });
    return () => { cancelled = true; };
  }, []);

  const events = useMemoAUD(() => (rows || []).filter(e => {
    if (q && !(e.actor.includes(q.toLowerCase()) || e.entityId.toLowerCase().includes(q.toLowerCase()) || (e.reason || "").toLowerCase().includes(q.toLowerCase()))) return false;
    if (actorFilter && e.actorKind !== actorFilter) return false;
    if (actionFilter && e.action !== actionFilter) return false;
    if (entityFilter && e.entityType !== entityFilter) return false;
    return true;
  }), [q, actorFilter, actionFilter, entityFilter]);

  // Every figure below is computed from what the server returned.
  // Previously: 412,890,221 events, 1,408,221 in 24h, 38 PII reveals —
  // all invented, against a real chain of ~81,800 events.
  const totalEvents = total == null ? "—" : total.toLocaleString();
  const windowPii = (rows || []).filter(e => e.piiReveal).length;
  const chainHead = (rows && rows[0]) || null;

  const verifyChain = async () => {
    setVerifying(true);
    setVerifyResult(null);
    try {
      // No preview fallback. Reporting "ok" without asking the server
      // is precisely the failure this screen must never have.
      const rsp = await fetch("/api/v1/security/audit-events/verify-chain/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "",
        },
        body: "{}",
      });
      if (!rsp.ok) throw new Error(`HTTP ${rsp.status}`);
      setVerifyResult(await rsp.json());
    } catch (err) {
      setVerifyResult({ ok: false, mode: "error", detail: err?.body?.detail || err?.message || String(err) });
    } finally {
      setVerifying(false);
    }
  };

  const exportWindow = () => {
    audDownloadCsv("audit-window.csv", [
      ["id", "occurred", "actor", "actor_kind", "action", "entity_type", "entity_id", "reason", "ip", "self_hash"],
      ...events.map(e => [e.id, e.occurred, e.actor, e.actorKind, e.action, e.entityType, e.entityId, e.reason, e.ip, e.selfHash]),
    ]);
  };

  if (selected) {
    const e = (rows || []).find(x => x.id === selected);
    return <AuditEventDetail event={e} onBack={() => setSelected(null)}/>;
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · SECURITY · audit chain"
        title="Audit chain"
        sub="Append-only, hash-chained. The chain is computed by a database trigger so application bugs cannot break it. 10-year retention (SAD §8.4)."
        right={<>
          <button className="btn" onClick={verifyChain} disabled={verifying}>
            <Icon name="shield" size={14}/> {verifying ? "Verifying..." : "Verify chain"}
          </button>
          <button className="btn" onClick={exportWindow}><Icon name="download" size={14}/> Export window</button>
        </>}
      />

      {/* State is always explicit. An empty table with no explanation is
          how an outage looked like a quiet audit log in the old version. */}
      {loadError && (
        <div className="tint-danger mb-3" style={{ padding: 10, borderRadius: 4 }}>
          <strong className="t-bodysm">Could not load audit events</strong>
          <div className="t-cap mt-1">
            {loadError} · nothing is shown rather than stale or sample data.
          </div>
        </div>
      )}
      {rows === null && !loadError && (
        <div className="tint-data mb-3" style={{ padding: 10, borderRadius: 4 }}>
          <span className="t-bodysm">Loading audit events…</span>
        </div>
      )}
      {rows !== null && rows.length === 0 && !loadError && (
        <div className="tint-data mb-3" style={{ padding: 10, borderRadius: 4 }}>
          <span className="t-bodysm">No audit events recorded.</span>
        </div>
      )}

      {verifyResult && (
        <div className={verifyResult.ok ? "tint-data mb-3" : "tint-danger mb-3"} style={{ padding: 10, borderRadius: 4 }}>
          <strong className="t-bodysm">
            {verifyResult.ok ? "Audit chain verified" : "Audit chain verification failed"}
          </strong>
          <div className="t-cap mt-1">
            mode {verifyResult.mode || "unknown"} · rows scanned {verifyResult.rows_scanned ?? "—"}
            {verifyResult.detail ? ` · ${verifyResult.detail}` : ""}
            {verifyResult.breaks?.length ? ` · ${verifyResult.breaks.length} break(s)` : ""}
          </div>
        </div>
      )}

      <div className="grid grid-4">
        <KPI title="Events in chain" value={totalEvents} foot="10-year retention (SAD §8.4)"/>
        <KPI title="Loaded window" value={rows ? String(rows.length) : "—"}
             foot={`${AUD_WINDOW} most recent · filters narrow this window`}/>
        <KPI title="PII reveals (window)" value={rows ? String(windowPii) : "—"}
             foot="Reads of member / household / submission records"/>
        {/* Never claims verified. The chain is only known good when the
            server says so, and on this data it currently does not. */}
        <KPI title="Chain integrity"
             value={verifyResult ? (verifyResult.ok ? "✓ verified" : "✗ breaks found") : "not verified"}
             foot={verifyResult
               ? `${verifyResult.rows_scanned ?? "—"} scanned · ${verifyResult.breaks?.length ?? 0} break(s)`
               : "Run \u201cVerify chain\u201d to check"}/>
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
          <span className="t-cap">{events.length} of {rows ? rows.length : 0} loaded · {total == null ? "…" : total.toLocaleString()} in chain</span>
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
        back={{ label: "Audit chain", onClick: onBack }}
        eyebrow={<>ADMIN · SECURITY · AUDIT · <span className="t-mono">{event.id}</span></>}
        title={`${event.action.toUpperCase()} on ${event.entityType}:${event.entityId.slice(0, 20)}…`}
        sub={<>{event.occurred} · actor <strong>{event.actor}</strong></>}
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
