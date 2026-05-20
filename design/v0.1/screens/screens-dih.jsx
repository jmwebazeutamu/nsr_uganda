/* global React, Icon, Chip, KPI, PageHeader, AuditDrawer, ActionBar, ReasonModal, Modal, Toast */
// NSR MIS — 11.3 NSR Unit DIH review queue
// US-S11-013: live-data wiring. The screen tries to fetch from
// /api/v1/dih/stage-records/?state=pending_promotion on mount; if
// that succeeds it renders the real backend rows and the Promote /
// Reject actions POST back to the API. If the fetch fails (file://
// harness, unauthenticated, backend down) the screen falls back to
// MOCK_DIH_ROWS so the design preview still works.

const { useState: useStateDIH, useMemo: useMemoDIH, useEffect: useEffectDIH, useRef: useRefDIH } = React;


// Reads Django's csrftoken cookie — required for session-auth POSTs
// against the DRF endpoints. The Django admin login flow sets this
// cookie automatically; cross-origin previews don't have it.
const _getCsrfToken = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};


// Map an API StageRecord into the row shape the table renders. The
// API ships canonical_payload + dqa_summary + ddup_candidates + a
// state; we synthesise the display-only fields (ageH, sla) on the
// client side so the backend stays lean.
const _stageToRow = (stage) => {
  const payload = stage.canonical_payload || {};
  const members = payload.members || [];
  const head = members.find(m => m.is_head) || members[0] || {};
  const headName = [head.surname, head.first_name].filter(Boolean).join(" ");
  const geo = payload.geographic || {};
  const sourceKeys = payload._source_keys || {};
  const isKobo = Boolean(sourceKeys.kobo_form_id);
  const regionLabel = sourceKeys.kobo_region_name
    ? sourceKeys.kobo_region_name.replace(/^./, c => c.toUpperCase())
    : (geo.region || "");
  const parishLabel = geo.parish || "";

  // DQA counts pulled from the staged summary written by
  // process_stage_record. Pre-S2 stages may have an empty dict.
  const dqaSummary = stage.dqa_summary || {};
  const dqa = {
    b: (dqaSummary.blocking_failures || []).length,
    w: (dqaSummary.warnings || []).length,
    i: (dqaSummary.info || []).length,
  };
  // DDUP — top candidate score (the queue's most actionable signal)
  // and the full list for the detail-rail compare. Pre-DDUP stages
  // have an empty list.
  const ddupCandidates = stage.ddup_candidates || [];
  const ddup = ddupCandidates.length
    ? Math.max(...ddupCandidates.map(c => c.score || 0))
    : null;
  const idvLabel = (stage.idv_outcome || "").trim() || "—";

  // Age-since-created in compact "Xh Ym" or "Xm" form.
  const createdMs = Date.parse(stage.created_at);
  const ageMin = Number.isFinite(createdMs)
    ? Math.max(0, Math.round((Date.now() - createdMs) / 60000))
    : null;
  const ageH = ageMin == null ? "—"
    : ageMin >= 60 ? `${Math.floor(ageMin / 60)}h ${ageMin % 60}m`
    : `${ageMin}m`;
  // Walk-in SLA = 24h. Kobo pulls don't have a per-row SLA today;
  // we apply the same window for visual parity until DIH defines
  // a Kobo-specific one (DIH-O-CONN-01 from ADR-0007).
  const sla = ageMin == null ? "ok"
    : ageMin > 24 * 60 ? "crit"
    : ageMin > 12 * 60 ? "warn"
    : "ok";

  return {
    id: stage.id,
    head: headName || "(no head)",
    hh: members.length,
    region: regionLabel,
    parish: parishLabel,
    source: isKobo ? "Kobo" : "Walk-in",
    channel: isKobo ? "Kobo" : "CAPI",
    ddup,
    dqa,
    idv: idvLabel,
    ageH,
    sla,
    status: (stage.state || "pending").replace(/_/g, " "),
    // Lineage so the detail rail can pull it out without re-fetching.
    _payload: payload,
    _stage: stage,
    _dqaSummary: dqaSummary,
    _ddupCandidates: ddupCandidates,
  };
};


const MOCK_DIH_ROWS = [
  { id: "01HXY7K3B2N9PVQE4M6FZRWS18", head: "Lokol Naume",      hh: 6, region: "Karamoja",    parish: "Nakiloro · Moroto", source: "Walk-in", channel: "CAPI", ddup: null, dqa: { b: 0, w: 3, i: 1 }, idv: "Matched", ageH: "47m", sla: "ok",     status: "Pending" },
  { id: "01HXZ9MR4N8P2QFB7K6FZRWS33", head: "Akello Grace",     hh: 5, region: "Acholi",      parish: "Pageya · Gulu",     source: "Walk-in", channel: "CAPI", ddup: 0.83, dqa: { b: 0, w: 2, i: 0 }, idv: "Matched", ageH: "1h 12m", sla: "warn", status: "Pending" },
  { id: "01HXZBVK6QN8M2PFB7K6FZRWS41", head: "Onyango David",   hh: 7, region: "West Nile",   parish: "Logiri · Arua",     source: "Bulk",    channel: "OPM-PDM", ddup: null, dqa: { b: 0, w: 0, i: 2 }, idv: "Matched", ageH: "2h 04m", sla: "ok",  status: "Pending" },
  { id: "01HXZGN3W8MN6P2FB7K6FZRWS52", head: "Nakato Sarah",    hh: 4, region: "West Nile",   parish: "Kuluba · Yumbe",    source: "Walk-in", channel: "CAPI", ddup: 0.91, dqa: { b: 1, w: 0, i: 0 }, idv: "Mismatch","ageH": "3h 18m", sla: "ok", status: "Pending" },
  { id: "01HY02FNQ9P8MN6FB7K6FZRWS67", head: "Mugisha James",   hh: 6, region: "Karamoja",    parish: "Lorengedwat · Napak", source: "Walk-in", channel: "CAPI", ddup: 0.95, dqa: { b: 0, w: 1, i: 0 }, idv: "Matched", ageH: "5h 41m", sla: "ok",     status: "Pending" },
  { id: "01HY04MQR0N8P2FB7K6FZRWS73", head: "Auma Beatrice",    hh: 8, region: "Karamoja",    parish: "Apeitolim · Napak", source: "Walk-in", channel: "CAPI", ddup: null, dqa: { b: 0, w: 0, i: 0 }, idv: "Matched", ageH: "9h 22m", sla: "ok",     status: "Pending" },
  { id: "01HY09KRS1P9MN6FB7K6FZRWS84", head: "Lopuwa John",     hh: 7, region: "Karamoja",    parish: "Kakingol · Moroto", source: "Walk-in", channel: "CAPI", ddup: 0.86, dqa: { b: 0, w: 2, i: 1 }, idv: "Matched", ageH: "18h 15m", sla: "crit", status: "Pending" },
  { id: "01HY0AMNT8P2N6FB7K6FZRWS92", head: "Acheng Rose",      hh: 3, region: "Acholi",      parish: "Aywee · Gulu",      source: "Walk-in", channel: "CAPI", ddup: null, dqa: { b: 0, w: 0, i: 0 }, idv: "Matched", ageH: "21h 03m", sla: "crit", status: "Pending" },
];

// Quick-filter definitions. Each carries a `predicate(row)` so the
// count + the row filtering use the same logic. Counts get computed
// live in DIHScreen against the rows actually in the queue (the
// hardcoded numbers from the original mock were misleading once we
// wired live data in S11-013).
const QUICK_FILTERS = [
  { id: "sla24",  label: "SLA at risk (warn or breached)",   icon: "clock",     tone: "quality",
    predicate: r => r.sla === "warn" || r.sla === "crit" },
  { id: "ddup",   label: "Has DDUP match ≥ 0.90",            icon: "duplicate", tone: "danger",
    predicate: r => r.ddup != null && r.ddup >= 0.90 },
  { id: "blocking", label: "DQA blocking failures",          icon: "alert",     tone: "danger",
    predicate: r => (r.dqa?.b || 0) > 0 },
  { id: "clean",  label: "Clean (no DQA / DDUP issues)",     icon: "checkCircle", tone: "eligibility",
    predicate: r => (r.dqa?.b || 0) === 0 && (r.dqa?.w || 0) === 0 && r.ddup == null },
];

const DIHScreen = () => {
  // Live row state; starts as the mock so the design preview renders
  // immediately. The effect below replaces it with live API rows when
  // available.
  const [rows, setRows] = useStateDIH(MOCK_DIH_ROWS);
  const [dataSource, setDataSource] = useStateDIH("mock"); // 'mock' | 'live'
  const [selectedRow, setSelectedRow] = useStateDIH(MOCK_DIH_ROWS[1].id);
  const [auditOpen, setAuditOpen] = useStateDIH(false);
  const [modal, setModal] = useStateDIH(null); // 'promote' | 'merge' | 'hold' | 'reject'
  const [toast, setToast] = useStateDIH("");
  const [selection, setSelection] = useStateDIH(new Set());
  const [quickFilter, setQuickFilter] = useStateDIH(null);

  // Fetch live data once on mount. Same-origin so the Django session
  // cookie flows automatically; cross-origin / file:// previews fall
  // through to the mock data with no console noise.
  useEffectDIH(() => {
    let cancelled = false;
    fetch("/api/v1/dih/stage-records/?state=pending_promotion", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return;
        const apiRows = (data.results || data).map(_stageToRow);
        if (apiRows.length === 0) {
          // No pending rows — keep the mock visible so the screen
          // doesn't look empty during the demo. A banner cues the
          // operator that the queue is real but currently zero.
          setDataSource("live-empty");
          return;
        }
        setRows(apiRows);
        setSelectedRow(apiRows[0].id);
        setDataSource("live");
      })
      .catch(() => {
        // Stays on MOCK_DIH_ROWS; dataSource already 'mock'.
      });
    return () => { cancelled = true; };
  }, []);

  // Filtered view of rows for the table. Quick filters narrow by the
  // predicate defined in QUICK_FILTERS; null = show everything.
  const visibleRows = useMemoDIH(() => {
    if (!quickFilter) return rows;
    const f = QUICK_FILTERS.find(q => q.id === quickFilter);
    return f ? rows.filter(f.predicate) : rows;
  }, [rows, quickFilter]);

  // Counts per quick filter, computed against the FULL row set so the
  // numbers match the chip labels regardless of which one is active.
  const filterCounts = useMemoDIH(() => {
    const out = {};
    for (const f of QUICK_FILTERS) {
      out[f.id] = rows.filter(f.predicate).length;
    }
    return out;
  }, [rows]);

  const current = useMemoDIH(
    () => visibleRows.find(r => r.id === selectedRow) || rows.find(r => r.id === selectedRow),
    [visibleRows, rows, selectedRow],
  );

  // Detail rail sits BELOW the queue table (not beside it) — clicking
  // a row scrolls it into view so operators don't have to hunt for it.
  // Only fires when the user actively changes selection (the initial
  // render also runs this but `behavior:smooth` makes that visible
  // anyway, which doubles as a cue).
  const detailRef = useRefDIH(null);
  useEffectDIH(() => {
    if (current && detailRef.current) {
      detailRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selectedRow]);

  const auditEvents = [
    { who: "System DIH", action: "received from", detail: "Capture channel CAPI · tablet PCH-7411 · Parish Office Pageya", time: "1h 12m ago", audit: "A-2026-05-14-00471", tone: "system" },
    { who: "System DQA", action: "evaluated", detail: "Ruleset DQA-v3.4 · 2 warnings raised · 0 blocking", time: "1h 11m ago", audit: "A-2026-05-14-00472", tone: "system" },
    { who: "System IDV", action: "matched to NIRA", detail: "NIN CM89241023ABCD · confidence 0.97 (AC-IDV-MATCH)", time: "1h 11m ago", audit: "A-2026-05-14-00473", tone: "system" },
    { who: "System DDUP", action: "found candidate", detail: "Match 01HXP2KR3N8M2QF · composite 0.83 · weak queue", time: "1h 10m ago", audit: "A-2026-05-14-00474", tone: "system" },
    { who: "Johnson Mwebaze", action: "opened for review", detail: "NSR Unit Coordinator · viewed three-column compare", time: "12m ago", audit: "A-2026-05-14-00501", tone: "user" },
  ];

  const reasonsReject = [
    "Duplicate of existing registered household",
    "Failed IDV — NIRA mismatch (AC-IDV-MATCH)",
    "Blocking DQA failure not resolved",
    "Consent statement missing or refused",
    "Geographic data outside operator scope",
    "Other (specify in note)",
  ];
  const reasonsHold = [
    "Awaiting NIRA reconciliation",
    "Awaiting parish-side evidence (photo, witness)",
    "Awaiting GRM case resolution",
    "Other (specify in note)",
  ];
  const reasonsPromote = [
    "All DQA warnings reviewed and accepted",
    "IDV matched, no DDUP candidate above threshold",
    "Manual override (specify in note)",
  ];

  const fire = ({ reason, note } = {}) => {
    const kind = modal;
    // Mock-mode fallback — no backend, just toast and close.
    if (dataSource !== "live") {
      const fallbackMsg = {
        promote: "Promoted to Registered. Same Registry ID retained.",
        merge: "Promote-as-merge committed. PMT recompute queued.",
        hold: "Held for more info. Citizen notified by SMS.",
        reject: "Rejected. Provisional ID voided. Reason written to audit chain.",
      }[kind] || "Done.";
      setToast(fallbackMsg);
      setModal(null);
      return;
    }

    // Live mode — only promote + reject have backend endpoints today.
    // hold / merge are deferred (no service yet); fall back to toast.
    if (kind !== "promote" && kind !== "reject") {
      setToast(`${kind} not yet wired to backend — recorded locally.`);
      setModal(null);
      return;
    }
    const id = selectedRow;
    const url = `/api/v1/dih/stage-records/${id}/${kind}/`;
    const body = kind === "promote"
      ? { actor: "admin", reason: reason || "" }
      : { actor: "admin", reason: reason || note || "rejected via DIH queue" };
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": _getCsrfToken(),
      },
      body: JSON.stringify(body),
    })
      .then(async r => {
        if (r.ok) return r.json();
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${r.status}`);
      })
      .then(_stage => {
        // Drop the acted row out of the queue and select the next one.
        const remaining = rows.filter(r => r.id !== id);
        setRows(remaining);
        setSelectedRow(remaining[0]?.id || null);
        const verb = kind === "promote" ? "Promoted" : "Rejected";
        setToast(`${verb} stage ${id.slice(0, 12)}… — written to audit chain.`);
        setModal(null);
      })
      .catch(err => {
        setToast(`${kind} failed: ${err.message}`);
        setModal(null);
      });
  };

  const toggleSel = (id) => {
    const next = new Set(selection);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection(next);
  };

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow="DIH REVIEW QUEUE · US-109"
        title={<>
          NSR Unit DIH review queue{" "}
          <Chip>{rows.length} {dataSource === "live" ? "live" : "pending"}</Chip>
          {dataSource === "mock" && <Chip tone="quality" size="sm">mock</Chip>}
          {dataSource === "live" && <Chip tone="eligibility" size="sm">live</Chip>}
          {dataSource === "live-empty" && <Chip tone="data" size="sm">live (queue empty — mock shown)</Chip>}
        </>}
        sub="Promote, promote-as-merge, hold, or reject. Walk-in SLA = 24 hours from capture."
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn"><Icon name="download"/> Export CSV</button>
        </>}
      />

      {/* Filter bar */}
      <div className="card" style={{padding:'14px 20px', marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:'wrap'}}>
          <div className="row gap-2">
            <span className="t-cap" style={{fontWeight:600}}>QUICK FILTERS</span>
          </div>
          {QUICK_FILTERS.map(f => (
            <button key={f.id} onClick={() => setQuickFilter(quickFilter === f.id ? null : f.id)}
              title={filterCounts[f.id] === 0 ? "No rows match this filter" : ""}
              style={{
                display:'inline-flex', alignItems:'center', gap:6,
                padding:'6px 10px', borderRadius:16, fontSize:12.5, fontWeight:500,
                border: `1px solid ${quickFilter === f.id ? `var(--accent-${f.tone})` : 'var(--neutral-300)'}`,
                background: quickFilter === f.id ? `var(--accent-${f.tone}-bg)` : 'var(--neutral-0)',
                color: quickFilter === f.id ? `var(--accent-${f.tone})` : 'var(--neutral-700)',
                cursor:'pointer',
                opacity: filterCounts[f.id] === 0 ? 0.55 : 1,
              }}>
              <Icon name={f.icon} size={13}/>{f.label}
              <span style={{padding:'1px 6px', borderRadius:10, background:'var(--neutral-100)', color:'var(--neutral-700)', fontSize:11}}>{filterCounts[f.id]}</span>
            </button>
          ))}

          <div style={{width:1, height:24, background:'var(--neutral-300)', margin:'0 6px'}}/>

          {[
            ["Source", ["Walk-in","Bulk","API"]],
            ["Sub-region", ["Karamoja","West Nile","Acholi","Teso"]],
            ["Channel", ["CAPI","OPM-PDM","NUSAF","UBOS"]],
            ["DQA", ["Any","No flags","Warnings only","Blocking"]],
            ["IDV", ["Any","Matched","Mismatch","Pending"]],
          ].map(([label, opts]) => (
            <select key={label} className="field-select" style={{height:30, width:'auto', minWidth:130, fontSize:13}}>
              <option>{label}</option>
              {opts.map(o => <option key={o}>{o}</option>)}
            </select>
          ))}

          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost"><Icon name="filter" size={14}/> Reset</button>
        </div>
      </div>

      {/* Queue table */}
      <div className="card" style={{marginBottom:16}}>
        <div className="card-toolbar">
          <div className="row gap-3">
            <span className="t-bodysm" style={{fontWeight:600}}>Staged records</span>
            <span className="t-cap">8 of 342 shown · sort by SLA risk</span>
          </div>
          <div style={{flex:1}}/>
          <button className="btn btn-sm" disabled={selection.size === 0}>
            <Icon name="check" size={14}/> Bulk approve ({selection.size})
          </button>
          <button className="btn btn-sm btn-ghost"><Icon name="sliders" size={14}/> Density</button>
        </div>
        <div style={{maxHeight:280, overflowY:'auto'}}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{width:36}}></th>
                <th>Provisional ID</th>
                <th>Head · Parish</th>
                <th>Source</th>
                <th>DQA</th>
                <th>IDV</th>
                <th>DDUP</th>
                <th>Age</th>
                <th>SLA</th>
                <th className="col-actions">Status</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.length === 0 && quickFilter && (
                <tr><td colSpan={9} style={{padding:24, textAlign:'center', color:'var(--neutral-500)', fontSize:13}}>
                  No rows match this filter. <button className="link" onClick={() => setQuickFilter(null)}>clear filter</button>
                </td></tr>
              )}
              {visibleRows.map(r => (
                <tr key={r.id} className={r.id === selectedRow ? "selected" : ""} onClick={() => setSelectedRow(r.id)} style={{cursor:'pointer'}}>
                  <td onClick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>
                    <input type="checkbox" checked={selection.has(r.id)} readOnly disabled={r.dqa.b > 0 || r.ddup !== null}/>
                  </td>
                  <td className="col-id">{r.id.slice(0,18)}…</td>
                  <td>
                    <div style={{fontWeight:500}}>{r.head}</div>
                    <div className="t-cap">HH {r.hh} · {r.parish}</div>
                  </td>
                  <td>
                    <div>{r.source}</div>
                    <div className="t-cap">{r.channel}</div>
                  </td>
                  <td>
                    <div className="row gap-2">
                      {r.dqa.b > 0 && <Chip size="sm" tone="danger">B {r.dqa.b}</Chip>}
                      {r.dqa.w > 0 && <Chip size="sm" tone="quality">W {r.dqa.w}</Chip>}
                      {r.dqa.i > 0 && <Chip size="sm" tone="system">I {r.dqa.i}</Chip>}
                      {!r.dqa.b && !r.dqa.w && !r.dqa.i && <span className="muted t-cap">clean</span>}
                    </div>
                  </td>
                  <td>
                    {r.idv === "Matched" ? <Chip size="sm" tone="identity"><Icon name="check" size={11}/> Matched</Chip>
                    : r.idv === "Mismatch" ? <Chip size="sm" tone="danger">Mismatch</Chip>
                    : <Chip size="sm" tone="quality">Pending</Chip>}
                  </td>
                  <td>
                    {r.ddup === null
                      ? <span className="muted t-cap">no match</span>
                      : <Chip size="sm" tone={r.ddup >= 0.9 ? "danger" : "quality"}>{r.ddup.toFixed(2)}</Chip>}
                  </td>
                  <td className="t-cap">{r.ageH}</td>
                  <td>
                    {r.sla === 'crit' ? <Chip size="sm" tone="danger"><Icon name="alert" size={11}/> 24h</Chip>
                    : r.sla === 'warn' ? <Chip size="sm" tone="quality">at risk</Chip>
                    : <Chip size="sm" tone="data">ok</Chip>}
                  </td>
                  <td className="col-actions"><Chip size="sm">{r.status}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Three-column compare — only rendered when a row is selected */}
      {!current && (
        <div className="card" style={{padding:48, textAlign:'center', color:'var(--neutral-500)'}}>
          <Icon name="inbox" size={32} color="var(--neutral-300)"/>
          <div className="t-bodysm mt-2">
            {dataSource === "live"
              ? "Queue empty — nothing pending promotion."
              : "Select a row to review."}
          </div>
        </div>
      )}
      {current && (
      <div ref={detailRef} style={{display:'grid', gridTemplateColumns:'1fr 1fr 360px', gap:16, scrollMarginTop:80}}>
        {/* Column 1: Staged */}
        <div className="card" style={{borderTop:'3px solid var(--accent-data)'}}>
          <div className="card-header" style={{padding:'14px 20px'}}>
            <div>
              <div className="t-cap" style={{color:'var(--accent-data)'}}><Icon name="database" size={11}/> STAGED RECORD</div>
              <h3 className="t-h3" style={{margin:'2px 0 0'}}>{current.head}</h3>
              <div className="t-cap">{current.parish} · HH {current.hh} · Captured 14:35 EAT today</div>
            </div>
            <Chip>{current.status}</Chip>
          </div>
          <div style={{padding:16}}>
            {(() => {
              // Live mode: derive the summary + roster from the
              // canonical payload the API returned. Mock mode: fall
              // back to the original hardcoded fields so the design
              // preview still tells the visual story.
              const payload = current._payload;
              if (payload) {
                const members = payload.members || [];
                const head = members.find(m => m.is_head) || members[0] || {};
                const geo = payload.geographic || {};
                const sourceKeys = payload._source_keys || {};
                const gpsLine = (payload.gps_lat != null && payload.gps_lng != null)
                  ? `${Number(payload.gps_lat).toFixed(5)}, ${Number(payload.gps_lng).toFixed(5)}` +
                    (payload.gps_accuracy_m ? ` · ${payload.gps_accuracy_m}m` : "")
                  : "—";
                const sourceLine = sourceKeys.kobo_form_id
                  ? `Kobo · form ${sourceKeys.kobo_form_id} · submitted by ${sourceKeys.kobo_submitted_by || "unknown"}`
                  : "—";
                return (
                  <>
                    <RecordSummary
                      fields={[
                        ["Provisional ID", current.id, "mono"],
                        ["Head NIN", head.nin || "—", "mono"],
                        ["Phone", head.telephone_1 || "—"],
                        ["Parish", `${geo.parish || "—"} · ${sourceKeys.kobo_village_name || "—"}`],
                        ["GPS", gpsLine, "mono"],
                        ["Members", `${members.length}`],
                        ["Address", payload.address_narrative || "—"],
                        ["Urban / rural", payload.urban_rural || "—"],
                        ["Source", sourceLine],
                      ]}
                    />
                    <SectionAccordion title={`Roster (${members.length} members)`} tint="identity" defaultOpen>
                      <RosterTable members={members.map(m => ({
                        name: [m.surname, m.first_name].filter(Boolean).join(" "),
                        rel: m.is_head ? "Head" : (m.relationship_to_head || "—"),
                        sex: m.sex || "—",
                        age: m.age_years != null ? m.age_years : "—",
                        nin: m.nin || "—",
                      }))}/>
                    </SectionAccordion>
                  </>
                );
              }
              // Mock fallback — original design-preview content.
              return (
                <>
                  <RecordSummary
                    fields={[
                      ["Provisional ID", current.id, "mono"],
                      ["Head NIN", "CM89241023ABCD", "mono"],
                      ["Phone", "+256 781 552119"],
                      ["Parish", "Pageya · Bobi · Gulu"],
                      ["GPS", "2.79103, 32.29841 · 8m", "mono"],
                      ["Members", "5 (head + spouse + 3 dependants)"],
                      ["PMT band", <Chip tone="eligibility">Poorest 40%</Chip>],
                      ["Roof material", "Iron sheets"],
                      ["Source", "Walk-in CAPI · Lokwang Peter (PCH-7411)"],
                    ]}
                  />
                  <SectionAccordion title="Roster (5 members)" tint="identity" defaultOpen>
                    <RosterTable members={[
                      { name: "Akello Grace",     rel: "Head",    sex: "F", age: 34, nin: "CM89241023ABCD" },
                      { name: "Okello Charles",   rel: "Spouse",  sex: "M", age: 38, nin: "CM89110218EFGH" },
                      { name: "Akello Joy",       rel: "Daughter",sex: "F", age: 12, nin: "—" },
                      { name: "Okello Brian",     rel: "Son",     sex: "M", age: 9,  nin: "—" },
                      { name: "Akello Mercy",     rel: "Daughter",sex: "F", age: 4,  nin: "—" },
                    ]}/>
                  </SectionAccordion>
                </>
              );
            })()}
            {/* Health / Education / Housing accordions stay mock-only
                for now — these come from later modules (PMT, etc.) and
                aren't carried on the canonical_payload yet. Hidden in
                live mode so operators don't see misleading numbers. */}
            {!current._payload && (
              <>
                <SectionAccordion title="Health & Disability" tint="danger">
                  <SimpleKV rows={[["Members with disability","0"],["Chronic conditions","none reported"],["Pregnant / lactating","1 (head)"]]}/>
                </SectionAccordion>
                <SectionAccordion title="Education" tint="update">
                  <SimpleKV rows={[["School-age children","3 of 3 enrolled"],["Adult literacy","head literate"]]}/>
                </SectionAccordion>
                <SectionAccordion title="Housing & Assets" tint="eligibility">
                  <SimpleKV rows={[["Roof","Iron sheets"],["Walls","Brick (burnt)"],["Floor","Cement"],["Toilet","Pit latrine (covered)"],["Water source","Borehole, < 1 km"]]}/>
                </SectionAccordion>
              </>
            )}
          </div>
        </div>

        {/* Column 2: DDUP candidates (or empty-state if clean) */}
        {(() => {
          const cands = current._ddupCandidates || [];
          const isLive = Boolean(current._payload);
          // Live mode: render whatever ddup_candidates the staging
          // pipeline recorded. Mock mode: keep the original visual
          // CompareTable for design preview.
          if (isLive) {
            if (cands.length === 0) {
              return (
                <div className="card" style={{borderTop:'3px solid var(--accent-eligibility)'}}>
                  <div className="card-header" style={{padding:'14px 20px'}}>
                    <div>
                      <div className="t-cap" style={{color:'var(--accent-eligibility)'}}><Icon name="checkCircle" size={11}/> NO DDUP CANDIDATES</div>
                      <h3 className="t-h3" style={{margin:'2px 0 0'}}>Clean — no duplicates detected</h3>
                      <div className="t-cap">Safe to promote without manual merge review.</div>
                    </div>
                  </div>
                </div>
              );
            }
            const top = cands[0];
            const topScore = (top.score || 0).toFixed(2);
            return (
              <div className="card" style={{borderTop:'3px solid var(--accent-danger)'}}>
                <div className="card-header" style={{padding:'14px 20px'}}>
                  <div>
                    <div className="t-cap" style={{color:'var(--accent-danger)'}}>
                      <Icon name="duplicate" size={11}/> DDUP CANDIDATE{cands.length > 1 ? `S (${cands.length})` : ""} · TOP {topScore}
                    </div>
                    <h3 className="t-h3" style={{margin:'2px 0 0', fontFamily:'monospace', fontSize:13}}>{top.member_id || "—"}</h3>
                    <div className="t-cap">{top.reason || ""}</div>
                  </div>
                  <Chip tone="danger">{topScore}</Chip>
                </div>
                <div style={{padding:16}}>
                  {cands.length === 1 && (
                    <div className="t-bodysm muted">One candidate above the discovery threshold.</div>
                  )}
                  {cands.length > 1 && (
                    <table className="tbl" style={{fontSize:12}}>
                      <thead><tr><th>Member ID</th><th>Score</th><th>Reason</th></tr></thead>
                      <tbody>
                        {cands.map((c, i) => (
                          <tr key={i}>
                            <td className="t-mono">{c.member_id}</td>
                            <td>{(c.score || 0).toFixed(2)}</td>
                            <td>{c.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            );
          }
          return (
            <div className="card" style={{borderTop:'3px solid var(--accent-danger)'}}>
              <div className="card-header" style={{padding:'14px 20px'}}>
                <div>
                  <div className="t-cap" style={{color:'var(--accent-danger)'}}><Icon name="duplicate" size={11}/> DDUP CANDIDATE · COMPOSITE 0.83</div>
                  <h3 className="t-h3" style={{margin:'2px 0 0'}}>Akello Grace <span className="t-cap" style={{marginLeft:8}}>weak queue</span></h3>
                  <div className="t-cap">01HXP2KR3N8M2QF · Registered 8 Nov 2025 · same parish</div>
                </div>
                <Chip tone="danger">0.83</Chip>
              </div>
              <div style={{padding:16}}>
                <CompareTable
                  left={[
                    ["Provisional ID", "01HXZ9MR…RWS33", null, "mono"],
                    ["Head name", "Akello Grace", 1.00, null],
                    ["NIN", "CM89241023ABCD", 1.00, "mono"],
                    ["Phone", "+256 781 552119", 0.45, "mono"],
                    ["DoB", "12 Mar 1991", 1.00, null],
                    ["Parish", "Pageya · Bobi · Gulu", 1.00, null],
                    ["GPS distance", "—", null, null],
                    ["HH size", "5", 0.80, null],
                    ["PMT band", "Poorest 40%", 1.00, null],
                  ]}
                  right={[
                    ["Registry ID", "01HXP2KR3N8M2QF", null, "mono"],
                    ["Head name", "Akello Grace", null, null],
                    ["NIN", "CM89241023ABCD", null, "mono"],
                    ["Phone", "+256 700 110492", null, "mono"],
                    ["DoB", "12 Mar 1991", null, null],
                    ["Parish", "Pageya · Bobi · Gulu", null, null],
                    ["GPS distance", "2.4 km", null, null],
                    ["HH size", "4 → 5 (added in 2025)", null, null],
                    ["PMT band", "Poorest 40%", null, null],
                  ]}
                />
              </div>
            </div>
          );
        })()}

        {/* Column 3: Decision panel */}
        <div className="col gap-3">
          <div className="card" style={{borderTop:'3px solid var(--primary-900)'}}>
            <div className="card-header" style={{padding:'14px 16px'}}>
              <h3 className="t-h3" style={{margin:0}}>Decision panel</h3>
            </div>
            <div style={{padding:16}}>
              {/* DQA — live counts + rule list from dqa_summary; mock fallback. */}
              {(() => {
                const summary = current._dqaSummary;
                if (summary) {
                  const blocking = summary.blocking_failures || [];
                  const warnings = summary.warnings || [];
                  const info = summary.info || [];
                  const ruleLines = [...blocking, ...warnings].slice(0, 3)
                    .map(r => r.rule_id).filter(Boolean).join(", ");
                  return (
                    <div>
                      <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DQA OUTCOMES</div>
                      <div className="row-wrap" style={{marginBottom:8}}>
                        <Chip tone="data">{blocking.length} blocking</Chip>
                        <Chip tone="quality">{warnings.length} warnings</Chip>
                        <Chip tone="system">{info.length} info</Chip>
                      </div>
                      <div className="t-bodysm muted">
                        {(blocking.length + warnings.length) === 0
                          ? "Clean — all rules passed."
                          : `Raised: ${ruleLines || "(see audit chain)"}.`}
                      </div>
                    </div>
                  );
                }
                return (
                  <div>
                    <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DQA OUTCOMES</div>
                    <div className="row-wrap" style={{marginBottom:8}}>
                      <Chip tone="quality">2 warnings</Chip>
                      <Chip tone="system">0 info</Chip>
                      <Chip tone="data">0 blocking</Chip>
                    </div>
                    <div className="t-bodysm muted">AC-DQA-PHONE-LENGTH, AC-DQA-AGE-HEAD raised. Acknowledge to clear.</div>
                  </div>
                );
              })()}

              <div className="divider"/>

              {/* IDV — live label from stage.idv_outcome; mock fallback. */}
              {(() => {
                const idvLive = current._stage?.idv_outcome;
                if (current._payload) {
                  const tone = idvLive === "matched" ? "identity"
                    : idvLive === "mismatch" ? "danger"
                    : "data";
                  const icon = idvLive === "matched" ? "check" : "info";
                  return (
                    <div>
                      <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>IDV (NIRA)</div>
                      <Chip tone={tone}><Icon name={icon} size={11}/> {idvLive || "not run"}</Chip>
                      <div className="t-bodysm muted mt-2">
                        {idvLive === "matched"
                          ? "NIN reconciled with NIRA."
                          : idvLive === "mismatch"
                          ? "NIN found but demographics didn't align — reconcile before promote."
                          : idvLive === "pending"
                          ? "NIRA queue retry pending."
                          : "No NIN provided or IDV not yet run."}
                      </div>
                    </div>
                  );
                }
                return (
                  <div>
                    <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>IDV (NIRA)</div>
                    <Chip tone="identity"><Icon name="check" size={11}/> Matched · 0.97</Chip>
                    <div className="t-bodysm muted mt-2">NIN CM89241023ABCD reconciled · sex/age aligned · AC-IDV-MATCH passed.</div>
                  </div>
                );
              })()}

              <div className="divider"/>

              {/* DDUP — live candidate list; mock fallback. */}
              {(() => {
                const cands = current._ddupCandidates;
                if (current._payload) {
                  if (!cands || cands.length === 0) {
                    return (
                      <div>
                        <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DDUP CANDIDATES</div>
                        <Chip tone="eligibility"><Icon name="checkCircle" size={11}/> none</Chip>
                        <div className="t-bodysm muted mt-2">No duplicates detected — safe to promote.</div>
                      </div>
                    );
                  }
                  return (
                    <div>
                      <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DDUP CANDIDATES</div>
                      {cands.slice(0, 3).map((c, i) => (
                        <div key={i} className="row gap-2"
                          style={{padding:'8px 10px', background:'var(--accent-danger-bg)', borderRadius:4, border:'1px solid rgba(169,50,38,0.15)', marginBottom:6}}>
                          <Chip size="sm" tone="danger">{(c.score || 0).toFixed(2)}</Chip>
                          <div className="flex-1">
                            <div className="t-bodysm" style={{fontWeight:500, fontFamily:'monospace', fontSize:12}}>{c.member_id}</div>
                            <div className="t-cap">{c.reason}</div>
                          </div>
                        </div>
                      ))}
                      <div className="t-bodysm muted">Manual merge review before promote.</div>
                    </div>
                  );
                }
                return (
                  <div>
                    <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>DDUP CANDIDATES</div>
                    <div className="row gap-2" style={{padding:'8px 10px', background:'var(--accent-danger-bg)', borderRadius:4, border:'1px solid rgba(169,50,38,0.15)', marginBottom:6}}>
                      <Chip size="sm" tone="danger">0.83</Chip>
                      <div className="flex-1">
                        <div className="t-bodysm" style={{fontWeight:500}}>01HXP2KR3N8M2QF · Akello Grace</div>
                        <div className="t-cap">phone differs · HH size +1</div>
                      </div>
                    </div>
                    <div className="t-bodysm muted">Below 0.90 — consider <strong>Promote-as-merge</strong> only after manual review.</div>
                  </div>
                );
              })()}

              <div className="divider"/>

              {/* Walk-in SLA */}
              <div className="row gap-2" style={{padding:'10px 12px', background:'var(--accent-quality-bg)', borderRadius:4, borderLeft:'3px solid var(--accent-quality)'}}>
                <Icon name="clock" size={16} color="var(--accent-quality)"/>
                <div className="t-bodysm" style={{color:'var(--neutral-900)'}}>
                  <strong>SLA at risk:</strong> 22h 48m until walk-in cutoff (24h from capture).
                </div>
              </div>
            </div>
          </div>

          <div className="card" style={{padding:16, borderLeft:'3px solid var(--accent-update)'}}>
            <div className="row gap-2" style={{marginBottom:6}}>
              <Icon name="info" size={14} color="var(--accent-update)"/>
              <strong className="t-bodysm">Keyboard shortcut</strong>
            </div>
            <div className="t-bodysm muted">
              <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>⌘</kbd> + <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>↵</kbd> approve · <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>⌘</kbd> + <kbd style={{padding:'1px 5px', background:'var(--neutral-100)', border:'1px solid var(--neutral-300)', borderRadius:3, fontSize:11}}>⌫</kbd> reject
            </div>
          </div>
        </div>
      </div>
      )}

      {/* Sticky action bar */}
      {current && (
        <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
          <ActionBar left={<>Reviewing <span className="t-mono" style={{color:'var(--neutral-900)'}}>{current.id.slice(0,18)}…</span> · {current.head} · {rows.indexOf(current) + 1} of {rows.length}</>}>
            <button className="btn btn-danger" onClick={() => setModal('reject')}><Icon name="xCircle" size={14}/> Reject</button>
            <button className="btn btn-warn" onClick={() => setModal('hold')}><Icon name="clock" size={14}/> Hold for info</button>
            <button className="btn" onClick={() => setModal('merge')}><Icon name="duplicate" size={14}/> Promote-as-merge</button>
            <button className="btn btn-success" onClick={() => setModal('promote')}><Icon name="check" size={14}/> Promote</button>
          </ActionBar>
        </div>
      )}

      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} events={auditEvents} title={`Audit · ${current?.head || ""}`}/>

      <ReasonModal open={modal === 'promote'} title="Promote to Registered" intent="success"
        reasonOptions={reasonsPromote} recordLabel={current?.id || ""}
        onClose={() => setModal(null)} onConfirm={fire}/>
      <ReasonModal open={modal === 'merge'} title="Promote as merge" intent="primary"
        reasonOptions={["Accept DDUP candidate as same household","Both records are same household — keep this one","Other (specify in note)"]}
        recordLabel={current?.id || ""}
        onClose={() => setModal(null)} onConfirm={fire}/>
      <ReasonModal open={modal === 'hold'} title="Hold for more information" intent="primary"
        reasonOptions={reasonsHold} recordLabel={current?.id || ""}
        onClose={() => setModal(null)} onConfirm={fire}/>
      <ReasonModal open={modal === 'reject'} title="Reject submission" intent="danger"
        reasonOptions={reasonsReject} recordLabel={current?.id || ""}
        onClose={() => setModal(null)} onConfirm={fire}/>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

const RecordSummary = ({ fields }) => (
  <div style={{display:'grid', gridTemplateColumns:'120px 1fr', rowGap:8, columnGap:12}}>
    {fields.map(([k, v, m], i) => (
      <React.Fragment key={i}>
        <div className="t-cap" style={{color:'var(--neutral-500)'}}>{k}</div>
        <div className={m === 'mono' ? 't-mono' : 't-bodysm'} style={{fontSize: m === 'mono' ? 12.5 : 13}}>{v}</div>
      </React.Fragment>
    ))}
  </div>
);

const SectionAccordion = ({ title, tint = "data", defaultOpen = false, children }) => {
  const [open, setOpen] = useStateDIH(defaultOpen);
  return (
    <div style={{marginTop:12, border:'1px solid var(--neutral-200)', borderRadius:4, borderLeft: `3px solid var(--accent-${tint})`, overflow:'hidden'}}>
      <button onClick={() => setOpen(!open)} style={{width:'100%', display:'flex', alignItems:'center', gap:8, padding:'10px 12px', border:0, background:'var(--neutral-50)', cursor:'pointer', textAlign:'left'}}>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14}/>
        <strong className="t-bodysm">{title}</strong>
      </button>
      {open && <div style={{padding:12, background:'var(--neutral-0)'}}>{children}</div>}
    </div>
  );
};

const SimpleKV = ({ rows }) => (
  <div style={{display:'grid', gridTemplateColumns:'140px 1fr', rowGap:6, columnGap:12, fontSize:13}}>
    {rows.map(([k, v], i) => (<React.Fragment key={i}><div className="muted">{k}</div><div>{v}</div></React.Fragment>))}
  </div>
);

const RosterTable = ({ members }) => (
  <table className="tbl" style={{fontSize:12.5}}>
    <thead><tr><th>Name</th><th>Rel</th><th>Sex</th><th>Age</th><th>NIN</th></tr></thead>
    <tbody>{members.map((m, i) => (
      <tr key={i}><td>{m.name}</td><td className="muted">{m.rel}</td><td className="muted">{m.sex}</td><td className="t-num">{m.age}</td><td className="col-id">{m.nin}</td></tr>
    ))}</tbody>
  </table>
);

const CompareTable = ({ left, right }) => (
  <div style={{display:'grid', gridTemplateColumns:'100px 1fr 1fr', rowGap:8, columnGap:10, fontSize:13}}>
    <div className="t-cap" style={{color:'var(--neutral-500)'}}>Field</div>
    <div className="t-cap" style={{color:'var(--accent-data)'}}>Staged</div>
    <div className="t-cap" style={{color:'var(--accent-danger)'}}>Registry candidate</div>
    {left.map((row, i) => {
      const [field, val, sim, mono] = row;
      const [, rval] = right[i];
      const diff = sim !== null && sim !== undefined && sim < 1;
      return (
        <React.Fragment key={i}>
          <div className="muted" style={{paddingTop:4}}>{field}</div>
          <div className={mono === 'mono' ? 't-mono' : ''} style={{padding:'4px 8px', borderRadius:3, background: diff ? 'var(--accent-danger-bg)' : 'transparent', borderLeft: diff ? '2px solid var(--accent-danger)' : '2px solid transparent', fontSize: mono === 'mono' ? 12 : 13}}>
            {val}
            {sim !== null && sim !== undefined && <span className="t-cap" style={{marginLeft:6, color: diff ? 'var(--accent-danger)' : 'var(--accent-data)'}}>{sim.toFixed(2)}</span>}
          </div>
          <div className={mono === 'mono' ? 't-mono' : ''} style={{padding:'4px 8px', borderRadius:3, background: diff ? 'var(--accent-danger-bg)' : 'transparent', borderLeft: diff ? '2px solid var(--accent-danger)' : '2px solid transparent', fontSize: mono === 'mono' ? 12 : 13}}>{rval}</div>
        </React.Fragment>
      );
    })}
  </div>
);

Object.assign(window, { DIHScreen });
