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

const FIELDS = [
  // group, name, sensitivity, disabled?, reason
  ["Identifiers", "registry_id",        "Public",    false],
  ["Identifiers", "household_number",   "Public",    false],
  ["Identifiers", "captured_date",      "Public",    false],
  ["Identifiers", "captured_parish",    "Internal",  false],
  ["Geography",   "subregion",          "Public",    false],
  ["Geography",   "district",           "Public",    false],
  ["Geography",   "subcounty",          "Public",    false],
  ["Geography",   "parish",             "Internal",  false],
  ["Geography",   "village",            "Internal",  false],
  ["Geography",   "gps_lat",            "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["Geography",   "gps_lng",            "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["Household",   "household_size",     "Public",    false],
  ["Household",   "head_sex",           "Public",    false],
  ["Household",   "head_age_band",      "Public",    false],
  ["Household",   "head_education",     "Internal",  false],
  ["Identity",    "nin_value",          "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["Identity",    "head_name",          "Personal",  false],
  ["Identity",    "phone",              "Personal",  false],
  ["Identity",    "photo_ref",          "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
  ["PMT",         "pmt_score",          "Internal",  false],
  ["PMT",         "pmt_band",           "Internal",  false],
  ["Housing",     "roof_material",      "Internal",  false],
  ["Housing",     "walls_material",     "Internal",  false],
  ["Housing",     "toilet_type",        "Internal",  false],
  ["Housing",     "water_source",       "Internal",  false],
  ["Wealth",      "household_savings_amount", "Sensitive", true, "Disabled by DSA clause 4.2.b. Request expansion via your data steward."],
];

const PREVIEW_ROWS = [
  { rid: "01HXY7K3B2N9PVQE4M6FZRWS18", hh: "HH-7411-002-0148", parish: "Nakiloro", subreg: "Karamoja", size: 6, sex: "F", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••4567" },
  { rid: "01HXZ9MR4N8P2QFB7K6FZRWS33", hh: "HH-3122-005-0091", parish: "Pageya",  subreg: "Acholi",   size: 5, sex: "F", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••2119" },
  { rid: "01HY09KRS1P9MN6FB7K6FZRWS84", hh: "HH-7411-002-0103", parish: "Kakingol",subreg: "Karamoja", size: 7, sex: "M", age: "40-49", band: "Poorest 20%", roof: "Iron sheets", phone: "+256 ••• ••8221" },
  { rid: "01HY02FNQ9P8MN6FB7K6FZRWS67", hh: "HH-7531-001-0048", parish: "Lorengedwat", subreg: "Karamoja", size: 6, sex: "F", age: "20-29", band: "Poorest 20%", roof: "Thatch",      phone: "+256 ••• ••5582" },
  { rid: "01HY04MQR0N8P2FB7K6FZRWS73", hh: "HH-7531-002-0017", parish: "Apeitolim", subreg: "Karamoja", size: 8, sex: "F", age: "40-49", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••6620" },
  { rid: "01HXP02CN4QFB7K6FZRWS00111", hh: "HH-2110-008-0021", parish: "Anyiribu", subreg: "West Nile", size: 4, sex: "M", age: "50-59", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••0044" },
  { rid: "01HXP02CN4QFB7K6FZRWS00118", hh: "HH-2110-008-0033", parish: "Logiri",   subreg: "West Nile", size: 7, sex: "M", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••9912" },
  { rid: "01HXP02CN4QFB7K6FZRWS00124", hh: "HH-3122-009-0019", parish: "Bobi",     subreg: "Acholi",    size: 5, sex: "F", age: "20-29", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••3322" },
  { rid: "01HXP02CN4QFB7K6FZRWS00135", hh: "HH-2110-008-0040", parish: "Kuluba",   subreg: "West Nile", size: 4, sex: "F", age: "30-39", band: "Poorest 40%", roof: "Iron sheets", phone: "+256 ••• ••7711" },
  { rid: "01HXP02CN4QFB7K6FZRWS00148", hh: "HH-7411-002-0211", parish: "Tapac",    subreg: "Karamoja",  size: 6, sex: "F", age: "40-49", band: "Poorest 20%", roof: "Iron sheets", phone: "+256 ••• ••1188" },
];

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
  // Selected fields hold whatever the effective catalogue's `name`
  // column is. When `schema` arrives the catalogue switches to the
  // backend's dotted keys ("household.id"); until then the mock
  // tail-names ("registry_id") are the placeholder. Defaults are
  // empty — the user picks intentionally.
  const [selectedFields, setSel] = useStateDRS(new Set());
  // US-S27-011 / US-S27-012 — captured query-builder state. The
  // backend validator (validate_against_dsa) only recognises
  // fields / sub_region_codes / programme_codes / max_rows; entity
  // is derived from field prefix; delivery method is metadata.
  // The filterRows array is the query-builder source of truth —
  // each row is one predicate. On submit we group by payload_key
  // (from schema.filter_fields) so multiple rows on the same
  // field union their values into one payload entry.
  const [entity, setEntity] = useStateDRS("household");
  const [maxRows, setMaxRows] = useStateDRS("");
  const [deliveryMethod, setDeliveryMethod] = useStateDRS("");
  // filterRows: [{ id, fieldKey, operator, values: Set<string> }]
  const [filterRows, setFilterRows] = useStateDRS([]);
  // valueCache: { [value_source URL]: [{code, label}, …] }
  const [valueCache, setValueCache] = useStateDRS({});
  const [submitOpen, setSubmitOpen] = useStateDRS(false);
  const [submitting, setSubmitting] = useStateDRS(false);
  const [toast, setToast] = useStateDRS("");
  const stepIdx = STEPS.findIndex(s => s.id === step);

  const next = () => setStep(STEPS[Math.min(stepIdx + 1, STEPS.length - 1)].id);
  const prev = () => setStep(STEPS[Math.max(stepIdx - 1, 0)].id);

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

  // US-S27-012 — schema-driven value sources. Each filter_field
  // in the schema carries a `value_source` URL the UI fetches to
  // populate that field's value picker. We fetch all unique
  // sources once on schema load and cache the rows by URL. Adding
  // a new predicate to the catalogue is a backend-only change —
  // the UI grows automatically.
  React.useEffect(() => {
    if (!schema?.filter_fields) return;
    const urls = [...new Set(schema.filter_fields.map(f => f.value_source))];
    let cancelled = false;
    Promise.all(urls.map(url =>
      fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => [url, data])
        .catch(() => [url, null]),
    )).then(pairs => {
      if (cancelled) return;
      setValueCache(prev => {
        const next = { ...prev };
        for (const [url, data] of pairs) {
          if (data == null) { next[url] = []; continue; }
          const rows = data.results || data || [];
          next[url] = Array.isArray(rows) ? rows : [];
        }
        return next;
      });
    });
    return () => { cancelled = true; };
  }, [schema]);

  // Compose the effective FIELDS catalogue. When the schema is
  // loaded the catalogue comes straight from the backend — the
  // tuple's `name` column carries the dotted key ("household.id")
  // so it can be POSTed verbatim. When the schema isn't reachable
  // (offline preview), the hardcoded mock FIELDS catalogue takes
  // over with its short tail-names — submit is disabled in that
  // case anyway because `schema.dsa_id` won't exist.
  const effectiveFields = React.useMemo(() => {
    if (!schema || !schema.fields) return FIELDS;
    return schema.fields.map(f => [
      f.group, f.key, f.sensitivity,
      Boolean(f.disabled),
      f.disabled_reason || "",
    ]);
  }, [schema]);

  const toggleField = (name, disabled, reason) => {
    if (disabled) return;
    const next = new Set(selectedFields);
    if (next.has(name)) next.delete(name); else next.add(name);
    setSel(next);
  };

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
    if (selectedFields.size === 0) {
      setToast("Pick at least one field before submitting.");
      return;
    }
    setSubmitting(true);
    const payload = {
      fields: [...selectedFields],
    };
    // US-S27-012 — translate filterRows into the flat predicate
    // shape validate_against_dsa expects. Each filter_field
    // declares its `payload_key` in the schema; multiple rows on
    // the same field union their values into one payload entry.
    const groups = {};
    for (const row of filterRows) {
      const def = (schema?.filter_fields || []).find(
        f => f.key === row.fieldKey,
      );
      if (!def || !row.values || row.values.size === 0) continue;
      const key = def.payload_key;
      if (!groups[key]) groups[key] = new Set();
      for (const v of row.values) groups[key].add(v);
    }
    for (const [key, set] of Object.entries(groups)) {
      payload[key] = [...set];
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
          <button className="btn"><Icon name="save" size={14}/> Save as template</button>
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
      {step === 'build' && <BuildStep
        filterFields={schema?.filter_fields || []}
        valueCache={valueCache}
        rows={filterRows}
        onChange={setFilterRows}
        maxRows={maxRows}
        onMaxRows={setMaxRows}
      />}
      {step === 'fields' && <FieldStep selected={selectedFields} onToggle={toggleField} fields={effectiveFields}/>}
      {step === 'preview' && <PreviewStep selected={selectedFields}/>}
      {step === 'delivery' && <DeliveryStep
        methods={schema?.delivery_methods || []}
        value={deliveryMethod}
        onChange={setDeliveryMethod}
      />}
      {step === 'submit' && <SubmitStep
        onSubmit={() => setSubmitOpen(true)}
        entity={entity}
        selected={selectedFields}
        filterRows={filterRows}
        filterFields={schema?.filter_fields || []}
        valueCache={valueCache}
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
              {selectedFields.size} selected
              {effectiveFields.length > 0 && ` of ${effectiveFields.length}`}
              {effectiveFields.filter(f => f[3]).length > 0 &&
                ` (${effectiveFields.filter(f => f[3]).length} disabled by DSA)`}
            </div>
            <div className="muted">Filters</div>
            <div>
              {filterRows.filter(r => r.values && r.values.size > 0).length === 0
                ? <span className="muted">(none — DSA scope applies)</span>
                : `${filterRows.filter(r => r.values && r.values.size > 0).length} predicate${filterRows.filter(r => r.values && r.values.size > 0).length === 1 ? "" : "s"}`}
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
// US-S27-012 — schema-driven query builder. Each row is a single
// predicate: pick a field from `filterFields` (advertised by the
// backend), pick an operator from that field's `operators`, pick
// one or more values from a multi-select populated from the
// field's `value_source` URL. Predicates AND together. Each row
// translates into one entry in request_payload at submit time
// (via the field's `payload_key`); rows on the same field union.
//
// The backend grows new predicates by adding a `filter_fields`
// entry — the UI follows automatically.
const _rowId = () => `r${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const BuildStep = ({
  filterFields, valueCache, rows, onChange,
  maxRows, onMaxRows,
}) => {
  const addRow = () => onChange([
    ...rows,
    { id: _rowId(), fieldKey: "", operator: "", values: new Set() },
  ]);
  const removeRow = (id) => onChange(rows.filter(r => r.id !== id));
  const setFieldOnRow = (id, fieldKey) => {
    const def = filterFields.find(f => f.key === fieldKey);
    onChange(rows.map(r => r.id === id
      ? { ...r, fieldKey, operator: def?.operators?.[0] || "", values: new Set() }
      : r));
  };
  const toggleValueOnRow = (id, code) => {
    onChange(rows.map(r => {
      if (r.id !== id) return r;
      const next = new Set(r.values);
      next.has(code) ? next.delete(code) : next.add(code);
      return { ...r, values: next };
    }));
  };

  const opLabel = (op) => ({
    in: "is one of", not_in: "is not one of", eq: "is", neq: "is not",
    between: "between", starts_with: "starts with", is_null: "is missing",
  }[op] || op);

  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 360px', gap:16}}>
      <div className="card">
        <div className="card-header">
          <div>
            <h3 className="t-h3" style={{margin:0}}>Query builder</h3>
            <div className="t-cap">Predicates combine with AND · field catalogue from /builder-schema/</div>
          </div>
          <button className="btn btn-sm" onClick={addRow}
                  disabled={filterFields.length === 0}>
            <Icon name="plus" size={14}/> Add filter
          </button>
        </div>
        <div style={{padding:16, display:'flex', flexDirection:'column', gap:12}}>
          {filterFields.length === 0 && (
            <div className="t-cap muted">(no filter fields available — schema offline)</div>
          )}
          {rows.length === 0 && filterFields.length > 0 && (
            <div className="t-cap muted">
              No filters added yet. The request will read every row the DSA scope permits.
              Click <strong>Add filter</strong> to narrow it.
            </div>
          )}
          {rows.map((row, i) => {
            const def = filterFields.find(f => f.key === row.fieldKey);
            const values = def ? (valueCache[def.value_source] || []) : [];
            return (
              <div key={row.id} style={{
                border:'1px solid var(--neutral-300)', borderRadius:6,
                background:'var(--neutral-0)', padding:'10px 12px',
                display:'flex', flexDirection:'column', gap:10,
              }}>
                <div style={{display:'grid', gridTemplateColumns:'56px 1fr 160px auto', gap:10, alignItems:'center'}}>
                  <span className="t-cap" style={{textAlign:'right'}}>
                    {i === 0 ? "WHERE" : <Chip size="sm" tone="system">AND</Chip>}
                  </span>
                  <select
                    className="field-select"
                    value={row.fieldKey}
                    onChange={e => setFieldOnRow(row.id, e.target.value)}
                    style={{height:32, fontSize:13}}
                  >
                    <option value="">— pick a field —</option>
                    {filterFields.map(f => (
                      <option key={f.key} value={f.key}>{f.label}</option>
                    ))}
                  </select>
                  <div className="t-cap" style={{textAlign:'center'}}>
                    {def ? opLabel(def.operators[0]) : "—"}
                  </div>
                  <button className="btn btn-sm btn-ghost"
                          onClick={() => removeRow(row.id)} title="Remove filter">
                    <Icon name="x" size={14}/>
                  </button>
                </div>
                {def && (
                  <div style={{
                    padding:'8px 10px', background:'var(--neutral-50)',
                    border:'1px solid var(--neutral-200)', borderRadius:4,
                    display:'flex', flexDirection:'column', gap:8,
                  }}>
                    <div className="row gap-2" style={{justifyContent:'space-between', alignItems:'baseline'}}>
                      <span className="t-cap">
                        {values.length === 0
                          ? "loading values…"
                          : `${row.values.size} of ${values.length} selected`}
                      </span>
                    </div>
                    {values.length > 0 && (
                      <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:6, maxHeight:200, overflowY:'auto'}}>
                        {values.map(v => {
                          const code = v[def.value_code_field] || v.code || v.id;
                          const label = v[def.value_label_field] || v.label || v.name || code;
                          const on = row.values.has(code);
                          return (
                            <label key={code} style={{
                              display:'flex', alignItems:'center', gap:6, cursor:'pointer',
                              padding:'5px 8px', borderRadius:3,
                              background: on ? 'var(--accent-system-bg)' : 'var(--neutral-0)',
                              border: `1px solid ${on ? 'var(--accent-system)' : 'var(--neutral-200)'}`,
                            }}>
                              <input type="checkbox" checked={on}
                                onChange={() => toggleValueOnRow(row.id, code)}/>
                              <div style={{flex:1, minWidth:0}}>
                                <div className="t-bodysm" style={{fontWeight: on ? 600 : 400, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{label}</div>
                                <div className="t-cap t-mono" style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{code}</div>
                              </div>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          <div className="divider"/>

          {/* Row cap — separate from predicate rows because it's a LIMIT, not a WHERE */}
          <div>
            <div className="row gap-2" style={{justifyContent:'space-between', alignItems:'baseline', marginBottom:6}}>
              <strong className="t-bodysm">Row cap (max_rows)</strong>
              <span className="t-cap">Optional · DSA monthly budget applies even if blank</span>
            </div>
            <input
              className="field-input"
              type="number" min={1} step={1000} placeholder="e.g. 10000"
              value={maxRows}
              onChange={e => onMaxRows(e.target.value.replace(/[^0-9]/g, ""))}
              style={{maxWidth:240}}
            />
          </div>

          <div className="divider"/>

          <div className="t-cap" style={{marginBottom:6}}>EXPRESSION PREVIEW</div>
          <div className="t-mono" style={{padding:12, background:'var(--neutral-50)', borderRadius:4, fontSize:12, lineHeight:1.6, color:'var(--neutral-900)', whiteSpace:'pre-wrap', border:'1px solid var(--neutral-200)'}}>
{rows.filter(r => r.fieldKey && r.values.size > 0).length === 0
  ? "(no predicates — DSA scope applies as-is)"
  : `AND (\n${rows
      .filter(r => r.fieldKey && r.values.size > 0)
      .map(r => {
        const def = filterFields.find(f => f.key === r.fieldKey);
        const vals = [...r.values].map(v => `'${v}'`).join(", ");
        return `  ${def?.key} ${def?.operators?.[0]?.toUpperCase() || "?"} (${vals})`;
      }).join(",\n")}\n)`}
{maxRows ? `\nLIMIT ${Number(maxRows).toLocaleString()}` : ""}
          </div>
        </div>
      </div>

      <div className="col gap-3">
        <DSACard/>
      </div>
    </div>
  );
};

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
const FieldStep = ({ selected, onToggle, fields }) => {
  // `fields` is the effective catalogue: DSA-overlaid when the
  // builder-schema fetch succeeded, otherwise the mock FIELDS
  // (US-S18-003). Falls back to the module constant defensively.
  const list = fields || FIELDS;
  const groups = list.reduce((acc, f) => { (acc[f[0]] = acc[f[0]] || []).push(f); return acc; }, {});
  return (
    <div style={{display:'grid', gridTemplateColumns:'1fr 320px', gap:16}}>
      <div className="card">
        <div className="card-header">
          <div>
            <h3 className="t-h3" style={{margin:0}}>Field selector</h3>
            <div className="t-cap">{selected.size} selected · {list.filter(f => f[3]).length} sensitive fields disabled</div>
          </div>
          <div className="row gap-2">
            <button className="btn btn-sm">Select all available</button>
            <button className="btn btn-sm btn-ghost"><Icon name="save" size={14}/> Save selection</button>
          </div>
        </div>
        <div>
          {Object.entries(groups).map(([group, fields]) => (
            <React.Fragment key={group}>
              <div style={{padding:'10px 20px', background:'var(--neutral-100)', borderBottom:'1px solid var(--neutral-200)', fontSize:12, fontWeight:600, letterSpacing:'0.06em', textTransform:'uppercase', color:'var(--neutral-700)'}}>
                {group}
              </div>
              {fields.map(([, name, sens, disabled, reason]) => (
                <div key={name} title={reason || ""} onClick={() => onToggle(name, disabled, reason)} style={{
                  padding:'10px 20px', borderBottom:'1px solid var(--neutral-200)',
                  display:'grid', gridTemplateColumns:'24px 1fr 120px 200px', alignItems:'center', gap:12,
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  background: selected.has(name) ? 'var(--accent-system-bg)' : disabled ? 'var(--neutral-50)' : 'transparent',
                  opacity: disabled ? 0.7 : 1,
                }}>
                  <input type="checkbox" checked={selected.has(name)} disabled={disabled} readOnly/>
                  <div className="t-mono" style={{fontSize:13, color: disabled ? 'var(--neutral-500)' : 'var(--neutral-900)'}}>{name}</div>
                  <Chip>{sens}</Chip>
                  <div className="t-cap" style={{color: disabled ? 'var(--accent-danger)' : 'var(--neutral-500)'}}>
                    {disabled ? <><Icon name="lock" size={11}/> DSA clause 4.2.b</> : "Available under DSA"}
                  </div>
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </div>

      <div className="col gap-3">
        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>Sensitivity legend</h3></div>
          <div style={{padding:14, display:'flex', flexDirection:'column', gap:10}}>
            {[["Public", "Geography rolled up; aggregate counts"],
              ["Internal", "Programme-level reporting"],
              ["Personal", "Identifies a person; PII"],
              ["Sensitive", "Identifies + categorical risk; requires expansion"]].map(([s, desc]) => (
              <div key={s} className="row gap-3">
                <Chip>{s}</Chip>
                <span className="t-bodysm muted">{desc}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{borderLeft:'3px solid var(--accent-danger)'}}>
          <div style={{padding:14}}>
            <div className="row gap-2" style={{marginBottom:4}}>
              <Icon name="lock" size={14} color="var(--accent-danger)"/>
              <strong className="t-bodysm">DSA-clause guard</strong>
            </div>
            <div className="t-bodysm muted">
              Fields marked <Chip size="sm">Sensitive</Chip> are blocked by clause 4.2.b of your active DSA. To enable, request a scope expansion via your data steward.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ============================================================
   Step 4 — Preview
   ============================================================ */
const PreviewStep = ({ selected }) => {
  const cols = [
    ["Registry ID", "rid", "mono"],
    ["Household number", "hh", "mono"],
    ["Sub-region", "subreg"],
    ["Parish", "parish"],
    ["HH size", "size"],
    ["Sex (head)", "sex"],
    ["Age band (head)", "age"],
    ["PMT band", "band"],
    ["Roof", "roof"],
    ["Phone (masked)", "phone", "mono"],
  ];
  return (
    <div className="col gap-4">
      <div className="card" style={{padding:16, display:'flex', alignItems:'center', gap:24}}>
        <div>
          <div className="t-cap">MATCHED</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>47,233</div>
          <div className="t-cap">of 12,089,442 households (0.39%)</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">PREVIEW SHOWN</div>
          <div className="t-num" style={{fontSize:24, fontWeight:700, letterSpacing:'-0.01em'}}>10</div>
          <div className="t-cap">server-side masked sample</div>
        </div>
        <div style={{width:1, height:48, background:'var(--neutral-200)'}}/>
        <div>
          <div className="t-cap">QUERY HASH</div>
          <div className="t-mono" style={{fontSize:13.5, fontWeight:600}}>a4e9d2f1…b7c3</div>
          <div className="t-cap">written to DPO console</div>
        </div>
        <div style={{flex:1}}/>
        <button className="btn"><Icon name="refresh" size={14}/> Refresh preview</button>
      </div>

      <div className="card">
        <div className="card-toolbar">
          <strong className="t-bodysm">Preview rows (masked)</strong>
          <span className="t-cap">Phone last 4 digits revealed only · IDs always full · sensitive fields excluded</span>
        </div>
        <div style={{overflowX:'auto'}}>
          <table className="tbl">
            <thead><tr>{cols.map(c => <th key={c[1]}>{c[0]}</th>)}</tr></thead>
            <tbody>
              {PREVIEW_ROWS.map((r, i) => (
                <tr key={i}>
                  {cols.map(c => (
                    <td key={c[1]} className={c[2] === 'mono' ? 'col-id' : ''}>
                      {c[1] === 'rid' ? r.rid.slice(0, 22) + '…' : r[c[1]]}
                    </td>
                  ))}
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
// US-S27-012 — summary card walks the captured filterRows so it
// reflects whatever the query builder produced. Purpose /
// retention / recipient inputs on the left remain presentational;
// the DRS submit endpoint doesn't persist them yet (the DPO
// review surface lands in a follow-up slice).
const SubmitStep = ({
  onSubmit, entity, selected,
  filterRows, filterFields, valueCache,
  maxRows, deliveryMethod,
  deliveryMethods, dsaReference,
}) => {
  const deliveryLabel = (deliveryMethods.find(m => m.id === deliveryMethod) || {}).label || "—";
  const populated = filterRows.filter(r => r.fieldKey && r.values && r.values.size > 0);
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
            <div className="muted">Predicates</div>
            <div>
              {populated.length === 0
                ? <span className="muted">(none — DSA scope applies)</span>
                : <div className="col gap-1">
                    {populated.map((row, i) => {
                      const def = filterFields.find(f => f.key === row.fieldKey);
                      const op = (def?.operators?.[0] || "?").toUpperCase();
                      const sample = [...row.values].slice(0, 3).join(", ");
                      const more = row.values.size > 3 ? ` +${row.values.size - 3}` : "";
                      return (
                        <div key={row.id} className="t-mono" style={{fontSize:12}}>
                          {i > 0 && <span className="t-cap" style={{marginRight:6}}>AND</span>}
                          {def?.label || row.fieldKey} {op} ({sample}{more})
                        </div>
                      );
                    })}
                  </div>}
            </div>
            <div className="muted">Row cap</div>
            <div>{maxRows ? Number(maxRows).toLocaleString() : "(unbounded)"}</div>
            <div className="muted">Fields</div>
            <div>{selected.size}</div>
            <div className="muted">Delivery</div>
            <div>{deliveryLabel}</div>
          </div>
        </div>
        <DSACard/>
      </div>
    </div>
  );
};

Object.assign(window, { DRSScreen });
