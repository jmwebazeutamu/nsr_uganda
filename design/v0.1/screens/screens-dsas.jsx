/* global React, Icon, Chip, KPI, PageHeader, Modal, Field, Toast, useApi, nsrApi, ScopeEditModal */
// DSA management workspace — list, detail, create wizard, renewal,
// quick-find. Lives at /dsas/ in the design harness; wired into the
// admin sidebar, home dashboard, partner detail, and DRS inbox.
//
// Endpoints consumed:
//   GET    /api/v1/dsas/?q=&status=&partner=&expiring_within_days=
//   GET    /api/v1/dsas/{id}/
//   POST   /api/v1/dsas/
//   PATCH  /api/v1/dsas/{id}/
//   POST   /api/v1/dsas/{id}/submit-for-signoff/
//   POST   /api/v1/dsas/{id}/edit-scope/      via ScopeEditModal
//   POST   /api/v1/dsas/{id}/renew/
//   GET    /api/v1/partners/?page_size=200
//
// Status palette mirrors the partner-detail tab so badges stay
// visually consistent across the app.

const {
  useState: useSDsa,
  useEffect: useESDsa,
  useMemo: useMSDsa,
  useCallback: useCSDsa,
} = React;

const DSA_STATUSES = [
  { id: "draft",              label: "Draft",              tone: "update" },
  { id: "pending_signature",  label: "Pending signature",  tone: "update" },
  { id: "active",             label: "Active",             tone: "eligibility" },
  { id: "expiring",           label: "Expiring",           tone: "update" },
  { id: "expired",            label: "Expired",            tone: "danger" },
  { id: "suspended",          label: "Suspended",          tone: "danger" },
  { id: "renewed",            label: "Superseded",         tone: "neutral" },
];
const DSA_STATUS_BY_ID = Object.fromEntries(DSA_STATUSES.map(s => [s.id, s]));

// Lifecycle stages the workspace can ACT on. Anything else is
// terminal / awaiting external sign-off.
const _DSA_EDITABLE = new Set(["draft", "active"]);
const _DSA_SUBMITTABLE = new Set(["draft"]);
const _DSA_RENEWABLE = new Set(["active", "expiring", "expired"]);
// US-S11-040 — Suspend is available when the DSA is operationally
// live (active) or naturally aged out (expired). Drafts use Delete,
// renewed DSAs are already terminal (superseded by v+1).
const _DSA_SUSPENDABLE = new Set(["active", "expired"]);

// Days-until-expiry helper. Returns null when effective_to is
// missing or unparseable. Negative numbers mean "already expired".
const _dsaDaysToExpiry = (dsa) => {
  if (!dsa || !dsa.effective_to) return null;
  const ms = Date.parse(dsa.effective_to) - Date.now();
  if (!Number.isFinite(ms)) return null;
  return Math.round(ms / (24 * 60 * 60 * 1000));
};

// Render a tiny days-to-expiry badge — green if comfortable,
// amber if inside 30 days, red if expired. Used in list + detail.
const _DsaExpiryBadge = ({ dsa }) => {
  const d = _dsaDaysToExpiry(dsa);
  if (d == null) return <span className="t-cap muted">—</span>;
  if (d < 0) {
    return <Chip size="sm" tone="danger">Expired {Math.abs(d)}d ago</Chip>;
  }
  if (d <= 30) {
    return <Chip size="sm" tone="update">in {d}d</Chip>;
  }
  if (d <= 120) {
    return <Chip size="sm" tone="data">in {d}d</Chip>;
  }
  return <span className="t-cap muted">in {d}d</span>;
};

// Status chip — falls back to "Unknown" rather than throwing on
// statuses we haven't catalogued (forward compatibility).
const _DsaStatusChip = ({ status, size }) => {
  const s = DSA_STATUS_BY_ID[status] || { label: status || "—", tone: "neutral" };
  return <Chip size={size} tone={s.tone}>{s.label}</Chip>;
};

// All UI dates render in ISO YYYY-MM-DD per the operator preference
// (single, unambiguous, locale-independent shape across the app).
// Datetimes are truncated at the date — the wizard, detail rails,
// and audit cells don't need wall-clock precision; the audit chain
// keeps full UTC timestamps for forensics.
const _fmtDate = (iso) => {
  if (!iso) return "—";
  return String(iso).slice(0, 10);
};

// Truthy-key count on a JSONField scope dict. Used for the
// summary line ("3 entities · 5 field groups").
const _countTruthy = (obj) => {
  if (!obj || typeof obj !== "object") return 0;
  return Object.values(obj).filter(Boolean).length;
};


// ════════════════════════════════════════════════════════════════
// 1.  DSA list screen — the workspace landing
// ════════════════════════════════════════════════════════════════

const DsasScreen = ({ onOpen, onNew, onNavigate }) => {
  const [statusFilter, setStatusFilter] = useSDsa("active");
  const [partnerFilter, setPartnerFilter] = useSDsa("");
  const [expiringFilter, setExpiringFilter] = useSDsa("");
  const [q, setQ] = useSDsa("");
  const [toast, setToast] = useSDsa("");

  // Debounce search input to avoid one fetch per keystroke.
  const [qDebounced, setQDebounced] = useSDsa("");
  useESDsa(() => {
    const t = setTimeout(() => setQDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Build the query string. Empty params are omitted so the cache
  // key stays stable across "no filter" vs "filter cleared".
  const dsaUrl = useMSDsa(() => {
    const parts = ["page_size=200", "ordering=-created_at"];
    if (statusFilter && statusFilter !== "all") parts.push(`status=${encodeURIComponent(statusFilter)}`);
    if (partnerFilter) parts.push(`partner=${encodeURIComponent(partnerFilter)}`);
    if (expiringFilter) parts.push(`expiring_within_days=${encodeURIComponent(expiringFilter)}`);
    if (qDebounced) parts.push(`q=${encodeURIComponent(qDebounced)}`);
    return `/api/v1/dsas/?${parts.join("&")}`;
  }, [statusFilter, partnerFilter, expiringFilter, qDebounced]);

  const [dsasResp, dsasMeta] = useApi(dsaUrl);
  const [partnersResp] = useApi("/api/v1/partners/?page_size=200");
  const [summary] = useApi("/api/v1/partners/summary/");

  const dsas = (dsasResp && (dsasResp.results || dsasResp)) || [];
  const partners = (partnersResp && (partnersResp.results || partnersResp)) || [];

  return (
    <div className="page" style={{paddingBottom: 0}}>
      <PageHeader
        eyebrow="PARTNERS · DATA SHARING AGREEMENTS"
        title="DSA workspace"
        sub="Browse, search, and manage every DSA across all partners. Renewals, sign-offs, and scope edits live here."
        right={<>
          <button className="btn btn-primary" onClick={onNew}>
            <Icon name="plus" size={14}/> New DSA
          </button>
        </>}
      />

      {/* KPI strip — pulls live counts from /partners/summary/. */}
      <div className="grid grid-4" style={{marginBottom: 16}}>
        <KPI title="Active DSAs"
             value={summary?.active_dsas != null ? String(summary.active_dsas) : "—"}
             foot="Currently in force"/>
        <KPI title="Expiring in 30d"
             value={summary?.dsas_expiring_30d != null ? String(summary.dsas_expiring_30d) : "—"}
             foot="Trigger renewal flow"
             trend={summary?.dsas_expiring_30d > 0 ? "down" : "flat"}/>
        <KPI title="Over budget (30d)"
             value={summary?.dsas_over_budget_30d != null ? String(summary.dsas_over_budget_30d) : "—"}
             foot="Monthly row budget breached"/>
        <KPI title="Drafts in flight"
             value={String(dsas.filter(d => d.status === "draft").length)}
             foot="Awaiting submit for sign-off"/>
      </div>

      {/* Filter / search bar. */}
      <div className="card" style={{padding: 14, marginBottom: 16}}>
        <div className="row gap-3" style={{flexWrap: "wrap", alignItems: "flex-end"}}>
          <Field label="Search">
            <input
              className="field-input"
              placeholder="reference, partner code, or partner name"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{minWidth: 280}}
            />
          </Field>
          <Field label="Status">
            <select
              className="field-input"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All statuses</option>
              {DSA_STATUSES.map(s => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
              <option value="active,expiring">Active + Expiring</option>
            </select>
          </Field>
          <Field label="Partner">
            <select
              className="field-input"
              value={partnerFilter}
              onChange={(e) => setPartnerFilter(e.target.value)}
            >
              <option value="">All partners</option>
              {partners.map(p => (
                <option key={p.id} value={p.id}>{p.code} · {p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Expiring within">
            <select
              className="field-input"
              value={expiringFilter}
              onChange={(e) => setExpiringFilter(e.target.value)}
            >
              <option value="">Any time</option>
              <option value="30">30 days</option>
              <option value="60">60 days</option>
              <option value="120">120 days</option>
            </select>
          </Field>
          <div style={{flex: 1}}/>
          {(q || partnerFilter || expiringFilter || statusFilter !== "active") && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setQ(""); setStatusFilter("active");
                setPartnerFilter(""); setExpiringFilter("");
              }}
            ><Icon name="x" size={13}/> Clear filters</button>
          )}
        </div>
        <div className="t-cap muted" style={{marginTop: 8}}>
          {dsasMeta.loading ? "Loading…" :
            `${dsas.length} ${dsas.length === 1 ? "DSA" : "DSAs"} match.`}
          {dsasMeta.error && <span style={{color: "var(--accent-danger)"}}> · {dsasMeta.error}</span>}
        </div>
      </div>

      {/* Results table. */}
      <div className="card">
        <table className="table" style={{width: "100%", borderCollapse: "collapse"}}>
          <thead>
            <tr style={{borderBottom: "1px solid var(--neutral-200)", textAlign: "left"}}>
              <th style={{padding: "10px 16px"}} className="t-cap">Reference</th>
              <th style={{padding: "10px 16px"}} className="t-cap">Partner</th>
              <th style={{padding: "10px 16px"}} className="t-cap">Status</th>
              <th style={{padding: "10px 16px"}} className="t-cap">Version</th>
              <th style={{padding: "10px 16px"}} className="t-cap">Effective</th>
              <th style={{padding: "10px 16px"}} className="t-cap">Expiry</th>
              <th style={{padding: "10px 16px"}} className="t-cap">Row budget</th>
              <th style={{padding: "10px 16px", width: 80}}/>
            </tr>
          </thead>
          <tbody>
            {dsas.length === 0 && !dsasMeta.loading && (
              <tr>
                <td colSpan={8} style={{padding: "40px 20px", textAlign: "center"}}>
                  <Icon name="file" size={32} color="var(--neutral-300)"/>
                  <div style={{marginTop: 8, fontWeight: 500}}>No DSAs match these filters.</div>
                  <div className="t-bodysm muted" style={{marginTop: 4}}>
                    Try widening the status filter or clearing the search box.
                  </div>
                </td>
              </tr>
            )}
            {dsas.map(d => (
              <tr key={d.id}
                  onClick={() => onOpen && onOpen(d.id)}
                  style={{borderBottom: "1px solid var(--neutral-100)", cursor: "pointer"}}>
                <td style={{padding: "10px 16px"}}>
                  <span className="t-mono" style={{fontWeight: 600}}>{d.reference}</span>
                  <div className="t-cap muted">v{d.version}</div>
                </td>
                <td style={{padding: "10px 16px"}}>
                  <div style={{fontWeight: 500}}>{d.partner_name || d.partner_code || "—"}</div>
                  <div className="t-cap muted">{d.partner_code}</div>
                </td>
                <td style={{padding: "10px 16px"}}>
                  <_DsaStatusChip status={d.status} size="sm"/>
                </td>
                <td style={{padding: "10px 16px"}} className="t-mono">v{d.version}</td>
                <td style={{padding: "10px 16px"}} className="t-bodysm">
                  {_fmtDate(d.effective_from)}<br/>
                  <span className="muted">→ {_fmtDate(d.effective_to)}</span>
                </td>
                <td style={{padding: "10px 16px"}}>
                  <_DsaExpiryBadge dsa={d}/>
                </td>
                <td style={{padding: "10px 16px"}} className="t-mono">
                  {d.monthly_row_budget != null
                    ? Number(d.monthly_row_budget).toLocaleString()
                    : <span className="muted">unbounded</span>}
                </td>
                <td style={{padding: "10px 16px", textAlign: "right"}}>
                  <Icon name="chevronRight" size={14} color="var(--neutral-400)"/>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};


// ════════════════════════════════════════════════════════════════
// 2.  DSA detail screen — lifecycle, scope, signatures, versions
// ════════════════════════════════════════════════════════════════

const DsaDetailScreen = ({ dsaId, onBack, onNavigate }) => {
  const [dsaResp, dsaMeta] = useApi(dsaId ? `/api/v1/dsas/${dsaId}/` : null);
  // Sibling versions sharing the same reference. Lets the operator
  // jump back and forth between v1 / v2 of the same agreement.
  const [siblingsResp] = useApi(
    dsaResp?.reference
      ? `/api/v1/dsas/?q=${encodeURIComponent(dsaResp.reference)}&status=all`
      : null,
  );
  const [scopeOpen, setScopeOpen] = useSDsa(false);
  const [renewOpen, setRenewOpen] = useSDsa(false);
  const [submitOpen, setSubmitOpen] = useSDsa(false);
  // US-S11-038 — non-scope Edit + draft-only Delete. Scope edits
  // route through ScopeEditModal (existing); this modal patches the
  // header-level fields the operator actually wants to fix during
  // draft (effective_to, monthly_row_budget, breach_sla_hours, etc).
  const [editOpen, setEditOpen] = useSDsa(false);
  const [deleteOpen, setDeleteOpen] = useSDsa(false);
  const [suspendOpen, setSuspendOpen] = useSDsa(false);
  const [toast, setToast] = useSDsa("");

  if (!dsaId) {
    return <div className="page"><div className="card" style={{padding: 32}}>No DSA selected.</div></div>;
  }

  const d = dsaResp;
  if (dsaMeta.loading && !d) {
    return <div className="page"><div className="card" style={{padding: 32}}>Loading…</div></div>;
  }
  if (!d) {
    return (
      <div className="page">
        <div className="card" style={{padding: 32}}>
          <strong>DSA not found.</strong>
          <div className="t-bodysm muted" style={{marginTop: 6}}>{dsaMeta.error || "The agreement may have been removed."}</div>
          <button className="btn mt-3" onClick={onBack}><Icon name="arrowLeft" size={13}/> Back to workspace</button>
        </div>
      </div>
    );
  }

  // Versions list (same reference, all statuses).
  const siblings = (siblingsResp && (siblingsResp.results || siblingsResp))
    || [];
  const versions = siblings
    .filter(s => s.reference === d.reference)
    .sort((a, b) => b.version - a.version);

  return (
    <div className="page" style={{paddingBottom: 0}}>
      <PageHeader
        eyebrow={`PARTNERS · DSA · ${d.partner_code || "—"}`}
        title={<span className="t-mono">{d.reference}</span>}
        sub={<>
          v{d.version} · <_DsaStatusChip status={d.status} size="sm"/> · {d.partner_name}
          {d.effective_from && d.effective_to && (
            <> · {_fmtDate(d.effective_from)} → {_fmtDate(d.effective_to)} (<_DsaExpiryBadge dsa={d}/>)</>
          )}
        </>}
        right={<>
          <button className="btn btn-ghost" onClick={onBack}>
            <Icon name="arrowLeft" size={14}/> Workspace
          </button>
          {_DSA_SUBMITTABLE.has(d.status) && (
            <button className="btn btn-primary" onClick={() => setSubmitOpen(true)}>
              <Icon name="check" size={13}/> Submit for sign-off
            </button>
          )}
          {_DSA_EDITABLE.has(d.status) && (
            <button className="btn" onClick={() => setScopeOpen(true)}>
              <Icon name="edit" size={13}/> Edit scope{d.status === "active" ? " (clone v+1)" : ""}
            </button>
          )}
          {_DSA_RENEWABLE.has(d.status) && (
            <button className="btn" onClick={() => setRenewOpen(true)}>
              <Icon name="refresh" size={13}/> Renew
            </button>
          )}
          {_DSA_SUSPENDABLE.has(d.status) && (
            <button className="btn"
                    style={{color:"var(--accent-quality)"}}
                    onClick={() => setSuspendOpen(true)}
                    title="Suspend the DSA so the partner can be wound down (POST /api/v1/dsas/{id}/suspend/)">
              <Icon name="pause" size={13}/> Suspend
            </button>
          )}
          {d.status === "draft" && (
            <>
              <button className="btn" onClick={() => setEditOpen(true)}
                      title="Edit dates, monthly budget, retention, breach SLA, classification">
                <Icon name="edit" size={13}/> Edit details
              </button>
              <button className="btn"
                      style={{color:"var(--accent-danger)"}}
                      onClick={() => setDeleteOpen(true)}
                      title="Hard-delete the draft (DELETE /api/v1/dsas/{id}/)">
                <Icon name="trash" size={13}/> Delete draft
              </button>
            </>
          )}
        </>}
      />

      <div className="grid grid-2 mt-4" style={{gap: 16, gridTemplateColumns: "1fr 360px"}}>
        {/* Left column — scope + signatures + versions */}
        <div className="col gap-3">
          {/* Scope summary */}
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Scope</h3>
              <span className="t-cap">
                {_countTruthy(d.entities_scope)} entities · {_countTruthy(d.field_scope)} field groups · {(d.geographic_scope || []).length} geographic units
              </span>
            </div>
            <div style={{padding: 16}}>
              <div className="t-cap muted" style={{marginBottom: 6}}>ENTITIES</div>
              <div className="row gap-2" style={{flexWrap: "wrap", marginBottom: 14}}>
                {Object.entries(d.entities_scope || {})
                  .filter(([, v]) => v)
                  .map(([k]) => <Chip key={k} size="sm" tone="data">{k}</Chip>)}
                {_countTruthy(d.entities_scope) === 0 && <span className="t-bodysm muted">— none —</span>}
              </div>

              <div className="t-cap muted" style={{marginBottom: 6}}>FIELD GROUPS</div>
              <div className="row gap-2" style={{flexWrap: "wrap", marginBottom: 14}}>
                {Object.entries(d.field_scope || {})
                  .filter(([, v]) => v)
                  .map(([k]) => <Chip key={k} size="sm" tone="programme">{k}</Chip>)}
                {_countTruthy(d.field_scope) === 0 && <span className="t-bodysm muted">— none —</span>}
              </div>

              <div style={{display: "grid", gridTemplateColumns: "180px 1fr", rowGap: 6, fontSize: 13}}>
                <div className="muted">Monthly row budget</div>
                <div className="t-mono">{d.monthly_row_budget != null
                  ? Number(d.monthly_row_budget).toLocaleString()
                  : <span className="muted">unbounded</span>}</div>
                <div className="muted">Sensitive data</div>
                <div>{d.sensitive_data_handling_label || d.sensitive_data_handling || "—"}</div>
                <div className="muted">Retention</div>
                <div>{d.retention_days != null ? `${d.retention_days} days` : "—"}</div>
                <div className="muted">Breach SLA</div>
                <div>{d.breach_sla_hours != null ? `${d.breach_sla_hours} hours` : "—"}</div>
                <div className="muted">Classification</div>
                <div>{d.classification || <span className="muted">—</span>}</div>
                <div className="muted">DPIA</div>
                <div className="t-mono">{d.dpia_document_ref || <span className="muted">—</span>}</div>
              </div>
            </div>
          </div>

          {/* Signatures */}
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Sign-off chain</h3>
              <span className="t-cap">
                {(d.signatures || []).length === 0
                  ? "Not yet dispatched"
                  : `${(d.signatures || []).filter(s => s.status === "signed").length}/${(d.signatures || []).length} signatures recorded`}
              </span>
            </div>
            <div style={{padding: 16}}>
              {(d.signatures || []).length === 0 ? (
                <div className="t-bodysm muted">
                  No signatures dispatched yet. Submitting the draft creates
                  three rows — partner signer (DocuSign), NSR Unit Lead
                  (in-console), DPO (in-console) — per ADR-0012.
                </div>
              ) : (
                <div className="col gap-2">
                  {(d.signatures || [])
                    .sort((a, b) => a.sequence_order - b.sequence_order)
                    .map(s => (
                      <div key={s.id || s.sequence_order} className="row gap-3" style={{
                        padding: 12, borderRadius: 6,
                        background: s.status === "signed"
                          ? "var(--accent-eligibility-bg)"
                          : "var(--neutral-50, #f7f8fa)",
                        border: "1px solid var(--neutral-200)",
                      }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: "50%",
                          display: "grid", placeItems: "center",
                          background: s.status === "signed"
                            ? "var(--accent-eligibility)" : "var(--neutral-300)",
                          color: "white", fontSize: 12, fontWeight: 600,
                        }}>{s.sequence_order}</div>
                        <div style={{flex: 1, minWidth: 0}}>
                          <div style={{fontWeight: 500}}>
                            {s.signer_name || s.signer_email || "—"}
                            <span className="t-cap muted" style={{marginLeft: 8}}>
                              {s.signer_role_label || s.signer_role}
                            </span>
                          </div>
                          <div className="t-cap muted">
                            {s.method_label || s.method}
                            {s.signed_at && <> · signed {_fmtDate(s.signed_at)}</>}
                            {s.docusign_envelope_id && <> · env {s.docusign_envelope_id.slice(0, 24)}</>}
                          </div>
                        </div>
                        <Chip size="sm" tone={s.status === "signed" ? "eligibility" : "neutral"}>
                          {s.status_label || s.status}
                        </Chip>
                      </div>
                    ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right column — versions + metadata */}
        <div className="col gap-3">
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Versions</h3>
              <span className="t-cap">{versions.length} on file</span>
            </div>
            <div>
              {versions.map(v => {
                const isCurrent = v.id === d.id;
                return (
                  <div
                    key={v.id}
                    onClick={() => !isCurrent && onNavigate && onNavigate("dsa-detail", { dsaId: v.id })}
                    style={{
                      padding: "10px 14px", borderBottom: "1px solid var(--neutral-100)",
                      cursor: isCurrent ? "default" : "pointer",
                      background: isCurrent ? "var(--accent-system-bg, #eef3fb)" : "transparent",
                    }}
                  >
                    <div className="row gap-2">
                      <strong>v{v.version}</strong>
                      <_DsaStatusChip status={v.status} size="sm"/>
                      {isCurrent && <Chip size="sm">current</Chip>}
                    </div>
                    <div className="t-cap muted" style={{marginTop: 2}}>
                      {_fmtDate(v.effective_from)} → {_fmtDate(v.effective_to)}
                    </div>
                  </div>
                );
              })}
              {versions.length === 0 && (
                <div className="t-bodysm muted" style={{padding: "20px 14px"}}>
                  This is the only version on record.
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>Cross-links</h3></div>
            <div style={{padding: 14}} className="col gap-2">
              <button
                className="btn btn-sm"
                onClick={() => onNavigate && onNavigate("partner-detail", { partnerId: d.partner })}
              >
                <Icon name="users" size={13}/> Open partner: {d.partner_code}
              </button>
              <button
                className="btn btn-sm"
                onClick={() => onNavigate && onNavigate("drs")}
              >
                <Icon name="download" size={13}/> View DRS requests under this DSA
              </button>
            </div>
          </div>

          <div className="card" style={{padding: 14}}>
            <div className="t-cap muted">METADATA</div>
            <div style={{display: "grid", gridTemplateColumns: "100px 1fr", rowGap: 4, fontSize: 12, marginTop: 6}}>
              <div className="muted">DSA ID</div>
              <div className="t-mono" style={{wordBreak: "break-all"}}>{d.id}</div>
              <div className="muted">Created</div>
              <div>{_fmtDate(d.created_at)}</div>
              <div className="muted">Updated</div>
              <div>{_fmtDate(d.updated_at)}</div>
              <div className="muted">Signed</div>
              <div>{_fmtDate(d.signed_at)}</div>
            </div>
          </div>
        </div>
      </div>

      <ScopeEditModal
        open={scopeOpen}
        onClose={() => setScopeOpen(false)}
        dsa={d}
        onSuccess={(result, ctx) => {
          setScopeOpen(false);
          if (ctx?.cloned && result?.id && result.id !== d.id) {
            setToast(`Cloned to v${result.version} draft — opening it now.`);
            onNavigate && onNavigate("dsa-detail", { dsaId: result.id });
          } else {
            setToast("Scope updated.");
            dsaMeta.refresh();
          }
        }}
      />

      <DsaSuspendConfirm
        open={suspendOpen}
        dsa={d}
        onClose={() => setSuspendOpen(false)}
        onSuspended={() => {
          setSuspendOpen(false);
          setToast(`Suspended ${d.reference} — audit chain updated.`);
          dsaMeta.refresh();
        }}
        onError={(msg) => setToast(`Suspend failed: ${msg}`)}
      />

      <DsaEditDetailsModal
        open={editOpen}
        dsa={d}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          setToast(`Updated ${d.reference} details.`);
          dsaMeta.refresh();
        }}
        onError={(msg) => setToast(`Edit failed: ${msg}`)}
      />

      <DsaDeleteDraftConfirm
        open={deleteOpen}
        dsa={d}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => {
          setDeleteOpen(false);
          setToast(`Deleted draft ${d.reference}.`);
          if (onBack) onBack();
        }}
        onError={(msg) => setToast(`Delete failed: ${msg}`)}
      />

      <DsaRenewModal
        open={renewOpen}
        dsa={d}
        onClose={() => setRenewOpen(false)}
        onRenewed={(newDsa) => {
          setRenewOpen(false);
          setToast(`Renewed to v${newDsa.version} draft.`);
          onNavigate && onNavigate("dsa-detail", { dsaId: newDsa.id });
        }}
        onError={(msg) => setToast(`Renew failed: ${msg}`)}
      />

      <DsaSubmitForSignoffModal
        open={submitOpen}
        dsa={d}
        onClose={() => setSubmitOpen(false)}
        onSubmitted={() => {
          setSubmitOpen(false);
          setToast(`Submitted for sign-off — three envelopes dispatched.`);
          dsaMeta.refresh();
        }}
        onError={(msg) => setToast(`Submit failed: ${msg}`)}
      />

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};


// ════════════════════════════════════════════════════════════════
// 2b. Edit-details modal — wraps PATCH /api/v1/dsas/{id}/ (US-S11-038)
//
// Header-level fields only — scope edits route through ScopeEditModal.
// Available on draft DSAs; active+ DSAs use renew/edit-scope/submit
// for the audit-bearing change path.
// ════════════════════════════════════════════════════════════════

const DsaEditDetailsModal = ({ open, dsa, onClose, onSaved, onError }) => {
  const [effectiveFrom, setEffectiveFrom] = useSDsa("");
  const [effectiveTo, setEffectiveTo] = useSDsa("");
  const [monthlyBudget, setMonthlyBudget] = useSDsa("");
  const [retentionDays, setRetentionDays] = useSDsa("");
  const [breachSlaHours, setBreachSlaHours] = useSDsa("");
  const [classification, setClassification] = useSDsa("");
  const [dpiaRef, setDpiaRef] = useSDsa("");
  const [submitting, setSubmitting] = useSDsa(false);

  React.useEffect(() => {
    if (!open || !dsa) return;
    setEffectiveFrom(dsa.effective_from || "");
    setEffectiveTo(dsa.effective_to || "");
    setMonthlyBudget(dsa.monthly_row_budget ?? "");
    setRetentionDays(dsa.retention_days ?? "");
    setBreachSlaHours(dsa.breach_sla_hours ?? "");
    setClassification(dsa.classification || "");
    setDpiaRef(dsa.dpia_document_ref || "");
  }, [open, dsa]);

  if (!open || !dsa) return null;
  const canSave = !submitting;

  const save = async () => {
    if (!canSave) return;
    setSubmitting(true);
    try {
      const payload = {
        effective_from: effectiveFrom || null,
        effective_to: effectiveTo || null,
        classification: classification.trim(),
        dpia_document_ref: dpiaRef.trim(),
      };
      // Numerics — only ship when filled; serializer rejects "" on
      // IntegerField.
      if (monthlyBudget !== "")  payload.monthly_row_budget = parseInt(monthlyBudget, 10);
      if (retentionDays !== "")  payload.retention_days   = parseInt(retentionDays, 10);
      if (breachSlaHours !== "") payload.breach_sla_hours = parseInt(breachSlaHours, 10);
      await nsrApi.patch(`/api/v1/dsas/${dsa.id}/`, payload);
      setSubmitting(false);
      onSaved();
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || Object.values(err.body).flat().join(" · "))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Edit details · ${dsa.reference}`} size="md">
      <p className="t-bodysm muted" style={{marginTop:0, marginBottom:16}}>
        Patches header-level fields on a draft DSA. Scope edits and
        partner changes route through their dedicated workflows
        (Edit scope / Submit for sign-off).
      </p>

      <div className="grid grid-2" style={{gap:12, marginBottom:12}}>
        <Field label="Effective from">
          <input type="date" value={effectiveFrom}
                 onChange={e => setEffectiveFrom(e.target.value)} disabled={submitting}/>
        </Field>
        <Field label="Effective to">
          <input type="date" value={effectiveTo}
                 onChange={e => setEffectiveTo(e.target.value)} disabled={submitting}/>
        </Field>
      </div>

      <div className="grid grid-3" style={{gap:12, marginBottom:12}}>
        <Field label="Monthly row budget">
          <input type="number" min={0} value={monthlyBudget}
                 onChange={e => setMonthlyBudget(e.target.value)} disabled={submitting}/>
        </Field>
        <Field label="Retention (days)">
          <input type="number" min={0} value={retentionDays}
                 onChange={e => setRetentionDays(e.target.value)} disabled={submitting}/>
        </Field>
        <Field label="Breach SLA (hours)">
          <input type="number" min={0} value={breachSlaHours}
                 onChange={e => setBreachSlaHours(e.target.value)} disabled={submitting}/>
        </Field>
      </div>

      <Field label="Classification">
        <input value={classification} onChange={e => setClassification(e.target.value)}
               disabled={submitting} placeholder="e.g. RESTRICTED, INTERNAL"/>
      </Field>
      <Field label="DPIA document ref">
        <input value={dpiaRef} onChange={e => setDpiaRef(e.target.value)} disabled={submitting}
               placeholder="DPIA-… or document store link"/>
      </Field>

      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!canSave}>
          {submitting ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
};


// ════════════════════════════════════════════════════════════════
// 2c. Delete-draft confirm — DELETE /api/v1/dsas/{id}/ (US-S11-038)
// ════════════════════════════════════════════════════════════════

const DsaDeleteDraftConfirm = ({ open, dsa, onClose, onDeleted, onError }) => {
  const [reason, setReason] = useSDsa("");
  const [submitting, setSubmitting] = useSDsa(false);
  React.useEffect(() => { if (open) setReason(""); }, [open]);
  if (!open || !dsa) return null;
  const isDraft = dsa.status === "draft";

  const fire = async () => {
    setSubmitting(true);
    try {
      await nsrApi.delete(`/api/v1/dsas/${dsa.id}/`);
      setSubmitting(false);
      onDeleted();
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || JSON.stringify(err.body))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Delete draft ${dsa.reference}?`} size="sm">
      {!isDraft && (
        <div className="callout" style={{
          background:"var(--accent-danger-bg)", color:"var(--accent-danger)",
          padding:"10px 12px", borderRadius:4, marginBottom:12, fontSize:13,
        }}>
          <strong>DSA is not in draft.</strong> Hard-delete is disabled —
          use Edit scope (v+1 clone), Renew, or wait for natural expiry.
        </div>
      )}
      <p className="t-bodysm" style={{margin:"4px 0 12px"}}>
        Hard-deletes the draft DSA. No signatures or programmes can be
        attached to a draft, so the cascade is clean.
      </p>
      <Field label="Reason (audit only)">
        <textarea value={reason} onChange={e => setReason(e.target.value)}
                  rows={2} disabled={submitting}
                  placeholder="e.g. partner withdrew before sign-off, replaced by new partner-managed draft."/>
      </Field>
      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button
          className="btn"
          style={{background:"var(--accent-danger)", color:"white", borderColor:"var(--accent-danger)"}}
          onClick={fire} disabled={!isDraft || submitting || !reason.trim()}
        >
          {submitting ? "Deleting…" : "Delete draft"}
        </button>
      </div>
    </Modal>
  );
};


// ════════════════════════════════════════════════════════════════
// 2d. Suspend modal — wraps POST /api/v1/dsas/{id}/suspend/ (US-S11-040)
//
// Lifecycle close — moves active/expired DSAs to status='suspended'
// so the Partner can be wound down. Audit-bearing on the server side.
// ════════════════════════════════════════════════════════════════

const DsaSuspendConfirm = ({ open, dsa, onClose, onSuspended, onError }) => {
  const [reason, setReason] = useSDsa("");
  const [submitting, setSubmitting] = useSDsa(false);
  React.useEffect(() => { if (open) setReason(""); }, [open]);
  if (!open || !dsa) return null;

  const fire = async () => {
    setSubmitting(true);
    try {
      await nsrApi.post(`/api/v1/dsas/${dsa.id}/suspend/`, {
        reason: reason.trim(),
      });
      setSubmitting(false);
      onSuspended();
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || JSON.stringify(err.body))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Suspend ${dsa.reference}?`} size="sm">
      <p className="t-bodysm" style={{margin:"4px 0 12px"}}>
        Marks the DSA as <strong>suspended</strong>. Programmes that
        reference this DSA stop accepting new enrolments. The audit
        chain captures the operator + reason; the row stays queryable
        but won't block a Partner delete once all DSAs are terminal.
      </p>
      <Field label="Reason (audit-bearing)">
        <textarea value={reason} onChange={e => setReason(e.target.value)}
                  rows={2} disabled={submitting}
                  placeholder="e.g. Partner withdrew from MGLSD framework; winding down."/>
      </Field>
      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button
          className="btn"
          style={{background:"var(--accent-quality)", color:"white", borderColor:"var(--accent-quality)"}}
          onClick={fire} disabled={submitting || !reason.trim()}
        >
          {submitting ? "Suspending…" : "Suspend DSA"}
        </button>
      </div>
    </Modal>
  );
};


// ════════════════════════════════════════════════════════════════
// 3.  Renewal modal — wraps POST /api/v1/dsas/{id}/renew/
// ════════════════════════════════════════════════════════════════

const DsaRenewModal = ({ open, dsa, onClose, onRenewed, onError }) => {
  const [busy, setBusy] = useSDsa(false);
  const submit = async () => {
    if (!dsa || busy) return;
    setBusy(true);
    try {
      const next = await nsrApi.post(`/api/v1/dsas/${dsa.id}/renew/`, {});
      if (onRenewed) onRenewed(next);
    } catch (e) {
      if (onError) onError(String(e.body?.detail || e.message || e));
    } finally {
      setBusy(false);
    }
  };
  if (!dsa) return null;
  return (
    <Modal open={open} onClose={() => busy ? null : onClose && onClose()}
      title={`Renew ${dsa.reference}`} width={520}
      footer={<>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" onClick={submit} disabled={busy}>
          <Icon name="refresh" size={13}/> {busy ? "Renewing…" : "Clone to v" + (dsa.version + 1) + " draft"}
        </button>
      </>}>
      <div className="col gap-3">
        <p style={{margin: 0}}>
          Renewing clones <strong className="t-mono">{dsa.reference}</strong> v{dsa.version}
          {" "}into a fresh <strong>v{dsa.version + 1} draft</strong>. The scope
          (entities, fields, geography, budgets) is copied verbatim;
          signatures and effective dates reset to blank for you to
          fill in.
        </p>
        <div className="tint-update" style={{padding: 12, borderRadius: 6, borderLeft: "3px solid var(--accent-update)"}}>
          <div className="row gap-2">
            <Icon name="alertCircle" size={14} color="var(--accent-update)"/>
            <strong className="t-bodysm">The current v{dsa.version} keeps its status until v{dsa.version + 1} reaches ACTIVE.</strong>
          </div>
          <p className="t-bodysm" style={{margin: "4px 0 0", color: "var(--neutral-700)"}}>
            Per ADR-0016 the prior version is automatically superseded
            when the new version's final signature is recorded.
          </p>
        </div>
      </div>
    </Modal>
  );
};


// ════════════════════════════════════════════════════════════════
// 4.  Submit-for-sign-off modal — wraps POST /api/v1/dsas/{id}/submit-for-signoff/
// ════════════════════════════════════════════════════════════════

const DsaSubmitForSignoffModal = ({ open, dsa, onClose, onSubmitted, onError }) => {
  const [psName, setPsName]   = useSDsa("");
  const [psEmail, setPsEmail] = useSDsa("");
  const [lName, setLName]     = useSDsa("");
  const [lEmail, setLEmail]   = useSDsa("");
  const [dName, setDName]     = useSDsa("");
  const [dEmail, setDEmail]   = useSDsa("");
  const [busy, setBusy]       = useSDsa(false);
  const [err, setErr]         = useSDsa("");

  useESDsa(() => {
    if (!open) return;
    setPsName(""); setPsEmail("");
    setLName(""); setLEmail("");
    setDName(""); setDEmail("");
    setBusy(false); setErr("");
  }, [open]);

  const valid = psEmail && lEmail && dEmail
    && psEmail !== lEmail && psEmail !== dEmail && lEmail !== dEmail;

  const submit = async () => {
    if (!dsa || busy || !valid) return;
    setBusy(true); setErr("");
    try {
      await nsrApi.post(`/api/v1/dsas/${dsa.id}/submit-for-signoff/`, {
        partner_signer_name: psName, partner_signer_email: psEmail,
        nsr_unit_lead_name: lName,   nsr_unit_lead_email: lEmail,
        dpo_name: dName,             dpo_email: dEmail,
      });
      if (onSubmitted) onSubmitted();
    } catch (e) {
      const msg = String(e.body?.detail || e.message || e);
      setErr(msg);
      if (onError) onError(msg);
    } finally {
      setBusy(false);
    }
  };

  if (!dsa) return null;
  return (
    <Modal open={open} onClose={() => busy ? null : onClose && onClose()}
      title={`Submit ${dsa.reference} for sign-off`} width={640}
      footer={<>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" onClick={submit} disabled={busy || !valid}>
          <Icon name="check" size={13}/> {busy ? "Dispatching…" : "Dispatch envelopes"}
        </button>
      </>}>
      <div className="col gap-3">
        <p style={{margin: 0}}>
          Submitting this DSA creates three signature rows per
          ADR-0012 — partner signer (DocuSign), NSR Unit Lead
          (in-console), DPO (in-console) — and dispatches the
          first envelope. The three email addresses must all be
          distinct.
        </p>
        <div className="grid grid-2" style={{gap: 10}}>
          <Field label="Partner signer name">
            <input className="field-input" value={psName} onChange={(e) => setPsName(e.target.value)}/>
          </Field>
          <Field label="Partner signer email" required>
            <input className="field-input" type="email" value={psEmail} onChange={(e) => setPsEmail(e.target.value)}/>
          </Field>
          <Field label="NSR Unit Lead name">
            <input className="field-input" value={lName} onChange={(e) => setLName(e.target.value)}/>
          </Field>
          <Field label="NSR Unit Lead email" required>
            <input className="field-input" type="email" value={lEmail} onChange={(e) => setLEmail(e.target.value)}/>
          </Field>
          <Field label="DPO name">
            <input className="field-input" value={dName} onChange={(e) => setDName(e.target.value)}/>
          </Field>
          <Field label="DPO email" required>
            <input className="field-input" type="email" value={dEmail} onChange={(e) => setDEmail(e.target.value)}/>
          </Field>
        </div>
        {(psEmail && lEmail && dEmail && !valid) && (
          <div className="tint-danger" style={{padding: 10, borderRadius: 6, borderLeft: "3px solid var(--accent-danger)"}}>
            <strong className="t-bodysm">The three emails must be distinct.</strong>
          </div>
        )}
        {err && <div className="tint-danger" style={{padding: 10, borderRadius: 6, borderLeft: "3px solid var(--accent-danger)"}}>{err}</div>}
      </div>
    </Modal>
  );
};


// ════════════════════════════════════════════════════════════════
// 5.  DSA create wizard — POST /api/v1/dsas/
// ════════════════════════════════════════════════════════════════

// Pure builder — the wizard collects scope as { entities, fields, ...}
// flat dicts; this assembles the create payload the API accepts.
const buildCreateDsaPayload = (form) => ({
  reference: (form.reference || "").trim(),
  partner: form.partner_id,
  status: "draft",
  effective_from: form.effective_from || null,
  effective_to: form.effective_to || null,
  monthly_row_budget: form.monthly_row_budget
    ? Number(form.monthly_row_budget) : null,
  entities_scope: { ...(form.entities || {}) },
  field_scope: { ...(form.fields || {}) },
  sensitive_data_handling: form.sensitive_data_handling || "none",
  retention_days: form.retention_days ? Number(form.retention_days) : 180,
  classification: form.classification || "",
  dpia_document_ref: form.dpia_document_ref || "",
  breach_sla_hours: form.breach_sla_hours
    ? Number(form.breach_sla_hours) : 72,
});

const DsaCreateWizard = ({ onBack, onCreated, prefillPartnerId = null }) => {
  const [partnersResp] = useApi("/api/v1/partners/?page_size=200&status=active");
  const partners = (partnersResp && (partnersResp.results || partnersResp)) || [];

  const [step, setStep] = useSDsa(0);
  const [form, setForm] = useSDsa({
    partner_id: prefillPartnerId || "",
    reference: "",
    effective_from: "",
    effective_to: "",
    monthly_row_budget: "",
    entities: { household: true, member: true, referral: false, grievance: false },
    fields: {
      Identifiers: true, PMT: false, Health: false, Education: false,
      Employment: false, Housing: false, FoodShocks: false, Roster: true,
    },
    sensitive_data_handling: "none",
    retention_days: "180",
    classification: "",
    dpia_document_ref: "",
    breach_sla_hours: "72",
  });
  const [busy, setBusy] = useSDsa(false);
  const [err, setErr] = useSDsa("");

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const toggle = (group, key) => setForm(f => ({
    ...f, [group]: { ...f[group], [key]: !f[group][key] },
  }));

  const STEPS = [
    { id: "basics",  label: "Basics" },
    { id: "scope",   label: "Scope" },
    { id: "review",  label: "Review" },
  ];

  const stepValid = (i) => {
    if (i === 0) {
      return !!form.partner_id && !!(form.reference || "").trim();
    }
    if (i === 1) {
      return _countTruthy(form.entities) > 0 && _countTruthy(form.fields) > 0;
    }
    return true;
  };
  const canContinue = stepValid(step);

  const submit = async () => {
    if (busy) return;
    setBusy(true); setErr("");
    try {
      const payload = buildCreateDsaPayload(form);
      const created = await nsrApi.post("/api/v1/dsas/", payload);
      if (onCreated) onCreated(created);
    } catch (e) {
      setErr(String(e.body?.detail || e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page" style={{paddingBottom: 0}}>
      <PageHeader
        eyebrow="PARTNERS · DSA · NEW"
        title="Create a Data Sharing Agreement"
        sub="Three steps: identify the partner + reference, set the scope, review. The DSA is created as a draft — sign-off dispatch is a separate action."
        right={<>
          <button className="btn btn-ghost" onClick={onBack}>
            <Icon name="x" size={14}/> Cancel
          </button>
        </>}
      />

      {/* Step indicator */}
      <div className="card" style={{padding: "12px 20px", marginBottom: 16, display: "flex", alignItems: "center"}}>
        {STEPS.map((s, i) => {
          const done = i < step;
          const active = i === step;
          return (
            <React.Fragment key={s.id}>
              <button
                onClick={() => i < step && setStep(i)}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "4px 12px", border: 0, background: "transparent",
                  cursor: i < step ? "pointer" : "default",
                  color: active ? "var(--accent-system)" : done ? "var(--neutral-700)" : "var(--neutral-500)",
                  fontWeight: active ? 600 : 500, fontSize: 13.5,
                }}>
                <span style={{
                  width: 24, height: 24, borderRadius: "50%",
                  display: "grid", placeItems: "center",
                  background: active ? "var(--accent-system)" : done ? "var(--accent-system-bg)" : "var(--neutral-100)",
                  color: active ? "white" : done ? "var(--accent-system)" : "var(--neutral-500)",
                  fontSize: 12, fontWeight: 600,
                  border: active ? 0 : `1px solid ${done ? "var(--accent-system)" : "var(--neutral-300)"}`,
                }}>{done ? <Icon name="check" size={12}/> : i + 1}</span>
                {s.label}
              </button>
              {i < STEPS.length - 1 && (
                <div style={{
                  flex: 1, height: 1,
                  background: i < step ? "var(--accent-system)" : "var(--neutral-300)",
                  minWidth: 14,
                }}/>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Step body */}
      {step === 0 && (
        <div className="card" style={{padding: 20}}>
          <div className="grid grid-2" style={{gap: 12, gridTemplateColumns: "1fr 1fr"}}>
            <Field label="Partner" required>
              <select
                className="field-input"
                value={form.partner_id}
                onChange={(e) => set("partner_id", e.target.value)}
              >
                <option value="">— Select a partner —</option>
                {partners.map(p => (
                  <option key={p.id} value={p.id}>
                    {p.code} · {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="DSA reference" required hint="Stable across versions. v1 will be created.">
              <input
                className="field-input"
                placeholder="e.g. DSA-OPM-2026-001"
                value={form.reference}
                onChange={(e) => set("reference", e.target.value)}
              />
            </Field>
            <Field label="Effective from">
              <input
                type="date" className="field-input"
                value={form.effective_from}
                onChange={(e) => set("effective_from", e.target.value)}
              />
            </Field>
            <Field label="Effective to">
              <input
                type="date" className="field-input"
                value={form.effective_to}
                onChange={(e) => set("effective_to", e.target.value)}
              />
            </Field>
          </div>
          <div className="t-cap muted" style={{marginTop: 14}}>
            Dates can be set later (when sign-off completes the DSA
            takes effect). Reference is the human-readable handle —
            renewals share it across versions.
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="grid" style={{gap: 16, gridTemplateColumns: "1fr 1fr"}}>
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Entities</h3>
              <span className="t-cap">Pick the registry surfaces this DSA can read</span>
            </div>
            <div style={{padding: 16}} className="col gap-2">
              {["household", "member", "referral", "grievance"].map(k => (
                <label key={k} className="row gap-2" style={{cursor: "pointer"}}>
                  <input type="checkbox"
                         checked={!!form.entities[k]}
                         onChange={() => toggle("entities", k)}/>
                  <span style={{textTransform: "capitalize"}}>{k}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Field groups</h3>
              <span className="t-cap">Categories of columns granted by the DSA</span>
            </div>
            <div style={{padding: 16}} className="col gap-2">
              {[
                ["Identifiers",  "Identifiers (household ID, geographic codes)"],
                ["PMT",          "PMT inputs (vulnerability score, band)"],
                ["Roster",       "Household roster (head, members, ages)"],
                ["Health",       "Health (chronic illness flags)"],
                ["Education",    "Education (highest grade, attendance)"],
                ["Employment",   "Employment (sector, income brackets)"],
                ["Housing",      "Housing & assets (dwelling, utilities)"],
                ["FoodShocks",   "Food & shocks (FCS, FIES, shock history)"],
              ].map(([k, label]) => (
                <label key={k} className="row gap-2" style={{cursor: "pointer"}}>
                  <input type="checkbox"
                         checked={!!form.fields[k]}
                         onChange={() => toggle("fields", k)}/>
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="card" style={{gridColumn: "1 / -1"}}>
            <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>Limits & sensitivity</h3></div>
            <div className="grid grid-2" style={{padding: 16, gap: 12, gridTemplateColumns: "repeat(2, 1fr)"}}>
              <Field label="Monthly row budget" hint="Empty = unbounded">
                <input className="field-input" type="number" min="0"
                       value={form.monthly_row_budget}
                       onChange={(e) => set("monthly_row_budget", e.target.value)}/>
              </Field>
              <Field label="Sensitive data handling">
                <select className="field-input"
                        value={form.sensitive_data_handling}
                        onChange={(e) => set("sensitive_data_handling", e.target.value)}>
                  <option value="none">None — sensitive blocked</option>
                  <option value="specific">Specific — opt-in clauses</option>
                  <option value="full">Full — sensitive included</option>
                </select>
              </Field>
              <Field label="Retention (days)">
                <input className="field-input" type="number" min="1"
                       value={form.retention_days}
                       onChange={(e) => set("retention_days", e.target.value)}/>
              </Field>
              <Field label="Breach SLA (hours)">
                <input className="field-input" type="number" min="1"
                       value={form.breach_sla_hours}
                       onChange={(e) => set("breach_sla_hours", e.target.value)}/>
              </Field>
              <Field label="Classification">
                <input className="field-input"
                       placeholder="e.g. Restricted-Operator"
                       value={form.classification}
                       onChange={(e) => set("classification", e.target.value)}/>
              </Field>
              <Field label="DPIA document reference">
                <input className="field-input"
                       placeholder="e.g. DPIA-OPM-2026"
                       value={form.dpia_document_ref}
                       onChange={(e) => set("dpia_document_ref", e.target.value)}/>
              </Field>
            </div>
          </div>
        </div>
      )}

      {step === 2 && (() => {
        const p = partners.find(x => x.id === form.partner_id);
        return (
          <div className="card" style={{padding: 20}}>
            <h3 className="t-h3" style={{marginTop: 0}}>Review</h3>
            <div style={{display: "grid", gridTemplateColumns: "200px 1fr", rowGap: 8}}>
              <div className="muted">Partner</div>
              <div>{p ? `${p.code} · ${p.name}` : "—"}</div>
              <div className="muted">Reference</div>
              <div className="t-mono">{form.reference || "—"}</div>
              <div className="muted">Effective</div>
              <div>{_fmtDate(form.effective_from)} → {_fmtDate(form.effective_to)}</div>
              <div className="muted">Entities</div>
              <div>{Object.entries(form.entities).filter(([, v]) => v).map(([k]) => k).join(", ") || "—"}</div>
              <div className="muted">Field groups</div>
              <div>{Object.entries(form.fields).filter(([, v]) => v).map(([k]) => k).join(", ") || "—"}</div>
              <div className="muted">Monthly row budget</div>
              <div className="t-mono">{form.monthly_row_budget
                ? Number(form.monthly_row_budget).toLocaleString()
                : "unbounded"}</div>
              <div className="muted">Sensitive handling</div>
              <div>{form.sensitive_data_handling}</div>
              <div className="muted">Retention</div>
              <div>{form.retention_days || 180} days</div>
              <div className="muted">Breach SLA</div>
              <div>{form.breach_sla_hours || 72} hours</div>
            </div>
            {err && (
              <div className="tint-danger" style={{padding: 10, borderRadius: 6, marginTop: 14, borderLeft: "3px solid var(--accent-danger)"}}>
                {err}
              </div>
            )}
            <div className="t-cap muted" style={{marginTop: 14}}>
              The DSA is created as a <strong>draft</strong>. You can dispatch
              the sign-off chain (partner signer · NSR Unit Lead · DPO) from
              the detail page once you've reviewed the scope.
            </div>
          </div>
        );
      })()}

      {/* Action bar */}
      <div style={{
        margin: "16px -24px 0", position: "sticky", bottom: 0, zIndex: 20,
        background: "var(--neutral-0)", borderTop: "1px solid var(--neutral-300)",
        padding: "12px 20px", display: "flex", gap: 12, alignItems: "center",
      }}>
        <span className="t-bodysm muted">Step {step + 1} of {STEPS.length} · <strong>{STEPS[step].label}</strong></span>
        <div style={{flex: 1}}/>
        <button className="btn" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>
          <Icon name="chevronLeft" size={13}/> Back
        </button>
        {step < STEPS.length - 1 ? (
          <button className="btn btn-primary"
                  onClick={() => canContinue && setStep(step + 1)}
                  disabled={!canContinue}>
            Continue <Icon name="chevronRight" size={13}/>
          </button>
        ) : (
          <button className="btn btn-primary" onClick={submit} disabled={busy || !canContinue}>
            <Icon name="check" size={13}/> {busy ? "Creating…" : "Create DSA"}
          </button>
        )}
      </div>
    </div>
  );
};


// ════════════════════════════════════════════════════════════════
// 6.  Console quick-find — global overlay for "find a DSA"
// ════════════════════════════════════════════════════════════════

const DsaQuickFind = ({ open, onClose, onPick }) => {
  const [q, setQ] = useSDsa("");
  const [qDeb, setQDeb] = useSDsa("");
  useESDsa(() => {
    const t = setTimeout(() => setQDeb(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);
  useESDsa(() => {
    if (!open) { setQ(""); setQDeb(""); }
  }, [open]);
  // Skip the fetch until the user types something — the workspace
  // is the right surface for "show me everything", not this overlay.
  const url = qDeb
    ? `/api/v1/dsas/?q=${encodeURIComponent(qDeb)}&page_size=20`
    : null;
  const [resp, meta] = useApi(url, { skip: !url });
  const rows = (resp && (resp.results || resp)) || [];
  return (
    <Modal open={open} onClose={onClose} title="Find a DSA" width={680}
      footer={<>
        <button className="btn" onClick={onClose}>Close</button>
      </>}>
      <div className="col gap-3">
        <input
          className="field-input"
          placeholder="Type a reference, partner code, or partner name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
          style={{padding: "10px 12px"}}
        />
        {!qDeb && (
          <div className="t-bodysm muted">Type at least one character to search.</div>
        )}
        {qDeb && meta.loading && <div className="t-bodysm muted">Searching…</div>}
        {qDeb && !meta.loading && rows.length === 0 && (
          <div className="t-bodysm muted">No DSAs match "{qDeb}".</div>
        )}
        {rows.length > 0 && (
          <div style={{border: "1px solid var(--neutral-200)", borderRadius: 6, maxHeight: 360, overflowY: "auto"}}>
            {rows.map(d => (
              <div
                key={d.id}
                onClick={() => onPick && onPick(d)}
                style={{
                  padding: "10px 14px",
                  borderBottom: "1px solid var(--neutral-100)",
                  cursor: "pointer",
                }}
              >
                <div className="row gap-2" style={{alignItems: "center"}}>
                  <strong className="t-mono">{d.reference}</strong>
                  <_DsaStatusChip status={d.status} size="sm"/>
                  <span className="t-cap muted">v{d.version}</span>
                </div>
                <div className="t-cap" style={{marginTop: 2, color: "var(--neutral-700)"}}>
                  {d.partner_name || d.partner_code}
                  {d.effective_to && <> · expires {_fmtDate(d.effective_to)}</>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
};


// ────────────────────────────────────────────────────────────────
// Exports — bind to window so the harness picks them up.
// Internal helpers (_dsaDaysToExpiry, buildCreateDsaPayload) ride
// along for vitest.
// ────────────────────────────────────────────────────────────────

Object.assign(window, {
  DsasScreen,
  DsaDetailScreen,
  DsaCreateWizard,
  DsaRenewModal,
  DsaSubmitForSignoffModal,
  DsaQuickFind,
  _dsaDaysToExpiry,
  buildCreateDsaPayload,
  DSA_STATUSES,
});
