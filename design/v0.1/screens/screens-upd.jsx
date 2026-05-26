/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, ReasonModal, ActionBar, Toast */
// NSR MIS — UPD reviewer (US-S22-001 live wiring).
// Mirrors the GRM workbench pattern from US-S21-002: queue + bulk +
// per-row actions fetch /api/v1/upd/change-requests/ and route through
// the matching POST endpoint. The mock queue below is the offline
// fallback for file:// previews — the diff panel + PMT preview rail
// still drive off the static UPD constant; live-row-driven diff is a
// separate slice.

const { useState: useStateUpd, useEffect: useEffectUpd } = React;

// CSRF cookie reader — required for DRF session-auth POSTs. Same
// pattern as screens-grm. file:// previews lack the cookie, so the
// action fetches 403 (and we fall back to the offline-preview path).
const _updCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

// Map ChangeRequest.change_type codes (apps.update_workflow.models.
// ChangeType) to the human label the queue column expects.
const _updTypeLabel = {
  correction:       "Data correction",
  addition:         "Roster: add member",
  removal:          "Roster: remove member",
  vital_event:      "Roster: vital event",
  programme_state:  "Programme state update",
  recertification:  "Recertification",
};

// Project a ChangeRequestSerializer row into the view-model the queue
// renders. SLA semantics: slaDays = days since created_at, slaCap =
// days from created_at to sla_deadline; breach = slaDays > slaCap.
// canSelfApprove defaults to true — the server enforces the guard
// and the bulk endpoint reports skipped ids with reason.
const _DAY_MS = 86_400_000;
const _updApiToView = (cr) => {
  const created = cr.created_at ? new Date(cr.created_at).getTime() : null;
  const deadline = cr.sla_deadline ? new Date(cr.sla_deadline).getTime() : null;
  const now = Date.now();
  const slaDays = created !== null
    ? Math.max(0, Math.ceil((now - created) / _DAY_MS))
    : 0;
  const slaCap = (created !== null && deadline !== null)
    ? Math.max(1, Math.ceil((deadline - created) / _DAY_MS))
    : 3;
  return {
    id: cr.id,
    head: cr.entity_id ? cr.entity_id.slice(0, 12) + "…" : "—",
    parish: cr.entity_type === "household" ? "Household" : "Member",
    type: _updTypeLabel[cr.change_type] || cr.change_type,
    pmt: !!cr.pmt_relevant,
    slaDays, slaCap,
    submitter: cr.requester || "—",
    canSelfApprove: true,
    _raw: cr,
  };
};

// Mock queue — what's PENDING_APPROVAL in the reviewer's scope.
// In production this comes from GET /api/v1/upd/change-requests/?status=
// pending_approval, sorted by SLA-soonest-first. Mix of change_types +
// PMT-relevance + SLA states so the demo exercises every visual state.
const UPD_QUEUE = [
  { id: "UPD-2026-05-14-00237", head: "Lokol Naume", parish: "Nakiloro · Tapac",
    type: "Roster: add member", pmt: true, slaDays: 2, slaCap: 3,
    submitter: "Lokwang Peter", canSelfApprove: true },
  { id: "UPD-2026-05-14-00241", head: "Akello Sarah", parish: "Lopuwapuwa · Tapac",
    type: "Address: village move", pmt: false, slaDays: 1, slaCap: 3,
    submitter: "Adong Florence", canSelfApprove: false },
  { id: "UPD-2026-05-13-00208", head: "Omara John", parish: "Kakingol · Tapac",
    type: "Roster: vital event (death)", pmt: true, slaDays: 3, slaCap: 3,
    submitter: "Lokwang Peter", canSelfApprove: true },
  { id: "UPD-2026-05-13-00203", head: "Apio Grace", parish: "Nakiloro · Tapac",
    type: "Phone update", pmt: false, slaDays: 4, slaCap: 3,
    submitter: "Otto Vincent", canSelfApprove: true },
  { id: "UPD-2026-05-12-00191", head: "Loum Margaret", parish: "Lopuwapuwa · Tapac",
    type: "Education: school enrolment", pmt: true, slaDays: 2, slaCap: 3,
    submitter: "Lokwang Peter", canSelfApprove: true },
  { id: "UPD-2026-05-12-00188", head: "Ekiru Peter", parish: "Kakingol · Tapac",
    type: "Roster: add member", pmt: true, slaDays: 5, slaCap: 3,
    submitter: "Adong Florence", canSelfApprove: false },
  { id: "UPD-2026-05-12-00182", head: "Achan Beatrice", parish: "Nakiloro · Tapac",
    type: "Identification update (NIN)", pmt: false, slaDays: 1, slaCap: 3,
    submitter: "Otto Vincent", canSelfApprove: true },
  { id: "UPD-2026-05-11-00170", head: "Lopeyok Mary", parish: "Lopuwapuwa · Tapac",
    type: "Housing: roof material", pmt: true, slaDays: 3, slaCap: 3,
    submitter: "Otto Vincent", canSelfApprove: true },
];

// Simulates POST /api/v1/upd/change-requests/bulk-<action>/. The backend
// shape (S10-004): { acted: [ids], skipped: [{id, reason}], not_found: [ids] }
// Rows where the current actor is the submitter get skipped under
// AC-UPD-NO-SELF-APPROVE for the approve action; reject + escalate
// have no self-action constraint.
const mockBulkResponse = (rows, action) => {
  const acted = [];
  const skipped = [];
  rows.forEach(r => {
    if (action === 'approve' && !r.canSelfApprove) {
      skipped.push({ id: r.id, reason: "AC-UPD-NO-SELF-APPROVE: cannot approve your own submission" });
    } else {
      acted.push(r.id);
    }
  });
  return { acted, skipped, not_found: [] };
};

const UPD = {
  id: "UPD-2026-05-14-00237",
  household: "01HXY7K3B2N9PVQE4M6FZRWS18",
  head: "Lokol Naume",
  parish: "Nakiloro · Tapac · Moroto",
  change_type: "Roster: add member",
  pmt_impact: "pmt_relevant",
  sla: { days_open: 2, sla: 3, breach: false },
  submitter: "Lokwang Peter · Parish Chief · PCH-7411",
  reviewer: "Adong Florence · CDO Tapac",
  evidence: ["Photo (baby)", "Witness statement", "Health-centre note"],
  reason: "Birth of dependant in household (Apr 2026)",
  diff: [
    { field: "Household size",   before: "6",  after: "7", section: "Roster",    important: true },
    { field: "Member 07 · Name", before: "—",  after: "Lokol Sarah", section: "Roster" },
    { field: "Member 07 · Sex",  before: "—",  after: "F", section: "Roster" },
    { field: "Member 07 · DoB",  before: "—",  after: "8 Apr 2026", section: "Roster" },
    { field: "Member 07 · Relation", before: "—", after: "Daughter", section: "Roster" },
    { field: "Children under 5", before: "1",  after: "2", section: "Health & Disability", important: true },
    { field: "Birth-registered", before: "1",  after: "2", section: "Health & Disability" },
    { field: "Phone",            before: "+256 786 234567", after: "+256 786 234567", section: "Identification", unchanged: true },
    { field: "GPS lat,lng",      before: "2.49423, 34.65103", after: "2.49423, 34.65103", section: "Identification", unchanged: true },
    { field: "Roof material",    before: "Iron sheets", after: "Iron sheets", section: "Housing", unchanged: true },
    { field: "PMT score",        before: "0.412", after: "0.387", section: "PMT (recomputed)", important: true, mono: true },
    { field: "PMT band",         before: "Poorest 40%", after: "Poorest 20%", section: "PMT (recomputed)", important: true },
  ],
};

const UPDScreen = ({ changeRequestId, onNavigate }) => {
  const [showAll, setShowAll] = useStateUpd(false);
  const [auditOpen, setAuditOpen] = useStateUpd(false);
  const [modal, setModal] = useStateUpd(null);
  const [toast, setToast] = useStateUpd("");
  const [selfApprove] = useStateUpd(false); // disabled in UI

  // Live wiring state (US-S22-001). `queue` is the rendered roster —
  // mock by default, swapped for live rows on successful fetch.
  // `dataSource` drives the eyebrow indicator and the fallback paths
  // in fire / fireBulk. `busy` disables action buttons in-flight.
  // `current` is the row clicked to open detail (drives the diff +
  // PMT preview + sticky bar). `me` is the /me probe's response and
  // gets bound as `actor` on every action POST.
  const [queue, setQueue] = useStateUpd(UPD_QUEUE);
  const [dataSource, setDataSource] = useStateUpd("mock");
  const [busy, setBusy] = useStateUpd(false);
  const [current, setCurrent] = useStateUpd(null);
  const [me, setMe] = useStateUpd(null);

  // Bulk-action state (US-S11-004). `selected` holds the row ids;
  // `bulkModal` opens the reason modal with the captured action.
  // `bulkResult` stays around long enough to render the skipped-rows
  // breakdown below the queue after the API call returns.
  const [selected, setSelected] = useStateUpd(() => new Set());
  const [bulkModal, setBulkModal] = useStateUpd(null);
  const [bulkResult, setBulkResult] = useStateUpd(null);

  // Refresh the pending-approval queue from the API. Used on mount
  // and after every successful action. On unreachable API (file://
  // preview) it sets dataSource so the eyebrow + fallbacks reflect
  // offline mode.
  const refresh = () => fetch(
    "/api/v1/upd/change-requests/?status=pending_approval&page_size=100", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => {
      const list = (data.results || data || []).map(_updApiToView);
      if (list.length === 0) {
        setDataSource("live-empty");
        return;
      }
      setQueue(list);
      setDataSource("live");
    })
    .catch(() => { setDataSource("offline"); });

  useEffectUpd(() => { refresh(); /* eslint-disable-line */ }, []);

  // Probe /me to learn the current user's username, then bind it as
  // `actor` on subsequent action POSTs. 401/403 (file:// preview)
  // leaves me=null and falls back to "console-operator".
  useEffectUpd(() => {
    fetch("/api/v1/upd/change-requests/me/", {
      credentials: "same-origin", headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setMe(data); })
      .catch(() => {});
  }, []);

  // When the live queue refreshes, default `current` to the first row
  // so the detail rail isn't empty. If the previous `current` is
  // still in the new queue, keep it (refresh after an action retains
  // context). Offline keeps current=null so the mock UPD constant
  // renders.
  useEffectUpd(() => {
    if (dataSource !== "live" && dataSource !== "live-empty") return;
    if (queue.length === 0) { setCurrent(null); return; }
    if (current && queue.some(r => r.id === current.id)) {
      const refreshed = queue.find(r => r.id === current.id);
      setCurrent(refreshed);
      return;
    }
    setCurrent(queue[0]);
    /* eslint-disable-next-line */
  }, [queue, dataSource]);

  const toggleRow = (id) => {
    const next = new Set(selected);
    if (next.has(id)) { next.delete(id); } else { next.add(id); }
    setSelected(next);
  };
  const toggleAll = () => {
    if (selected.size === queue.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(queue.map(r => r.id)));
    }
  };
  const clearSelected = () => setSelected(new Set());

  // Bulk dispatcher. Live mode POSTs once to /bulk-<action>/ with
  // {ids, actor, reason}; the server response shape is identical to
  // mockBulkResponse so the result panel renders unchanged. Offline
  // mode keeps the mock pathway so the design preview still demos.
  const fireBulk = ({ reason, note }) => {
    const action = bulkModal;
    const ids = Array.from(selected);
    const verb = action === 'approve' ? 'approved'
               : action === 'reject'  ? 'rejected'
               : 'escalated';

    if (dataSource !== "live" && dataSource !== "live-empty") {
      const rows = queue.filter(r => selected.has(r.id));
      const result = mockBulkResponse(rows, action);
      setBulkResult({ ...result, action, reason, note });
      const remaining = new Set(selected);
      result.acted.forEach(id => remaining.delete(id));
      setSelected(remaining);
      setBulkModal(null);
      setToast(`${result.acted.length} ${verb} · ${result.skipped.length} skipped · ${result.not_found.length} not found`);
      return;
    }

    setBusy(true);
    fetch(`/api/v1/upd/change-requests/bulk-${action}/`, {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _updCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({
        ids,
        actor: "console-operator",
        reason: reason || note || "",
      }),
    })
      .then(async r => {
        if (r.ok) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(result => {
        setBulkResult({ ...result, action, reason, note });
        const remaining = new Set(selected);
        result.acted.forEach(id => remaining.delete(id));
        setSelected(remaining);
        setBulkModal(null);
        setToast(`${result.acted.length} ${verb} · ${result.skipped.length} skipped · ${result.not_found.length} not found`);
        return refresh();
      })
      .catch(e => {
        setBulkModal(null);
        setToast(`Bulk ${action} failed: ${e.message}`);
      })
      .finally(() => setBusy(false));
  };

  // Cross-screen handoff (US-S9-004). When the GRM workbench navigates
  // here with a linked_change_request_id, we override the mock id so
  // the operator sees they landed on the right CR. Backend wiring is
  // unchanged — Grievance.linked_change_request_id (S2-008) is what
  // the real fetch will resolve.
  const effectiveId = changeRequestId || (isLive ? current.id : UPD.id);
  const fromGrm = Boolean(changeRequestId);

  // Eyebrow indicator — mirrors the GRM workbench convention.
  const eyebrow = fromGrm
    ? "UPDATES · US-090 · OPENED FROM GRM"
    : dataSource === "live"      ? "UPDATES · US-S22-001 · LIVE"
    : dataSource === "live-empty" ? "UPDATES · US-S22-001 · live (0 in scope)"
    : dataSource === "offline"   ? "UPDATES · US-S22-001 · OFFLINE PREVIEW"
    : "UPDATES · US-S22-001";

  // Diff data: live mode projects current._raw.changes JSON into the
  // same shape the table renders. The serializer's diff has no
  // semantic section metadata, so live rows collapse into a single
  // "Change fields" section. Mock keeps the rich pre-grouped UPD.diff.
  const diffSource = isLive
    && current._raw.changes
    && Object.keys(current._raw.changes).length > 0
    ? Object.entries(current._raw.changes).map(([field, ch]) => ({
        field,
        before: ch && ch.old !== undefined && ch.old !== null && ch.old !== ""
                  ? String(ch.old) : "—",
        after:  ch && ch.new !== undefined && ch.new !== null
                  ? String(ch.new) : "—",
        section: "Change fields",
        important: false,
      }))
    : UPD.diff;
  const visible = showAll ? diffSource : diffSource.filter(d => !d.unchanged);
  const grouped = visible.reduce((acc, r) => {
    (acc[r.section] = acc[r.section] || []).push(r); return acc;
  }, {});

  const reasonsReject = [
    "Insufficient evidence (AC-UPD-EVIDENCE)",
    "Field outside operator scope",
    "Conflicting with active GRM case",
    "Other (specify in note)",
  ];

  // Per-row dispatcher for the sticky action bar. Operates on
  // `current` (the row opened for detail). ReasonModal calls onConfirm
  // with {reason, note}; both get folded into the API's `reason`
  // field. Actor is bound from /me when live; falls back to
  // "console-operator" for previews. Successful action drops current
  // so the next refresh seeds a new one.
  const fire = (kind, reasonObj = {}) => {
    const { reason = "", note = "" } = reasonObj || {};
    if (dataSource !== "live" && dataSource !== "live-empty") {
      const m = {
        approve:  "Approved. New HouseholdVersion written. PMT recompute queued. (preview — not persisted)",
        reject:   "Rejected. Citizen will be notified by SMS. (preview — not persisted)",
        hold:     "Held for more info. Reviewer notified. (preview — not persisted)",
        release:  "Released back into the queue. (preview — not persisted)",
        escalate: "Escalated to District M&E Officer. (preview — not persisted)",
      };
      setToast(m[kind] || "Done.");
      setModal(null);
      return;
    }
    if (!current) {
      setToast("Open a row from the queue first.");
      setModal(null);
      return;
    }
    const actor = me?.username || "console-operator";
    setBusy(true);
    fetch(`/api/v1/upd/change-requests/${current.id}/${kind}/`, {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _updCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({ actor, reason: reason || note || "" }),
    })
      .then(async r => {
        if (r.ok) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(() => {
        const verb = kind === "approve" ? "approved"
                   : kind === "reject"  ? "rejected"
                   : kind === "hold"    ? "held"
                   : kind === "release" ? "released"
                   : "escalated";
        setToast(`Change request ${current.id.slice(0, 8)}… ${verb}.`);
        setModal(null);
        // hold keeps row in queue (status flips to ON_HOLD which
        // drops out of ?status=pending_approval); release brings a
        // new row into the queue. Either way, refresh repopulates
        // current via the queue-watch effect.
        setCurrent(null);
        return refresh();
      })
      .catch(e => {
        setToast(`${kind} failed: ${e.message}`);
        setModal(null);
      })
      .finally(() => setBusy(false));
  };

  // View-model projection for the header strip, diff panel, and PMT
  // preview rail. Live: drive off current's serializer row. Offline /
  // no current: keep the static UPD mock so the design preview still
  // demos. Self-approve banner uses `me` to detect requester==reviewer.
  // Live rendering requires both a live data source AND a current
  // row that actually carries the serializer payload (`_raw`). When
  // the API returns 0 rows we keep the mock queue visible for the
  // design preview, but those rows have no `_raw` — falling through
  // to the live branch then dereferences current._raw.* and crashes
  // the screen. Gate `isLive` on the presence of _raw to keep the
  // render coherent in the live-empty case.
  const isLive = (dataSource === "live" || dataSource === "live-empty")
    && current
    && current._raw;
  const headerVM = isLive
    ? {
        change_type: _updTypeLabel[current._raw.change_type] || current._raw.change_type,
        pmt_relevant: !!current._raw.pmt_relevant,
        evidence: Array.isArray(current._raw.evidence) ? current._raw.evidence : [],
        slaDays: current.slaDays,
        slaCap: current.slaCap,
        submitter: current._raw.requester || "—",
        reviewer: me?.username || "—",
        reason: current._raw.requester_note || "",
        status: current._raw.status,
        household: current._raw.entity_id || "—",
        // household_id is the navigation target for "Open household".
        // For entity_type='household' it equals entity_id; for 'member'
        // the backend resolves Member.household_id (apps/update_workflow
        // /api.py ChangeRequestSerializer.get_household_id).
        household_id: current._raw.household_id || (
          current._raw.entity_type === "household" ? current._raw.entity_id : null
        ),
        entity_label: current._raw.entity_type === "household" ? "Household" : "Member",
      }
    : {
        change_type: UPD.change_type,
        pmt_relevant: true,
        evidence: UPD.evidence,
        slaDays: UPD.sla.days_open,
        slaCap: UPD.sla.sla,
        submitter: UPD.submitter.split(" · ")[0],
        reviewer: UPD.reviewer.split(" · ")[0],
        reason: UPD.reason,
        status: "pending_approval",
        household: UPD.household,
        household_id: UPD.household,
        entity_label: "Household",
      };
  const isSelfRequest = isLive && me?.username && me.username === current._raw.requester;
  const isOnHold = isLive && current._raw.status === "on_hold";

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow={eyebrow}
        title={<>Change request <span className="t-mono" style={{fontSize:14, marginLeft:8, color:'var(--neutral-500)'}}>{effectiveId}</span></>}
        sub={<>
          {fromGrm && <Chip tone="data" size="sm" style={{marginRight:8}}>linked from grievance</Chip>}
          {headerVM.entity_label} <span className="t-mono">{(headerVM.household || "").slice(0,18)}{headerVM.household && headerVM.household.length > 18 ? "…" : ""}</span>
          {isLive ? <> · <Chip tone="neutral" size="sm">{headerVM.status}</Chip></> : <> · {UPD.head} · {UPD.parish}</>}
        </>}
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn"
                  disabled={!headerVM.household_id}
                  onClick={() => headerVM.household_id && onNavigate?.("household", { householdId: headerVM.household_id })}
                  title={headerVM.household_id ? "Open the household this change request affects" : "Household not resolvable for this change request"}>
            <Icon name="eye"/> Open household
          </button>
        </>}
      />

      {/* Queue + bulk actions (US-S11-004) */}
      <div className="card" style={{marginBottom:16}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">My queue · pending approval</strong>
          <Chip tone="data" size="sm">{queue.length} rows</Chip>
          <div style={{flex:1}}/>
          <span className="t-cap">
            {selected.size > 0
              ? <><strong>{selected.size}</strong> selected · cap 200 per batch</>
              : "Click a row to open · tick to select for bulk"}
          </span>
        </div>
        <div style={{maxHeight:240, overflowY:'auto'}}>
          <div style={{display:'grid', gridTemplateColumns:'32px 220px 1fr 200px 140px 100px 100px',
                        position:'sticky', top:0, background:'var(--neutral-50)',
                        borderBottom:'1px solid var(--neutral-200)', zIndex:1}}>
            <div style={{padding:'8px 10px'}}>
              <input type="checkbox"
                checked={queue.length > 0 && selected.size === queue.length}
                ref={el => { if (el) el.indeterminate = selected.size > 0 && selected.size < queue.length; }}
                onChange={toggleAll}/>
            </div>
            <div className="t-cap" style={{padding:'10px 12px'}}>ID</div>
            <div className="t-cap" style={{padding:'10px 12px'}}>HEAD &middot; PARISH</div>
            <div className="t-cap" style={{padding:'10px 12px'}}>CHANGE TYPE</div>
            <div className="t-cap" style={{padding:'10px 12px'}}>PMT</div>
            <div className="t-cap" style={{padding:'10px 12px'}}>SLA</div>
            <div className="t-cap" style={{padding:'10px 12px'}}>SUBMITTER</div>
          </div>
          {queue.map(r => {
            const selectedRow = selected.has(r.id);
            const isCurrent = current && current.id === r.id;
            const breach = r.slaDays > r.slaCap;
            return (
              <div key={r.id}
                onClick={() => setCurrent(r)}
                style={{display:'grid', gridTemplateColumns:'32px 220px 1fr 200px 140px 100px 100px',
                        borderBottom:'1px solid var(--neutral-200)',
                        background: isCurrent ? 'var(--accent-update-bg)'
                                  : selectedRow ? 'var(--neutral-100)' : 'white',
                        borderLeft: isCurrent ? '3px solid var(--accent-update)' : '3px solid transparent',
                        cursor:'pointer'}}>
                <div style={{padding:'10px'}}>
                  <input type="checkbox" checked={selectedRow}
                    onChange={() => toggleRow(r.id)} onClick={(e) => e.stopPropagation()}/>
                </div>
                <div className="t-mono" style={{padding:'10px 12px', fontSize:12, display:'flex', alignItems:'center'}}>
                  {r.id}
                </div>
                <div style={{padding:'10px 12px', fontSize:13, display:'flex', flexDirection:'column'}}>
                  <strong>{r.head}</strong>
                  <span className="t-bodysm muted">{r.parish}</span>
                </div>
                <div style={{padding:'10px 12px', fontSize:13, display:'flex', alignItems:'center'}}>
                  {r.type}
                </div>
                <div style={{padding:'10px 12px', display:'flex', alignItems:'center'}}>
                  {r.pmt ? <Chip tone="eligibility" size="sm">pmt_relevant</Chip>
                         : <span className="t-bodysm muted">—</span>}
                </div>
                <div style={{padding:'10px 12px', display:'flex', alignItems:'center'}}>
                  <Chip tone={breach ? "danger" : "data"} size="sm">
                    {r.slaDays}d / {r.slaCap}d
                  </Chip>
                </div>
                <div style={{padding:'10px 12px', fontSize:12,
                              color: r.canSelfApprove ? 'var(--neutral-700)' : 'var(--accent-quality)',
                              display:'flex', alignItems:'center', gap:4}}>
                  {!r.canSelfApprove && <Icon name="shield" size={11}/>}
                  {r.submitter.split(' ')[0]}
                </div>
              </div>
            );
          })}
        </div>

        {/* Bulk-action toolbar — appears whenever rows are selected */}
        {selected.size > 0 && (
          <div style={{display:'flex', alignItems:'center', gap:12,
                        padding:'10px 16px', background:'var(--neutral-100)',
                        borderTop:'1px solid var(--neutral-200)'}}>
            <strong className="t-bodysm">{selected.size} selected</strong>
            <span className="t-cap">Bulk actions use the same per-row guards (AC-UPD-NO-SELF-APPROVE).</span>
            <div style={{flex:1}}/>
            <button className="btn btn-sm" onClick={clearSelected}>Clear</button>
            <button className="btn btn-sm btn-danger" onClick={() => setBulkModal('reject')}>
              <Icon name="xCircle" size={12}/> Bulk reject
            </button>
            <button className="btn btn-sm" onClick={() => setBulkModal('escalate')}>
              <Icon name="arrowUp" size={12}/> Bulk escalate
            </button>
            <button className="btn btn-sm btn-success" onClick={() => setBulkModal('approve')}>
              <Icon name="check" size={12}/> Bulk approve
            </button>
          </div>
        )}

        {/* Result panel — shows the last bulk-call's skipped breakdown */}
        {bulkResult && (
          <div style={{padding:'10px 16px', background:'var(--neutral-50)',
                        borderTop:'1px solid var(--neutral-200)', fontSize:13}}>
            <div className="row gap-2" style={{marginBottom:6}}>
              <Chip tone="data" size="sm">last bulk: {bulkResult.action}</Chip>
              <span className="t-bodysm muted">
                {bulkResult.acted.length} acted &middot; {bulkResult.skipped.length} skipped &middot; {bulkResult.not_found.length} not found
              </span>
              <div style={{flex:1}}/>
              <button className="btn btn-sm" onClick={() => setBulkResult(null)}>Dismiss</button>
            </div>
            {bulkResult.skipped.length > 0 && (
              <ul style={{margin:'4px 0 0 18px', padding:0, color:'var(--neutral-700)'}}>
                {bulkResult.skipped.map(s => (
                  <li key={s.id}>
                    <span className="t-mono" style={{fontSize:12}}>{s.id}</span>
                    {' — '}{s.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Header strip */}
      <div className="card" style={{padding:'16px 20px', display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr 1fr 1fr', gap:24, marginBottom:16, alignItems:'center'}}>
        <div>
          <div className="t-cap">CHANGE TYPE</div>
          <div className="row gap-2"><Chip tone="update">{headerVM.change_type}</Chip></div>
          <div className="t-bodysm muted mt-2">{headerVM.reason || (isLive ? "(no requester note)" : "")}</div>
        </div>
        <div>
          <div className="t-cap">PMT IMPACT</div>
          {headerVM.pmt_relevant
            ? <Chip tone="eligibility"><Icon name="target" size={11}/> pmt_relevant</Chip>
            : <Chip tone="neutral" size="sm">not PMT-relevant</Chip>}
          <div className="t-bodysm muted mt-2">{headerVM.pmt_relevant ? "Recompute previewed →" : "No PMT recompute"}</div>
        </div>
        <div>
          <div className="t-cap">EVIDENCE</div>
          <div className="row-wrap mt-1">
            {headerVM.evidence.length > 0
              ? headerVM.evidence.map((e, i) => (
                  <Chip key={i} size="sm" tone="programme">
                    {typeof e === "string" ? e : (e.label || e.kind || JSON.stringify(e))}
                  </Chip>
                ))
              : <span className="t-bodysm muted">{isLive ? "—" : ""}</span>}
          </div>
        </div>
        <div>
          <div className="t-cap">SLA</div>
          <div className="row gap-2">
            <Chip tone={headerVM.slaDays > headerVM.slaCap ? "danger" : "data"}>
              <Icon name="clock" size={11}/> {headerVM.slaDays}d / {headerVM.slaCap}d
            </Chip>
          </div>
          <div className="t-bodysm muted mt-1">
            {headerVM.slaDays > headerVM.slaCap ? "Past SLA" : "Within window"}
          </div>
        </div>
        <div>
          <div className="t-cap">PEOPLE</div>
          <div className="t-bodysm" style={{fontWeight:500}}>Submitted: {headerVM.submitter}</div>
          <div className="t-cap">Reviewer: {headerVM.reviewer}</div>
        </div>
      </div>

      {/* Diff + PMT preview */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 340px', gap:16}}>
        <div className="card">
          <div className="card-toolbar">
            <strong className="t-bodysm">Before / after diff</strong>
            <span className="t-cap">{visible.length} fields shown · {diffSource.length} total</span>
            <div style={{flex:1}}/>
            <label className="row gap-2" style={{fontSize:13}}>
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)}/>
              Show unchanged fields
            </label>
          </div>
          <div>
            {/* header */}
            <div style={{display:'grid', gridTemplateColumns:'200px 1fr 1fr', borderBottom:'1px solid var(--neutral-200)', background:'var(--neutral-50)'}}>
              <div className="t-cap" style={{padding:'10px 16px'}}>FIELD</div>
              <div className="t-cap" style={{padding:'10px 16px', borderLeft:'1px solid var(--neutral-200)'}}>BEFORE</div>
              <div className="t-cap" style={{padding:'10px 16px', borderLeft:'1px solid var(--neutral-200)'}}>AFTER</div>
            </div>

            {Object.entries(grouped).map(([section, rows]) => (
              <React.Fragment key={section}>
                <div style={{padding:'8px 16px', background:'var(--neutral-100)', fontSize:11, fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--neutral-700)', borderBottom:'1px solid var(--neutral-200)'}}>
                  {section}
                </div>
                {rows.map((row, i) => (
                  <div key={i} style={{display:'grid', gridTemplateColumns:'200px 1fr 1fr', borderBottom:'1px solid var(--neutral-200)', alignItems:'stretch'}}>
                    <div style={{padding:'10px 16px', fontSize:13, fontWeight:500, display:'flex', alignItems:'center', gap:6}}>
                      {row.important && <span style={{width:6, height:6, borderRadius:'50%', background:'var(--accent-update)'}}/>}
                      {row.field}
                    </div>
                    <div className={row.mono ? 't-mono' : ''} style={{padding:'10px 16px', borderLeft: row.unchanged ? '1px solid var(--neutral-200)' : '3px solid var(--neutral-200)', background: row.unchanged ? 'var(--neutral-50)' : 'transparent', fontSize: 13, color: row.unchanged ? 'var(--neutral-500)' : 'var(--neutral-900)'}}>
                      {row.before}
                    </div>
                    <div className={row.mono ? 't-mono' : ''} style={{padding:'10px 16px', borderLeft: row.unchanged ? '1px solid var(--neutral-200)' : '3px solid var(--accent-update)', background: row.unchanged ? 'var(--neutral-50)' : 'var(--accent-update-bg)', fontSize: 13, fontWeight: row.unchanged ? 400 : 500, color: row.unchanged ? 'var(--neutral-500)' : 'var(--neutral-900)'}}>
                      {row.after}
                    </div>
                  </div>
                ))}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* Right rail */}
        <div className="col gap-3">
          {/* PMT preview — live rows show pmt_preview JSON when present,
              otherwise a "deferred until apps.pmt" placeholder. Mock
              keeps the rich demo card. Hidden entirely when the
              current change request isn't PMT-relevant. */}
          {headerVM.pmt_relevant && (isLive
            ? (() => {
                const preview = current._raw.pmt_preview || {};
                const hasPreview = preview && Object.keys(preview).length > 0;
                return (
                  <div className="card" style={{borderTop:'3px solid var(--accent-eligibility)'}}>
                    <div className="card-header" style={{padding:'12px 16px'}}>
                      <div>
                        <div className="t-cap" style={{color:'var(--accent-eligibility)'}}><Icon name="target" size={11}/> PMT PREVIEW</div>
                        <h3 className="t-h3" style={{margin:'2px 0 0'}}>If approved</h3>
                      </div>
                      <Chip tone="eligibility">pmt_relevant</Chip>
                    </div>
                    <div style={{padding:16}}>
                      {hasPreview ? (
                        <>
                          {preview.current_score !== undefined && (
                            <>
                              <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>CURRENT</div>
                              <div className="row" style={{justifyContent:'space-between'}}>
                                <span className="t-mono" style={{fontSize:22, fontWeight:700}}>{preview.current_score}</span>
                                {preview.current_band && <Chip tone="eligibility">{preview.current_band}</Chip>}
                              </div>
                            </>
                          )}
                          {preview.recomputed_score !== undefined && (
                            <>
                              <div className="t-cap" style={{fontWeight:600, color:'var(--accent-eligibility)', margin:'12px 0 6px'}}>RECOMPUTED IF APPROVED</div>
                              <div className="row" style={{justifyContent:'space-between'}}>
                                <span className="t-mono" style={{fontSize:22, fontWeight:700, color:'var(--accent-eligibility)'}}>{preview.recomputed_score}</span>
                                {preview.recomputed_band && (
                                  <Chip tone="eligibility" style={{background:'var(--accent-eligibility)', color:'white', borderColor:'var(--accent-eligibility)'}}>
                                    {preview.recomputed_band}
                                  </Chip>
                                )}
                              </div>
                            </>
                          )}
                          {preview.notes && (
                            <div className="t-bodysm muted mt-2">{preview.notes}</div>
                          )}
                        </>
                      ) : (
                        <div className="t-bodysm muted">
                          PMT recompute is deferred until <span className="t-mono">apps.pmt</span> writes the preview snapshot. Row is flagged <Chip tone="eligibility" size="sm">pmt_relevant</Chip>.
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()
            : (
                <div className="card" style={{borderTop:'3px solid var(--accent-eligibility)'}}>
                  <div className="card-header" style={{padding:'12px 16px'}}>
                    <div>
                      <div className="t-cap" style={{color:'var(--accent-eligibility)'}}><Icon name="target" size={11}/> PMT PREVIEW</div>
                      <h3 className="t-h3" style={{margin:'2px 0 0'}}>If approved</h3>
                    </div>
                    <Chip tone="eligibility">pmt_relevant</Chip>
                  </div>
                  <div style={{padding:16}}>
                    <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>CURRENT</div>
                    <div className="row" style={{justifyContent:'space-between'}}>
                      <span className="t-mono" style={{fontSize:22, fontWeight:700}}>0.412</span>
                      <Chip tone="eligibility">Poorest 40%</Chip>
                    </div>
                    <div className="t-bodysm muted mt-1">Calculated on 14 May 2026 · Model v2.4</div>

                    <div className="row" style={{margin:'14px 0', justifyContent:'center'}}>
                      <div style={{width:28, height:28, borderRadius:'50%', background:'var(--accent-eligibility-bg)', color:'var(--accent-eligibility)', display:'grid', placeItems:'center'}}>
                        <Icon name="arrowDown" size={14}/>
                      </div>
                      <span className="t-cap" style={{marginLeft:6}}>−0.025 score · 1 band poorer</span>
                    </div>

                    <div className="t-cap" style={{fontWeight:600, color:'var(--accent-eligibility)', marginBottom:6}}>RECOMPUTED IF APPROVED</div>
                    <div className="row" style={{justifyContent:'space-between'}}>
                      <span className="t-mono" style={{fontSize:22, fontWeight:700, color:'var(--accent-eligibility)'}}>0.387</span>
                      <Chip tone="eligibility" style={{background:'var(--accent-eligibility)', color:'white', borderColor:'var(--accent-eligibility)'}}>Poorest 20%</Chip>
                    </div>
                    <div className="t-bodysm muted mt-1">Driven by: +1 dependant under 5 · roster size 7</div>

                    <div className="divider"/>

                    <div className="t-cap" style={{fontWeight:600, color:'var(--neutral-700)', marginBottom:6}}>PROGRAMME IMPLICATIONS</div>
                    <ul className="t-bodysm" style={{margin:0, paddingLeft:18, color:'var(--neutral-700)'}}>
                      <li>OPM-PDM 2026 Q2 — newly eligible</li>
                      <li>NUSAF cash transfer — eligibility unchanged</li>
                      <li>WFP food assistance — eligibility unchanged</li>
                    </ul>
                  </div>
                </div>
              )
          )}

          {/* No self-approve — live mode resolves names from /me;
              mock keeps the demo strings. */}
          <div className="card" style={{padding:14, borderLeft:'3px solid var(--accent-quality)'}}>
            <div className="row gap-2" style={{marginBottom:4}}>
              <Icon name="info" size={14} color="var(--accent-quality)"/>
              <strong className="t-bodysm">Self-approval policy</strong>
            </div>
            <div className="t-bodysm muted">
              {isLive ? (
                isSelfRequest ? (
                  <>You (<strong>{me.username}</strong>) submitted this request — <strong>self-approve is blocked</strong> (AC-UPD-NO-SELF-APPROVE).</>
                ) : (
                  <>Submitter is <strong>{headerVM.submitter}</strong>; reviewer is <strong>{headerVM.reviewer}</strong>. Approval is permitted (AC-UPD-NO-SELF-APPROVE).</>
                )
              ) : (
                <>Submitter is <strong>Lokwang Peter</strong>; current reviewer is <strong>Adong Florence</strong>. Approval is permitted (AC-UPD-NO-SELF-APPROVE).</>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Sticky action bar — operates on `current`. Approve is blocked
          when the viewer is the submitter (AC-UPD-NO-SELF-APPROVE).
          ON_HOLD rows hide Approve/Reject/Hold and surface Release;
          PENDING_APPROVAL rows show the usual quartet. */}
      <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
        <ActionBar left={
          <>SLA: <strong>{headerVM.slaDays}d</strong> of {headerVM.slaCap}d · Reviewer: {headerVM.reviewer}
            {isLive && <Chip tone="neutral" size="sm" style={{marginLeft:8}}>{current.id.slice(0,12)}…</Chip>}
          </>
        }>
          {isOnHold ? (
            <button className="btn btn-success" disabled={busy || (isSelfRequest && !selfApprove)} onClick={() => setModal('release')}>
              <Icon name="arrowUp" size={14}/> Release
            </button>
          ) : (
            <>
              <button className="btn btn-danger" disabled={busy} onClick={() => setModal('reject')}>
                <Icon name="xCircle" size={14}/> Reject
              </button>
              <button className="btn btn-warn" disabled={busy} onClick={() => setModal('hold')}>
                <Icon name="clock" size={14}/> Hold for info
              </button>
              <button className="btn" disabled={busy} onClick={() => setModal('escalate')}>
                <Icon name="arrowUp" size={14}/> Escalate
              </button>
              <button className="btn btn-success"
                disabled={busy || selfApprove || isSelfRequest}
                title={isSelfRequest ? "You submitted this request — AC-UPD-NO-SELF-APPROVE blocks self-approval" : ""}
                onClick={() => setModal('approve')}>
                <Icon name="check" size={14}/> Approve
              </button>
            </>
          )}
        </ActionBar>
      </div>

      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} title={`Audit · ${effectiveId}`}
        events={[
          { who: "Lokwang Peter", action: "submitted change request", detail: `${UPD.change_type} · evidence: photo, witness, health-centre note`, time: "2d ago", audit: "A-2026-05-12-00091", tone: "user" },
          { who: "System DQA", action: "evaluated", detail: "0 warnings on update payload · ruleset v3.4", time: "2d ago", audit: "A-2026-05-12-00092", tone: "system" },
          { who: "System PMT", action: "previewed recompute", detail: "Δ −0.025 · band shift Poorest 40% → Poorest 20%", time: "2d ago", audit: "A-2026-05-12-00093", tone: "system" },
          { who: "Adong Florence", action: "opened for review", detail: "CDO Tapac · viewed diff and PMT preview", time: "8m ago", audit: "A-2026-05-14-00501", tone: "user" },
        ]}/>

      <ReasonModal open={modal === 'approve'} title="Approve change request" intent="success"
        reasonOptions={["Evidence sufficient · field-confirmed","PMT impact accepted","Routine cosmetic change","Other (specify in note)"]}
        recordLabel={effectiveId} onClose={() => setModal(null)} onConfirm={(r) => fire('approve', r)}/>
      <ReasonModal open={modal === 'reject'} title="Reject change request" intent="danger"
        reasonOptions={reasonsReject} recordLabel={effectiveId}
        onClose={() => setModal(null)} onConfirm={(r) => fire('reject', r)}/>
      <ReasonModal open={modal === 'hold'} title="Hold for more information" intent="primary"
        reasonOptions={["Awaiting additional photo / witness","Awaiting NIRA reconciliation","Awaiting GRM case resolution","Other"]}
        recordLabel={effectiveId} onClose={() => setModal(null)} onConfirm={(r) => fire('hold', r)}/>
      <ReasonModal open={modal === 'escalate'} title="Escalate to District M&E" intent="primary"
        reasonOptions={["Out of scope for CDO","Disputed change","Other"]}
        recordLabel={effectiveId} onClose={() => setModal(null)} onConfirm={(r) => fire('escalate', r)}/>
      <ReasonModal open={modal === 'release'} title="Release from hold" intent="success"
        reasonOptions={["Awaited info received","Linked GRM case resolved","NIRA reconciliation complete","Other"]}
        recordLabel={effectiveId} onClose={() => setModal(null)} onConfirm={(r) => fire('release', r)}/>

      {/* Bulk-action modals (US-S11-004) — same ReasonModal, recordLabel
          reads "N rows" rather than a single CR id. The reason + note
          fan out to every selected row's audit event. */}
      <ReasonModal open={bulkModal === 'approve'} title={`Bulk approve · ${selected.size} rows`}
        intent="success"
        reasonOptions={["Evidence sufficient · field-confirmed batch","Routine cosmetic updates","Identical reason applies to all","Other (specify in note)"]}
        recordLabel={`${selected.size} change requests`}
        onClose={() => setBulkModal(null)} onConfirm={fireBulk}/>
      <ReasonModal open={bulkModal === 'reject'} title={`Bulk reject · ${selected.size} rows`}
        intent="danger"
        reasonOptions={reasonsReject}
        recordLabel={`${selected.size} change requests`}
        onClose={() => setBulkModal(null)} onConfirm={fireBulk}/>
      <ReasonModal open={bulkModal === 'escalate'} title={`Bulk escalate · ${selected.size} rows`}
        intent="primary"
        reasonOptions={["Out of scope for CDO","Disputed batch","SLA breach","Other"]}
        recordLabel={`${selected.size} change requests`}
        onClose={() => setBulkModal(null)} onConfirm={fireBulk}/>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

Object.assign(window, { UPDScreen });
