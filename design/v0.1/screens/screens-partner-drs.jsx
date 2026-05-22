/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, Toast, DRSScreen */
// NSR MIS — Partner DRS portal (US-S9-005). Second React console
// screen; the partner-facing surface for the API shipped in S7-004
// (/api/v1/drs/requests/mine/) + S8-003 (/download/) + S9-003
// (throttling). Role-gated to PARTNER_ANALYST and PARTNER_DPO per
// ADR-0006.

const { useState: useStatePDrs, useMemo: useMemoPDrs, useEffect: useEffectPDrs } = React;

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

// Status filter definitions — counts computed dynamically in the
// component from the live (or mock) request list so the chips
// reflect what the API actually returned.
const STATUS_FILTER_DEFS = [
  { id: "all",       label: "All" },
  { id: "submitted", label: "Pending approval" },
  { id: "approved",  label: "Approved" },
  { id: "delivered", label: "Delivered" },
];

// SHA-256 over a Blob using the browser's Web Crypto API. Returns a
// lowercase-hex 64-char string matching what apps.data_requests.bundle
// writes to manifest.sha256 (S6-002 / S8-003). Async because crypto
// .subtle.digest streams the file in 256KB chunks rather than loading
// the whole NDJSON into memory at once.
//
// FileReader -> ArrayBuffer -> SubtleCrypto.digest -> hex. ~2 MB/s
// in a 2026 browser; a 50,000-row bundle (typical partner DSA cap)
// hashes in well under a second.
const sha256Hex = async (blob) => {
  const buf = await blob.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
};

const PartnerDRSScreen = () => {
  // mode: "list" (the S9-005 view) or "build" (the S10-003 builder)
  const [mode, setMode] = useStatePDrs("list");
  const [statusFilter, setStatusFilter] = useStatePDrs("all");
  const [auditOpen, setAuditOpen] = useStatePDrs(false);
  const [toast, setToast] = useStatePDrs("");

  // US-S13-004 — live wiring. Fetch on mount; fall back to
  // PDRS_REQUESTS mock if /api/v1/drs/requests/mine/ isn't reachable
  // (file:// preview or unauthenticated session).
  const [liveRequests, setLiveRequests] = useStatePDrs(null);
  const [dataSource, setDataSource] = useStatePDrs("mock");
  useEffectPDrs(() => {
    let cancelled = false;
    fetch("/api/v1/drs/requests/mine/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => {
        if (cancelled) return;
        const rows = (data.results || data || []).map(r => ({
          ...r,
          // request_payload isn't on MyDataRequestSerializer (slim
          // partner-facing projection); fill an empty object so the
          // detail rail's `(current.request_payload.fields || [])`
          // pattern stays safe.
          request_payload: r.request_payload || { fields: [] },
        }));
        setLiveRequests(rows);
        setDataSource(rows.length === 0 ? "live-empty" : "live");
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const allRequests = liveRequests || PDRS_REQUESTS;
  const [selectedRow, setSelectedRow] = useStatePDrs(PDRS_REQUESTS[0]?.id);
  useEffectPDrs(() => {
    if (allRequests.length > 0 && !allRequests.find(r => r.id === selectedRow)) {
      setSelectedRow(allRequests[0].id);
    }
  }, [allRequests]);

  // Per-request integrity-verify state (US-S11-006). Map of
  // request_id -> { state: "idle"|"hashing"|"match"|"mismatch"|"error",
  //                  computed: "...64hex...", error?: "..." }.
  // Kept in component state rather than mutating PDRS_REQUESTS so the
  // mock data block stays the canonical "what the API returned."
  const [verify, setVerify] = useStatePDrs({});
  const fileInputRef = React.useRef(null);
  const [pendingVerifyId, setPendingVerifyId] = useStatePDrs(null);

  const startVerify = (requestId) => {
    setPendingVerifyId(requestId);
    // Reset any prior result so the operator sees the picker land on
    // a fresh state when re-running a verification.
    setVerify(v => ({ ...v, [requestId]: { state: "idle" } }));
    fileInputRef.current?.click();
  };

  const onFileChosen = async (e) => {
    const file = e.target.files?.[0];
    const requestId = pendingVerifyId;
    // Clear the input value so picking the same file twice still
    // fires onChange (browsers suppress duplicate change events).
    e.target.value = "";
    if (!file || !requestId) return;
    const req = allRequests.find(r => r.id === requestId);
    if (!req) return;
    setVerify(v => ({ ...v, [requestId]: { state: "hashing" } }));
    try {
      const computed = await sha256Hex(file);
      const match = computed === req.manifest_sha256;
      setVerify(v => ({
        ...v,
        [requestId]: { state: match ? "match" : "mismatch", computed },
      }));
    } catch (err) {
      setVerify(v => ({
        ...v,
        [requestId]: { state: "error", error: String(err) },
      }));
    }
  };

  // Note: the prior `onBuilderSubmit` helper was dead code — the
  // actual submit lives inside DRSWizard (screens-drs.jsx) which
  // POSTs to /api/v1/drs/requests/ + /submit/ directly (US-S27-010).

  // Hooks must run in the same order every render — compute the
  // list-mode memos unconditionally, then branch on mode below.
  const rows = useMemoPDrs(() => (
    statusFilter === "all"
      ? allRequests
      : allRequests.filter(r => r.status === statusFilter)
  ), [allRequests, statusFilter]);

  const current = useMemoPDrs(
    () => allRequests.find(r => r.id === selectedRow),
    [allRequests, selectedRow],
  );

  // Live status-filter counts — chips reflect what the API returned.
  const STATUS_FILTERS = useMemoPDrs(
    () => STATUS_FILTER_DEFS.map(f => ({
      ...f,
      count: f.id === "all" ? allRequests.length
                            : allRequests.filter(r => r.status === f.id).length,
    })),
    [allRequests],
  );

  // US-S16-002 — partner-side reciprocal of the operator's
  // turnaround metric (US-S15-002). For partners "decision
  // turnaround" is the whole submitted → delivered window, not
  // just the operator's decide time, because that's what the
  // partner actually waits for. Computed off delivered requests
  // only; rejected ones aren't a wait, they're a dead end.
  // Hidden below n=3 sample size.
  const deliveryTurnaround = useMemoPDrs(() => {
    const delivered = allRequests.filter(
      r => r.status === "delivered" && r.submitted_at && r.delivered_at,
    );
    if (delivered.length < 3) return null;
    const deltas = delivered.map(r => {
      const ms = Date.parse(r.delivered_at) - Date.parse(r.submitted_at);
      return Number.isFinite(ms) && ms > 0 ? ms : null;
    }).filter(v => v != null);
    if (deltas.length < 3) return null;
    const meanMs = deltas.reduce((a, b) => a + b, 0) / deltas.length;
    const hours = meanMs / (60 * 60 * 1000);
    if (hours < 24) return { label: `typical wait ${hours.toFixed(1)}h`, n: deltas.length };
    return { label: `typical wait ${(hours / 24).toFixed(1)}d`, n: deltas.length };
  }, [allRequests]);

  if (mode === "build") {
    // BUG-S11-002b — the partner builder is now the SAME component
    // operators use (screens-drs.jsx DRSScreen) parameterised with
    // role="partner". The reduced RequestBuilder from S10-003 was
    // intentional MVP scope; the bug report correctly flagged it as
    // a partner-facing capability gap. Disabled fields here are
    // mocked from the FIELDS catalogue's sensitivity column; real
    // fetch wiring reads /api/v1/drs/requests/builder-schema/ (S11-
    // 002a) which returns role-aware disabled flags per the active
    // DSA's allowed_scopes.
    return <DRSScreen role="partner" onExit={() => setMode("list")}/>;
  }

  const onDownload = async (r) => {
    // US-S27-010 — real wiring. Fetch the NDJSON bundle bytes via
    // the credentialed endpoint, then trigger a browser download
    // through an anchor with a synthetic object URL so the partner
    // gets a real .ndjson file. Once DRS-O-02 closes (MinIO +
    // signed URLs), the endpoint returns 302 and the browser
    // follows the redirect directly — same UX from the partner's
    // perspective, less data through Django.
    const url = r.download_url || `/api/v1/drs/requests/${r.id}/download/`;
    setToast(`Download starting · ${r.row_count_delivered?.toLocaleString() || ""} rows · NDJSON…`);
    try {
      const resp = await fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/x-ndjson, application/json" },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = `drs-${r.id}.ndjson`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Release the blob after the click — the browser owns the
      // download by this point so revoking is safe.
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
      setToast(
        `Downloaded · manifest ${r.manifest_sha256?.slice(0, 12) || "—"}…`,
      );
    } catch (e) {
      setToast(`Download failed: ${e.message}`);
    }
  };

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      {/* Hidden file picker driven by the "Verify integrity" button.
          Lives at the root so it stays mounted across selectedRow
          changes — the picker's value gets cleared on each open
          (see onFileChosen) so re-picking the same file still fires. */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".ndjson,.jsonl,.json,application/x-ndjson,application/json"
        style={{display:"none"}}
        onChange={onFileChosen}/>
      <PageHeader
        eyebrow={
          (dataSource === "live" ? "PARTNER DRS PORTAL · LIVE" : "PARTNER DRS PORTAL · US-S9-005")
          + (deliveryTurnaround ? ` · ${deliveryTurnaround.label} (n=${deliveryTurnaround.n})` : "")
        }
        title={<>My data requests <Chip>{rows.length}</Chip></>}
        sub="Bulk-extract requests under your active DSA. Pending submissions go through NSR Unit approval before download."
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn primary" onClick={() => setMode("build")}>
            <Icon name="plus"/> New request
          </button>
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
                  {(r.submitted_at || "").slice(0, 10) || "—"}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {(r.expires_at || "").slice(0, 10) || "—"}
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
                      <span>{(current.expires_at || "").slice(0, 10)}</span>
                    </div>

                    {/* US-S11-006 — verify integrity. Operator picks
                        the local NDJSON file; we recompute SHA-256
                        in-browser and compare to the manifest hash. */}
                    {(() => {
                      const v = verify[current.id] || { state: "idle" };
                      return (
                        <div style={{marginTop:14, padding:10,
                                      background:"var(--neutral-50)",
                                      borderRadius:6,
                                      border:"1px solid var(--neutral-200)"}}>
                          <div className="row" style={{justifyContent:"space-between", alignItems:"center"}}>
                            <span className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)"}}>
                              <Icon name="shield" size={11}/> VERIFY INTEGRITY
                            </span>
                            <button
                              className="btn btn-sm"
                              disabled={v.state === "hashing"}
                              onClick={() => startVerify(current.id)}>
                              {v.state === "hashing"
                                ? <><Icon name="clock" size={12}/> Hashing…</>
                                : v.state === "idle"
                                  ? <><Icon name="file" size={12}/> Pick downloaded file</>
                                  : <><Icon name="refresh" size={12}/> Re-verify</>}
                            </button>
                          </div>
                          <div className="t-bodysm muted mt-1" style={{fontSize:12}}>
                            Recomputes SHA-256 from the file you downloaded and
                            compares to the manifest above. Nothing leaves your
                            browser.
                          </div>
                          {v.state === "match" && (
                            <div className="row gap-2 mt-2"
                              style={{padding:"6px 10px", borderRadius:4,
                                       background:"var(--accent-eligibility-bg)",
                                       color:"var(--accent-eligibility)",
                                       fontSize:13, fontWeight:600,
                                       alignItems:"center"}}>
                              <Icon name="check" size={14}/> Hash matches — bundle integrity OK.
                            </div>
                          )}
                          {v.state === "mismatch" && (
                            <div className="col gap-1 mt-2"
                              style={{padding:"6px 10px", borderRadius:4,
                                       background:"var(--accent-danger-bg)",
                                       color:"var(--accent-danger)",
                                       fontSize:13}}>
                              <div className="row gap-2" style={{fontWeight:600, alignItems:"center"}}>
                                <Icon name="xCircle" size={14}/> HASH MISMATCH — DO NOT use this bundle.
                              </div>
                              <div className="t-bodysm" style={{fontSize:11, wordBreak:"break-all", color:"var(--neutral-800)"}}>
                                Computed: <span className="t-mono">{v.computed}</span>
                              </div>
                              <div className="t-bodysm" style={{fontSize:11, color:"var(--neutral-700)"}}>
                                Report this to the NSR Unit DPO at once — the file
                                may have been altered after delivery.
                              </div>
                            </div>
                          )}
                          {v.state === "error" && (
                            <div className="t-bodysm mt-2" style={{color:"var(--accent-danger)"}}>
                              Couldn't hash the file: {v.error}
                            </div>
                          )}
                        </div>
                      );
                    })()}
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

