/* global React, Icon, Chip, PageHeader, useApi, nsrApi */
// Partner self-service read-only surfaces — My DSA + My Programmes.
//
// Lives next to the partner DRS portal. Both screens read endpoints
// the partner already has ABAC access to:
//
//   GET /api/v1/dsas/?page_size=50         → their partner's DSAs
//   GET /api/v1/programmes/?page_size=100  → their partner's programmes
//
// Server-side PartnerScopedQuerysetMixin narrows both to the
// authenticated user's partner_code; nothing partner-A sees here can
// leak partner-B's rows. The screens are intentionally read-only —
// edits route through the operator (/dsas/{id}/edit-scope/ +
// /programmes/{id}/) and require the sign-off chain.

const { useState: useSPP, useEffect: useESPP } = React;

// ISO date helper — matches the app-wide policy.
const _ppFmtDate = (iso) => (iso || "").slice(0, 10) || "—";

// DSA status palette — small subset, mirrors screens-dsas.jsx tones.
const _PP_STATUS_TONE = {
  draft: "neutral",
  pending_signature: "update",
  active: "eligibility",
  expiring: "update",
  expired: "danger",
  suspended: "danger",
  renewed: "neutral",
};

// Days-until-expiry chip. Returns null when there's no effective_to.
const _PpExpiryChip = ({ effective_to }) => {
  if (!effective_to) return null;
  const ms = Date.parse(effective_to) - Date.now();
  if (!Number.isFinite(ms)) return null;
  const days = Math.round(ms / 86400000);
  if (days < 0) return <Chip size="sm" tone="danger">Expired {Math.abs(days)}d ago</Chip>;
  if (days <= 30) return <Chip size="sm" tone="update">in {days}d</Chip>;
  return <Chip size="sm" tone="data">in {days}d</Chip>;
};


// ════════════════════════════════════════════════════════════════
// My DSA — read-only view of the partner's active agreement(s)
// ════════════════════════════════════════════════════════════════

const MyDsaScreen = () => {
  // page_size=50 is plenty — a single partner rarely has > a handful
  // of DSAs even counting renewals.
  const [resp, meta] = useApi("/api/v1/dsas/?page_size=50&ordering=-effective_from");
  const dsas = (resp && (resp.results || resp)) || [];
  // The "main" DSA the partner is operating under = first active.
  // Drafts + expired + renewed siblings render in a secondary panel.
  const primary = dsas.find(d => d.status === "active") || dsas[0] || null;

  if (meta.loading && !primary) {
    return (
      <div className="page">
        <PageHeader eyebrow="PARTNER PORTAL · MY DSA" title="Loading…"/>
      </div>
    );
  }
  if (!primary) {
    return (
      <div className="page">
        <PageHeader eyebrow="PARTNER PORTAL · MY DSA" title="No DSA on file"
          sub="Your organisation does not currently have a Data Sharing Agreement bound to your account."/>
        <div className="card" style={{padding: 20}}>
          <p className="t-bodysm" style={{marginTop: 0}}>
            DSAs are issued by the NSR Unit after the sign-off chain
            (partner signer → NSR Unit Lead → DPO). If you believe
            this is in error, contact your data steward.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow={<>PARTNER PORTAL · MY DSA · <span className="t-mono">{primary.reference}</span></>}
        title={<>{primary.partner_name || primary.partner_code}</>}
        sub={<>
          v{primary.version} · <Chip size="sm" tone={_PP_STATUS_TONE[primary.status] || "neutral"}>{primary.status_label || primary.status}</Chip>
          {primary.effective_from && primary.effective_to && (
            <> · {_ppFmtDate(primary.effective_from)} → {_ppFmtDate(primary.effective_to)} <_PpExpiryChip effective_to={primary.effective_to}/></>
          )}
        </>}
        right={<>
          <span className="t-cap muted">Read-only · edits route through the NSR Unit</span>
        </>}
      />

      <div className="grid grid-2" style={{gap: 16, gridTemplateColumns: "1fr 360px"}}>
        {/* Scope card */}
        <div className="col gap-3">
          <div className="card">
            <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>Scope</h3></div>
            <div style={{padding: 16}}>
              <div className="t-cap muted" style={{marginBottom: 6}}>ENTITIES</div>
              <div className="row gap-2" style={{flexWrap: "wrap", marginBottom: 14}}>
                {Object.entries(primary.entities_scope || {})
                  .filter(([, v]) => v)
                  .map(([k]) => <Chip key={k} size="sm" tone="data">{k}</Chip>)}
                {Object.values(primary.entities_scope || {}).filter(Boolean).length === 0 && (
                  <span className="t-bodysm muted">— none —</span>
                )}
              </div>

              <div className="t-cap muted" style={{marginBottom: 6}}>FIELD GROUPS</div>
              <div className="row gap-2" style={{flexWrap: "wrap", marginBottom: 14}}>
                {Object.entries(primary.field_scope || {})
                  .filter(([, v]) => v)
                  .map(([k]) => <Chip key={k} size="sm" tone="programme">{k}</Chip>)}
                {Object.values(primary.field_scope || {}).filter(Boolean).length === 0 && (
                  <span className="t-bodysm muted">— none —</span>
                )}
              </div>

              <div className="t-cap muted" style={{marginBottom: 6}}>GEOGRAPHIC SCOPE</div>
              <div className="row gap-2" style={{flexWrap: "wrap"}}>
                {(primary.geographic_scope || []).length === 0
                  ? <span className="t-bodysm muted">National (no geographic restriction)</span>
                  : (primary.geographic_scope || []).map(g => (
                      <Chip key={g} size="sm" tone="neutral">{g}</Chip>
                    ))}
              </div>
            </div>
          </div>

          {/* Limits + sensitivity */}
          <div className="card">
            <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>Limits, sensitivity, retention</h3></div>
            <div style={{padding: 16, display: "grid", gridTemplateColumns: "180px 1fr", rowGap: 8, fontSize: 13}}>
              <div className="muted">Monthly row budget</div>
              <div className="t-mono">{primary.monthly_row_budget != null
                ? `${Number(primary.monthly_row_budget).toLocaleString()} rows / month`
                : <span className="muted">unbounded</span>}</div>
              <div className="muted">Sensitive data handling</div>
              <div>{primary.sensitive_data_handling_label || primary.sensitive_data_handling || "—"}</div>
              <div className="muted">Retention</div>
              <div>{primary.retention_days != null ? `${primary.retention_days} days post-project-close` : "—"}</div>
              <div className="muted">Breach SLA</div>
              <div>{primary.breach_sla_hours != null ? `${primary.breach_sla_hours} hours from detection` : "—"}</div>
              <div className="muted">Classification</div>
              <div>{primary.classification || <span className="muted">—</span>}</div>
              <div className="muted">DPIA reference</div>
              <div className="t-mono">{primary.dpia_document_ref || <span className="muted">—</span>}</div>
            </div>
          </div>

          {/* Sign-off chain */}
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Sign-off chain</h3>
              <span className="t-cap">
                {(primary.signatures || []).filter(s => s.status === "signed").length}/{(primary.signatures || []).length} signatures recorded
              </span>
            </div>
            <div style={{padding: 16}}>
              {(primary.signatures || []).length === 0 ? (
                <div className="t-bodysm muted">No signatures dispatched yet.</div>
              ) : (
                <div className="col gap-2">
                  {(primary.signatures || [])
                    .slice()
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
                            {s.signed_at && <> · signed {_ppFmtDate(s.signed_at)}</>}
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

        {/* Right rail — versions + metadata */}
        <div className="col gap-3">
          <div className="card">
            <div className="card-header">
              <h3 className="t-h3" style={{margin: 0}}>Other versions</h3>
              <span className="t-cap">{Math.max(0, dsas.length - 1)} on file</span>
            </div>
            <div>
              {dsas.filter(d => d.id !== primary.id).map(d => (
                <div key={d.id} style={{padding: "10px 14px", borderBottom: "1px solid var(--neutral-100)"}}>
                  <div className="row gap-2">
                    <strong>v{d.version}</strong>
                    <Chip size="sm" tone={_PP_STATUS_TONE[d.status] || "neutral"}>{d.status_label || d.status}</Chip>
                  </div>
                  <div className="t-cap muted" style={{marginTop: 2}}>
                    {_ppFmtDate(d.effective_from)} → {_ppFmtDate(d.effective_to)}
                  </div>
                </div>
              ))}
              {dsas.length <= 1 && (
                <div className="t-bodysm muted" style={{padding: "20px 14px"}}>
                  This is the only version on record.
                </div>
              )}
            </div>
          </div>

          <div className="card" style={{padding: 14}}>
            <div className="t-cap muted">METADATA</div>
            <div style={{display: "grid", gridTemplateColumns: "100px 1fr", rowGap: 4, fontSize: 12, marginTop: 6}}>
              <div className="muted">DSA ID</div>
              <div className="t-mono" style={{wordBreak: "break-all"}}>{primary.id}</div>
              <div className="muted">Created</div>
              <div>{_ppFmtDate(primary.created_at)}</div>
              <div className="muted">Updated</div>
              <div>{_ppFmtDate(primary.updated_at)}</div>
              <div className="muted">Signed</div>
              <div>{_ppFmtDate(primary.signed_at)}</div>
            </div>
          </div>

          <div className="card" style={{padding: 14, background: "var(--neutral-50)"}}>
            <div className="t-cap" style={{fontWeight: 600, color: "var(--neutral-700)", marginBottom: 6}}>
              <Icon name="info" size={11}/> ABOUT THIS PAGE
            </div>
            <div className="t-bodysm" style={{color: "var(--neutral-700)", lineHeight: 1.5}}>
              The DSA defines what you can request from the registry —
              entities, field groups, geography, monthly row budget,
              and retention rules. Scope changes route through the NSR
              Unit; contact your data steward to start an edit or
              renewal. Every read is recorded in the audit chain.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};


// ════════════════════════════════════════════════════════════════
// My Programmes — read-only programmes register for the partner
// ════════════════════════════════════════════════════════════════

const MyProgrammesScreen = () => {
  const [resp, meta] = useApi("/api/v1/programmes/?page_size=100&ordering=-created_at");
  const programmes = (resp && (resp.results || resp)) || [];

  return (
    <div className="page">
      <PageHeader
        eyebrow="PARTNER PORTAL · MY PROGRAMMES"
        title={<>My programmes <Chip>{programmes.length}</Chip></>}
        sub="Programmes your organisation runs against the registry. New programmes are registered by the NSR Unit; this list is read-only."
        right={<>
          <span className="t-cap muted">Read-only · ABAC scoped to your partner</span>
        </>}
      />

      <div className="card">
        {programmes.length === 0 && !meta.loading && (
          <div style={{padding: "40px 20px", textAlign: "center"}}>
            <Icon name="book" size={32} color="var(--neutral-300)"/>
            <div style={{marginTop: 8, fontWeight: 500}}>No programmes registered yet.</div>
            <div className="t-bodysm muted" style={{marginTop: 4}}>
              Programmes are linked to your DSA and registered by the
              NSR Unit. Once added, they'll appear here.
            </div>
          </div>
        )}

        {meta.loading && programmes.length === 0 && (
          <div style={{padding: 20}} className="t-bodysm muted">Loading…</div>
        )}

        {programmes.length > 0 && (
          <table className="table" style={{width: "100%", borderCollapse: "collapse"}}>
            <thead>
              <tr style={{borderBottom: "1px solid var(--neutral-200)", textAlign: "left"}}>
                <th style={{padding: "10px 16px"}} className="t-cap">Code</th>
                <th style={{padding: "10px 16px"}} className="t-cap">Name</th>
                <th style={{padding: "10px 16px"}} className="t-cap">Kind</th>
                <th style={{padding: "10px 16px"}} className="t-cap">Status</th>
                <th style={{padding: "10px 16px"}} className="t-cap">DSA</th>
                <th style={{padding: "10px 16px"}} className="t-cap">Cohort target</th>
                <th style={{padding: "10px 16px"}} className="t-cap">Created</th>
              </tr>
            </thead>
            <tbody>
              {programmes.map(p => (
                <tr key={p.id} style={{borderBottom: "1px solid var(--neutral-100)"}}>
                  <td style={{padding: "10px 16px"}} className="t-mono">{p.code || "—"}</td>
                  <td style={{padding: "10px 16px", fontWeight: 500}}>{p.name}</td>
                  <td style={{padding: "10px 16px"}} className="t-cap">{p.kind_label || p.kind || "—"}</td>
                  <td style={{padding: "10px 16px"}}>
                    <Chip size="sm" tone={p.status === "active" ? "eligibility"
                                        : p.status === "draft" ? "neutral"
                                        : p.status === "closed" ? "neutral" : "update"}>
                      {p.status_label || p.status}
                    </Chip>
                  </td>
                  <td style={{padding: "10px 16px"}} className="t-mono">{p.dsa_reference || "—"}</td>
                  <td style={{padding: "10px 16px", textAlign: "right"}} className="t-mono">
                    {p.cohort_target != null ? Number(p.cohort_target).toLocaleString() : "—"}
                  </td>
                  <td style={{padding: "10px 16px"}} className="t-cap">{_ppFmtDate(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="t-cap muted" style={{marginTop: 14, padding: "0 4px"}}>
        Want to add a programme? Contact your NSR Unit liaison — the
        programme registration wizard lives on the operator side and
        requires linkage to your current DSA.
      </div>
    </div>
  );
};


Object.assign(window, {
  MyDsaScreen,
  MyProgrammesScreen,
});
