/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, Toast */
// NSR MIS — Partner DRS portal (US-S9-005). Second React console
// screen; the partner-facing surface for the API shipped in S7-004
// (/api/v1/drs/requests/mine/) + S8-003 (/download/) + S9-003
// (throttling). Role-gated to PARTNER_ANALYST and PARTNER_DPO per
// ADR-0006.

const { useState: useStatePDrs, useMemo: useMemoPDrs } = React;

// DataRequest statuses mirror apps.data_requests.models.RequestStatus.
// Partner-facing labels use plainer English than the operator-side
// vocabulary — "Pending approval" not "submitted", etc.
const PDRS_STATUSES = {
  draft:     { label: "Draft",            tone: "neutral",     icon: "edit"     },
  submitted: { label: "Pending approval", tone: "update",      icon: "clock"    },
  approved:  { label: "Approved",         tone: "data",        icon: "check"    },
  rejected:  { label: "Rejected",         tone: "danger",      icon: "x"        },
  delivered: { label: "Delivered",        tone: "eligibility", icon: "download" },
  expired:   { label: "Expired",          tone: "neutral",     icon: "lock"     },
};

// Mock rows mirror the MyDataRequestSerializer shape from
// apps/data_requests/api.py (S7-004). When the fetch wiring lands
// these get replaced with the real /requests/mine/ response.
const PDRS_REQUESTS = [
  {
    id: "01DRS2026051400001",
    dsa_reference: "DSA-PDM-2026-01",
    status: "delivered",
    submitted_at: "12 May 09:00",
    delivered_at: "13 May 11:42",
    expires_at:   "12 Jun 11:42",
    manifest_sha256: "a3f8e91c52d04b7e2c1f6a5b9d0e7f4c8b6a2e1d4f5c9a7b3e0d8c2f1a9b5e6d",
    row_count_delivered: 1284,
    download_url: "/api/v1/drs/requests/01DRS2026051400001/download/",
    request_payload: {
      fields: ["household.id", "household.sub_region_code",
               "household.current_vulnerability_band",
               "member.line_number", "member.first_name", "member.sex"],
      sub_region_codes: ["SR-BUGANDA-SOUTH"],
      max_rows: 5000,
    },
  },
  {
    id: "01DRS2026051400002",
    dsa_reference: "DSA-PDM-2026-01",
    status: "approved",
    submitted_at: "14 May 08:30",
    delivered_at: null,
    expires_at:   null,
    manifest_sha256: "",
    row_count_delivered: null,
    download_url: null,
    request_payload: {
      fields: ["household.id", "household.current_vulnerability_band"],
      sub_region_codes: ["SR-BUGANDA-SOUTH", "SR-BUGANDA-NORTH"],
      max_rows: 10000,
    },
  },
  {
    id: "01DRS2026051400003",
    dsa_reference: "DSA-PDM-2026-01",
    status: "submitted",
    submitted_at: "14 May 14:15",
    delivered_at: null,
    expires_at:   null,
    manifest_sha256: "",
    row_count_delivered: null,
    download_url: null,
    request_payload: {
      fields: ["household.id", "household.sub_region_code"],
      programme_codes: ["PDM"],
    },
  },
  {
    id: "01DRS2026051400004",
    dsa_reference: "DSA-PDM-2026-01",
    status: "rejected",
    submitted_at: "10 May 11:00",
    delivered_at: null,
    expires_at:   null,
    manifest_sha256: "",
    row_count_delivered: null,
    download_url: null,
    decision_reason: "Field 'member.nin_value' outside DSA scope. Resubmit with allowed fields only.",
    request_payload: {
      fields: ["member.nin_value"],  // would fail validate_against_dsa
    },
  },
  {
    id: "01DRS2026051400005",
    dsa_reference: "DSA-PDM-2026-01",
    status: "expired",
    submitted_at: "01 Apr 09:00",
    delivered_at: "02 Apr 14:30",
    expires_at:   "02 May 14:30",
    manifest_sha256: "b7c1f9d3a8e0c5f4b2a6d9e3f7c8b4e1d2a5f0c8e6b3a9d4f1c7e8b2a5d0f3c9",
    row_count_delivered: 842,
    download_url: null,  // expired → no download
    request_payload: {
      fields: ["household.id", "household.current_vulnerability_band"],
    },
  },
];

const STATUS_FILTERS = [
  { id: "all",       label: "All",              count: PDRS_REQUESTS.length },
  { id: "submitted", label: "Pending approval", count: PDRS_REQUESTS.filter(r => r.status === "submitted").length },
  { id: "approved",  label: "Approved",         count: PDRS_REQUESTS.filter(r => r.status === "approved").length },
  { id: "delivered", label: "Delivered",        count: PDRS_REQUESTS.filter(r => r.status === "delivered").length },
];

const PartnerDRSScreen = () => {
  const [statusFilter, setStatusFilter] = useStatePDrs("all");
  const [selectedRow, setSelectedRow] = useStatePDrs(PDRS_REQUESTS[0].id);
  const [auditOpen, setAuditOpen] = useStatePDrs(false);
  const [toast, setToast] = useStatePDrs("");

  const rows = useMemoPDrs(() => (
    statusFilter === "all"
      ? PDRS_REQUESTS
      : PDRS_REQUESTS.filter(r => r.status === statusFilter)
  ), [statusFilter]);

  const current = useMemoPDrs(
    () => PDRS_REQUESTS.find(r => r.id === selectedRow),
    [selectedRow],
  );

  const onDownload = (r) => {
    // Real wiring: hit r.download_url; the response is NDJSON
    // application/x-ndjson with Content-Disposition attachment from
    // S8-003. For the mockup we just toast.
    setToast(`Download started — ${r.row_count_delivered.toLocaleString()} rows · NDJSON · manifest ${r.manifest_sha256.slice(0,12)}…`);
  };

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow="PARTNER DRS PORTAL · US-S9-005"
        title={<>My data requests <Chip>{rows.length}</Chip></>}
        sub="Bulk-extract requests under your active DSA. Pending submissions go through NSR Unit approval before download."
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn primary"><Icon name="plus"/> New request</button>
        </>}
      />

      {/* Status filter strip */}
      <div className="card" style={{padding:"14px 20px", marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:"wrap"}}>
          <span className="t-cap" style={{fontWeight:600}}>STATUS</span>
          {STATUS_FILTERS.map(f => {
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
            <span className="t-cap">DSA-PDM-2026-01 · 1,000-50,000 rows/req · 30d TTL</span>
          </div>

          {/* Header */}
          <div style={{display:"grid", gridTemplateColumns:"1fr 140px 100px 130px 130px 110px", borderBottom:"1px solid var(--neutral-200)", background:"var(--neutral-50)", fontSize:11, fontWeight:600, letterSpacing:"0.06em", textTransform:"uppercase", color:"var(--neutral-700)"}}>
            <div style={{padding:"10px 16px"}}>Request</div>
            <div style={{padding:"10px 8px"}}>Status</div>
            <div style={{padding:"10px 8px", textAlign:"right"}}>Rows</div>
            <div style={{padding:"10px 8px"}}>Submitted</div>
            <div style={{padding:"10px 8px"}}>Expires</div>
            <div style={{padding:"10px 8px"}}/>
          </div>

          {rows.map(r => {
            const active = selectedRow === r.id;
            const st = PDRS_STATUSES[r.status];
            return (
              <div
                key={r.id}
                onClick={() => setSelectedRow(r.id)}
                style={{
                  display:"grid", gridTemplateColumns:"1fr 140px 100px 130px 130px 110px",
                  borderBottom:"1px solid var(--neutral-200)",
                  background: active ? "var(--accent-data-bg)" : "white",
                  cursor:"pointer",
                  alignItems:"center",
                }}>
                <div style={{padding:"12px 16px"}}>
                  <div className="t-mono" style={{fontSize:12, color:"var(--neutral-900)"}}>{r.id}</div>
                  <div className="t-bodysm muted" style={{marginTop:2}}>{r.dsa_reference}</div>
                </div>
                <div style={{padding:"12px 8px"}}>
                  <Chip size="sm" tone={st.tone} icon={st.icon}>{st.label}</Chip>
                </div>
                <div style={{padding:"12px 8px", textAlign:"right", fontFamily:"monospace", fontSize:12, color: r.row_count_delivered ? "var(--neutral-900)" : "var(--neutral-400)"}}>
                  {r.row_count_delivered != null ? r.row_count_delivered.toLocaleString() : "—"}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {r.submitted_at || "—"}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {r.expires_at || "—"}
                </div>
                <div style={{padding:"12px 8px"}}>
                  {r.download_url
                    ? <button
                        className="btn primary"
                        style={{padding:"4px 10px", fontSize:12}}
                        onClick={(e) => { e.stopPropagation(); onDownload(r); }}>
                        <Icon name="download" size={12}/> Download
                      </button>
                    : <span className="t-cap" style={{color:"var(--neutral-400)"}}>—</span>
                  }
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
                  <div className="t-cap"><Icon name="download" size={11}/> REQUEST DETAIL</div>
                  <h3 className="t-h3" style={{margin:"2px 0 0", fontFamily:"monospace", fontSize:13}}>{current.id}</h3>
                </div>
                <Chip tone={PDRS_STATUSES[current.status].tone}>{PDRS_STATUSES[current.status].label}</Chip>
              </div>
              <div style={{padding:16}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>DSA</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.dsa_reference}</div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>FIELDS REQUESTED</div>
                <div className="row-wrap" style={{display:"flex", flexWrap:"wrap", gap:6}}>
                  {(current.request_payload.fields || []).map(f => (
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
                    <div className="t-mono" style={{fontSize:13}}>{current.request_payload.max_rows.toLocaleString()}</div>
                  </>
                )}

                {current.status === "rejected" && current.decision_reason && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--accent-danger)", margin:"14px 0 6px"}}>REJECTION REASON</div>
                    <div className="t-bodysm" style={{color:"var(--neutral-800)", padding:8, background:"var(--accent-danger-bg)", borderRadius:6, lineHeight:1.5}}>
                      {current.decision_reason}
                    </div>
                  </>
                )}

                {current.status === "delivered" && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>BUNDLE</div>
                    <div className="t-bodysm">
                      <span className="muted">Rows:</span>{" "}
                      <span className="t-mono">{current.row_count_delivered.toLocaleString()}</span>
                    </div>
                    <div className="t-bodysm mt-1">
                      <span className="muted">SHA-256:</span>{" "}
                      <span className="t-mono" style={{fontSize:11, wordBreak:"break-all"}}>
                        {current.manifest_sha256}
                      </span>
                    </div>
                    <div className="t-bodysm mt-1">
                      <span className="muted">Expires:</span>{" "}
                      <span>{current.expires_at}</span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="card">
              <div style={{padding:"12px 16px"}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:8}}>ACTIONS</div>
                <div className="col gap-2">
                  {current.download_url && (
                    <button className="btn primary" onClick={() => onDownload(current)}>
                      <Icon name="download" size={13}/> Download NDJSON ({current.row_count_delivered.toLocaleString()} rows)
                    </button>
                  )}
                  {current.status === "rejected" && (
                    <button className="btn">
                      <Icon name="refresh" size={13}/> Duplicate as new draft
                    </button>
                  )}
                  {current.status === "delivered" && (
                    <button className="btn">
                      <Icon name="refresh" size={13}/> Re-request (same scope)
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Hints */}
            <div className="card" style={{padding:"12px 16px", background:"var(--neutral-50)"}}>
              <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>
                <Icon name="info" size={11}/> ABOUT THIS PORTAL
              </div>
              <div className="t-bodysm" style={{color:"var(--neutral-700)", lineHeight:1.5}}>
                You can see only requests under DSAs your organisation
                signed. Downloads are rate-limited to 10/min and bundles
                expire 30 days after delivery. Every read and download
                is recorded in the audit chain.
              </div>
            </div>
          </div>
        )}
      </div>

      <AuditDrawer
        open={auditOpen}
        events={current ? [
          { who: current.id.slice(-12), action: "submitted", detail: `Via partner portal · DSA ${current.dsa_reference}`, time: current.submitted_at, audit: `A-${current.id.slice(-10)}`, tone: "user" },
          ...(current.status !== "draft" && current.status !== "submitted" ? [{ who: "NSR Unit", action: current.status === "rejected" ? "rejected" : "approved", detail: current.decision_reason || "Within DSA scope", time: "later", audit: `A-${current.id.slice(-10)}-2`, tone: "user" }] : []),
          ...(current.status === "delivered" ? [{ who: "System DRS", action: "rendered + delivered", detail: `Manifest SHA-256 locked, ${current.row_count_delivered.toLocaleString()} rows`, time: current.delivered_at, audit: `A-${current.id.slice(-10)}-3`, tone: "system" }] : []),
        ] : []}
        onClose={() => setAuditOpen(false)}
      />
      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};
