/* global React, Icon, Chip, PageHeader, KPI, useApi, nsrApi */
// NSR MIS — Admin · Approvals dashboard
// ===========================================================
// Unified queue of items awaiting a second signature across the
// admin console: choice lists, DQA rules, PMT model versions.
// Sign / reject inline for the two-step modules (CL, DQA); PMT
// rows deep-link to the configuration screen because PMT uses a
// three-step sign-off (MGLSD steward → UBOS DG → author confirm).
//
// Maps to:
//   GET  /api/v1/admin/approvals/
//   POST /api/v1/admin/refdata/choice-lists/<n>/versions/<v>/sign|reject/
//   POST /api/v1/admin/workflow/dqa/rules/<id>/v<v>/sign|reject/
//   POST /api/v1/admin/pmt/versions/<id>/sign/<step>/   (PMT screen)

const { useState: useStateAP, useMemo: useMemoAP, useCallback: useCallbackAP } = React;

const KIND_TONE = {
  choice_list: "data",
  dqa_rule: "quality",
  pmt_model: "identity",
};

const KIND_ICON = {
  choice_list: "database",
  dqa_rule: "shield",
  pmt_model: "sliders",
};

const AdminApprovalsScreen = ({ onNavigate } = {}) => {
  // useApi gives us [data, {loading, error, refresh}].
  const [resp, meta] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/approvals/")
    : [null, { loading: false, error: null, refresh: () => {} }];

  const [kindFilter, setKindFilter] = useStateAP("");
  const [q, setQ] = useStateAP("");
  // Inline modal: { mode: 'sign'|'reject', row, approver, note/reason }.
  const [modal, setModal] = useStateAP(null);
  const [busy, setBusy] = useStateAP(false);

  const apiAvailable = typeof nsrApi !== "undefined" && nsrApi && typeof nsrApi.post === "function";

  const allRows = useMemoAP(() => (resp && resp.results) || [], [resp]);
  const counts = useMemoAP(() => (resp && resp.by_kind) || {}, [resp]);

  const rows = useMemoAP(() => allRows.filter(r => {
    if (kindFilter && r.kind !== kindFilter) return false;
    if (q) {
      const needle = q.toLowerCase();
      if (!r.name.toLowerCase().includes(needle) && !(r.label || "").toLowerCase().includes(needle)) return false;
    }
    return true;
  }), [allRows, kindFilter, q]);

  const refresh = useCallbackAP(() => meta && meta.refresh && meta.refresh(), [meta]);

  const openSign = (row) => setModal({ mode: "sign", row, approver: "", note: "" });
  const openReject = (row) => setModal({ mode: "reject", row, approver: "", reason: "" });
  const closeModal = () => { if (!busy) setModal(null); };

  const submitDecision = async () => {
    if (!modal || !apiAvailable || busy) return;
    const { mode, row } = modal;
    const url = mode === "sign" ? row.links.sign : row.links.reject;
    if (!url) return;
    if (!modal.approver.trim()) {
      // eslint-disable-next-line no-alert
      alert("Approver name is required.");
      return;
    }
    if (mode === "reject" && !modal.reason.trim()) {
      // eslint-disable-next-line no-alert
      alert("Rejection reason is required.");
      return;
    }
    const body = mode === "sign"
      ? { approver: modal.approver.trim(), note: modal.note }
      : { approver: modal.approver.trim(), reason: modal.reason };
    setBusy(true);
    try {
      await nsrApi.post(url, body);
      setModal(null);
      refresh();
    } catch (err) {
      // eslint-disable-next-line no-alert
      alert(`Could not ${mode}: ${err.body && err.body.detail ? err.body.detail : err.message || err}`);
    } finally {
      setBusy(false);
    }
  };

  const goToDetail = (row) => {
    if (typeof onNavigate === "function" && row.detail_screen) {
      onNavigate(row.detail_screen);
    }
  };

  const total = (resp && resp.count) || 0;

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · APPROVALS"
        title="Approvals dashboard"
        sub="Every item currently awaiting a second signature across reference data, DQA rules, and PMT models. Sign or reject inline; the registry's no-self-approve rule is enforced on the server."
        right={<>
          <button className="btn" onClick={refresh} disabled={meta && meta.loading}>
            <Icon name="refresh" size={14}/> {meta && meta.loading ? "Refreshing…" : "Refresh"}
          </button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Pending total" value={total} foot="Across all admin modules"/>
        <KPI title="Choice lists" value={counts.choice_list || 0} foot="Reference data drafts awaiting sign-off"/>
        <KPI title="DQA rules"    value={counts.dqa_rule || 0}    foot="Data-quality rules awaiting approval"/>
        <KPI title="PMT models"   value={counts.pmt_model || 0}   foot="Three-step sign-off in PMT Configuration"/>
      </div>

      <div className="card mt-5" style={{ padding: '14px 16px' }}>
        <div className="row gap-3" style={{ flexWrap: 'wrap' }}>
          <div className="search" style={{ maxWidth: 380, height: 34, background: 'var(--neutral-0)' }}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name or label…"/>
          </div>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 180 }}
                  value={kindFilter} onChange={e => setKindFilter(e.target.value)}>
            <option value="">All kinds</option>
            <option value="choice_list">Choice lists</option>
            <option value="dqa_rule">DQA rules</option>
            <option value="pmt_model">PMT model versions</option>
          </select>
          <div style={{ flex: 1 }}/>
          <span className="t-cap">{rows.length} of {total} pending</span>
        </div>
      </div>

      <div className="card mt-4">
        {meta && meta.error && (
          <div className="tint-danger" style={{ padding: '10px 16px', borderLeft: '3px solid var(--accent-danger)' }}>
            <Icon name="alert" size={13} color="var(--accent-danger)"/>
            <span className="t-bodysm" style={{ marginLeft: 8 }}>Could not load the approvals queue: {meta.error}</span>
          </div>
        )}
        <table className="tbl">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Name · summary</th>
              <th>Version</th>
              <th>Author</th>
              <th>Submitted</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const isPmt = r.kind === "pmt_model";
              return (
                <tr key={`${r.kind}:${r.id}`}>
                  <td>
                    <Chip size="sm" tone={KIND_TONE[r.kind] || "neutral"}>
                      <Icon name={KIND_ICON[r.kind] || "file"} size={10}/> {r.kind_label}
                    </Chip>
                  </td>
                  <td>
                    <div className="t-mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{r.name}</div>
                    <div className="t-cap" style={{ maxWidth: 480, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.label}
                    </div>
                  </td>
                  <td><Chip size="sm">v{r.version}</Chip></td>
                  <td className="t-bodysm">{r.author || <span className="muted">—</span>}</td>
                  <td className="t-cap" style={{ whiteSpace: 'nowrap' }}>
                    {r.submitted_at ? r.submitted_at.slice(0, 16).replace("T", " ") : <span className="muted">—</span>}
                  </td>
                  <td className="col-actions">
                    {isPmt
                      ? <button className="btn btn-sm" onClick={() => goToDetail(r)}>
                          <Icon name="arrowRight" size={12}/> Open in PMT config
                        </button>
                      : <>
                          <button className="btn btn-sm" onClick={() => goToDetail(r)} title="Open the module screen for full context">
                            <Icon name="eye" size={12}/> View
                          </button>
                          <button className="btn btn-sm" onClick={() => openReject(r)} disabled={!apiAvailable}>
                            <Icon name="x" size={12}/> Reject
                          </button>
                          <button className="btn btn-sm btn-primary" onClick={() => openSign(r)} disabled={!apiAvailable}>
                            <Icon name="check" size={12}/> Sign
                          </button>
                        </>}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && !(meta && meta.loading) && (
              <tr><td colSpan={6} className="t-cap muted" style={{ padding: 24, textAlign: 'center' }}>
                {total === 0 ? "Nothing is awaiting approval." : "No items match this filter."}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Sign/Reject modal — lightweight inline overlay */}
      {modal && (
        <div onClick={closeModal} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
          display: 'grid', placeItems: 'center', zIndex: 100,
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            background: 'var(--neutral-0)', borderRadius: 8, minWidth: 480, maxWidth: 560,
            boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
          }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--neutral-200)' }}>
              <div className="t-cap">{modal.row.kind_label.toUpperCase()} · v{modal.row.version}</div>
              <h3 style={{ margin: '4px 0 0', fontSize: 18 }}>
                {modal.mode === "sign" ? "Sign off" : "Reject"} <span className="t-mono">{modal.row.name}</span>
              </h3>
            </div>
            <div style={{ padding: 20, display: 'grid', gap: 12 }}>
              <div className="t-bodysm muted">
                {modal.mode === "sign"
                  ? "Activates this version and atomically retires the prior active one. The server enforces the no-self-approve rule — you cannot sign your own draft."
                  : "Sends the item back to DRAFT. The reason is recorded on the audit chain."}
              </div>
              <label className="t-cap">Approver (your username or email)</label>
              <input className="field-input" autoFocus
                     value={modal.approver}
                     onChange={e => setModal({ ...modal, approver: e.target.value })}/>
              {modal.mode === "sign" ? <>
                <label className="t-cap">Approval note (optional)</label>
                <textarea className="field-textarea" rows={3}
                          value={modal.note}
                          onChange={e => setModal({ ...modal, note: e.target.value })}/>
              </> : <>
                <label className="t-cap">Rejection reason (required)</label>
                <textarea className="field-textarea" rows={3}
                          value={modal.reason}
                          onChange={e => setModal({ ...modal, reason: e.target.value })}/>
              </>}
            </div>
            <div style={{ padding: '14px 20px', borderTop: '1px solid var(--neutral-200)', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={closeModal} disabled={busy}>Cancel</button>
              <button className={`btn ${modal.mode === "sign" ? "btn-primary" : ""}`}
                      style={modal.mode === "reject" ? { background: 'var(--accent-danger)', color: 'var(--neutral-0)' } : null}
                      onClick={submitDecision} disabled={busy}>
                <Icon name={modal.mode === "sign" ? "check" : "x"} size={12}/>
                {busy ? "Working…" : (modal.mode === "sign" ? "Sign and activate" : "Reject")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

Object.assign(window, { AdminApprovalsScreen });
