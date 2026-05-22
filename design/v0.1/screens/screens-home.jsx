/* global React, Icon, Chip, KPI, PageHeader */
// NSR MIS — Home (role-aware dashboard) + Kit page

const { useState: useStateHome, useEffect: useEffectHome } = React;


// US-S13-002 — wire each role's queue panels to live API. Each
// queue title maps to an endpoint URL + a projector that turns the
// API response into {id, who, note, chip, age} (the shape the
// existing queue renderer expects). Titles without a mapping
// retain their mock items so the design preview still tells the
// visual story.
const _ago = (iso) => {
  const ms = Date.parse(iso || "");
  if (!Number.isFinite(ms)) return "—";
  const mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
};

const _stageItem = (s) => {
  const payload = s.canonical_payload || {};
  const members = payload.members || [];
  const head = members.find(m => m.is_head) || members[0] || {};
  const headName = [head.surname, head.first_name].filter(Boolean).join(" ") || "(no head)";
  const geo = payload.geographic || {};
  const dqa = s.dqa_summary || {};
  const w = (dqa.warnings || []).length;
  const b = (dqa.blocking_failures || []).length;
  const ddup = (s.ddup_candidates || []).length;
  const noteBits = [];
  if (ddup) noteBits.push(`DDUP ×${ddup}`);
  if (b) noteBits.push(`${b} blocking`);
  if (w) noteBits.push(`${w} warning${w === 1 ? "" : "s"}`);
  if (!noteBits.length) noteBits.push("Clean");
  return {
    id: s.id,
    who: `${headName} · ${geo.parish || ""}`.trim(),
    note: noteBits.join(" · "),
    chip: (s.state || "pending").replace(/_/g, " "),
    age: _ago(s.created_at),
  };
};

const _changeRequestItem = (cr) => ({
  id: cr.id,
  who: `${(cr.entity_id || "").slice(0, 12)}… · ${cr.pmt_relevant ? "pmt_relevant" : "cosmetic"}`,
  note: `${cr.change_type || "—"} · by ${cr.requester || "—"}`,
  chip: cr.status,
  age: _ago(cr.created_at),
});

const _grievanceItem = (g) => ({
  id: g.id,
  who: `${g.category || "—"} · tier ${g.tier || "?"}`,
  note: (g.description || "").slice(0, 80) || "—",
  chip: g.status,
  age: _ago(g.created_at),
});

const _drsItem = (dr) => ({
  id: dr.id,
  who: `${dr.dsa_reference || "—"} · ${(dr.row_count_delivered || 0).toLocaleString()} rows`,
  note: `${(dr.fields || []).slice(0, 3).join(", ")}${(dr.fields || []).length > 3 ? "…" : ""}`,
  chip: dr.status,
  age: _ago(dr.created_at),
});

// Map by queue title → { url, projector, target (nav screen),
// geographic }. `geographic: true` means the panel honours the
// home-screen region drill-down (US-S15-003) — the queue's list
// endpoint accepts ?sub_region_code= and joins through Household.
// Partner-DRS panels are partner-side ABAC, so they stay national
// regardless of the operator's region selection.
const HOME_QUEUE_LIVE_MAP = {
  "Pending DIH promotions": {
    url: "/api/v1/dih/stage-records/?state=pending_promotion&page_size=4",
    projector: _stageItem,
    target: "dih",
    geographic: true,
  },
  "Pending UPD reviews": {
    url: "/api/v1/upd/change-requests/?status=pending_approval&page_size=4",
    projector: _changeRequestItem,
    target: "upd",
    geographic: true,
  },
  "GRM L2 cases": {
    url: "/api/v1/grm/grievances/?tier=L2&page_size=4",
    projector: _grievanceItem,
    target: "grm",
    geographic: true,
  },
  "Pending approval": {
    url: "/api/v1/drs/requests/mine/?status=submitted&page_size=4",
    projector: _drsItem,
    target: "partner-drs",
  },
  "Delivered (downloadable)": {
    url: "/api/v1/drs/requests/mine/?status=delivered&page_size=4",
    projector: _drsItem,
    target: "partner-drs",
  },
};


// Map a KPI's `title` to the field on the dashboard payload it
// should read. Wiring a new KPI to live data = add an entry here.
// Falls back to the hardcoded mock value when the field is missing
// from the payload (or when the API call hasn't returned yet).
const HOME_KPI_LIVE_MAP = {
  // nsr-unit
  "DIH review queue": "stages_pending_promotion",
  "Bulk batches awaiting dual-approval": null,  // no backend signal yet
  "Partner DSAs expiring in 30d":         null,
  "Fast-track auto-promote":              null,
  // cdo
  "UPD review queue":     "change_requests_pending",
  "GRM L2 cases":         "grievances_l2_open",
  "Programme referrals":  null,
  "Avg approval time (UPD)": null,
  // parish
  "Captures today":          null,
  "Drafts about to expire":  null,
  "GRM L1 cases (my parish)": "grievances_open",
  "Sync queue (CAPI)":       null,
  // dpo
  "Anomaly alerts (US-103)": null,
  "Rows shipped 7d":         null,
  "Erasure requests":        null,
  "DPIA review tasks":       null,
  // partner-analyst
  "Delivered (30d)":         "data_requests_delivered_7d",
  "Pending approval":        "data_requests_pending_approval",
  "Bundles expiring 7d":     null,
  "Active DSA":              null,
};

/* ============================================================
   ROLE config
   ============================================================ */
const ROLE_CONTENT = {
  "nsr-unit": {
    name: "NSR Unit Coordinator",
    person: "Johnson Mwebaze",
    org: "MGLSD · NSR Unit",
    kpis: [
      { title: "DIH review queue", value: "342", trend: "up", trendValue: "+38 today", foot: "vs. 7-day avg 287", spark: [180,210,250,235,280,310,342] },
      { title: "Fast-track auto-promote", value: "61.4", suffix: "%", trend: "up", trendValue: "+2.1pp wk", foot: "Target ≥ 60% (AC-DIH-AUTO)", spark: [54,55,58,57,60,59,61.4] },
      { title: "Bulk batches awaiting dual-approval", value: "4", trend: "flat", trendValue: "no change", foot: "1 batch > 10,000 (US-108)", spark: [4,3,4,5,4,4,4] },
      { title: "Partner DSAs expiring in 30d", value: "3", trend: "down", trendValue: "−1 since Monday", foot: "Renewal owner notified", spark: [6,5,5,5,4,4,3] },
    ],
    queues: [
      { title: "Pending DIH promotions", icon: "inbox", count: 342, items: [
        { id: "01HXY7K3B2N9PVQE4M6FZRWS18", who: "Lokol Naume · Nakiloro, Moroto", note: "Walk-in · No DDUP match · 0 warnings", chip: "Pending", age: "12m" },
        { id: "01HXZ9MR4N8P2QFB7K6FZRWS33", who: "Akello Grace · Pageya, Gulu", note: "Walk-in · DDUP 0.83 · 2 warnings", chip: "Pending", age: "47m" },
        { id: "01HXZBVK6QN8M2PFB7K6FZRWS41", who: "Onyango David · Logiri, Arua", note: "Bulk OPM-PDM · 0 warnings", chip: "Pending", age: "2h" },
        { id: "01HXZGN3W8MN6P2FB7K6FZRWS52", who: "Nakato Sarah · Kuluba, Yumbe", note: "Walk-in · NIRA mismatch · 1 blocking", chip: "Pending", age: "3h" },
      ]},
      { title: "Bulk batches awaiting dual-approval", icon: "duplicate", count: 4, items: [
        { id: "CR-2026-05-13-00112", who: "UBOS-NUSAF-2026-BULK", note: "11,402 records · awaits second approver", chip: "Pending Approval", age: "yesterday" },
        { id: "CR-2026-05-12-00031", who: "OPM-PDM-2026-Q2-BULK",  note: "8,213 records · awaits second approver",  chip: "Pending Approval", age: "2d" },
      ]},
    ],
  },
  "parish": {
    name: "Parish Chief",
    person: "Lokwang Peter",
    org: "Nakiloro Parish · Tapac · Moroto",
    kpis: [
      { title: "Captures today", value: "14", trend: "up", trendValue: "+3 vs. yesterday", foot: "8 in queue, 6 promoted", spark: [4,7,9,11,12,13,14] },
      { title: "Drafts about to expire", value: "2", trend: "flat", trendValue: "—", foot: "Both due in < 3 days", spark: [3,3,2,2,3,2,2] },
      { title: "GRM L1 cases (my parish)", value: "5", trend: "down", trendValue: "−1 this week", foot: "Avg L1 close 2.4 days", spark: [7,6,6,6,5,5,5] },
      { title: "Sync queue (CAPI)", value: "0", trend: "flat", trendValue: "all synced", foot: "Last sync 09:12 EAT", spark: [4,2,1,3,1,0,0] },
    ],
    queues: [
      { title: "Today's captures", icon: "users", count: 14, items: [
        { id: "01HXY7K3B2N9PVQE4M6FZRWS18", who: "Lokol Naume · HH size 6 · 14:35 EAT", note: "Submitted · 3 warnings, 0 blocking", chip: "Provisional", age: "8m" },
        { id: "01HXY7H1B0N7PVQE4M6FZRWS09", who: "Lochoro Mary · HH size 4 · 13:22 EAT", note: "Submitted · 0 warnings", chip: "Provisional", age: "1h" },
        { id: "01HXY6X9B0M6PVQE4M6FZRWS00", who: "Lopuwa John · HH size 7 · 11:58 EAT", note: "Promoted · Registry confirmed", chip: "Registered", age: "2h" },
      ]},
      { title: "Drafts about to expire", icon: "clock", count: 2, items: [
        { id: "DRAFT-2026-05-11-00012", who: "Nakong Anna · partial (4/7 sections)", note: "Expires in 2 days (Draft TTL = 14d)", chip: "Draft", age: "12d" },
      ]},
    ],
  },
  "cdo": {
    name: "Community Development Officer",
    person: "Adong Florence",
    org: "Tapac Sub-county · Moroto",
    kpis: [
      { title: "UPD review queue", value: "23", trend: "up", trendValue: "+5 today", foot: "9 PMT-relevant", spark: [12,14,15,18,20,22,23] },
      { title: "GRM L2 cases", value: "8", trend: "flat", trendValue: "—", foot: "2 awaiting citizen response", spark: [8,9,8,8,9,8,8] },
      { title: "Programme referrals", value: "16", trend: "up", trendValue: "+4 wk", foot: "OPM-PDM batch incoming", spark: [10,12,11,13,14,15,16] },
      { title: "Avg approval time (UPD)", value: "1.8", suffix: "d", trend: "down", trendValue: "−0.4d wk", foot: "SLA = 3 working days", spark: [2.6,2.4,2.2,2.0,1.9,1.8,1.8] },
    ],
    queues: [
      { title: "Pending UPD reviews", icon: "edit", count: 23, items: [
        { id: "UPD-2026-05-14-00237", who: "01HXY7K3… · pmt_relevant", note: "Roster: add member · evidence: photo, witness", chip: "Pending Approval", age: "3h" },
        { id: "UPD-2026-05-14-00231", who: "01HXZ9MR… · cosmetic", note: "Phone number update · evidence: USSD echo", chip: "Pending Approval", age: "6h" },
        { id: "UPD-2026-05-13-00188", who: "01HXZGN3… · pmt_relevant", note: "Housing: roof material change · evidence: photo", chip: "Pending Approval", age: "yesterday" },
      ]},
      { title: "GRM L2 cases", icon: "message", count: 8, items: [
        { id: "GRV-2026-05-14-00091", who: "Akello Grace · Pageya, Gulu", note: "Missed enrolment in OPM-PDM 2026 Q2", chip: "In progress", age: "2d" },
        { id: "GRV-2026-05-13-00088", who: "Nakato Sarah · Kuluba, Yumbe", note: "NIRA mismatch on head of household", chip: "Awaiting citizen response", age: "3d" },
      ]},
    ],
  },
  "partner-analyst": {
    name: "Partner Analyst",
    person: "Nakimuli Sarah",
    org: "PDM Programme Office · MGLSD",
    kpis: [
      { title: "Delivered (30d)", value: "12", trend: "up", trendValue: "+3 wk", foot: "Avg 2,140 rows/req", spark: [6,7,8,9,10,11,12] },
      { title: "Pending approval", value: "1", trend: "flat", trendValue: "—", foot: "Submitted 14 May 14:15", spark: [0,1,1,2,1,1,1] },
      { title: "Bundles expiring 7d", value: "2", trend: "flat", trendValue: "—", foot: "30d TTL since delivery", spark: [3,3,2,2,2,2,2] },
      { title: "Active DSA", value: "DSA-PDM-2026-01", suffix: "", foot: "Valid 01 Jan 2026 → 31 Dec 2026" },
    ],
    queues: [
      { title: "Pending approval", icon: "clock", count: 1, items: [
        { id: "01DRS2026051400003", who: "DSA-PDM-2026-01 · sub-region BUGANDA-SOUTH", note: "household.id + sub_region_code · programme PDM", chip: "Pending Approval", age: "6h" },
      ]},
      { title: "Delivered (downloadable)", icon: "download", count: 2, items: [
        { id: "01DRS2026051400001", who: "DSA-PDM-2026-01 · 1,284 rows", note: "Manifest a3f8e91c… · expires 12 Jun 11:42", chip: "Delivered", age: "yesterday" },
      ]},
    ],
  },
  "dpo": {
    name: "Data Protection Officer",
    person: "Mukasa Robert",
    org: "MGLSD · DPO Office",
    kpis: [
      { title: "Anomaly alerts (US-103)", value: "3", trend: "up", trendValue: "+2 today", foot: "1 critical: 30d > DSA budget +18%", spark: [1,1,2,2,1,2,3] },
      { title: "Rows shipped 7d", value: "2.4", suffix: "M", trend: "up", trendValue: "+11% wk", foot: "Across 14 active requesters", spark: [1.8,1.9,2.1,2.0,2.2,2.3,2.4] },
      { title: "Erasure requests", value: "6", trend: "flat", trendValue: "—", foot: "2 awaiting controller review", spark: [4,5,5,6,5,6,6] },
      { title: "DPIA review tasks", value: "2", trend: "down", trendValue: "−1", foot: "Both due in next 7 days", spark: [4,3,3,3,3,2,2] },
    ],
    queues: [
      { title: "Active anomalies", icon: "alert", count: 3, items: [
        { id: "ANOM-2026-05-14-008", who: "MoH-Vital-Stats · CSV via DRS", note: "30-day volume 124% of DSA budget (US-103 AC-DPO-VOL)", chip: "Blocking", age: "47m" },
        { id: "ANOM-2026-05-14-005", who: "UBOS-NUSAF-2026-BULK · query reused 6x", note: "Identical query hash across 6 requesters", chip: "Warning", age: "3h" },
      ]},
    ],
  },
};

const ROLES = Object.keys(ROLE_CONTENT);

/* ============================================================
   Home dashboard
   ============================================================ */
const HomeScreen = ({ role, onNavigate }) => {
  const r = ROLE_CONTENT[role] || ROLE_CONTENT["nsr-unit"];

  // US-S12-001 — overlay live KPI counts from
  // /api/v1/rpt/dashboards/operator-kpis/ onto the role's mock cards.
  // Missing fetch (no backend / unauthenticated) leaves the mock
  // values intact so the design preview still tells the visual story.
  //
  // US-S14-004 — added a per-region drill-down. `region` defaults to
  // empty (= all regions in operator's scope); a selector below lets
  // the user narrow to a single sub-region and refetches the
  // aggregator. Only the KPIs that depend on Household geography
  // narrow — DRS counts are partner-side ABAC, stays national.
  const [liveKpis, setLiveKpis] = useStateHome(null);
  const [region, setRegion] = useStateHome("");
  const [subRegions, setSubRegions] = useStateHome([]);
  useEffectHome(() => {
    let cancelled = false;
    const url = "/api/v1/rpt/dashboards/operator-kpis/"
      + (region ? `?region=${encodeURIComponent(region)}` : "");
    fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(rsp => rsp.ok ? rsp.json() : Promise.reject(rsp.status))
      .then(data => { if (!cancelled) setLiveKpis(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [region]);

  // Sub-region selector options — fetched once. Falls back to empty
  // (the dropdown is hidden) when the reference-data endpoint is
  // unreachable, e.g. preview under file:// without backend.
  useEffectHome(() => {
    let cancelled = false;
    fetch("/api/v1/reference-data/geographic-units/?level=sub_region&page_size=100", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(rsp => rsp.ok ? rsp.json() : Promise.reject(rsp.status))
      .then(data => {
        if (cancelled) return;
        const rows = (data.results || data || [])
          .filter(g => (g.status || "active") === "active")
          .map(g => ({ code: g.code, name: g.name }));
        rows.sort((a, b) => a.name.localeCompare(b.name));
        setSubRegions(rows);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Project the role's KPI list, replacing `value` with the live
  // count when one is available, and stripping the misleading
  // spark/trend lines (the live count is a single point — sparks
  // come back when /api/v1/rpt/dashboards/comparative/ wires in).
  const kpis = r.kpis.map(k => {
    const fieldName = HOME_KPI_LIVE_MAP[k.title];
    if (liveKpis && fieldName && liveKpis[fieldName] != null) {
      return {
        ...k,
        value: String(liveKpis[fieldName]),
        spark: undefined,
        trend: undefined,
        trendValue: undefined,
        foot: `${k.foot} · live`,
      };
    }
    return k;
  });

  // US-S13-002 — per-queue live item fetch. State: titles → list
  // of projected items (or null while loading). Each queue's title
  // is its key. Titles not in HOME_QUEUE_LIVE_MAP stay mock.
  //
  // US-S15-003 — region drill-down also narrows geographic queues.
  // Refetches when `region` changes; partner-DRS queues skip the
  // filter (their endpoint is partner-side ABAC).
  const [liveQueues, setLiveQueues] = useStateHome({});
  useEffectHome(() => {
    let cancelled = false;
    // Fetch only the queues this role displays AND that have a
    // live mapping. Avoids 4 unnecessary requests on a page mount.
    const titles = r.queues.map(q => q.title)
                           .filter(t => HOME_QUEUE_LIVE_MAP[t]);
    titles.forEach(title => {
      const cfg = HOME_QUEUE_LIVE_MAP[title];
      const url = (region && cfg.geographic)
        ? `${cfg.url}&sub_region_code=${encodeURIComponent(region)}`
        : cfg.url;
      fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
        .then(rsp => rsp.ok ? rsp.json() : Promise.reject(rsp.status))
        .then(data => {
          if (cancelled) return;
          const items = (data.results || data || []).map(cfg.projector);
          setLiveQueues(prev => ({ ...prev, [title]: items }));
        })
        .catch(() => {});
    });
    return () => { cancelled = true; };
  }, [r.queues, region]);

  const queues = r.queues.map(q => {
    const live = liveQueues[q.title];
    if (live === undefined) return q;  // not wired or still loading
    return {
      ...q,
      items: live,
      count: live.length,
      _live: true,
      _target: HOME_QUEUE_LIVE_MAP[q.title]?.target || "home",
    };
  });

  return (
    <div className="page">
      <PageHeader
        eyebrow={liveKpis
          ? (region ? `HOME · LIVE · DRILLED INTO ${region}` : "HOME · LIVE")
          : "HOME"}
        title={<span>Good afternoon, <span style={{color:'var(--primary-900)'}}>{r.person.split(' ')[0]}</span></span>}
        sub={<>Signed in as {r.name}. Scope: {r.org}. Today is Thursday, 14 May 2026.</>}
        right={<>
          {subRegions.length > 0 && (
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="field-select"
              style={{maxWidth:220, fontSize:13}}
              aria-label="Drill down into a sub-region"
              title="Narrow the KPIs and queues to one sub-region"
            >
              <option value="">All regions in scope</option>
              {subRegions.map(s => (
                <option key={s.code} value={s.code}>{s.name}</option>
              ))}
            </select>
          )}
          <button className="btn"><Icon name="download"/> Export brief</button>
          <button className="btn btn-primary"><Icon name="plus"/> New capture</button>
        </>}
      />

      {/* US-S18-002 — drill-down breadcrumb. Only rendered while a
          region is selected; gives the operator a one-click reset and
          a visible reminder that they're NOT seeing national totals.
          Without this, an operator can leave the drill-down selector
          set, navigate away, and come back to mis-read the numbers
          as full-scope counts. */}
      {region && (() => {
        const sr = subRegions.find(s => s.code === region);
        const label = sr ? sr.name : region;
        return (
          <div
            role="status"
            aria-live="polite"
            style={{
              display:'flex', alignItems:'center', gap:8,
              padding:'8px 14px', marginBottom:12, borderRadius:6,
              background:'var(--accent-data-bg)',
              border:'1px solid var(--accent-data)',
              fontSize:13.5,
            }}>
            <Icon name="filter" size={14} color="var(--accent-data)"/>
            <span className="muted">All regions</span>
            <Icon name="chevronRight" size={12} color="var(--neutral-500)"/>
            <strong>{label}</strong>
            <span className="t-cap" style={{color:'var(--neutral-600)'}}>
              · KPIs + geographic queue panels narrowed; DRS counts stay national
            </span>
            <div style={{flex:1}}/>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setRegion("")}
              aria-label="Clear region drill-down"
              title="Back to all regions in scope"
            >
              <Icon name="x" size={12}/> Clear drill-down
            </button>
          </div>
        );
      })()}

      <div className="grid grid-4">
        {kpis.map((k, i) => <KPI key={i} {...k}/>)}
      </div>

      {/* DSA workspace shortcut — operator / DPO roles get a one-click
          path into the DSA management surface. Lives under the KPI strip
          rather than inside it so it survives KPI rearrangement, and
          shows partner-side totals from /partners/summary/ regardless of
          which sub-region drill-down is active. */}
      {(role === "nsr-unit" || role === "dpo") && (
        <DsaWorkspaceTile onNavigate={onNavigate}/>
      )}

      <div className="grid grid-2 mt-5">
        {queues.map((q, i) => {
          const target = q._target || "dih";
          return (
            <div className="card" key={i}>
              <div className="card-header">
                <div className="row gap-3">
                  <div style={{width:32, height:32, borderRadius:6, background:'var(--primary-100)', color:'var(--primary-900)', display:'grid', placeItems:'center'}}>
                    <Icon name={q.icon} size={18}/>
                  </div>
                  <div>
                    <h3 className="t-h3" style={{margin:0}}>
                      {q.title}
                      {q._live && <span className="t-cap" style={{marginLeft:8, color:"var(--accent-eligibility)"}}>· live</span>}
                    </h3>
                    <div className="t-cap">{q.count} {q.items.length === 1 ? "open" : "open"}</div>
                  </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => onNavigate?.(target)}>
                  Open queue <Icon name="chevronRight" size={14}/>
                </button>
              </div>
              <div>
                {q.items.length === 0 && (
                  <div className="t-bodysm muted" style={{padding:"24px 20px", textAlign:"center"}}>
                    Queue empty.
                  </div>
                )}
                {q.items.map((item, j) => (
                  <div key={j} className="row gap-3" style={{padding:'12px 20px', borderBottom: j < q.items.length - 1 ? '1px solid var(--neutral-200)' : 'none', cursor:'pointer'}}
                       onClick={() => onNavigate?.(target)}>
                    <div style={{minWidth:0, flex:1}}>
                      <div className="t-mono" style={{color:'var(--neutral-700)', fontSize:12, marginBottom:2}}>{item.id}</div>
                      <div style={{fontWeight:500}}>{item.who}</div>
                      <div className="t-bodysm muted" style={{marginTop:2}}>{item.note}</div>
                    </div>
                    <div className="col" style={{alignItems:'flex-end', gap:6}}>
                      <Chip>{item.chip}</Chip>
                      <span className="t-cap">{item.age}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="card mt-5">
        <div className="card-header">
          <h3 className="t-h3" style={{margin:0}}>Across the registry</h3>
          <span className="t-cap">{liveKpis ? "live (one-shot fetch)" : "Refreshed 14:35 EAT · poll 60s"}</span>
        </div>
        <div className="grid grid-4" style={{padding:20}}>
          <RegistryStat
            label="Total households (Registered)"
            value={liveKpis ? liveKpis.households_total.toLocaleString() : "9,847,221"}
            sub={liveKpis ? "in your ABAC scope" : "of 12.1M target (81.4%)"}/>
          <RegistryStat
            label="Provisional, pending promotion"
            value={liveKpis ? liveKpis.stages_pending_promotion.toLocaleString() : "124,309"}
            sub={liveKpis ? `quality-fail ${liveKpis.stages_quality_failed} · ddup ${liveKpis.stages_ddup_review} · idv ${liveKpis.stages_idv_pending}` : "walk-in 38k · bulk 86k"}/>
          <RegistryStat
            label={liveKpis ? "Households with PMT score" : "Confirmed individuals"}
            value={liveKpis ? liveKpis.households_with_pmt.toLocaleString() : "48,116,802"}
            sub={liveKpis ? "ready for programme eligibility" : "avg HH size 4.89"}/>
          <RegistryStat
            label={liveKpis ? "Operator queues" : "Connectors active (7d)"}
            value={liveKpis ? `UPD ${liveKpis.change_requests_pending} · GRM ${liveKpis.grievances_open}` : "11 / 14"}
            sub={liveKpis ? `DRS ${liveKpis.data_requests_pending_approval} pending` : "2 paused · 1 quarantined"}/>
        </div>
      </div>

      <div className="t-cap" style={{marginTop:24, textAlign:'center'}}>
        NSR MIS v0.1 · Solution Architecture Document v0.6 · ERD v0.6 · NITA-U Government Data Centre
      </div>
    </div>
  );
};

const RegistryStat = ({ label, value, sub }) => (
  <div style={{borderRight:'1px solid var(--neutral-200)', paddingRight:20}}>
    <div className="t-cap">{label}</div>
    <div className="t-num" style={{fontSize:22, fontWeight:700, margin:'2px 0', letterSpacing:'-0.01em'}}>{value}</div>
    <div className="t-cap" style={{color:'var(--neutral-700)'}}>{sub}</div>
  </div>
);

// Operator/DPO dashboard shortcut to the DSA workspace. Pulls live
// counts from /partners/summary/ so the tile says something useful
// before the user clicks through. Falls back to dashes when offline.
const DsaWorkspaceTile = ({ onNavigate }) => {
  const [summary, setSummary] = useStateHome(null);
  useEffectHome(() => {
    let cancelled = false;
    fetch("/api/v1/partners/summary/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { if (!cancelled) setSummary(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const active   = summary?.active_dsas;
  const expiring = summary?.dsas_expiring_30d;
  const overBudget = summary?.dsas_over_budget_30d;
  return (
    <div
      className="card mt-4"
      style={{
        padding: 16, display: "flex", alignItems: "center", gap: 16,
        borderLeft: "3px solid var(--accent-system)",
      }}
    >
      <div style={{
        width: 40, height: 40, borderRadius: 8,
        background: "var(--accent-system-bg)",
        color: "var(--accent-system)",
        display: "grid", placeItems: "center",
      }}>
        <Icon name="file" size={20}/>
      </div>
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{fontWeight: 600, fontSize: 14.5}}>Data Sharing Agreements</div>
        <div className="t-cap" style={{marginTop: 2, color: "var(--neutral-700)"}}>
          {active != null ? `${active} active` : "—"}
          {" · "}
          {expiring != null
            ? <strong style={{color: expiring > 0 ? "var(--accent-update)" : undefined}}>{expiring} expiring in 30d</strong>
            : "—"}
          {overBudget != null && overBudget > 0 && (
            <> · <strong style={{color: "var(--accent-danger)"}}>{overBudget} over budget</strong></>
          )}
        </div>
      </div>
      <button className="btn btn-primary btn-sm" onClick={() => onNavigate?.("dsas")}>
        Open workspace <Icon name="chevronRight" size={13}/>
      </button>
    </div>
  );
};

/* ============================================================
   Kit page — design system reference
   ============================================================ */
const KitScreen = () => {
  const allStatuses = [
    ["Registry ID", ["Provisional","Pending","Registered","Rejected","Voided"]],
    ["Submission / Change Request", ["Draft","Submitted","Pending QA","Accepted","Pending Approval","Approved","Rejected","Committed","Reversed"]],
    ["Dedup pair", ["Pending","Merged","Rejected","On hold","Cross-household"]],
    ["Connector run", ["Queued","Running","Completed","Failed","Cancelled"]],
    ["DRS request", ["Draft","Submitted","Pending DPO review","Approved","Generating","Delivered","Expired","Rejected","Revoked"]],
    ["Grievance", ["Open","In progress","Awaiting citizen response","Resolved","Closed"]],
    ["DQA severity", ["Blocking","Warning","Info"]],
    ["Sensitivity (DRS)", ["Public","Internal","Personal","Sensitive"]],
  ];
  const moduleAccents = [
    ["primary",      "Primary",       "var(--primary-900)",   "Nav, primary CTA"],
    ["data",         "DAT — Data",    "var(--accent-data)",   "Captures, success"],
    ["quality",      "DQA — Quality", "var(--accent-quality)","Warnings"],
    ["danger",       "DDUP — Danger", "var(--accent-danger)", "Errors, blocking"],
    ["identity",     "IDV — Identity","var(--accent-identity)","NIRA, member detail"],
    ["update",       "UPD — Update",  "var(--accent-update)", "Update workflow"],
    ["eligibility",  "PMT — Eligibility","var(--accent-eligibility)","PMT scoring"],
    ["programme",    "REF — Programme","var(--accent-programme)","Programmes"],
    ["grm",          "GRM — Grievance","var(--accent-grm)",    "Cases"],
    ["reference",    "REF-DATA",      "var(--accent-reference)","Reference data"],
    ["system",       "API / SEC / RPT","var(--accent-system)", "System"],
  ];

  return (
    <div className="page">
      <PageHeader
        eyebrow="DESIGN SYSTEM"
        title="NSR MIS visual kit"
        sub="Tokens per Section 4. Components per Section 5. Status vocabulary per Section 8 of the brief."
        right={<button className="btn"><Icon name="download"/> Export tokens.css</button>}
      />

      {/* Module accents */}
      <div className="card">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Module accent palette</h3><span className="t-cap">11 module tints — one per SAD module</span></div>
        <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:16}}>
          {moduleAccents.map(([k, label, color, usage]) => (
            <div key={k} className={`tint-${k === 'primary' ? 'data' : k}`} style={{border:'1px solid var(--neutral-300)', borderRadius:8, padding:14, background: k === 'primary' ? 'var(--primary-100)' : undefined}}>
              <div style={{height:48, borderRadius:4, background: color, marginBottom:10}}/>
              <div style={{fontWeight:600, fontSize:13.5}}>{label}</div>
              <div className="t-cap">{usage}</div>
              <div className="t-mono t-cap" style={{marginTop:4}}>--accent-{k}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Status chips */}
      <div className="card mt-5">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Status vocabulary</h3><span className="t-cap">Section 8 — use these labels verbatim</span></div>
        <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:24}}>
          {allStatuses.map(([family, items]) => (
            <div key={family}>
              <div className="t-cap" style={{marginBottom:8, color:'var(--neutral-700)', fontWeight:600}}>{family}</div>
              <div className="row-wrap">
                {items.map(s => <Chip key={s}>{s}</Chip>)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Typography */}
      <div className="card mt-5">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Type scale</h3><span className="t-cap">Inter — operator web; Roboto — CAPI Android; Calibri — exports</span></div>
        <div style={{padding:20}}>
          <div style={{display:'grid', gridTemplateColumns:'120px 1fr 1fr', columnGap:24, rowGap:14, alignItems:'baseline'}}>
            <div className="t-cap">Display 32/40</div><div className="t-display">National Social Registry</div><div className="t-cap t-mono">700 / -0.02em</div>
            <div className="t-cap">H1 24/32</div><div className="t-h1">DIH review queue · 342 pending</div><div className="t-cap t-mono">700 / -0.01em</div>
            <div className="t-cap">H2 20/28</div><div className="t-h2">Karamoja sub-region · Moroto district</div><div className="t-cap t-mono">600</div>
            <div className="t-cap">H3 16/24</div><div className="t-h3">Roster section — 6 members</div><div className="t-cap t-mono">600</div>
            <div className="t-cap">Body 14/20</div><div className="t-body">Lokol Naume's household at Nakiloro Parish was captured by Parish Chief Lokwang Peter on 14 May 2026 at 14:35 EAT.</div><div className="t-cap t-mono">400</div>
            <div className="t-cap">Body sm 13/18</div><div className="t-bodysm">Helper text appears below form inputs. Errors are red and reference the rule.</div><div className="t-cap t-mono">400</div>
            <div className="t-cap">Caption 12/16</div><div className="t-cap" style={{color:'var(--neutral-900)'}}>Audit ID #A-2026-05-14-00471 · written to chain</div><div className="t-cap t-mono">400</div>
            <div className="t-cap">Mono 13/18</div><div className="t-mono">01HXY7K3B2N9PVQE4M6FZRWS18</div><div className="t-cap t-mono">JetBrains Mono</div>
          </div>
        </div>
      </div>

      {/* Buttons + actions */}
      <div className="grid grid-2 mt-5">
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Buttons</h3></div>
          <div style={{padding:20, display:'flex', flexWrap:'wrap', gap:12}}>
            <button className="btn btn-primary"><Icon name="check"/> Promote</button>
            <button className="btn btn-success"><Icon name="checkCircle"/> Approve</button>
            <button className="btn btn-danger"><Icon name="xCircle"/> Reject</button>
            <button className="btn btn-warn"><Icon name="clock"/> Hold</button>
            <button className="btn">Cancel</button>
            <button className="btn btn-ghost"><Icon name="moreH"/></button>
            <button className="btn btn-primary" disabled>Disabled</button>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>KPI card</h3></div>
          <div style={{padding:20}}>
            <KPI title="DIH review queue" value="342" trend="up" trendValue="+38 today" foot="vs. 7-day avg 287" spark={[180,210,250,235,280,310,342]}/>
          </div>
        </div>
      </div>

      {/* Form controls */}
      <div className="card mt-5">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Form controls</h3></div>
        <div style={{padding:20}}>
          <div className="field-row-3">
            <Field label="Respondent name" required>
              <input className="field-input" defaultValue="Lokol Naume"/>
            </Field>
            <Field label="Phone (E.164)" required hint="Format: +256 XXX XXXXXX">
              <input className="field-input" defaultValue="+256 786 234567"/>
            </Field>
            <Field label="Household size" required error="Must be at least 1 (AC-CAP-HHSIZE)">
              <input className="field-input" defaultValue="0"/>
            </Field>
          </div>
          <div className="field-row mt-4">
            <Field label="Consent statement" required>
              <div className="seg">
                <button className="on">Yes — consented</button>
                <button>No</button>
              </div>
            </Field>
            <Field label="Urban / Rural" required>
              <div className="seg">
                <button>Urban</button>
                <button className="on">Rural</button>
              </div>
            </Field>
          </div>
        </div>
      </div>

      {/* Spacing & elevation */}
      <div className="grid grid-2 mt-5">
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Spacing scale (4-point)</h3></div>
          <div style={{padding:20}}>
            {[1,2,3,4,5,6,7,8,9,10].map(n => (
              <div key={n} className="row" style={{gap:16, marginBottom:6}}>
                <div className="t-cap t-mono" style={{width:64}}>--space-{n}</div>
                <div className="t-cap" style={{width:42}}>{[4,8,12,16,20,24,32,40,48,64][n-1]}px</div>
                <div style={{height:8, background:'var(--primary-700)', width: [4,8,12,16,20,24,32,40,48,64][n-1]}}/>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Shape & elevation</h3></div>
          <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:16}}>
            <div className="card center" style={{height:120, border:'1px solid var(--neutral-300)', boxShadow:'none'}}>radius 4</div>
            <div className="card center" style={{height:120}}>radius 8 + lvl 1</div>
            <div className="center" style={{height:120, borderRadius:2, background:'var(--neutral-100)', border:'1px solid var(--neutral-300)'}}>radius 2 (tag)</div>
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { HomeScreen, KitScreen, ROLES, ROLE_CONTENT });
