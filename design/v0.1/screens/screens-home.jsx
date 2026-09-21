/* global React, Icon, Chip, KPI, PageHeader, HomeChartBand */
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
    // Surface every non-final state — operators need to act on
    // provisional + IDV-pending + pending-promotion + quality-failed,
    // not just pending_promotion (which is a narrow auto-promote
    // hand-off window). Endpoint accepts comma-separated values
    // (apps/ingestion_hub/api.py:161 splits on `,`).
    url: "/api/v1/dih/stage-records/?state=provisional,idv_pending,pending_promotion,quality_failed&page_size=4",
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


/* ============================================================
   REAL KPIs — every number on this screen comes from the API
   ============================================================

   Each entry reads one field of
   /api/v1/rpt/dashboards/operator-kpis/, which is ABAC-scoped
   server-side, so an operator sees counts for their own geography.

   The rule, and the reason this table exists: IF A NUMBER CANNOT COME
   FROM THE API, IT DOES NOT BELONG ON THIS SCREEN. It is not rendered
   with a placeholder, and it is certainly not rendered with an invented
   value.

   The previous version carried a full set of hardcoded KPIs per role —
   "DIH review queue 342", "Fast-track auto-promote 61.4%", "Bulk batches
   awaiting dual-approval 4" — with sparklines and week-on-week trends,
   all fabricated, on a registry holding 284 households. A live overlay
   existed but most fields mapped to null, so the fallback quietly showed
   the fiction. An operator had no way to tell which numbers were real.

   Adding a KPI: add the field to the operator-kpis serializer first,
   then add a row here. There is no other order that works.
   ============================================================ */
const HOME_KPIS_BY_ROLE = {
  "nsr-unit": [
    { title: "DIH review queue",      field: "stages_pending_promotion", foot: "Stage records awaiting promotion" },
    { title: "DDUP review queue",     field: "stages_ddup_review",       foot: "Held for de-duplication review" },
    { title: "Quality failures",      field: "stages_quality_failed",    foot: "Stage records failing DQA" },
    { title: "Households registered", field: "households_total",         foot: "Within your scope" },
  ],
  "sr-manager": [
    { title: "Change requests pending", field: "change_requests_pending", foot: "Awaiting review or approval" },
    { title: "Households registered",   field: "households_total",        foot: "Within your scope" },
    { title: "Households with PMT",     field: "households_with_pmt",     foot: "Scored by the Proxy Means Test" },
    { title: "Grievances open",         field: "grievances_open",         foot: "All tiers" },
  ],
  "parish": [
    { title: "Grievances open",         field: "grievances_open",         foot: "In your parish" },
    { title: "Change requests pending", field: "change_requests_pending", foot: "Awaiting review or approval" },
    { title: "Identity checks pending", field: "stages_idv_pending",      foot: "Awaiting NIRA verification" },
    { title: "Households registered",   field: "households_total",        foot: "Within your scope" },
  ],
  "cdo": [
    { title: "UPD review queue",      field: "change_requests_pending", foot: "Change requests awaiting approval" },
    { title: "GRM L2 cases",          field: "grievances_l2_open",      foot: "Open at tier 2" },
    { title: "Grievances open",       field: "grievances_open",         foot: "All tiers" },
    { title: "Households registered", field: "households_total",        foot: "Within your scope" },
  ],
  "partner-analyst": [
    // Labelled 7d because the field IS 7d. The previous card said
    // "Delivered (30d)" while reading data_requests_delivered_7d.
    { title: "Pending approval",  field: "data_requests_pending_approval", foot: "Your data requests awaiting approval" },
    { title: "Delivered (7d)",    field: "data_requests_delivered_7d",     foot: "Bundles delivered in the last 7 days" },
  ],
  "dpo": [
    { title: "Data requests pending", field: "data_requests_pending_approval", foot: "Awaiting approval" },
    { title: "Delivered (7d)",        field: "data_requests_delivered_7d",     foot: "Bundles delivered in the last 7 days" },
    { title: "Grievances open",       field: "grievances_open",                foot: "All tiers" },
    { title: "Households registered", field: "households_total",               foot: "Within your scope" },
  ],
  "explorer": [
    { title: "Households registered", field: "households_total",     foot: "Within your scope" },
    { title: "Households with PMT",   field: "households_with_pmt",  foot: "Scored by the Proxy Means Test" },
    { title: "Change requests pending", field: "change_requests_pending", foot: "Awaiting review or approval" },
    { title: "Grievances open",       field: "grievances_open",      foot: "All tiers" },
  ],
};

/* ============================================================
   ROLE config

   Identity and navigation only. The KPI arrays and the queue `items`
   that used to live here were demo content — fabricated counts,
   sparklines, and invented households with real-looking names and
   ULIDs — and they were rendered on a production registry.

   KPIs now come from HOME_KPIS_BY_ROLE above, which reads the
   operator-kpis endpoint. Queue contents come from
   HOME_QUEUE_LIVE_MAP. `person` and `org` remain solely as a fallback
   for the standalone design harness, where there is no session to ask
   who the operator is; the deployed console passes the real identity in.
   ============================================================ */
const ROLE_CONTENT = {
  "nsr-unit": {
    name: "NSR Unit Coordinator",
    person: "Johnson Mwebaze",
    org: "MGLSD · NSR Unit",
    queues: [
      { title: "Pending DIH promotions", icon: "inbox" },
      // Bulk DRS dual-approval queue — routes to the DRS screen,
      // NOT the DIH default. CR-YYYY-MM-DD IDs are change-request
      // identifiers for partner bulk requests (US-108).
      { title: "Bulk batches awaiting dual-approval", icon: "duplicate", _target: "drs" }
    ] },
  "sr-manager": {
    name: "Social Registry Manager",
    person: "Namutebi Esther",
    org: "MGLSD · NSR Unit",
    queues: [
      { title: "Approvals — awaiting my signature", icon: "shield", _target: "admin" },
      { title: "Bulk DRS batches awaiting dual-approval", icon: "duplicate", _target: "drs" }
    ] },
  "parish": {
    name: "Parish Chief",
    person: "Lokwang Peter",
    org: "Nakiloro Parish · Tapac · Moroto",
    queues: [
      { title: "Today's captures", icon: "users" },
      { title: "Drafts about to expire", icon: "clock" }
    ] },
  "cdo": {
    name: "Community Development Officer",
    person: "Adong Florence",
    org: "Tapac Sub-county · Moroto",
    queues: [
      { title: "Pending UPD reviews", icon: "edit" },
      { title: "GRM L2 cases", icon: "message" }
    ] },
  "partner-analyst": {
    name: "Partner Analyst",
    person: "Nakimuli Sarah",
    org: "PDM Programme Office · MGLSD",
    queues: [
      { title: "Pending approval", icon: "clock" },
      { title: "Delivered (downloadable)", icon: "download" }
    ] },
  "dpo": {
    name: "Data Protection Officer",
    person: "Mukasa Robert",
    org: "MGLSD · DPO Office",
    queues: [
      { title: "Active anomalies", icon: "alert" }
    ] },
  // Data Explorer Analyst — the EXPLORER realm role (ADR-0023,
  // US-DATA-EXP-001). Discovery + aggregate-preview surface; no
  // record-level access except via the DRS handoff. KPIs mirror the
  // suppression / throttle / handoff signals the analyst lives with.
  "explorer": {
    name: "Data Explorer Analyst",
    person: "Atim Brenda",
    org: "MGLSD · NSR Unit · Analytics",
    queues: [
      { title: "Recent aggregate runs", icon: "database", _target: "data-explorer" },
      { title: "Drafts handed to DRS", icon: "download", _target: "drs" }
    ] } };

const ROLES = Object.keys(ROLE_CONTENT);

/* ============================================================
   Home dashboard
   ============================================================ */
// operatorName is the signed-in user, resolved by the shell from
// /api/v1/security/users/me/. ROLE_CONTENT[role].person is demo data and
// is only a fallback for the standalone harness, where there is no
// session to ask about.
/* Times are rendered in EAT (UTC+3) per CLAUDE.md, which is also the
   operator's local time, so the browser clock is the right source. The
   previous greeting was the literal string "Good afternoon" — wrong for
   most of the working day, and wrong at 07:00 when enumeration starts. */
const _greeting = () => {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
};

const HomeScreen = ({ role, onNavigate, operatorName }) => {
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
  // Built entirely from HOME_KPIS_BY_ROLE, never from ROLE_CONTENT.kpis.
  //
  // Three deliberate consequences:
  //   * a role with no real field for something simply shows fewer cards,
  //     rather than a card with an invented number;
  //   * before the fetch returns, the value is an em dash, so a number on
  //     screen is always a number the server sent;
  //   * no spark, no trend. Both were fabricated series; the endpoint
  //     returns a single point, and drawing a week of history from one
  //     point would be inventing data again. They return when
  //     /api/v1/rpt/dashboards/comparative/ is wired in.
  const kpis = (HOME_KPIS_BY_ROLE[role] || HOME_KPIS_BY_ROLE["nsr-unit"])
    .map(({ title, field, foot }) => {
      const loaded = liveKpis && liveKpis[field] != null;
      return {
        title,
        value: loaded ? String(liveKpis[field]) : "—",
        foot: loaded ? foot : "Loading…",
      };
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
          // `data.count` is DRF's total across all pages — items
          // is capped at page_size=4 for the tile preview, but the
          // count displayed should reflect the full backlog.
          const total = (typeof data.count === "number") ? data.count : items.length;
          setLiveQueues(prev => ({ ...prev, [title]: { items, total } }));
        })
        .catch(() => {});
    });
    return () => { cancelled = true; };
  }, [r.queues, region]);

  // Only queues with a live endpoint are shown. An unwired queue used to
  // fall through to its mock items — four invented households with real
  // -looking names and ULIDs, which is considerably worse than showing
  // nothing on a registry of actual people.
  const queues = r.queues.filter(q => HOME_QUEUE_LIVE_MAP[q.title]).map(q => {
    const live = liveQueues[q.title];
    if (live === undefined) {
      return { ...q, count: null, items: [] };   // still loading
    }
    return {
      ...q,
      // `items` is read as `q.items.length` three times below, so a
      // queue entry without one takes the whole home screen down with
      // "Cannot read properties of undefined (reading 'length')" — the
      // error boundary's SCREEN CRASHED card, on the first thing an
      // operator sees. The setter always supplies an array today; this
      // is the guard that stops a future writer having to know that.
      items: Array.isArray(live.items) ? live.items : [],
      count: live.total,
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
        title={<span>{_greeting()}, <span style={{color:'var(--primary-900)'}}>{(operatorName || r.person).split(' ')[0]}</span></span>}
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
          <button className="btn"
                  onClick={() => window.print()}
                  title="Print or save as PDF — sidebar + topbar are hidden via the existing @media print rule">
            <Icon name="download"/> Export brief
          </button>
          <button className="btn btn-primary"
                  onClick={() => onNavigate?.("capture")}>
            <Icon name="plus"/> New capture
          </button>
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

      <div className="card mt-5">
        <div className="card-header">
          <h3 className="t-h3" style={{margin:0}}>Across the registry</h3>
          <span className="t-cap">{liveKpis ? "live (one-shot fetch)" : "loading\u2026"}</span>
        </div>
        {/* Same rule as the KPI row above: a number the API supplied, or
            an em dash. This block kept the pre-live fallbacks — 9,847,221
            households, 48,116,802 individuals, "Refreshed 14:35 EAT" —
            which is what an operator read while the fetch was in flight
            or after it failed. It also called .toLocaleString() straight
            off the payload, so a response missing one field took the
            whole home screen down with it. */}
        {/* Six stats now, so three-up rather than four: at four columns
            the sixth wraps alone onto a second row and reads as an
            afterthought. */}
        <div className="grid grid-3" style={{padding:20}}>
          <RegistryStat
            label="Total households (Registered)"
            value={_homeNum(liveKpis, "households_total")}
            sub={liveKpis ? "in your ABAC scope" : "not loaded"}/>
          <RegistryStat
            label="Provisional, pending promotion"
            value={_homeNum(liveKpis, "stages_pending_promotion")}
            sub={liveKpis
              ? `quality-fail ${_homeNum(liveKpis, "stages_quality_failed")}`
                + ` · ddup ${_homeNum(liveKpis, "stages_ddup_review")}`
                + ` · idv ${_homeNum(liveKpis, "stages_idv_pending")}`
              : "not loaded"}/>
          <RegistryStat
            label="Households with PMT score"
            value={_homeNum(liveKpis, "households_with_pmt")}
            sub={liveKpis ? "ready for programme eligibility" : "not loaded"}/>
          <RegistryStat
            label="Registered partners"
            value={_homeNum(liveKpis, "partners_total")}
            sub={liveKpis ? "national — a partner is not in a sub-region" : "not loaded"}/>
          <RegistryStat
            label="Active programmes"
            value={_homeNum(liveKpis, "programmes_active")}
            sub={liveKpis ? "accepting enrolments" : "not loaded"}/>
          <RegistryStat
            label="Operator queues"
            value={liveKpis
              ? `UPD ${_homeNum(liveKpis, "change_requests_pending")}`
                + ` · GRM ${_homeNum(liveKpis, "grievances_open")}`
              : "\u2014"}
            sub={liveKpis
              ? `DRS ${_homeNum(liveKpis, "data_requests_pending_approval")} pending`
              : "not loaded"}/>
        </div>
      </div>

      {/* Chart band (US-S24-HOME-CHARTS). Sits between the registry
          stats and the queues: the stats say how big the registry is,
          the charts say what shape it is, the queues say what to do
          today. Follows the sub-region drill-down like the KPIs do, and
          every card states its own scope so a printed copy cannot be
          read as national when it is not. */}
      {typeof HomeChartBand === "function" && (
        <HomeChartBand
          region={region}
          regionLabel={(subRegions.find(s => s.code === region) || {}).name}/>
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
                    <div className="t-cap">{(q.items || []).length} open</div>
                  </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => onNavigate?.(target)}>
                  Open queue <Icon name="chevronRight" size={14}/>
                </button>
              </div>
              <div>
                {(q.items || []).length === 0 && (
                  <div className="t-bodysm muted" style={{padding:"24px 20px", textAlign:"center"}}>
                    Queue empty.
                  </div>
                )}
                {(q.items || []).map((item, j) => (
                  <div key={j} className="row gap-3" style={{padding:'12px 20px', borderBottom: j < (q.items || []).length - 1 ? '1px solid var(--neutral-200)' : 'none', cursor:'pointer'}}
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

      <div className="t-cap" style={{marginTop:24, textAlign:'center'}}>
        NSR MIS v0.1 · Solution Architecture Document v0.6 · ERD v0.6 · NITA-U Government Data Centre
      </div>
    </div>
  );
};

// One number from the KPI payload, or an em dash. Never a fabricated
// stand-in, and never a method call on a field the response omitted.
const _homeNum = (kpis, field) => {
  const v = kpis ? kpis[field] : null;
  return (typeof v === "number") ? v.toLocaleString() : "\u2014";
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
