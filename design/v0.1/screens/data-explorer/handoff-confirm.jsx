/* global React, Icon, Chip, PageHeader, Toast, DataExplorerPrivacyChip, useDataExplorerCatalogue */
// NSR MIS — Data Explorer · Handoff confirm (US-DATA-EXP-001)
// =========================================================
// Pre-handoff hint + deep-link to API-DRS. The user lands here from
// the aggregate-builder's "Request record-level data" CTA (or the
// geographic-floor 422 path). On submit, this screen POSTs to
// /api/v1/data-explorer/handoff which seeds a DataRequest draft in
// API-DRS and redirects to /data-requests/{id}.
//
// Architecture: ADR-0023 §D1 (DataRequestDraft payload shape),
// §D4 (geographic floor + handoff propagation), §D3 (audit-chain
// note for DPO visibility).

const { useState: useStateDXH, useEffect: useEffectDXH } = React;

const DXH_I18N = {
  "data_explorer.handoff.eyebrow": "DATA EXPLORER · HANDOFF",
  "data_explorer.handoff.title": "Request record-level data",
  "data_explorer.handoff.sub":
    "We will seed a draft in Data Requests with your aggregate query attached. The DPO sees the full session when they review it.",
  "data_explorer.handoff.back": "Back",
  "data_explorer.handoff.summary.title": "What you're requesting",
  "data_explorer.handoff.summary.dataset": "Dataset",
  "data_explorer.handoff.summary.projection": "Projection variables",
  "data_explorer.handoff.summary.filters": "Filters",
  "data_explorer.handoff.summary.filters_empty": "(no filters — full cohort)",
  "data_explorer.handoff.summary.scope": "Geographic scope",
  "data_explorer.handoff.summary.estimated_rows": "Estimated row count",
  "data_explorer.handoff.summary.estimated_rows_hint":
    "From the last suppressed aggregate. The actual delivery row count is computed by API-DRS.",
  "data_explorer.handoff.privacy.title": "Privacy class summary",
  "data_explorer.handoff.privacy.sub":
    "The DSA review path is determined by the strictest class in the requested fields.",
  "data_explorer.handoff.privacy.review_path_label": "Review path",
  "data_explorer.handoff.privacy.review_path_dpo": "DPO review (single approver)",
  "data_explorer.handoff.privacy.review_path_dpo_dual": "DPO + Director (dual approver)",
  "data_explorer.handoff.privacy.review_path_blocked":
    "Sensitive — not deliverable. Contact your DPO before re-submitting.",
  "data_explorer.handoff.purpose.label": "Purpose of use",
  "data_explorer.handoff.purpose.placeholder":
    "Describe how the records will be used. Minimum 30 characters — this is the only narrative the DPO sees.",
  "data_explorer.handoff.purpose.help":
    "Required. The DPO uses this to decide which DSA clause applies.",
  "data_explorer.handoff.purpose.error_short":
    "Add a few more words — the DPO needs at least 30 characters.",
  "data_explorer.handoff.audit_note":
    "Your explorer session and the originating aggregate query will be visible to the DPO when they review this request.",
  "data_explorer.handoff.submit": "Submit handoff",
  "data_explorer.handoff.submitting": "Submitting…",
  "data_explorer.handoff.toast.success":
    "Draft created. Opening the DRS draft…",
  "data_explorer.handoff.toast.error":
    "Handoff failed: {detail}",
};
const th = (key, vars = {}) => {
  let s = DXH_I18N[key] || key;
  for (const [k, v] of Object.entries(vars)) {
    s = s.replaceAll(`{${k}}`, String(v));
  }
  return s;
};

const _csrfHandoff = () => {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

const PURPOSE_MIN_LEN = 30;

/* ============================================================
   HandoffConfirmScreen — primary export
   ============================================================ */
const HandoffConfirmScreen = ({
  aggregateContext,
  onBack,
  onRedirect,
} = {}) => {
  const { privacyClasses } = useDataExplorerCatalogue();

  const [purpose, setPurpose] = useStateDXH("");
  const [submitting, setSubmitting] = useStateDXH(false);
  const [toast, setToast] = useStateDXH("");

  // aggregateContext shape (built by aggregate-builder + carried via
  // router state):
  //   {
  //     dataset_id, dataset_title,
  //     projection_variables: [code, …],
  //     filters: [{variable_label, op, value}, …],
  //     geographic_scope: {level, codes: [...], requested_below_floor},
  //     estimated_row_count, estimated_rows_suppressed,
  //     privacy_classes_spanned: ["Internal", "Personal"],
  //   }
  const ctx = aggregateContext || {};

  const purposeValid = purpose.trim().length >= PURPOSE_MIN_LEN;
  const canSubmit = purposeValid && !submitting && ctx.dataset_id;

  // Compute the review path from the spanned classes.
  const reviewPath = (() => {
    const spans = ctx.privacy_classes_spanned || [];
    if (spans.includes("Sensitive")) {
      return {
        label: th("data_explorer.handoff.privacy.review_path_blocked"),
        tone: "danger",
        blocked: true,
      };
    }
    if (spans.includes("Personal")) {
      return {
        label: th("data_explorer.handoff.privacy.review_path_dpo_dual"),
        tone: "quality",
        blocked: false,
      };
    }
    return {
      label: th("data_explorer.handoff.privacy.review_path_dpo"),
      tone: "update",
      blocked: false,
    };
  })();

  const submit = () => {
    if (!canSubmit) return;
    setSubmitting(true);

    const payload = {
      dataset_id: ctx.dataset_id,
      projection_variables: ctx.projection_variables || [],
      filters: ctx.filters || [],
      geographic_scope: ctx.geographic_scope || { level: "sub_county" },
      estimated_row_count: ctx.estimated_row_count || 0,
      purpose_of_use: purpose.trim(),
    };

    fetch("/api/v1/data-explorer/handoff", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": _csrfHandoff(),
      },
      body: JSON.stringify(payload),
    })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw body;
        return body;
      })
      .then((body) => {
        setToast(th("data_explorer.handoff.toast.success"));
        // Slight delay so the toast is seen before the redirect.
        setTimeout(() => {
          if (body.redirect) {
            if (onRedirect) onRedirect(body.redirect, body.data_request_id);
            else if (typeof window !== "undefined") window.location.assign(body.redirect);
          } else if (body.data_request_id && onRedirect) {
            onRedirect(`/data-requests/${body.data_request_id}`, body.data_request_id);
          }
        }, 400);
      })
      .catch((e) => {
        setToast(th("data_explorer.handoff.toast.error", {
          detail: e?.detail || e?.error || "unknown error",
        }));
      })
      .finally(() => setSubmitting(false));
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow={th("data_explorer.handoff.eyebrow")}
        title={th("data_explorer.handoff.title")}
        sub={th("data_explorer.handoff.sub")}
        right={onBack && (
          <button type="button" className="btn" onClick={onBack}>
            <Icon name="chevronLeft" size={14}/>
            {th("data_explorer.handoff.back")}
          </button>
        )}
      />

      <div className="grid" style={{ gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
        {/* Summary card */}
        <section
          className="card"
          style={{ padding: 20 }}
          aria-labelledby="dxh-summary-title"
        >
          <h3
            id="dxh-summary-title"
            className="t-h3"
            style={{ margin: "0 0 14px" }}
          >
            {th("data_explorer.handoff.summary.title")}
          </h3>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "200px 1fr",
              rowGap: 12, columnGap: 16, margin: 0,
            }}
          >
            <dt className="t-cap" style={{ fontWeight: 600 }}>
              {th("data_explorer.handoff.summary.dataset")}
            </dt>
            <dd style={{ margin: 0 }}>
              <span className="t-bodysm" style={{ fontWeight: 500 }}>
                {ctx.dataset_title || "—"}
              </span>
            </dd>

            <dt className="t-cap" style={{ fontWeight: 600 }}>
              {th("data_explorer.handoff.summary.projection")}
            </dt>
            <dd style={{ margin: 0 }}>
              {(ctx.projection_variables || []).length > 0 ? (
                <div className="row gap-1" style={{ flexWrap: "wrap" }}>
                  {(ctx.projection_variables || []).map((p) => (
                    <span
                      key={p}
                      className="chip chip-sm"
                      style={{
                        background: "var(--accent-system-bg)",
                        color: "var(--accent-system)",
                        border: "1px solid var(--accent-system)",
                      }}
                    >
                      <span className="t-mono">{p}</span>
                    </span>
                  ))}
                </div>
              ) : (
                <span className="t-cap muted">—</span>
              )}
            </dd>

            <dt className="t-cap" style={{ fontWeight: 600 }}>
              {th("data_explorer.handoff.summary.filters")}
            </dt>
            <dd style={{ margin: 0 }}>
              {(ctx.filters || []).length > 0 ? (
                <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                  {(ctx.filters || []).map((f, i) => (
                    <li key={i} className="t-bodysm" style={{ padding: "2px 0" }}>
                      <strong>{f.variable_label || f.variable_code}</strong>{" "}
                      <span style={{ color: "var(--neutral-600)" }}>{f.op}</span>{" "}
                      <span className="t-mono">{String(f.value)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="t-cap muted">
                  {th("data_explorer.handoff.summary.filters_empty")}
                </span>
              )}
            </dd>

            <dt className="t-cap" style={{ fontWeight: 600 }}>
              {th("data_explorer.handoff.summary.scope")}
            </dt>
            <dd style={{ margin: 0 }}>
              <span className="t-bodysm">
                <strong>{ctx.geographic_scope?.level || "—"}</strong>
                {ctx.geographic_scope?.requested_below_floor && (
                  <Chip size="sm" tone="quality" style={{ marginLeft: 8 }}>
                    <Icon name="alert" size={11}/> below sub-county floor
                  </Chip>
                )}
              </span>
              {(ctx.geographic_scope?.codes || []).length > 0 && (
                <div className="row gap-1 mt-1" style={{ flexWrap: "wrap" }}>
                  {(ctx.geographic_scope.codes || []).slice(0, 8).map((c) => (
                    <span key={c} className="chip chip-sm chip-neutral">
                      <span className="t-mono">{c}</span>
                    </span>
                  ))}
                  {(ctx.geographic_scope.codes || []).length > 8 && (
                    <span className="t-cap muted">
                      + {(ctx.geographic_scope.codes || []).length - 8} more
                    </span>
                  )}
                </div>
              )}
            </dd>

            <dt className="t-cap" style={{ fontWeight: 600 }}>
              {th("data_explorer.handoff.summary.estimated_rows")}
            </dt>
            <dd style={{ margin: 0 }}>
              <span className="t-num" style={{ fontSize: 18, fontWeight: 600 }}>
                {ctx.estimated_row_count != null
                  ? Number(ctx.estimated_row_count).toLocaleString()
                  : "—"}
              </span>
              <div className="t-cap mt-1" style={{ color: "var(--neutral-600)" }}>
                {th("data_explorer.handoff.summary.estimated_rows_hint")}
              </div>
            </dd>
          </dl>
        </section>

        {/* Privacy + purpose */}
        <div className="col gap-3" style={{ minWidth: 0 }}>
          <section
            className="card"
            style={{ padding: 18 }}
            aria-labelledby="dxh-privacy-title"
          >
            <h3
              id="dxh-privacy-title"
              className="t-h3"
              style={{ margin: "0 0 4px", fontSize: 15 }}
            >
              {th("data_explorer.handoff.privacy.title")}
            </h3>
            <p
              className="t-cap"
              style={{ margin: "0 0 12px", color: "var(--neutral-600)" }}
            >
              {th("data_explorer.handoff.privacy.sub")}
            </p>
            <div className="row gap-1" style={{ flexWrap: "wrap", marginBottom: 12 }}>
              {(ctx.privacy_classes_spanned || []).map((code) =>
                window.DataExplorerPrivacyChip ? (
                  <window.DataExplorerPrivacyChip
                    key={code}
                    classCode={code}
                    classes={privacyClasses}
                    size="sm"
                  />
                ) : null,
              )}
            </div>
            <div
              className="t-cap"
              style={{ fontWeight: 600, marginBottom: 4 }}
            >
              {th("data_explorer.handoff.privacy.review_path_label")}
            </div>
            <Chip size="sm" tone={reviewPath.tone}>
              {reviewPath.blocked && <Icon name="lock" size={11}/>}
              {reviewPath.label}
            </Chip>
          </section>

          <section
            className="card"
            style={{ padding: 18 }}
            aria-labelledby="dxh-purpose-title"
          >
            <label htmlFor="dxh-purpose" className="field-label">
              <span id="dxh-purpose-title">
                {th("data_explorer.handoff.purpose.label")}
              </span>{" "}
              <span className="req">*</span>
            </label>
            <textarea
              id="dxh-purpose"
              className="field-textarea"
              rows={5}
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder={th("data_explorer.handoff.purpose.placeholder")}
              aria-describedby="dxh-purpose-help"
              aria-required="true"
              aria-invalid={purpose.length > 0 && !purposeValid}
            />
            <div
              id="dxh-purpose-help"
              className="field-help"
              style={{ marginTop: 4 }}
            >
              {th("data_explorer.handoff.purpose.help")}{" "}
              <span
                className="t-cap"
                style={{ color: purposeValid ? "var(--accent-data)" : "var(--neutral-500)" }}
              >
                {purpose.trim().length}/{PURPOSE_MIN_LEN}
              </span>
            </div>
            {purpose.length > 0 && !purposeValid && (
              <span className="field-error" role="alert">
                {th("data_explorer.handoff.purpose.error_short")}
              </span>
            )}
          </section>

          <button
            type="button"
            className="btn btn-primary"
            disabled={!canSubmit}
            aria-disabled={!canSubmit}
            onClick={submit}
          >
            <Icon name="arrowRight" size={14}/>
            {submitting
              ? th("data_explorer.handoff.submitting")
              : th("data_explorer.handoff.submit")}
          </button>

          <div
            className="t-cap"
            style={{
              padding: 12,
              background: "var(--neutral-50, #f7f8fa)",
              borderRadius: 4,
              borderLeft: "3px solid var(--accent-system)",
              color: "var(--neutral-700)",
            }}
          >
            <Icon name="shield" size={12}/>{" "}
            {th("data_explorer.handoff.audit_note")}
          </div>
        </div>
      </div>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

Object.assign(window, {
  HandoffConfirmScreen,
  DXH_I18N,
});
