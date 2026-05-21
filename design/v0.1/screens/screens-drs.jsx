/* global React, Icon, Chip, PageHeader, Modal, Field, ReasonModal, Toast */
// NSR MIS — 11.7 DRS Query Builder + Field Selector
// US-S14-002: operator-side list view added in front of the
// existing wizard. Default mode = "list" (the inbox); "New
// request" toggles to the wizard. Partner role still mounts the
// wizard directly via PartnerDRSScreen.

const { useState: useStateDRS, useEffect: useEffectDRS, useMemo: useMemoDRS } = React;

// DataRequest statuses mirror apps.data_requests.models.RequestStatus.
// Operator-facing labels — "Pending decision" for the inbox state
// the NSR Unit reviewer actually needs to act on.
const ODRS_STATUSES = {
  draft:     { label: "Draft",            tone: "neutral",     icon: "edit"     },
  submitted: { label: "Pending decision", tone: "update",      icon: "clock"    },
  approved:  { label: "Approved",         tone: "data",        icon: "check"    },
  rejected:  { label: "Rejected",         tone: "danger",      icon: "x"        },
  delivered: { label: "Delivered",        tone: "eligibility", icon: "download" },
  expired:   { label: "Expired",          tone: "neutral",     icon: "lock"     },
};

// Operator-side mock list — only renders when the API call fails
// or the harness is mounted under file://. Real rows replace this
// from the /api/v1/drs/requests/ response.
const ODRS_REQUESTS_MOCK = [
  { id: "01DRS2026051400003", dsa: 1, dsa_reference: "DSA-PDM-2026-01",
    requester: "partner-pdm-analyst",
    request_payload: { fields: ["household.id", "household.sub_region_code"], programme_codes: ["PDM"] },
    status: "submitted", submitted_at: "14 May 14:15", approver: "",
    decided_at: null, decision_reason: "", delivered_at: null, expires_at: null,
    manifest_sha256: "", row_count_delivered: null },
  { id: "01DRS2026051400002", dsa: 1, dsa_reference: "DSA-PDM-2026-01",
    requester: "partner-pdm-analyst",
    request_payload: { fields: ["household.id", "household.current_vulnerability_band"],
                       sub_region_codes: ["SR-BUGANDA-SOUTH", "SR-BUGANDA-NORTH"], max_rows: 10000 },
    status: "approved", submitted_at: "14 May 08:30", approver: "nsr-unit-coordinator",
    decided_at: "14 May 09:11", decision_reason: "", delivered_at: null, expires_at: null,
    manifest_sha256: "", row_count_delivered: null },
  { id: "01DRS2026051400001", dsa: 1, dsa_reference: "DSA-PDM-2026-01",
    requester: "partner-pdm-analyst",
    request_payload: { fields: ["household.id", "household.sub_region_code", "household.current_vulnerability_band"],
                       sub_region_codes: ["SR-BUGANDA-SOUTH"], max_rows: 5000 },
    status: "delivered", submitted_at: "12 May 09:00", approver: "nsr-unit-coordinator",
    decided_at: "12 May 10:00",
    decision_reason: "", delivered_at: "13 May 11:42", expires_at: "12 Jun 11:42",
    manifest_sha256: "a3f8e91c52d04b7e2c1f6a5b9d0e7f4c8b6a2e1d4f5c9a7b3e0d8c2f1a9b5e6d",
    row_count_delivered: 1284 },
  { id: "01DRS2026051400004", dsa: 1, dsa_reference: "DSA-PDM-2026-01",
    requester: "partner-pdm-analyst",
    request_payload: { fields: ["member.nin_value"] },
    status: "rejected", submitted_at: "10 May 11:00", approver: "nsr-unit-coordinator",
    decided_at: "10 May 13:22",
    decision_reason: "Field 'member.nin_value' outside DSA scope. Resubmit with allowed fields only.",
    delivered_at: null, expires_at: null, manifest_sha256: "", row_count_delivered: null },
];

const ODRS_STATUS_FILTERS = [
  { id: "all",       label: "All" },
  { id: "submitted", label: "Pending decision" },
  { id: "approved",  label: "Approved" },
  { id: "delivered", label: "Delivered" },
  { id: "rejected",  label: "Rejected" },
];

const ODRS_REJECT_REASONS = [
  "Fields outside DSA allowed_scopes (resubmit needed)",
  "Row cap exceeds DSA budget for the period",
  "Geographic scope outside DSA region list",
  "Insufficient justification in requester_note",
  "Other (specify in note)",
];

const _odrsFetchJson = (url) => fetch(url, {
  credentials: "same-origin",
  headers: { Accept: "application/json" },
}).then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`));

const _odrsCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

const _odrsPost = (url, body) => fetch(url, {
  method: "POST", credentials: "same-origin",
  headers: { "Content-Type": "application/json",
             "X-CSRFToken": _odrsCsrf(), Accept: "application/json" },
  body: JSON.stringify(body),
});

const OperatorDRSList = ({ onNewRequest }) => {
  // US-S14-002 — operator list view. Mirrors the partner list
  // shape (S13-004) but reads /api/v1/drs/requests/ (full
  // DataRequestSerializer) and offers approve/reject actions
  // instead of download. The PartnerScopedQuerysetMixin on the
  // viewset means an operator with no partner_id sees everything;
  // a partner role would never end up here (partners get the
  // PartnerDRSScreen wired in app.jsx).
  const [liveRequests, setLiveRequests] = useStateDRS(null);
  const [dataSource, setDataSource] = useStateDRS("mock");
  const [reloadKey, setReloadKey] = useStateDRS(0);
  const [statusFilter, setStatusFilter] = useStateDRS("submitted");
  const [selectedRow, setSelectedRow] = useStateDRS(null);
  const [approveOpen, setApproveOpen] = useStateDRS(false);
  const [rejectOpen, setRejectOpen] = useStateDRS(false);
  const [toast, setToast] = useStateDRS("");

  useEffectDRS(() => {
    let cancelled = false;
    _odrsFetchJson("/api/v1/drs/requests/?page_size=50")
      .then(data => {
        if (cancelled) return;
        const rows = (data.results || data || []).map(r => ({
          ...r,
          request_payload: r.request_payload || { fields: [] },
        }));
        setLiveRequests(rows);
        setDataSource(rows.length === 0 ? "live-empty" : "live");
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [reloadKey]);

  const allRequests = liveRequests || ODRS_REQUESTS_MOCK;
  // Default selection: first row matching the active filter, else
  // first row overall. Re-evaluated when the request list changes.
  useEffectDRS(() => {
    if (allRequests.length === 0) return;
    if (selectedRow && allRequests.find(r => r.id === selectedRow)) return;
    setSelectedRow(allRequests[0].id);
  }, [allRequests]);

  const rows = useMemoDRS(() => (
    statusFilter === "all"
      ? allRequests
      : allRequests.filter(r => r.status === statusFilter)
  ), [allRequests, statusFilter]);

  const current = useMemoDRS(
    () => allRequests.find(r => r.id === selectedRow),
    [allRequests, selectedRow],
  );

  const filterCounts = useMemoDRS(
    () => ODRS_STATUS_FILTERS.map(f => ({
      ...f,
      count: f.id === "all"
        ? allRequests.length
        : allRequests.filter(r => r.status === f.id).length,
    })),
    [allRequests],
  );

  // US-S15-002 — average decision turnaround across the visible
  // list. Counts only requests where submitted_at AND decided_at
  // are both set (approved + rejected; never delivered, since
  // delivery is post-decision). Reported in hours with one decimal
  // if it's under 24, otherwise rounded days. Hidden when sample
  // size is < 3 — a single fast decision isn't representative.
  const decisionTurnaround = useMemoDRS(() => {
    const decided = allRequests.filter(r => r.submitted_at && r.decided_at);
    if (decided.length < 3) return null;
    const deltas = decided.map(r => {
      const ms = Date.parse(r.decided_at) - Date.parse(r.submitted_at);
      return Number.isFinite(ms) && ms > 0 ? ms : null;
    }).filter(v => v != null);
    if (deltas.length < 3) return null;
    const meanMs = deltas.reduce((a, b) => a + b, 0) / deltas.length;
    const hours = meanMs / (60 * 60 * 1000);
    if (hours < 24) return { label: `avg ${hours.toFixed(1)}h`, n: deltas.length };
    return { label: `avg ${(hours / 24).toFixed(1)}d`, n: deltas.length };
  }, [allRequests]);

  const isLive = dataSource === "live" || dataSource === "live-empty";

  const confirmApprove = ({ note }) => {
    setApproveOpen(false);
    if (!isLive || !current) {
      setToast(`Approved · ${selectedRow.slice(0, 16)}… (mock)`);
      return;
    }
    _odrsPost(`/api/v1/drs/requests/${current.id}/approve/`, {
      approver: "operator", reason: note || "approved via DRS list view",
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(() => {
        setToast(`Approved · ${current.id.slice(0, 16)}…`);
        setReloadKey(k => k + 1);
      })
      .catch(e => setToast(`Approve failed: ${e.message}`));
  };

  const confirmReject = ({ reason, note }) => {
    setRejectOpen(false);
    if (!isLive || !current) {
      setToast(`Rejected · ${selectedRow.slice(0, 16)}… (mock)`);
      return;
    }
    _odrsPost(`/api/v1/drs/requests/${current.id}/reject/`, {
      approver: "operator", reason: reason ? `${reason} — ${note}` : note,
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(() => {
        setToast(`Rejected · ${current.id.slice(0, 16)}…`);
        setReloadKey(k => k + 1);
      })
      .catch(e => setToast(`Reject failed: ${e.message}`));
  };

  const eyebrowSuffix = dataSource === "live" ? " · LIVE"
    : dataSource === "live-empty" ? " · live · queue empty"
    : "";
  const eyebrowTurnaround = decisionTurnaround
    ? ` · ${decisionTurnaround.label} (n=${decisionTurnaround.n})`
    : "";

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow={"DATA REQUESTS · NSR UNIT INBOX" + eyebrowSuffix + eyebrowTurnaround}
        title={<>Data requests <Chip>{rows.length}</Chip></>}
        sub="Triage incoming requests under each active DSA. Approve, reject or hold for clarification."
        right={<>
          <button className="btn btn-primary" onClick={onNewRequest}>
            <Icon name="plus" size={14}/> New request
          </button>
        </>}
      />

      {/* Status filter strip */}
      <div className="card" style={{padding:"14px 20px", marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:"wrap"}}>
          <span className="t-cap" style={{fontWeight:600}}>STATUS</span>
          {filterCounts.map(f => {
            const active = statusFilter === f.id;
            return (
              <button
                key={f.id}
                className={`chip-btn ${active ? "active" : ""}`}
                onClick={() => setStatusFilter(f.id)}
                style={{
                  display:"inline-flex", alignItems:"center", gap:6,
                  padding:"6px 10px", borderRadius:8, fontSize:13, fontWeight:500,
                  border: active ? "1px solid var(--accent-data)" : "1px solid var(--neutral-300)",
                  background: active ? "var(--accent-data-bg)" : "white",
                  color: active ? "var(--accent-data)" : "var(--neutral-800)",
                  cursor:"pointer",
                }}>
                {f.label}
                <span style={{
                  marginLeft:4, padding:"1px 6px", borderRadius:10, fontSize:11,
                  background: active ? "var(--accent-data)" : "var(--neutral-200)",
                  color: active ? "white" : "var(--neutral-700)",
                }}>{f.count}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* List + detail */}
      <div style={{display:"grid", gridTemplateColumns:"1fr 380px", gap:16}}>
        <div className="card">
          <div className="card-toolbar">
            <strong className="t-bodysm">{rows.length} requests</strong>
            <div style={{flex:1}}/>
            <span className="t-cap">Approve/reject actions are scoped by PartnerScope ABAC.</span>
          </div>

          <div style={{display:"grid", gridTemplateColumns:"1fr 150px 110px 120px 130px",
            borderBottom:"1px solid var(--neutral-200)", background:"var(--neutral-50)",
            fontSize:11, fontWeight:600, letterSpacing:"0.06em",
            textTransform:"uppercase", color:"var(--neutral-700)"}}>
            <div style={{padding:"10px 16px"}}>Request</div>
            <div style={{padding:"10px 8px"}}>Status</div>
            <div style={{padding:"10px 8px", textAlign:"right"}}>Rows</div>
            <div style={{padding:"10px 8px"}}>Submitted</div>
            <div style={{padding:"10px 8px"}}>Requester</div>
          </div>

          {rows.map(r => {
            const active = selectedRow === r.id;
            const st = ODRS_STATUSES[r.status] || ODRS_STATUSES.draft;
            return (
              <div
                key={r.id}
                onClick={() => setSelectedRow(r.id)}
                style={{
                  display:"grid", gridTemplateColumns:"1fr 150px 110px 120px 130px",
                  borderBottom:"1px solid var(--neutral-200)",
                  background: active ? "var(--accent-data-bg)" : "white",
                  cursor:"pointer", alignItems:"center",
                }}>
                <div style={{padding:"12px 16px"}}>
                  <div className="t-mono" style={{fontSize:12, color:"var(--neutral-900)"}}>{r.id}</div>
                  <div className="t-bodysm muted" style={{marginTop:2}}>{r.dsa_reference || `DSA ${r.dsa || "—"}`}</div>
                </div>
                <div style={{padding:"12px 8px"}}>
                  <Chip size="sm" tone={st.tone} icon={st.icon}>{st.label}</Chip>
                </div>
                <div style={{padding:"12px 8px", textAlign:"right", fontFamily:"monospace", fontSize:12,
                             color: r.row_count_delivered ? "var(--neutral-900)" : "var(--neutral-400)"}}>
                  {r.row_count_delivered != null ? r.row_count_delivered.toLocaleString() : "—"}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {r.submitted_at || "—"}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {r.requester || "—"}
                </div>
              </div>
            );
          })}

          {rows.length === 0 && (
            <div style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
              <Icon name="inbox" size={32} color="var(--neutral-300)"/>
              <div className="t-bodysm mt-2">No requests match this filter.</div>
            </div>
          )}
        </div>

        {/* Detail rail */}
        {current && (
          <div className="col gap-3">
            <div className="card" style={{borderTop:"3px solid var(--accent-data)"}}>
              <div className="card-header" style={{padding:"12px 16px"}}>
                <div>
                  <div className="t-cap"><Icon name="filter" size={11}/> REQUEST DETAIL</div>
                  <h3 className="t-h3" style={{margin:"2px 0 0", fontFamily:"monospace", fontSize:13}}>{current.id}</h3>
                </div>
                <Chip tone={(ODRS_STATUSES[current.status] || ODRS_STATUSES.draft).tone}>
                  {(ODRS_STATUSES[current.status] || ODRS_STATUSES.draft).label}
                </Chip>
              </div>
              <div style={{padding:16}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>REQUESTER</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.requester || "—"}</div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>DSA</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.dsa_reference || `DSA ${current.dsa || "—"}`}</div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>FIELDS REQUESTED</div>
                <div className="row-wrap" style={{display:"flex", flexWrap:"wrap", gap:6}}>
                  {(current.request_payload.fields || []).length === 0
                    ? <span className="t-bodysm muted">— none —</span>
                    : current.request_payload.fields.map(f => (
                      <Chip key={f} size="sm" tone="programme">{f}</Chip>
                    ))}
                </div>

                {current.request_payload.sub_region_codes && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>GEOGRAPHY</div>
                    <div className="row-wrap" style={{display:"flex", flexWrap:"wrap", gap:6}}>
                      {current.request_payload.sub_region_codes.map(s => (
                        <Chip key={s} size="sm" tone="data">{s}</Chip>
                      ))}
                    </div>
                  </>
                )}

                {current.request_payload.max_rows && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>ROW CAP</div>
                    <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{Number(current.request_payload.max_rows).toLocaleString()} rows</div>
                  </>
                )}

                {current.decision_reason && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>DECISION REASON</div>
                    <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.decision_reason}</div>
                  </>
                )}

                {current.approver && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>DECIDED BY</div>
                    <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.approver} · {current.decided_at || "—"}</div>
                  </>
                )}
              </div>
            </div>

            {current.status === "submitted" && (
              <div className="card" style={{padding:16}}>
                <div className="t-cap" style={{fontWeight:600, marginBottom:8}}>OPERATOR ACTIONS</div>
                <div className="row gap-2" style={{flexWrap:"wrap"}}>
                  <button className="btn btn-success" onClick={() => setApproveOpen(true)}>
                    <Icon name="check" size={14}/> Approve
                  </button>
                  <button className="btn btn-danger" onClick={() => setRejectOpen(true)}>
                    <Icon name="x" size={14}/> Reject
                  </button>
                </div>
                <p className="t-cap" style={{marginTop:8, color:"var(--neutral-600)"}}>
                  Approver cannot be the original requester (AC-DRS-DUAL-ACTOR).
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <ReasonModal open={approveOpen} title="Approve data request" intent="success"
        reasonOptions={["DSA scope match", "Justification confirmed",
                        "Volume within DSA budget", "Routine renewal"]}
        recordLabel={current?.id}
        onClose={() => setApproveOpen(false)} onConfirm={confirmApprove}/>

      <ReasonModal open={rejectOpen} title="Reject data request" intent="danger"
        reasonOptions={ODRS_REJECT_REASONS}
        recordLabel={current?.id}
        onClose={() => setRejectOpen(false)} onConfirm={confirmReject}/>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

const STEPS = [
  { id: "scope",    label: "Scope",          icon: "target" },
  { id: "build",    label: "Build",          icon: "filter" },
  { id: "fields",   label: "Field Selector", icon: "sliders" },
  { id: "preview",  label: "Preview",        icon: "eye" },
  { id: "delivery", label: "Delivery",       icon: "download" },
  { id: "submit",   label: "Submit",         icon: "check" },
];

// FIELDS mock removed — Step 3 (FieldStepV2) and Step 2 (BuildStepV2)
// both consume the live schema.fields catalogue from /builder-schema/
// (US-S27-013 / US-S27-014). Offline preview falls back to the
// templates' own inline catalogues.

// BUG-S27-019 — Step 4 preview now reflects the user's Step-3
// selection. There is no preview endpoint yet (DRS-O-PREVIEW open
// item), so cells are generated client-side from each field's
// catalogue metadata (type, options, sensitivity) plus the
// shared row-index banks below. Sensitive columns mask; Personal
// phone numbers reveal last-4 only — matching the design rule that
// the preview never surfaces more PII than the actual delivery.
const _PREVIEW_ROW_COUNT = 10;
const _PREVIEW_ULIDS = [
  "01HXY7K3B2N9PVQE4M6FZRWS18", "01HXZ9MR4N8P2QFB7K6FZRWS33",
  "01HY09KRS1P9MN6FB7K6FZRWS84", "01HY02FNQ9P8MN6FB7K6FZRWS67",
  "01HY04MQR0N8P2FB7K6FZRWS73", "01HXP02CN4QFB7K6FZRWS00111",
  "01HXP02CN4QFB7K6FZRWS00118", "01HXP02CN4QFB7K6FZRWS00124",
  "01HXP02CN4QFB7K6FZRWS00135", "01HXP02CN4QFB7K6FZRWS00148",
];
const _PREVIEW_HH_NUMBERS = [
  "HH-7411-002-0148", "HH-3122-005-0091", "HH-7411-002-0103",
  "HH-7531-001-0048", "HH-7531-002-0017", "HH-2110-008-0021",
  "HH-2110-008-0033", "HH-3122-009-0019", "HH-2110-008-0040",
  "HH-7411-002-0211",
];
const _PREVIEW_PLACES = [
  "Nakiloro", "Pageya", "Kakingol", "Lorengedwat", "Apeitolim",
  "Anyiribu", "Logiri", "Bobi", "Kuluba", "Tapac",
];
const _PREVIEW_SURNAMES = [
  "Akiteng", "Apio", "Bwambale", "Lokol", "Anyait",
  "Oboth", "Achan", "Nakato", "Birungi", "Mugisha",
];
const _PREVIEW_GIVEN = [
  "Margaret", "Sarah", "John", "Joseph", "Esther",
  "Robert", "Amina", "Ruth", "James", "Grace",
];
const _PREVIEW_PHONE_TAILS = [
  "4567", "2119", "8221", "5582", "6620",
  "0044", "9912", "3322", "7711", "1188",
];
const _PREVIEW_NIN_LAST4 = [
  "ABCD", "8821", "1109", "4F2C", "7733",
  "9911", "3361", "5520", "0844", "6678",
];
const _PREVIEW_DATES = [
  "2026-03-14", "2026-02-09", "2025-12-18", "2026-04-02", "2025-11-30",
  "2026-01-22", "2026-03-29", "2026-02-26", "2025-10-11", "2026-04-15",
];
const _PREVIEW_AGES = [34, 47, 28, 51, 22, 39, 64, 19, 45, 33];
const _PREVIEW_SIZES = [6, 5, 7, 6, 8, 4, 7, 5, 4, 6];

// BUG-S27-021 — walk the criteria tree once and collect a per-field
// "pin" for any rule that fixes the column's value. The preview row
// generator uses these pins so the rendered cells reflect the WHERE
// clause instead of cycling through every enum option. Pinning only
// applies to operators that constrain to a specific value or value
// set: eq / on / true / false (single), in / any (multi), between
// (range). Inequality / range / contains / set / unset don't pin —
// the field is still free to vary, just within the operator's
// constraint, which is good enough for a design-time preview.
//
// pin shapes:
//   { kind: "single", value: <raw code or literal> }
//   { kind: "multi",  values: [<raw>, <raw>, …] }
//   { kind: "range",  min: <number|date>, max: <number|date> }
const _buildPinMap = (tree) => {
  const pins = {};
  const walk = (node) => {
    if (!node) return;
    if (node.kind === "rule") {
      const k = node.field;
      const op = node.op;
      const v = node.value;
      if (!k) return;
      // True / false don't carry a value — synthesise one.
      if (op === "true")  { pins[k] = { kind: "single", value: true  }; return; }
      if (op === "false") { pins[k] = { kind: "single", value: false }; return; }
      // Empty-string / null guards — an unfilled rule shouldn't pin.
      const hasValue = v !== null && v !== undefined && v !== "";
      if (op === "eq" || op === "on") {
        if (hasValue) pins[k] = { kind: "single", value: v };
      } else if (op === "in" || op === "any" || op === "all") {
        if (Array.isArray(v) && v.length > 0) {
          pins[k] = { kind: "multi", values: v };
        }
      } else if (op === "between") {
        if (Array.isArray(v) && v.length === 2 && v[0] !== "" && v[1] !== "") {
          pins[k] = { kind: "range", min: v[0], max: v[1] };
        }
      }
      // gt/gte/lt/lte/contains/starts/before/after/lastN/set/
      // unset/neq/nin/none — don't fix a value; let the generator
      // run.
      return;
    }
    for (const c of node.rules || []) walk(c);
  };
  walk(tree);
  return pins;
};

// BUG-S27-024 — UBOS administrative hierarchy. Used by the preview's
// implicit-pin inferrer to constrain a descendant geographic column
// to options whose `parent_code` matches the pinned ancestor. The
// order is significant: the inferrer walks top-down so a region pin
// propagates to sub_region, then sub_region's now-implicit pin
// propagates to district, and so on.
const _GEO_CHAIN = [
  "household.region_code",
  "household.sub_region_code",
  "household.district_code",
  "household.county_code",
  "household.sub_county_code",
  "household.parish_code",
  "household.village_code",
];

// Pure: given the explicit pins from _buildPinMap, the selected
// columns, and the catalogue, derive *implicit* pins on geographic
// descendants whose parent geo level is pinned. The result is a new
// pin map (the original is not mutated) where each implicit pin
// carries `{ kind: "multi", values, implicit: true }` so the UI can
// distinguish them from explicit pins.
const _inferImplicitGeoPins = (pins, cols, catalogueByKey) => {
  const out = { ...pins };
  const colKeys = new Set((cols || []).map(c => c.key));
  for (let i = 1; i < _GEO_CHAIN.length; i++) {
    const childKey = _GEO_CHAIN[i];
    if (!colKeys.has(childKey)) continue;        // column not in preview
    if (out[childKey]) continue;                  // already explicitly pinned
    const parentKey = _GEO_CHAIN[i - 1];
    const parentPin = out[parentKey];
    if (!parentPin) continue;
    const allowed = new Set(
      parentPin.kind === "single" ? [parentPin.value]
      : parentPin.kind === "multi" ? (parentPin.values || [])
      : [],
    );
    if (allowed.size === 0) continue;
    const field = (catalogueByKey || {})[childKey];
    const childOpts = (field && field.options) || [];
    const matching = childOpts
      .filter(o => o.parent_code && allowed.has(o.parent_code))
      .map(o => o.value);
    if (matching.length > 0) {
      out[childKey] = { kind: "multi", values: matching, implicit: true };
    }
  }
  return out;
};

// Render a raw pinned value through the field's catalogue — for
// enum / enum-multi we want the human label, not the storage code.
const _renderPinned = (raw, field) => {
  if (raw === true || raw === false) return raw ? "Yes" : "No";
  if (field?.type === "enum" || field?.type === "enum-multi") {
    const opt = (field.options || []).find(o => String(o.value) === String(raw));
    return opt ? opt.label : String(raw);
  }
  return String(raw);
};

// Resolve a single preview cell for (field, rowIndex). Cell semantics
// mirror what the future preview endpoint will return: sensitive
// columns always mask, personal phones reveal last-4 only, enum
// values render their human label not the storage code. When `pin`
// is supplied, the WHERE clause dominates the generator — see
// _buildPinMap above.
const _previewCell = (key, field, i, pin) => {
  if (!field) return "—";
  const sens = field.sensitivity;
  const type = field.type;
  // ---- Sensitivity gate first (pinning never reveals masked data) ----
  if (sens === "Sensitive") {
    if (key.endsWith("_last4")) return _PREVIEW_NIN_LAST4[i];
    return "[masked]";
  }
  if (sens === "Personal" && /telephone|phone/.test(key)) {
    return "+256 ••• ••" + _PREVIEW_PHONE_TAILS[i];
  }
  // ---- WHERE-clause pinning takes over the rest ----
  if (pin) {
    if (pin.kind === "single") return _renderPinned(pin.value, field);
    if (pin.kind === "multi") {
      const vals = pin.values;
      return vals.length === 0 ? "—" : _renderPinned(vals[i % vals.length], field);
    }
    if (pin.kind === "range") {
      const a = Number(pin.min);
      const b = Number(pin.max);
      if (Number.isFinite(a) && Number.isFinite(b) && b >= a) {
        const span = b - a;
        const v = a + (span * i) / Math.max(1, _PREVIEW_ROW_COUNT - 1);
        return type === "number" ? v.toFixed(span < 10 ? 2 : 0) : String(Math.round(v));
      }
      // Date range or non-numeric — alternate the endpoints.
      return i % 2 === 0 ? String(pin.min) : String(pin.max);
    }
  }
  // ---- Type-driven values ----
  if (type === "bool") return i % 4 === 0 ? "No" : "Yes";
  if (type === "date") return _PREVIEW_DATES[i];
  if (type === "number") {
    if (/pmt|score/.test(key)) return (0.21 + i * 0.037).toFixed(3);
    if (/dependency_ratio/.test(key)) return (1.0 + (i % 5) * 0.25).toFixed(2);
    if (/age_years/.test(key)) return String(_PREVIEW_AGES[i]);
    if (/line_number/.test(key)) return String((i % 6) + 1);
    if (/size|count|rooms/.test(key)) return String(_PREVIEW_SIZES[i]);
    return String(_PREVIEW_SIZES[i]);
  }
  if (type === "enum" || type === "enum-multi") {
    const opts = field.options || [];
    if (opts.length > 0) {
      const opt = opts[i % opts.length];
      return opt.label || opt.value || "—";
    }
    // Geographic enums whose options_source hasn't resolved yet — fall
    // through to the place-name bank so the column reads as locations.
    if (/parish|county|district|region|village|sub_region/.test(key)) {
      return _PREVIEW_PLACES[i];
    }
    return "—";
  }
  // type === "text" (or unspecified)
  if (key === "household.id" || key === "member.id") return _PREVIEW_ULIDS[i];
  if (key === "household.household_number") return _PREVIEW_HH_NUMBERS[i];
  if (/surname/.test(key)) return _PREVIEW_SURNAMES[i];
  if (/first_name|other_name/.test(key)) return _PREVIEW_GIVEN[i];
  if (/parish|county|district|region|village/.test(key)) return _PREVIEW_PLACES[i];
  if (/enumeration_area/.test(key)) return "EA-" + String(7411 + i);
  if (/consent_state/.test(key)) return ["granted", "granted", "granted", "withdrawn", "granted", "granted", "pending", "granted", "granted", "granted"][i];
  if (/intake_source/.test(key)) return ["CAPI-walkin", "CAPI-walkin", "UBOS-2024", "CAPI-walkin", "CAPI-walkin", "UBOS-2024", "OPM-pdm", "CAPI-walkin", "CAPI-walkin", "OPM-pdm"][i];
  if (/relationship_to_head/.test(key)) return ["head", "spouse", "child", "head", "spouse", "head", "parent", "child", "head", "spouse"][i];
  if (/marital_status/.test(key)) return ["married", "single", "married", "widowed", "married", "single", "married", "divorced", "married", "married"][i];
  if (/nationality/.test(key)) return "Ugandan";
  return "—";
};

/* ============================================================
   Options-source resolution (BUG-S27-020)
   ============================================================ */
// `options_source` slugs on the live builder-schema fall into two
// shapes today:
//   1. URL-mapped slugs — geographic-units?level=X and `programmes`.
//      One slug → one HTTP GET. Backend response carries `code` +
//      `name` per row.
//   2. choice_list?name=XXX — every coded field introduced by the
//      US-S22-DE detail-entity work (dwelling_tenure, roof_material,
//      cooking_fuel, employment_status, wg_difficulty_level, …).
//      The bundle endpoint at /choice-list-bundle/?lists=a,b,c
//      returns all named lists in a single round-trip — far cheaper
//      than 20+ individual fetches. Bundle response carries `code` +
//      `label` per option.
// Step 3 (FieldStepV2) doesn't notice when options aren't resolved
// because it only renders the field name. Step 2 (BuildStepV2)
// renders dropdowns over `field.options`, so unresolved fields
// surface as empty selects. This module-level resolver is the
// fix — single source of truth for both effect-time fetching and
// memo-time enrichment, also pure-tested in screens-drs.test.jsx.

const _GEO_BASE = "/api/v1/reference-data/geographic-units/";
const _CHOICE_LIST_BUNDLE = "/api/v1/reference-data/choice-list-bundle/";

const _OPTIONS_SOURCE_URL = {
  "geographic-units?level=region":     `${_GEO_BASE}?level=region&status=active&page_size=500`,
  "geographic-units?level=sub_region": `${_GEO_BASE}?level=sub_region&status=active&page_size=500`,
  "geographic-units?level=district":   `${_GEO_BASE}?level=district&status=active&page_size=500`,
  "geographic-units?level=county":     `${_GEO_BASE}?level=county&status=active&page_size=500`,
  "geographic-units?level=sub_county": `${_GEO_BASE}?level=sub_county&status=active&page_size=2000`,
  "geographic-units?level=parish":     `${_GEO_BASE}?level=parish&status=active&page_size=5000`,
  "geographic-units?level=village":    `${_GEO_BASE}?level=village&status=active&page_size=10000`,
  "programmes":                        "/api/v1/programmes/?status=active&page_size=200",
};

const _choiceListNameFor = (slug) => {
  if (!slug || !slug.startsWith("choice_list?name=")) return null;
  return slug.slice("choice_list?name=".length);
};

// Pure: enrich each schema field whose `options_source` slug has
// already been resolved in `optionsCache`. Returns the same shape
// the rest of the wizard expects (each row carries `{value, label}`).
// Accepts both `name` (GeographicUnitSerializer) and `label`
// (ChoiceListBundle) as the human-readable label source.
// BUG-S27-024 — preserves `parent_code` on options when the
// upstream row carries one (GeographicUnit + ChoiceOption both
// expose it). The preview's implicit-pin inferrer uses this to
// constrain geographic descendants to their parent's children.
const _enrichFieldsWithOptions = (schemaFields, optionsCache) => {
  if (!Array.isArray(schemaFields)) return [];
  return schemaFields.map(f => {
    if (f.options || !f.options_source) return f;
    const rows = (optionsCache && optionsCache[f.options_source]) || [];
    const options = rows
      .map(r => {
        const opt = { value: r.code, label: r.label || r.name || r.code };
        if (r.parent_code) opt.parent_code = r.parent_code;
        return opt;
      })
      .filter(o => o.value);
    return { ...f, options };
  });
};

// Async: resolve every options_source slug the schema references.
// Returns a `{ [slug]: rows[] }` map suitable for merging into
// `optionsCache`. Choice-list slugs are batched into one bundle
// fetch; URL slugs go in parallel. Failures resolve to [] so the
// caller can still ship the rest of the wizard.
const _resolveOptionsForSchema = async (schemaFields) => {
  if (!Array.isArray(schemaFields)) return {};
  const allSlugs = [...new Set(schemaFields
    .map(f => f.options_source)
    .filter(Boolean),
  )];
  const urlSlugs    = allSlugs.filter(s => _OPTIONS_SOURCE_URL[s]);
  const bundleNames = [...new Set(allSlugs
    .map(_choiceListNameFor).filter(Boolean),
  )];
  if (urlSlugs.length === 0 && bundleNames.length === 0) return {};

  const _get = (url) => fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  }).then(r => r.ok ? r.json() : null).catch(() => null);

  const urlFetches = urlSlugs.map(async slug => {
    const data = await _get(_OPTIONS_SOURCE_URL[slug]);
    const rows = (data?.results || data || []);
    return [slug, Array.isArray(rows) ? rows : []];
  });
  const bundlePromise = bundleNames.length === 0 ? null :
    _get(`${_CHOICE_LIST_BUNDLE}?lists=${encodeURIComponent(bundleNames.join(","))}`);

  const urlPairs = await Promise.all(urlFetches);
  const bundle = bundlePromise ? await bundlePromise : null;

  const out = {};
  for (const [slug, rows] of urlPairs) out[slug] = rows;
  for (const lst of (bundle?.lists || [])) {
    out[`choice_list?name=${lst.list_name}`] = lst.options || [];
  }
  return out;
};

// Unified DRS query-builder wizard. Same component for both
// roles per BUG-S11-002b — operator (no `role` prop / "operator")
// gets the full catalogue; partner gets the same surface with
// DSA-disabled fields flagged in-place (no missing controls). The
// real disabled state comes from /api/v1/drs/requests/builder-
// schema/ (BUG-S11-002a) when fetch wiring lands; today the mock
// FIELDS already carries the disabled flags so the harness is
// representative.
//
// `onExit` is set when called from a host screen that owns its
// own back-navigation (e.g., the partner portal's list ↔ builder
// toggle in PartnerDRSScreen).
// US-S14-002 — DRSScreen is a thin router. Operators land on the
// list view (OperatorDRSList) by default and reach the wizard via
// "New request". Partner invocation (role="partner") still mounts
// the wizard directly — partners have their own list elsewhere in
// PartnerDRSScreen.
const DRSScreen = ({ role = "operator", onExit } = {}) => {
  const isPartner = role === "partner";
  const [view, setView] = useStateDRS(isPartner ? "build" : "list");
  if (view === "list" && !isPartner) {
    return <OperatorDRSList onNewRequest={() => setView("build")}/>;
  }
  return <DRSWizard
    role={role}
    onExit={onExit || (isPartner ? undefined : () => setView("list"))}
  />;
};

const DRSWizard = ({ role = "operator", onExit } = {}) => {
  const isPartner = role === "partner";
  const [step, setStep] = useStateDRS("build");
  // Selected fields are ordered dotted keys — the column order in
  // the delivered file follows the user's drag sequence on Step 3
  // (US-S27-014). FieldStepV2 owns add/remove/reorder.
  const [selectedFields, setSel] = useStateDRS([]);
  // US-S27-013 — captured query-builder state is now a recursive
  // tree (AND/OR groups with rules), built by BuildStepV2. On
  // submit we extract leaves matching the predicates the backend
  // validator currently recognises (sub_region / programme), AND
  // ship the full tree as request_payload.criteria for audit /
  // future evaluation.
  const [entity, setEntity] = useStateDRS("household");
  const [maxRows, setMaxRows] = useStateDRS("");
  const [deliveryMethod, setDeliveryMethod] = useStateDRS("");
  // tree: { id, kind:'group', combinator:'AND'|'OR', rules: [...] }
  const [tree, setTree] = useStateDRS(null);
  // optionsCache: { [resolved URL]: [{code, name, …}, …] } —
  // populated for enum fields whose `options_source` maps to a
  // reference-data endpoint.
  const [optionsCache, setOptionsCache] = useStateDRS({});
  const [submitOpen, setSubmitOpen] = useStateDRS(false);
  const [submitting, setSubmitting] = useStateDRS(false);
  const [toast, setToast] = useStateDRS("");
  const stepIdx = STEPS.findIndex(s => s.id === step);

  const next = () => setStep(STEPS[Math.min(stepIdx + 1, STEPS.length - 1)].id);
  const prev = () => setStep(STEPS[Math.max(stepIdx - 1, 0)].id);

  // US-S27-017 — alias the template globals locally. Babel-standalone
  // is finicky about JSX member-expression element types (the
  // `<window.BuildStepV2 />` pattern), and an aliased capitalised
  // identifier sidesteps the issue entirely. The locals also let the
  // wizard render a clear "template not loaded" message if a script
  // failed to compile (rather than throwing "Element type is invalid").
  const BuildStepV2 = window.BuildStepV2;
  const FieldStepV2 = window.FieldStepV2;
  const qbNewGroup  = window.qbNewGroup;

  // US-S18-003 / US-S27-010 — fetch the role-aware schema from
  // /api/v1/drs/requests/builder-schema/ on mount. Partner roles
  // get the live catalogue scoped to their active DSA (with
  // `disabled: true` flags on out-of-scope fields); operator roles
  // see the full catalogue with everything enabled. The response
  // also carries `dsa_id` so the wizard can POST a real
  // DataRequest at submit time. When the fetch fails (file://
  // preview, unauthenticated session) the wizard falls back to
  // the hardcoded FIELDS mock for design-time rendering only.
  const [schema, setSchema] = useStateDRS(null);
  React.useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/drs/requests/builder-schema/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => {
        if (cancelled) return;
        setSchema(data);
        // Pre-pick the first delivery method the schema offers so
        // the partner doesn't see a blank picker.
        if ((data.delivery_methods || []).length > 0) {
          setDeliveryMethod(data.delivery_methods[0].id);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Schema-driven options for enum fields whose value set lives
  // in reference data. Inline `options` skip this fetch entirely.
  React.useEffect(() => {
    if (!schema?.fields) return undefined;
    let cancelled = false;
    _resolveOptionsForSchema(schema.fields).then(updates => {
      if (cancelled) return;
      setOptionsCache(prev => ({ ...prev, ...updates }));
    });
    return () => { cancelled = true; };
  }, [schema]);

  // The catalogue passed to BuildStepV2: schema.fields enriched
  // with resolved `options` for every options_source we've
  // already fetched. Fields with inline `options` pass through.
  const builderFields = React.useMemo(
    () => _enrichFieldsWithOptions(schema?.fields, optionsCache),
    [schema, optionsCache],
  );

  // Initialise the tree once the catalogue is ready. The first
  // available (non-disabled) field anchors the default rule.
  // qbNewGroup may be undefined if the template script failed to
  // compile — guard explicitly so the wizard renders a clear error
  // rather than throwing on undefined.
  React.useEffect(() => {
    if (tree || builderFields.length === 0) return;
    if (typeof qbNewGroup !== "function") return;
    setTree(qbNewGroup("AND", builderFields));
  }, [builderFields, tree, qbNewGroup]);

  // US-S27-014: FieldStepV2 (Step 3) consumes builderFields
  // directly via its `fields` prop. The earlier `effectiveFields`
  // tuple shape used by the now-removed inline FieldStep is gone.

  // US-S27-010 — real submit chain replaces the prior toast-only
  // mock. POST creates a DRAFT row, then POST /submit/ runs the
  // DSA-scope validator. Either step can fail; the failure surfaces
  // verbatim in the toast so the user sees the actual server
  // message (e.g. "fields=['member.nin_hash'] outside DSA scope").
  // On success the wizard exits to its host's list view via
  // onExit; no onExit (legacy mount) keeps the wizard open with a
  // success toast.
  const confirmSubmit = async () => {
    if (submitting) return;
    if (!schema || !schema.dsa_id) {
      setSubmitOpen(false);
      setToast(
        isPartner
          ? "No active DSA for your account — submission unavailable."
          : "Operators submit on behalf of partners; no DSA bound to this session.",
      );
      return;
    }
    if (selectedFields.length === 0) {
      setToast("Pick at least one field before submitting.");
      return;
    }
    setSubmitting(true);
    const payload = {
      // Ordered — column order in the delivered file follows the
      // drag sequence on Step 3 (US-S27-014). validate_against_dsa
      // is order-insensitive so the server contract is unchanged.
      fields: [...selectedFields],
    };
    // US-S27-013 — the criteria tree IS the source of truth. The
    // validator currently reads flat `sub_region_codes` /
    // `programme_codes`; we extract those leaves from the tree so
    // existing validate_against_dsa keeps working unchanged. The
    // full tree also ships as `criteria` for the audit chain and
    // for the criteria-evaluator when it lands. Other predicates
    // (head_sex, age_years, …) are captured but not yet enforced
    // server-side — the wizard flags this to the user on submit.
    if (tree) {
      payload.criteria = tree;
      // US-S27-016 — every UBOS geo level translates to its
      // own flat payload key. validate_against_dsa enforces
      // each one against the DSA's geographic_scope at the
      // matching level (ADR-0011 §4).
      const leafExtractors = {
        "household.region_code":     "region_codes",
        "household.sub_region_code": "sub_region_codes",
        "household.district_code":   "district_codes",
        "household.county_code":     "county_codes",
        "household.sub_county_code": "sub_county_codes",
        "household.parish_code":     "parish_codes",
        "household.village_code":    "village_codes",
        "household.programme_codes": "programme_codes",
      };
      const grouped = {};
      const walk = (node) => {
        if (!node) return;
        if (node.kind === "rule") {
          const target = leafExtractors[node.field];
          if (!target) return;
          if (!grouped[target]) grouped[target] = new Set();
          const v = node.value;
          if (Array.isArray(v)) {
            for (const x of v) if (x) grouped[target].add(x);
          } else if (v != null && v !== "") {
            grouped[target].add(v);
          }
          return;
        }
        for (const child of (node.rules || [])) walk(child);
      };
      walk(tree);
      for (const [k, set] of Object.entries(grouped)) {
        if (set.size > 0) payload[k] = [...set];
      }
    }
    if (maxRows && Number(maxRows) > 0) {
      payload.max_rows = Number(maxRows);
    }
    // entity + deliveryMethod aren't on validate_against_dsa's
    // contract today (entity is inferred from field prefix;
    // delivery method awaits DRS-O-02). They travel via the
    // top-level DataRequest.requester_note column so the operator
    // can see what the partner intended at review time.
    const noteBits = [];
    if (entity) noteBits.push(`entity=${entity}`);
    if (deliveryMethod) noteBits.push(`delivery=${deliveryMethod}`);
    const requesterNote = noteBits.join(" · ");
    try {
      const createR = await fetch("/api/v1/drs/requests/", {
        method: "POST", credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": _odrsCsrf(),
          Accept: "application/json",
        },
        body: JSON.stringify({
          dsa: schema.dsa_id,
          request_payload: payload,
          requester_note: requesterNote,
        }),
      });
      if (!createR.ok) {
        const body = await createR.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${createR.status}`);
      }
      const draft = await createR.json();
      const submitR = await fetch(
        `/api/v1/drs/requests/${draft.id}/submit/`,
        {
          method: "POST", credentials: "same-origin",
          headers: {
            "X-CSRFToken": _odrsCsrf(),
            Accept: "application/json",
          },
        },
      );
      if (!submitR.ok) {
        const body = await submitR.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${submitR.status}`);
      }
      const submitted = await submitR.json();
      setSubmitOpen(false);
      setToast(
        `Submitted · ${submitted.id.slice(0, 16)}… — awaiting NSR Unit approval`,
      );
      if (onExit) {
        // Small delay so the toast is visible on the way out.
        window.setTimeout(() => onExit(), 600);
      }
    } catch (e) {
      setToast(`Submit failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow={
          (isPartner ? "PARTNER DRS · NEW REQUEST" : "DATA REQUESTS")
          + (schema?.dsa_reference ? ` · DSA ${schema.dsa_reference}` : "")
          + (schema ? " · LIVE SCHEMA" : "")
        }
        title={isPartner ? "Build data request" : "DRS query builder"}
        sub={schema
          ? (schema.dsa_reference
              ? <>Requester: {isPartner ? "you" : "operator"} · Active DSA <span className="t-mono">{schema.dsa_reference}</span></>
              : <>Requester: {isPartner ? "you" : "operator"} · No active DSA on this session — submit unavailable</>)
          : <>Loading session…</>}
        right={<>
          {/* "Save as template" removed (BUG-S27-023) — no backend
              for query templates yet; the button was a non-functional
              affordance. Reinstate when DRS-O-TEMPLATES lands. */}
          <button className="btn btn-ghost" onClick={onExit}>
            <Icon name="x" size={14}/> {onExit ? "Cancel" : "Discard"}
          </button>
        </>}
      />

      {/* Step indicator */}
      <div className="card" style={{padding:'14px 20px', marginBottom:16, display:'flex', alignItems:'center', gap:0}}>
        {STEPS.map((s, i) => {
          const done = i < stepIdx;
          const active = i === stepIdx;
          return (
            <React.Fragment key={s.id}>
              <button onClick={() => setStep(s.id)} style={{
                display:'flex', alignItems:'center', gap:8,
                padding:'4px 12px', border:0, background:'transparent', cursor:'pointer',
                color: active ? 'var(--accent-system)' : done ? 'var(--neutral-700)' : 'var(--neutral-500)',
                fontWeight: active ? 600 : 500, fontSize:13.5,
              }}>
                <span style={{
                  width:24, height:24, borderRadius:'50%', display:'grid', placeItems:'center',
                  background: active ? 'var(--accent-system)' : done ? 'var(--accent-system-bg)' : 'var(--neutral-100)',
                  color: active ? 'white' : done ? 'var(--accent-system)' : 'var(--neutral-500)',
                  fontSize:12, fontWeight:600,
                  border: active ? 0 : `1px solid ${done ? 'var(--accent-system)' : 'var(--neutral-300)'}`,
                }}>{done ? <Icon name="check" size={12}/> : i+1}</span>
                {s.label}
              </button>
              {i < STEPS.length - 1 && <div style={{flex:1, height:1, background: i < stepIdx ? 'var(--accent-system)' : 'var(--neutral-300)', minWidth:14}}/>}
            </React.Fragment>
          );
        })}
      </div>

      {step === 'scope' && <ScopeStep value={entity} onChange={setEntity}/>}
      {step === 'build' && (
        !BuildStepV2
          ? <div className="card" style={{padding:24}}>
              <div className="t-cap" style={{color:'var(--accent-danger)'}}>
                Query builder template not loaded — refresh the page; if
                it persists, check the browser console for a JS error in
                screens-drs-querybuilder.jsx.
              </div>
            </div>
          : !tree
          ? <div className="card" style={{padding:24}}>
              <div className="t-cap muted">
                {builderFields.length === 0
                  ? <>Loading field catalogue from <span className="t-mono">/api/v1/drs/requests/builder-schema/</span> · make sure you're logged in via <span className="t-mono">/admin/</span>.</>
                  : "Initialising query tree…"}
              </div>
            </div>
          : <BuildStepV2
              tree={tree}
              onChange={setTree}
              maxRows={maxRows}
              onMaxRows={setMaxRows}
              fields={builderFields}
              recipes={[]}
              showSQL={true}
              dsaReference={schema?.dsa_reference || ""}
            />
      )}
      {step === 'fields' && (
        !FieldStepV2
          ? <div className="card" style={{padding:24}}>
              <div className="t-cap" style={{color:'var(--accent-danger)'}}>
                Field selector template not loaded — refresh the page; if
                it persists, check the browser console for a JS error in
                screens-drs-fieldselector.jsx.
              </div>
            </div>
          : <FieldStepV2
              selectedKeys={selectedFields}
              onChange={setSel}
              fields={builderFields}
              dsaReference={schema?.dsa_reference || ""}
            />
      )}
      {step === 'preview' && <PreviewStep
        selected={selectedFields}
        catalogueByKey={builderFields.reduce((a, f) => (a[f.key] = f, a), {})}
        tree={tree}
      />}
      {step === 'delivery' && <DeliveryStep
        methods={schema?.delivery_methods || []}
        value={deliveryMethod}
        onChange={setDeliveryMethod}
      />}
      {step === 'submit' && <SubmitStep
        onSubmit={() => setSubmitOpen(true)}
        entity={entity}
        selected={selectedFields}
        tree={tree}
        catalogueByKey={builderFields.reduce((a, f) => (a[f.key] = f, a), {})}
        maxRows={maxRows}
        deliveryMethod={deliveryMethod}
        deliveryMethods={schema?.delivery_methods || []}
        dsaReference={schema?.dsa_reference}
      />}

      {/* Action bar */}
      <div style={{margin:'16px -24px 0', position:'sticky', bottom:0, zIndex:20, background:'var(--neutral-0)', borderTop:'1px solid var(--neutral-300)', padding:'12px 20px', display:'flex', gap:12, alignItems:'center', boxShadow:'0 -2px 8px rgba(0,0,0,0.04)'}}>
        <span className="t-bodysm muted">Step {stepIdx + 1} of {STEPS.length} · <strong style={{color:'var(--neutral-900)'}}>{STEPS[stepIdx].label}</strong></span>
        <div style={{flex:1}}/>
        <button className="btn" onClick={prev} disabled={stepIdx === 0}><Icon name="chevronLeft" size={14}/> Back</button>
        {stepIdx < STEPS.length - 1
          ? <button className="btn btn-primary" onClick={next}>Continue <Icon name="chevronRight" size={14}/></button>
          : <button className="btn btn-primary" onClick={() => setSubmitOpen(true)}><Icon name="check" size={14}/> Submit for approval</button>
        }
      </div>

      <Modal open={submitOpen} onClose={() => submitting ? null : setSubmitOpen(false)} title="Submit data request" width={520}
        footer={<>
          <button className="btn" onClick={() => setSubmitOpen(false)} disabled={submitting}>Cancel</button>
          <button className="btn btn-primary" onClick={confirmSubmit} disabled={submitting}>
            <Icon name="check" size={14}/> {submitting ? "Submitting…" : "Submit"}
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>
            A draft DataRequest will be created on
            {schema?.dsa_reference
              ? <> DSA <span className="t-mono">{schema.dsa_reference}</span></>
              : " your active DSA"}
            {" "}and submitted for NSR Unit DRS Reviewer + DPO approval.
            Server-side validation runs on submit; if the request includes
            fields or geographies outside the DSA scope, the submit will
            fail with a precise reason.
          </p>
          <div style={{display:'grid', gridTemplateColumns:'130px 1fr', rowGap:6, fontSize:13}}>
            <div className="muted">DSA</div>
            <div className="t-mono">{schema?.dsa_reference || "—"}</div>
            <div className="muted">Entity</div>
            <div style={{textTransform:'capitalize'}}>{entity}</div>
            <div className="muted">Fields</div>
            <div>
              {selectedFields.length} selected
              {builderFields.length > 0 && ` of ${builderFields.length}`}
              {builderFields.filter(f => f.disabled).length > 0 &&
                ` (${builderFields.filter(f => f.disabled).length} disabled by DSA)`}
            </div>
            <div className="muted">Criteria</div>
            <div>
              {(() => {
                let n = 0;
                const walk = (node) => {
                  if (!node) return;
                  if (node.kind === "rule") { n++; return; }
                  for (const c of (node.rules || [])) walk(c);
                };
                walk(tree);
                return n === 0
                  ? <span className="muted">(none — DSA scope applies)</span>
                  : `${n} rule${n === 1 ? "" : "s"} (full criteria tree shipped as request_payload.criteria)`;
              })()}
            </div>
            <div className="muted">Row cap</div>
            <div>{maxRows ? Number(maxRows).toLocaleString() : "(unbounded — DSA monthly budget applies)"}</div>
            <div className="muted">Delivery</div>
            <div>
              {deliveryMethod
                ? <span className="t-mono">{deliveryMethod}</span>
                : <span className="muted">(none selected)</span>}
              <span className="t-cap"> · travels via requester_note until DRS-O-02</span>
            </div>
          </div>
          <div className="t-cap muted" style={{marginTop:8}}>
            Note: today's validator enforces sub-region and programme rules
            only. Other predicates (e.g. on member.sex, age_years) are
            recorded in the audit chain but don't yet filter the result
            set; they'll start filtering when the criteria evaluator lands.
          </div>
          <div className="tint-update" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
            <div className="row gap-2"><Icon name="shield" size={14} color="var(--accent-update)"/><strong className="t-bodysm">DPIA + DPO review required</strong></div>
            <p className="t-bodysm" style={{margin:'4px 0 0', color:'var(--neutral-700)'}}>The DPO is notified automatically once the request enters the SUBMITTED state. Query hash and field selection are logged on the audit chain.</p>
          </div>
        </div>
      </Modal>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

/* ============================================================
   Step 1 — Scope
   ============================================================ */
// US-S27-011 — controlled entity radio. The backend infers the
// entity from field-prefix on the request_payload.fields list, so
// `entity` is a UI hint rather than a separate payload field —
// switching to "member" surfaces member-prefixed fields in the
// field selector while household-prefixed ones get filtered out
// on the FieldStep. Referral and grievance entities are out of
// the MVP DRS scope; greyed out per ADR-0011's narrow MVP grant.
const ScopeStep = ({ value, onChange }) => {
  const options = [
    { id: "household", label: "Household", sub: "Primary entity · one row per registered household", enabled: true },
    { id: "member",    label: "Member",    sub: "One row per individual within a household", enabled: true },
    { id: "referral",  label: "Referral summary", sub: "Programme referrals · aggregated", enabled: false },
    { id: "grievance", label: "Grievance summary", sub: "Case-level summary", enabled: false },
  ];
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
      <div className="card">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Choose entity</h3><span className="t-cap">Field selector adapts to this choice</span></div>
        <div style={{padding:20, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:12}}>
          {options.map(o => {
            const selected = value === o.id;
            return (
              <button
                key={o.id}
                disabled={!o.enabled}
                onClick={() => o.enabled && onChange(o.id)}
                style={{
                  textAlign:'left', padding:16, borderRadius:6,
                  border: `2px solid ${selected ? 'var(--accent-system)' : 'var(--neutral-300)'}`,
                  background: selected ? 'var(--accent-system-bg)' : !o.enabled ? 'var(--neutral-100)' : 'var(--neutral-0)',
                  opacity: o.enabled ? 1 : 0.5, cursor: o.enabled ? 'pointer' : 'not-allowed',
                }}
              >
                <div className="row gap-2"><strong>{o.label}</strong>{selected && <Icon name="check" size={14} color="var(--accent-system)"/>}</div>
                <div className="t-cap mt-1">{o.sub}</div>
                {!o.enabled && <div className="t-cap mt-2" style={{color:'var(--accent-danger)'}}><Icon name="lock" size={11}/> Outside MVP DRS scope</div>}
              </button>
            );
          })}
        </div>
      </div>
      <DSACard/>
    </div>
  );
};

/* ============================================================
   Step 2 — Build
   ============================================================ */
// US-S27-013 — the wizard mounts <BuildStepV2/> from
// screens-drs-querybuilder.jsx (the full nested-tree builder),
// driven by the live schema.fields catalogue. The earlier
// schema.filter_fields surface stays in the response for
// backwards compatibility but isn't consumed here.
// The simple-row BuildStep that briefly lived in this file is
// removed below.
/* ============================================================
   DSA card (shared)
   ============================================================ */
const DSACard = () => (
  <div className="card" style={{borderTop:'3px solid var(--accent-system)'}}>
    <div className="card-header" style={{padding:'12px 16px'}}>
      <div>
        <div className="t-cap" style={{color:'var(--accent-system)'}}>ACTIVE DSA</div>
        <h3 className="t-h3" style={{margin:'2px 0 0'}}>DSA-OPM-PDM-2026</h3>
      </div>
      <Chip tone="data">Active</Chip>
    </div>
    <div style={{padding:16}}>
      <div style={{display:'grid', gridTemplateColumns:'110px 1fr', rowGap:6, fontSize:13}}>
        <div className="muted">Partner</div><div>Office of the Prime Minister</div>
        <div className="muted">Programme</div><div>OPM-PDM 2026</div>
        <div className="muted">Valid from</div><div>1 Jan 2026</div>
        <div className="muted">Valid to</div><div>31 Dec 2026 <Chip size="sm" tone="data">8 months left</Chip></div>
        <div className="muted">Row budget</div><div>2,500,000 / month</div>
        <div className="muted">Used this month</div><div>1,824,317 (73%)</div>
      </div>
      <div style={{height:6, background:'var(--neutral-200)', borderRadius:3, marginTop:10, overflow:'hidden'}}>
        <div style={{width:'73%', height:'100%', background:'var(--accent-system)'}}/>
      </div>
      <div className="t-cap mt-3">Sensitive fields: <strong>4 disabled</strong> by clause 4.2.b.</div>
      <button className="btn btn-sm mt-3" style={{width:'100%'}}><Icon name="file" size={13}/> Open DSA document</button>
    </div>
  </div>
);

/* ============================================================
   Step 3 — Field Selector
   ============================================================ */
// US-S27-014: the inline FieldStep is removed. The wizard mounts
// <window.FieldStepV2/> from screens-drs-fieldselector.jsx — the
// two-pane "available → ordered output" surface with search,
// sensitivity filters, recommended packs, and drag-reorder.

/* ============================================================
   Step 4 — Preview
   ============================================================ */
// BUG-S27-019 — columns now reflect the ordered list from Step 3,
// labels come from the live catalogue, cells are generated by
// `_previewCell` from each field's type / options / sensitivity.
// BUG-S27-021 — `tree` is now consumed: any rule pinning a column
// (eq / in / between / true / false / on / any) fixes that column's
// value across the preview so the rendered rows match the captured
// WHERE clause. Unconstrained columns still vary via the generator.
const PreviewStep = ({ selected, catalogueByKey = {}, tree = null }) => {
  const cols = selected
    .map(key => ({ key, field: catalogueByKey[key] }))
    .filter(c => c.field);
  const unknown = selected.filter(k => !catalogueByKey[k]);
  const pins = _inferImplicitGeoPins(_buildPinMap(tree), cols, catalogueByKey);
  const pinnedSelectedCount = cols.filter(c => pins[c.key] && !pins[c.key].implicit).length;
  const scopedSelectedCount = cols.filter(c => pins[c.key] && pins[c.key].implicit).length;

  if (selected.length === 0) {
    return (
      <div className="card" style={{padding:40, textAlign:'center'}}>
        <Icon name="eye" size={32} color="var(--neutral-300)"/>
        <h3 className="t-h3" style={{margin:'12px 0 4px'}}>Nothing to preview yet</h3>
        <div className="t-bodysm muted">
          Go back to Step 3 (Field Selector) and pick at least one column.
          The preview reflects your selection in the order you arranged it.
        </div>
      </div>
    );
  }

  // Sensitivity counts drive the masking copy in the toolbar so the
  // operator knows what the preview is hiding.
  const sensitiveCount = cols.filter(c => c.field.sensitivity === "Sensitive").length;
  const personalCount  = cols.filter(c => c.field.sensitivity === "Personal").length;

  const rows = Array.from({length: _PREVIEW_ROW_COUNT}, (_, i) => i);

  return (
    <div className="col gap-4">
      <div className="card" style={{padding:16, display:'flex', alignItems:'center', gap:24, flexWrap:'wrap'}}>
        <div>
          <div className="t-cap">MATCHED</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>47,233</div>
          <div className="t-cap">of 12,089,442 households (0.39%)</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">COLUMNS</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>{cols.length}</div>
          <div className="t-cap">in your Step-3 selection order</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">PREVIEW SHOWN</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>{_PREVIEW_ROW_COUNT}</div>
          <div className="t-cap">design-time sample · no PII surfaced</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">QUERY HASH</div>
          <div className="t-mono" style={{fontSize:13.5, fontWeight:600}}>a4e9d2f1…b7c3</div>
          <div className="t-cap">written to DPO console</div>
        </div>
        <div style={{flex:1}}/>
        <button className="btn" disabled title="The preview endpoint (DRS-O-PREVIEW) lands in a follow-up slice.">
          <Icon name="refresh" size={14}/> Refresh preview
        </button>
      </div>

      {unknown.length > 0 && (
        <div className="tint-update" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-update)'}}>
          <div className="row gap-2"><Icon name="alertCircle" size={14} color="var(--accent-update)"/>
            <strong className="t-bodysm">{unknown.length} selected field{unknown.length === 1 ? "" : "s"} not in current catalogue</strong>
          </div>
          <div className="t-cap" style={{color:'var(--neutral-700)', marginTop:4}}>
            {unknown.slice(0, 4).map(k => <span key={k} className="t-mono" style={{marginRight:10}}>{k}</span>)}
            {unknown.length > 4 && `+${unknown.length - 4} more`}
            {" "}— hidden from preview. Verify the active DSA still covers them.
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">Preview rows · masked sample</strong>
          <span className="t-cap">
            {pinnedSelectedCount > 0 && <>{pinnedSelectedCount} column{pinnedSelectedCount === 1 ? "" : "s"} pinned by your Step-2 filter · </>}
            {scopedSelectedCount > 0 && <>{scopedSelectedCount} column{scopedSelectedCount === 1 ? "" : "s"} scoped to the pinned region · </>}
            {sensitiveCount > 0 && <>{sensitiveCount} Sensitive column{sensitiveCount === 1 ? "" : "s"} masked · </>}
            {personalCount > 0 && <>{personalCount} Personal phone column{personalCount === 1 ? "" : "s"} last-4 only · </>}
            cell values are design-time fixtures until DRS-O-PREVIEW lands
          </span>
        </div>
        <div style={{overflowX:'auto'}}>
          <table className="tbl">
            <thead>
              <tr>
                {cols.map(({key, field}) => {
                  const pin = pins[key];
                  return (
                    <th key={key} title={key}
                      style={pin ? {background:'var(--accent-system-bg)'} : undefined}>
                      <div style={{display:'flex', flexDirection:'column', gap:2, alignItems:'flex-start'}}>
                        <div style={{display:'flex', alignItems:'center', gap:6}}>
                          <span>{field.label || key}</span>
                          {pin && pin.implicit
                            ? <Chip size="sm" tone="data" icon="link">scoped</Chip>
                            : pin && <Chip size="sm" tone="system" icon="filter">filtered</Chip>}
                        </div>
                        <span className="t-cap t-mono" style={{fontSize:10, fontWeight:400, color:'var(--neutral-500)', textTransform:'none', letterSpacing:0}}>{key}</span>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map(i => (
                <tr key={i}>
                  {cols.map(({key, field}) => {
                    const v = _previewCell(key, field, i, pins[key]);
                    const isMono = /id$|number$|hash$|gps|score|nin/.test(key);
                    return (
                      <td key={key} className={isMono ? 'col-id' : ''}>{v}</td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

/* ============================================================
   Step 5 — Delivery
   ============================================================ */
// US-S27-011 — delivery channel pulled from the live builder-
// schema response (apps.data_requests.builder_schema.DELIVERY_METHODS).
// Today the captured `deliveryMethod` is metadata for the operator
// to honour at delivery time; the DRS submit endpoint doesn't have
// a slot for it (DRS-O-02 wiring will add one). Until then the
// chosen method just travels via the audit chain via the request's
// `requester_note` field — explicit gap, not silent fudge.
const DeliveryStep = ({ methods, value, onChange }) => {
  const iconFor = id => id === "portal_download" ? "download"
    : id === "sftp_push" ? "database"
    : id === "webhook"   ? "git"
    : "file";
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
      <div className="card">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Delivery channel</h3></div>
        <div style={{padding:16, display:'flex', flexDirection:'column', gap:10}}>
          {methods.length === 0
            ? <div className="t-cap muted">(no delivery methods available — schema offline)</div>
            : methods.map(m => {
                const on = value === m.id;
                return (
                  <button key={m.id} onClick={() => onChange(m.id)} style={{
                    textAlign:'left', padding:16, borderRadius:6,
                    border:`2px solid ${on ? 'var(--accent-system)' : 'var(--neutral-300)'}`,
                    background: on ? 'var(--accent-system-bg)' : 'var(--neutral-0)',
                    display:'flex', alignItems:'center', gap:14, cursor:'pointer',
                  }}>
                    <div style={{width:36, height:36, borderRadius:6, background:'var(--neutral-100)', display:'grid', placeItems:'center'}}><Icon name={iconFor(m.id)} size={18}/></div>
                    <div style={{flex:1}}>
                      <div className="row gap-2"><strong>{m.label}</strong>{on && <Icon name="check" size={14} color="var(--accent-system)"/>}</div>
                      <div className="t-cap t-mono">{m.id}</div>
                    </div>
                  </button>
                );
              })}
          <div className="t-cap muted" style={{marginTop:6}}>
            The DRS submit endpoint doesn't carry a delivery-method
            field yet (DRS-O-02). Your selection is recorded for the
            operator to honour at delivery time.
          </div>
        </div>
      </div>
      <DSACard/>
    </div>
  );
};

/* ============================================================
   Step 6 — Submit
   ============================================================ */
// US-S27-013 — summary card walks the captured criteria tree.
// Purpose / retention / recipient inputs on the left remain
// presentational; the DRS submit endpoint doesn't persist them
// yet (the DPO review surface lands in a follow-up slice).
const SubmitStep = ({
  onSubmit, entity, selected,
  tree, catalogueByKey,
  maxRows, deliveryMethod,
  deliveryMethods, dsaReference,
}) => {
  const deliveryLabel = (deliveryMethods.find(m => m.id === deliveryMethod) || {}).label || "—";
  // Flatten the tree into a list of leaf rules for the summary.
  const leaves = [];
  const walk = (node) => {
    if (!node) return;
    if (node.kind === "rule") { leaves.push(node); return; }
    for (const c of (node.rules || [])) walk(c);
  };
  walk(tree);
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
      <div className="card">
        <div className="card-header"><h3 className="t-h3" style={{margin:0}}>Purpose, retention, recipients</h3></div>
        <div style={{padding:16}}>
          <Field label="Purpose of use" hint="DPO-facing note; not yet persisted by the DRS submit endpoint.">
            <textarea className="field-textarea" rows={3} placeholder="State the legal basis and use case in your own words. The DPO will review on the operator side."/>
          </Field>
          <div className="t-cap muted" style={{marginTop:8}}>
            Purpose / retention pledge / recipient list controls are
            placeholders — the DRS submit endpoint will accept them in
            a follow-up slice (the DPO review surface).
          </div>
        </div>
      </div>
      <div className="col gap-3">
        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>Summary</h3></div>
          <div style={{padding:16, display:'grid', gridTemplateColumns:'130px 1fr', rowGap:6, fontSize:13}}>
            <div className="muted">DSA</div>
            <div className="t-mono">{dsaReference || "—"}</div>
            <div className="muted">Entity</div>
            <div style={{textTransform:'capitalize'}}>{entity}</div>
            <div className="muted">Criteria</div>
            <div>
              {leaves.length === 0
                ? <span className="muted">(none — DSA scope applies)</span>
                : <div className="col gap-1">
                    {leaves.slice(0, 6).map((rule, i) => {
                      const def = catalogueByKey[rule.field] || {};
                      const op = (rule.op || "?").toUpperCase();
                      const v = rule.value;
                      const sample = Array.isArray(v)
                        ? v.slice(0, 2).join(", ") + (v.length > 2 ? ` +${v.length - 2}` : "")
                        : (v == null || v === "" ? "?" : String(v));
                      return (
                        <div key={rule.id} className="t-mono" style={{fontSize:12}}>
                          {i > 0 && <span className="t-cap" style={{marginRight:6}}>·</span>}
                          {def.label || rule.field} {op} {sample}
                        </div>
                      );
                    })}
                    {leaves.length > 6 && (
                      <div className="t-cap muted">+{leaves.length - 6} more rule{leaves.length - 6 === 1 ? "" : "s"}</div>
                    )}
                  </div>}
            </div>
            <div className="muted">Row cap</div>
            <div>{maxRows ? Number(maxRows).toLocaleString() : "(unbounded)"}</div>
            <div className="muted">Fields</div>
            <div>{selected.length}</div>
            <div className="muted">Delivery</div>
            <div>{deliveryLabel}</div>
          </div>
        </div>
        <DSACard/>
      </div>
    </div>
  );
};

Object.assign(window, {
  DRSScreen, PreviewStep, _previewCell, _buildPinMap, _renderPinned,
  _inferImplicitGeoPins, _GEO_CHAIN,
  _choiceListNameFor, _enrichFieldsWithOptions, _resolveOptionsForSchema,
  _OPTIONS_SOURCE_URL,
});
