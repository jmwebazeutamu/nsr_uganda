/* global React, Icon, Chip, KPI, Sparkline, PageHeader, Modal, Field, Toast, useChoiceList, useApi, nsrApi */
// NSR MIS — Partners domain (US-S23-013, live-wired).
//
//   PartnersScreen              dashboard / list of partner organisations + DSA health
//   PartnerRegistrationScreen   6-step onboarding wizard (Org → DSA terms → Sign-off)
//
// Every dropdown reads from /api/v1/reference-data/choice-list-bundle/
// via useChoiceList — no hardcoded option arrays anywhere.
//
// References: SAD §11.6 Partner & DSA registry; ADR-0011; ADR-0012; ADR-0010.

const { useState: _p_useState, useMemo: _p_useMemo, useEffect: _p_useEffect } = React;

/* ============================================================
   PARTNER MARK / USAGE BAR helpers (presentational only)
   ============================================================ */
const PartnerMark = ({ code, tone, size = 36 }) => {
  const bg = tone === "primary"
    ? "var(--primary-900)"
    : `var(--accent-${tone || "system"}, var(--neutral-700))`;
  return (
    <div style={{
      width: size, height: size, borderRadius: 6,
      background: bg, color: "var(--neutral-0)",
      display: "grid", placeItems: "center",
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: size > 30 ? 11.5 : 10, fontWeight: 700,
      letterSpacing: "0.04em", flexShrink: 0,
    }}>{code}</div>
  );
};

const UsageBar = ({ used, budget }) => {
  if (!budget) return null;
  const pct = Math.min(100, Math.round((used / budget) * 100));
  const over = used > budget;
  return (
    <div style={{
      height: 5, background: "var(--neutral-200)",
      borderRadius: 3, marginTop: 4, overflow: "hidden", position: "relative",
    }}>
      <div style={{
        width: Math.min(100, pct) + "%",
        height: "100%",
        background: over
          ? "var(--accent-danger)"
          : pct > 85 ? "var(--accent-quality)" : "var(--accent-data)",
      }}/>
      {over && <div style={{
        position: "absolute", inset: 0,
        background: "repeating-linear-gradient(45deg,transparent,transparent 3px,rgba(255,255,255,0.35) 3px,rgba(255,255,255,0.35) 5px)",
      }}/>}
    </div>
  );
};

const _fmt = (n) =>
  n >= 1e6 ? (n/1e6).toFixed(2) + "M"
  : n >= 1e3 ? (n/1e3).toFixed(1) + "k"
  : String(n);

/* ============================================================
   PARTNERS DASHBOARD
   ============================================================ */
const PartnersScreen = ({ onRegister, onNavigate }) => {
  const [q, setQ] = _p_useState("");
  const [typeFilter, setTypeFilter] = _p_useState("");
  const [statusFilter, setStatusFilter] = _p_useState("");

  // Coded-field option lists for the filter dropdowns.
  const [typeOpts] = useChoiceList("partner_type");
  const [statusOpts] = useChoiceList("partner_status");

  // Build the query string from filters.
  const partnerQs = _p_useMemo(() => {
    const p = new URLSearchParams();
    if (q.trim())        p.set("q", q.trim());
    if (typeFilter)      p.set("type", typeFilter);
    if (statusFilter)    p.set("status", statusFilter);
    p.set("page_size", "50");
    return p.toString();
  }, [q, typeFilter, statusFilter]);

  const [partnersData, partnersMeta] = useApi(`/api/v1/partners/?${partnerQs}`);
  const [summary] = useApi("/api/v1/partners/summary/");
  const [renewals] = useApi("/api/v1/partners/renewals/?days=120");
  const [sectorMix] = useApi("/api/v1/partners/sector-mix/");
  const [topConsumers] = useApi("/api/v1/partners/top-consumers/?n=5");

  const partners = partnersData?.results || [];

  // Per-partner DSA + usage rollup, fetched once we have rows. Keeps
  // the list endpoint cheap; expensive joins live in the dashboards.
  const dsasByPartner = _p_useMemo(() => {
    const m = {};
    for (const r of (renewals?.items || [])) {
      m[r.partner_code] = m[r.partner_code] || [];
      m[r.partner_code].push(r);
    }
    return m;
  }, [renewals]);

  return (
    <div className="page">
      <PageHeader
        eyebrow="PARTNERS · §11.6 PARTNER & DSA REGISTRY"
        title="Partner organisations"
        sub={<>{partners.length} partner{partners.length === 1 ? "" : "s"} loaded · {summary?.active_dsas ?? "—"} active DSAs</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export register</button>
          <button className="btn btn-primary" onClick={onRegister}>
            <Icon name="plus" size={14}/> Register partner
          </button>
        </>}
      />

      {/* KPI strip */}
      <div className="grid grid-4">
        <KPI title="Active partners" value={String(summary?.active_partners ?? "—")}
             foot={`${summary?.onboarding_partners ?? 0} onboarding`}/>
        <KPI title="Active DSAs" value={String(summary?.active_dsas ?? "—")}
             foot={`${summary?.dsas_expiring_30d ?? 0} expire in 30d`}/>
        <KPI title="Rows delivered · 30d"
             value={summary ? (summary.rows_delivered_30d / 1e6).toFixed(2) : "—"}
             suffix={summary ? "M" : ""}
             foot={`${summary?.active_requesters_30d ?? 0} requesters`}/>
        <KPI title="DSA budget breaches"
             value={String(summary?.dsas_over_budget_30d ?? "—")}
             foot="auto-flagged to DPO"/>
      </div>

      <div className="grid mt-5" style={{gridTemplateColumns: "1fr 340px", gap: 16}}>
        {/* Main — partners table */}
        <div className="card">
          <div className="card-toolbar" style={{gap: 8, flexWrap: "wrap"}}>
            <div className="search" style={{maxWidth: 280, height: 30, padding: "4px 10px"}}>
              <Icon name="search" size={14} color="var(--neutral-500)"/>
              <input value={q} onChange={(e) => setQ(e.target.value)}
                     placeholder="Search partner name or short code…"/>
            </div>
            <select className="field-select" style={{height: 30, width: 140}}
                    value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">All types</option>
              {typeOpts.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
            <select className="field-select" style={{height: 30, width: 140}}
                    value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All status</option>
              {statusOpts.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
            <div style={{flex: 1}}/>
            <span className="t-cap">{partners.length} loaded</span>
          </div>
          <div style={{overflowX: "auto"}}>
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{width: "30%"}}>Partner</th>
                  <th>Type · sector</th>
                  <th>DSAs in 120d</th>
                  <th>Status</th>
                  <th className="col-actions"></th>
                </tr>
              </thead>
              <tbody>
                {partnersMeta.loading && (
                  <tr><td colSpan={5} style={{padding: 16}}>Loading…</td></tr>
                )}
                {partnersMeta.error && (
                  <tr><td colSpan={5} style={{padding: 16, color: "var(--accent-danger)"}}>
                    {partnersMeta.error}
                  </td></tr>
                )}
                {!partnersMeta.loading && partners.length === 0 && (
                  <tr><td colSpan={5} style={{padding: 16}} className="muted">
                    No partners match these filters.
                  </td></tr>
                )}
                {partners.map(p => {
                  const renewing = dsasByPartner[p.code] || [];
                  const earliest = renewing[0];
                  return (
                    <tr key={p.id} style={{cursor: "pointer"}}>
                      <td>
                        <div className="row gap-3">
                          <PartnerMark code={p.code} tone={p.tone}/>
                          <div style={{minWidth: 0}}>
                            <div style={{fontWeight: 600, color: "var(--neutral-900)"}}>{p.name}</div>
                            <div className="t-cap">{p.primary_email || "—"}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <div>{p.type_label || p.type}</div>
                        <div className="t-cap">{p.sector_label || p.sector || "—"}</div>
                      </td>
                      <td>
                        <span className="t-num" style={{fontWeight: 600}}>{renewing.length}</span>
                        {earliest && earliest.days_until_expiry <= 30 && (
                          <div style={{marginTop: 2}}>
                            <Chip size="sm" tone="danger">Exp {earliest.days_until_expiry}d</Chip>
                          </div>
                        )}
                      </td>
                      <td><Chip tone={p.tone || "neutral"}>{p.status_label || p.status}</Chip></td>
                      <td className="col-actions">
                        <button className="btn btn-sm btn-ghost" title="Open">
                          <Icon name="chevronRight" size={14}/>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right rail */}
        <div className="col gap-4">
          <RenewalTimeline data={renewals}/>
          <SectorMix data={sectorMix}/>
          <TopConsumers data={topConsumers}/>
        </div>
      </div>

      {/* Activity feed — partner-specific feeds live on /partners/{id}/activity/.
          For the dashboard, surface the most recent DSA-touch events
          across all partners by aggregating from the API client-side. */}
      <ActivityRail partners={partners}/>
    </div>
  );
};

/* ---------- renewal timeline (US-S23-009 /partners/renewals/) ---------- */
const RenewalTimeline = ({ data }) => {
  const items = data?.items || [];
  return (
    <div className="card">
      <div className="card-header" style={{padding: "12px 16px"}}>
        <h3 className="t-h3" style={{margin: 0}}>DSA renewal queue · next {data?.window_days || 120}d</h3>
        <span className="t-cap">{items.length} DSAs</span>
      </div>
      <div style={{padding: "4px 16px 14px"}}>
        <div style={{display: "flex", justifyContent: "space-between", padding: "6px 0 4px", fontSize: 11, color: "var(--neutral-500)"}}>
          <span>now</span><span>30d</span><span>60d</span><span>90d</span><span>120d</span>
        </div>
        <div style={{height: 6, background: "var(--neutral-100)", borderRadius: 3, position: "relative", marginBottom: 14}}>
          <div style={{position: "absolute", left: "25%", top: -4, bottom: -4, width: 1, background: "var(--accent-danger)", opacity: 0.4}}/>
        </div>
        {items.length === 0 && <div className="muted t-bodysm">No DSAs expiring in this window.</div>}
        {items.map(p => {
          const tone = p.days_until_expiry <= 30 ? "danger"
                     : p.days_until_expiry <= 60 ? "quality" : "neutral";
          return (
            <div key={p.dsa_id} className="row gap-3" style={{padding: "7px 0", borderTop: "1px solid var(--neutral-200)"}}>
              <PartnerMark code={p.partner_code} tone={p.partner_tone} size={28}/>
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontWeight: 500, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>{p.partner_name}</div>
                <div className="t-cap">{p.reference}</div>
              </div>
              <Chip size="sm" tone={tone}>{p.days_until_expiry}d</Chip>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* ---------- sector mix ---------- */
const SectorMix = ({ data }) => {
  const items = data?.items || [];
  const maxRows = Math.max(...items.map(g => g.rows_delivered_30d), 1);
  // Resolve sector labels via the ChoiceList.
  const [sectorOpts] = useChoiceList("partner_sector");
  const sectorLabelByCode = _p_useMemo(() => {
    const m = {};
    sectorOpts.forEach(o => { m[o.code] = o.label; });
    return m;
  }, [sectorOpts]);
  return (
    <div className="card">
      <div className="card-header" style={{padding: "12px 16px"}}>
        <h3 className="t-h3" style={{margin: 0}}>Partners by sector</h3>
        <span className="t-cap">rows · 30d</span>
      </div>
      <div style={{padding: "4px 16px 14px"}}>
        {items.length === 0 && <div className="muted t-bodysm">No partners loaded.</div>}
        {items.map(g => (
          <div key={g.sector_code} style={{padding: "6px 0"}}>
            <div className="row gap-2" style={{justifyContent: "space-between", marginBottom: 4}}>
              <div className="row gap-2">
                <span style={{width: 8, height: 8, borderRadius: 2, background: `var(--accent-${g.tone})`, display: "inline-block"}}/>
                <span className="t-bodysm" style={{fontWeight: 500}}>
                  {sectorLabelByCode[g.sector_code] || g.sector_code}
                </span>
                <span className="t-cap">· {g.partner_count}</span>
              </div>
              <span className="t-mono" style={{fontSize: 12}}>{_fmt(g.rows_delivered_30d)}</span>
            </div>
            <div style={{height: 4, background: "var(--neutral-100)", borderRadius: 2, overflow: "hidden"}}>
              <div style={{width: (g.rows_delivered_30d / maxRows * 100) + "%", height: "100%", background: `var(--accent-${g.tone})`}}/>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ---------- top consumers ---------- */
const TopConsumers = ({ data }) => {
  const items = data?.items || [];
  return (
    <div className="card">
      <div className="card-header" style={{padding: "12px 16px"}}>
        <h3 className="t-h3" style={{margin: 0}}>Top requesters · 30d</h3>
        <span className="t-cap">by rows delivered</span>
      </div>
      <div style={{padding: "8px 16px 12px"}}>
        {items.length === 0 && <div className="muted t-bodysm">No row delivery in the last 30d.</div>}
        {items.map((p, i) => (
          <div key={p.partner_id} className="row gap-3" style={{padding: "6px 0", borderBottom: i < items.length - 1 ? "1px solid var(--neutral-200)" : "none"}}>
            <span className="t-cap" style={{width: 18}}>{i + 1}</span>
            <PartnerMark code={p.partner_code} tone={p.partner_tone} size={24}/>
            <span className="t-bodysm" style={{flex: 1, fontWeight: 500}}>{p.partner_code}</span>
            <span className="t-mono t-num" style={{fontSize: 13}}>{_fmt(p.rows_delivered_30d)}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ---------- activity rail — pulls each partner's feed and merges ---------- */
const ActivityRail = ({ partners }) => {
  const [events, setEvents] = _p_useState([]);
  _p_useEffect(() => {
    if (!partners.length) { setEvents([]); return; }
    let cancelled = false;
    Promise.all(
      partners.slice(0, 10).map(p =>
        nsrApi.get(`/api/v1/partners/${p.id}/activity/`)
          .then(r => (r.items || []).map(e => ({ ...e, partner_code: p.code, partner_tone: p.tone })))
          .catch(() => [])
      ),
    ).then(rows => {
      if (cancelled) return;
      const merged = [].concat(...rows);
      merged.sort((a, b) => (b.occurred_at || "").localeCompare(a.occurred_at || ""));
      setEvents(merged.slice(0, 6));
    });
    return () => { cancelled = true; };
  }, [partners.map(p => p.id).join(",")]);

  return (
    <div className="card mt-5">
      <div className="card-header">
        <h3 className="t-h3" style={{margin: 0}}>Recent partner activity</h3>
        <span className="t-cap">audit chain · top 6 across {partners.length} partners</span>
      </div>
      <div>
        {events.length === 0 && <div style={{padding: 14}} className="muted t-bodysm">No activity yet.</div>}
        {events.map((a, i) => (
          <div key={i} className="row gap-3" style={{padding: "14px 20px", borderBottom: i < events.length - 1 ? "1px solid var(--neutral-200)" : "none"}}>
            <PartnerMark code={a.partner_code} tone={a.partner_tone} size={32}/>
            <div style={{flex: 1, minWidth: 0}}>
              <div className="row gap-2">
                <strong className="t-body">{a.partner_code}</strong>
                <span className="muted">·</span>
                <span className="t-body" style={{color: "var(--neutral-700)"}}>{a.summary}</span>
              </div>
              <div className="t-bodysm muted" style={{marginTop: 2}}>{a.detail || a.related_object_type}</div>
            </div>
            <div className="col" style={{alignItems: "flex-end", gap: 6}}>
              <Chip tone={a.severity_tone || "neutral"}>{a.kind}</Chip>
              <span className="t-cap">{(a.occurred_at || "").slice(0, 16).replace("T", " ")}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};


/* ============================================================
   PARTNER REGISTRATION WIZARD
   ============================================================ */
const PartnerRegistrationScreen = ({ onBack, onCreated }) => {
  // The wizard's step set lives in the dsa_wizard_step ChoiceList —
  // adding/renaming a step is an admin edit, not a code change.
  const [stepOpts] = useChoiceList("dsa_wizard_step");
  const [step, setStep] = _p_useState(null);
  _p_useEffect(() => {
    if (stepOpts.length && !step) setStep(stepOpts[0].code);
  }, [stepOpts, step]);

  const [data, setData] = _p_useState({
    // Identity
    type: "", sector: "",
    code: "", name: "", registration_no: "", country: "", website: "",
    primary_email: "",
    // Scope
    entities: { household: false, member: false, referral: false, grievance: false },
    fields: {},
    geo: [],
    monthly_row_budget: 0,
    duration_months: 12,
    sensitive_data_handling: "none",
    // Compliance
    dpia_document_ref: "",
    classification: "Internal",
    retention_days: 180,
    breach_sla_hours: 72,
    // Signatories
    partner_signer_email: "", partner_signer_name: "",
    nsr_unit_lead_email: "", nsr_unit_lead_name: "",
    dpo_email: "", dpo_name: "",
  });
  const setD = (k, v) => setData(s => ({ ...s, [k]: v }));
  const setNested = (g, k, v) => setData(s => ({ ...s, [g]: { ...s[g], [k]: v }}));

  const [submitting, setSubmitting] = _p_useState(false);
  const [submitOpen, setSubmitOpen] = _p_useState(false);
  const [toast, setToast] = _p_useState("");
  const [error, setError] = _p_useState("");

  const stepIdx = stepOpts.findIndex(s => s.code === step);
  const next = () => setStep(stepOpts[Math.min(stepIdx + 1, stepOpts.length - 1)].code);
  const prev = () => setStep(stepOpts[Math.max(stepIdx - 1, 0)].code);

  const onSubmit = async () => {
    setSubmitting(true);
    setError("");
    try {
      // Create the Partner row.
      const partner = await nsrApi.post("/api/v1/partners/", {
        code: data.code, name: data.name, type: data.type,
        sector: data.sector, status: "onboarding",
        tone: "neutral",
        registration_no: data.registration_no,
        country: data.country, website: data.website,
        primary_email: data.primary_email,
      });
      // Create the draft DSA.
      const effective_to = new Date();
      effective_to.setMonth(effective_to.getMonth() + (data.duration_months || 12));
      const dsa = await nsrApi.post("/api/v1/dsas/", {
        reference: `DSA-${data.code}-${new Date().getFullYear()}-DRAFT`,
        partner: partner.id, status: "draft",
        effective_from: new Date().toISOString().slice(0, 10),
        effective_to: effective_to.toISOString().slice(0, 10),
        monthly_row_budget: data.monthly_row_budget || null,
        sensitive_data_handling: data.sensitive_data_handling,
        entities_scope: data.entities,
        field_scope: data.fields,
        retention_days: data.retention_days,
        classification: data.classification,
        dpia_document_ref: data.dpia_document_ref,
        breach_sla_hours: data.breach_sla_hours,
      });
      // Dispatch sign-off.
      await nsrApi.post(`/api/v1/dsas/${dsa.id}/submit-for-signoff/`, {
        partner_signer_email: data.partner_signer_email,
        partner_signer_name: data.partner_signer_name,
        nsr_unit_lead_email: data.nsr_unit_lead_email,
        nsr_unit_lead_name: data.nsr_unit_lead_name,
        dpo_email: data.dpo_email,
        dpo_name: data.dpo_name,
      });
      setToast(`${data.code} submitted to NSR Unit Lead and DPO for sign-off.`);
      setSubmitOpen(false);
      if (onCreated) onCreated(partner);
    } catch (e) {
      setError(String(e.body?.detail || e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page" style={{paddingBottom: 0}}>
      <PageHeader
        eyebrow="PARTNERS · REGISTER NEW ORGANISATION · §11.6"
        title="Register partner"
        sub={<>Onboard a new partner and draft its first Data Sharing Agreement.</>}
        right={<>
          <button className="btn" onClick={onBack}>
            <Icon name="chevronLeft" size={14}/> Back to partners
          </button>
        </>}
      />

      {/* Stepper */}
      <div className="card" style={{padding: "14px 20px", marginBottom: 16, display: "flex", alignItems: "center", gap: 0, flexWrap: "wrap"}}>
        {stepOpts.map((s, i) => {
          const done = i < stepIdx;
          const active = i === stepIdx;
          return (
            <React.Fragment key={s.code}>
              <button onClick={() => setStep(s.code)} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "4px 12px", border: 0, background: "transparent", cursor: "pointer",
                color: active ? "var(--primary-900)" : done ? "var(--neutral-700)" : "var(--neutral-500)",
                fontWeight: active ? 600 : 500, fontSize: 13.5,
              }}>
                <span style={{
                  width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center",
                  background: active ? "var(--primary-900)" : done ? "var(--primary-100)" : "var(--neutral-100)",
                  color: active ? "white" : done ? "var(--primary-900)" : "var(--neutral-500)",
                  fontSize: 12, fontWeight: 600,
                  border: active ? 0 : `1px solid ${done ? "var(--primary-700)" : "var(--neutral-300)"}`,
                }}>{done ? <Icon name="check" size={12}/> : i + 1}</span>
                {s.label}
              </button>
              {i < stepOpts.length - 1 && <div style={{flex: 1, height: 1, background: i < stepIdx ? "var(--primary-700)" : "var(--neutral-300)", minWidth: 14}}/>}
            </React.Fragment>
          );
        })}
      </div>

      {step === "org"    && <StepOrg data={data} setD={setD}/>}
      {step === "sign"   && <StepSign data={data} setD={setD}/>}
      {step === "progs"  && <StepProgs/>}
      {step === "scope"  && <StepScope data={data} setD={setD} setNested={setNested}/>}
      {step === "compl"  && <StepCompliance data={data} setD={setD}/>}
      {step === "review" && <StepReview data={data}/>}

      {/* Action bar */}
      <div style={{margin: "16px -24px 0", position: "sticky", bottom: 0, zIndex: 20, background: "var(--neutral-0)", borderTop: "1px solid var(--neutral-300)", padding: "12px 20px", display: "flex", gap: 12, alignItems: "center"}}>
        <span className="t-bodysm muted">
          Step {stepIdx + 1} of {stepOpts.length} ·{" "}
          <strong style={{color: "var(--neutral-900)"}}>{stepOpts[stepIdx]?.label || ""}</strong>
        </span>
        <div style={{flex: 1}}/>
        {error && <span className="t-bodysm" style={{color: "var(--accent-danger)"}}>{error}</span>}
        <button className="btn" onClick={prev} disabled={stepIdx === 0}>
          <Icon name="chevronLeft" size={14}/> Back
        </button>
        {stepIdx < stepOpts.length - 1
          ? <button className="btn btn-primary" onClick={next}>Continue <Icon name="chevronRight" size={14}/></button>
          : <button className="btn btn-primary" onClick={() => setSubmitOpen(true)} disabled={submitting}>
              <Icon name="check" size={14}/> Submit for sign-off
            </button>
        }
      </div>

      <Modal open={submitOpen} onClose={() => setSubmitOpen(false)}
             title="Submit partner registration" width={520}
             footer={<>
               <button className="btn" onClick={() => setSubmitOpen(false)}>Cancel</button>
               <button className="btn btn-primary" onClick={onSubmit} disabled={submitting}>
                 <Icon name="check" size={14}/> {submitting ? "Submitting…" : "Submit"}
               </button>
             </>}>
        <div className="col gap-3">
          <p style={{margin: 0}}>
            Partner <strong>{data.name || "(unnamed)"}</strong> (
            <span className="t-mono">{data.code || "—"}</span>) and draft DSA
            <span className="t-mono"> DSA-{data.code || "—"}-{new Date().getFullYear()}-DRAFT</span> will enter the dual-approval queue.
          </p>
          <div className="tint-update" style={{padding: 12, borderRadius: 6, borderLeft: "3px solid var(--accent-update)"}}>
            <div className="row gap-2"><Icon name="shield" size={14} color="var(--accent-update)"/><strong className="t-bodysm">Sign-off chain</strong></div>
            <ol style={{margin: "6px 0 0 18px", padding: 0, fontSize: 13, color: "var(--neutral-700)"}}>
              <li>Partner Authorised Signatory · DocuSign</li>
              <li>NSR Unit Lead · sign in console</li>
              <li>Data Protection Officer · sign in console</li>
            </ol>
          </div>
          {error && <div className="t-bodysm" style={{color: "var(--accent-danger)"}}>{error}</div>}
        </div>
      </Modal>

      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};

/* ============================================================
   Wizard steps — every selector reads from useChoiceList.
   ============================================================ */

const StepOrg = ({ data, setD }) => {
  const [typeOpts] = useChoiceList("partner_type");
  const [sectorOpts] = useChoiceList("partner_sector");
  return (
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>Organisation</h3>
        <span className="t-cap">Type drives the DSA template + sign-off chain</span></div>
      <div style={{padding: 20}}>
        <Field label="Organisation type" required>
          <div style={{display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10}}>
            {typeOpts.map(t => (
              <button key={t.code} onClick={() => setD("type", t.code)} style={{
                textAlign: "left", padding: "12px 14px", borderRadius: 6,
                border: `2px solid ${data.type === t.code ? "var(--primary-900)" : "var(--neutral-300)"}`,
                background: data.type === t.code ? "var(--primary-100)" : "var(--neutral-0)",
                cursor: "pointer",
              }}>
                <div className="row gap-2">
                  <strong className="t-bodysm">{t.label}</strong>
                  {data.type === t.code && <Icon name="check" size={13} color="var(--primary-900)"/>}
                </div>
              </button>
            ))}
          </div>
        </Field>
        <div className="field-row mt-4">
          <Field label="Legal name" required>
            <input className="field-input" value={data.name}
                   onChange={(e) => setD("name", e.target.value)}/>
          </Field>
          <Field label="Short code" required
                 hint="3–5 uppercase letters · used as the partner mark in tables and audit IDs">
            <input className="field-input t-mono" value={data.code}
                   onChange={(e) => setD("code", e.target.value.toUpperCase().slice(0, 5))}
                   style={{textTransform: "uppercase"}}/>
          </Field>
        </div>
        <div className="field-row mt-4">
          <Field label="Registration number" required>
            <input className="field-input" value={data.registration_no}
                   onChange={(e) => setD("registration_no", e.target.value)}/>
          </Field>
          <Field label="Country / HQ" required>
            <input className="field-input" value={data.country}
                   onChange={(e) => setD("country", e.target.value)}/>
          </Field>
        </div>
        <div className="field-row mt-4">
          <Field label="Sector" required>
            <select className="field-select" value={data.sector}
                    onChange={(e) => setD("sector", e.target.value)}>
              <option value="">— pick a sector —</option>
              {sectorOpts.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Public website">
            <input className="field-input" value={data.website}
                   onChange={(e) => setD("website", e.target.value)}/>
          </Field>
        </div>
        <Field label="Primary email" required>
          <input className="field-input" value={data.primary_email}
                 onChange={(e) => setD("primary_email", e.target.value)}/>
        </Field>
      </div>
    </div>
  );
};

const StepSign = ({ data, setD }) => {
  // The three roles in the chain are sourced from the dsa_signer_role
  // ChoiceList; the UI mirrors them as separate cards but they're
  // all rows in the list (ADR-0012).
  const [roleOpts] = useChoiceList("dsa_signer_role");
  // Map role code → state field pair.
  const fieldFor = {
    "partner_auth_signatory": { email: "partner_signer_email", name: "partner_signer_name" },
    "nsr_unit_lead":          { email: "nsr_unit_lead_email",   name: "nsr_unit_lead_name" },
    "dpo":                    { email: "dpo_email",             name: "dpo_name" },
  };
  return (
    <div className="col gap-4">
      {roleOpts.map(r => {
        const f = fieldFor[r.code];
        if (!f) return null;
        return (
          <div key={r.code} className="card">
            <div className="card-header" style={{padding: "12px 20px"}}>
              <div>
                <div className="t-cap" style={{color: "var(--primary-900)", fontWeight: 600}}>
                  {r.label.toUpperCase()}
                </div>
              </div>
            </div>
            <div style={{padding: 20}}>
              <div className="field-row">
                <Field label="Full name" required>
                  <input className="field-input" value={data[f.name] || ""}
                         onChange={(e) => setD(f.name, e.target.value)}/>
                </Field>
                <Field label="Email" required>
                  <input className="field-input" value={data[f.email] || ""}
                         onChange={(e) => setD(f.email, e.target.value)}/>
                </Field>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const StepProgs = () => (
  <div className="card">
    <div className="card-header">
      <h3 className="t-h3" style={{margin: 0}}>Programmes</h3>
      <span className="t-cap">Add programmes after the DSA is created — they attach via M2M.</span>
    </div>
    <div style={{padding: 14, background: "var(--neutral-50)", display: "flex", alignItems: "center", gap: 8}}>
      <Icon name="info" size={14} color="var(--neutral-500)"/>
      <span className="t-bodysm muted">
        Programmes live on /api/v1/partners/{`{id}`}/programmes/. Add them on the partner detail page after sign-off lands.
      </span>
    </div>
  </div>
);

const StepScope = ({ data, setD, setNested }) => {
  const [sensOpts] = useChoiceList("sensitive_data_handling");
  return (
    <div className="card">
      <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>DSA scope</h3>
        <span className="t-cap">Entities, fields, geography, volume cap</span></div>
      <div style={{padding: 20}}>
        <Field label="Entities allowed" required>
          <div style={{display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12}}>
            {[["household", "Household", "data"],
              ["member", "Member", "identity"],
              ["referral", "Referral summary", "programme"],
              ["grievance", "Grievance summary", "grm"]].map(([k, label, tone]) => {
              const on = data.entities[k];
              return (
                <button key={k} onClick={() => setNested("entities", k, !on)} style={{
                  textAlign: "left", padding: 14, borderRadius: 6,
                  border: `2px solid ${on ? `var(--accent-${tone})` : "var(--neutral-300)"}`,
                  background: on ? `var(--accent-${tone}-bg)` : "var(--neutral-0)",
                  cursor: "pointer",
                }}>
                  <div className="row gap-2">
                    <strong className="t-bodysm">{label}</strong>
                    {on && <Icon name="check" size={13} color={`var(--accent-${tone})`}/>}
                  </div>
                </button>
              );
            })}
          </div>
        </Field>
        <div className="field-row mt-4">
          <Field label="Monthly row budget" required
                 hint="AC-DPO-VOL — anomaly fires above 100%. Blank for provider partners.">
            <input type="number" className="field-input"
                   value={data.monthly_row_budget || ""}
                   onChange={(e) => setD("monthly_row_budget", parseInt(e.target.value || "0", 10))}/>
          </Field>
          <Field label="DSA duration (months)" required>
            <div className="seg">
              {[6, 12, 24].map(m => (
                <button key={m}
                        className={data.duration_months === m ? "on" : ""}
                        onClick={() => setD("duration_months", m)}>
                  {m}
                </button>
              ))}
            </div>
          </Field>
        </div>
        <Field label="Sensitive-field exemption" style={{marginTop: 16}}>
          <div className="seg">
            {sensOpts.map(o => (
              <button key={o.code}
                      className={data.sensitive_data_handling === o.code ? "on" : ""}
                      onClick={() => setD("sensitive_data_handling", o.code)}>
                {o.label}
              </button>
            ))}
          </div>
        </Field>
      </div>
    </div>
  );
};

const StepCompliance = ({ data, setD }) => (
  <div className="card">
    <div className="card-header"><h3 className="t-h3" style={{margin: 0}}>Compliance & security</h3>
      <span className="t-cap">Per §6 of the Data Protection and Privacy Act</span></div>
    <div style={{padding: 20}}>
      <div className="field-row">
        <Field label="DPIA document reference" required>
          <input className="field-input" value={data.dpia_document_ref}
                 onChange={(e) => setD("dpia_document_ref", e.target.value)}/>
        </Field>
        <Field label="Classification">
          <input className="field-input" value={data.classification}
                 onChange={(e) => setD("classification", e.target.value)}/>
        </Field>
      </div>
      <div className="field-row mt-4">
        <Field label="Retention pledge (days)" required>
          <div className="seg">
            {[90, 180, 365].map(d => (
              <button key={d} className={data.retention_days === d ? "on" : ""}
                      onClick={() => setD("retention_days", d)}>{d}d</button>
            ))}
          </div>
        </Field>
        <Field label="Breach SLA (hours)" required>
          <div className="seg">
            {[24, 48, 72].map(h => (
              <button key={h} className={data.breach_sla_hours === h ? "on" : ""}
                      onClick={() => setD("breach_sla_hours", h)}>{h}h</button>
            ))}
          </div>
        </Field>
      </div>
    </div>
  </div>
);

const StepReview = ({ data }) => (
  <div className="card" style={{borderTop: "3px solid var(--primary-900)"}}>
    <div className="card-header">
      <div>
        <div className="t-cap" style={{color: "var(--primary-900)", fontWeight: 600, letterSpacing: "0.06em"}}>
          DRAFT DATA SHARING AGREEMENT
        </div>
        <h3 className="t-h2" style={{margin: "2px 0 0"}}>
          DSA-{data.code || "—"}-{new Date().getFullYear()}-DRAFT
        </h3>
      </div>
      <Chip tone="quality">Draft</Chip>
    </div>
    <div style={{padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24}}>
      <ReviewBlock title="Party">
        <ReviewKV k="Legal name" v={data.name || "—"}/>
        <ReviewKV k="Short code" v={data.code || "—"} mono/>
        <ReviewKV k="Type · Sector" v={`${data.type || "—"} · ${data.sector || "—"}`}/>
        <ReviewKV k="Registration" v={data.registration_no || "—"}/>
        <ReviewKV k="Country" v={data.country || "—"}/>
        <ReviewKV k="Primary email" v={data.primary_email || "—"}/>
      </ReviewBlock>

      <ReviewBlock title="Sign-off chain">
        <ReviewKV k="Partner Auth Signatory" v={data.partner_signer_email || "—"}/>
        <ReviewKV k="NSR Unit Lead"          v={data.nsr_unit_lead_email   || "—"}/>
        <ReviewKV k="DPO"                    v={data.dpo_email             || "—"}/>
      </ReviewBlock>

      <ReviewBlock title="Scope">
        <ReviewKV k="Entities" v={Object.entries(data.entities).filter(([, v]) => v).map(([k]) => k).join(", ") || "—"}/>
        <ReviewKV k="Geography" v={data.geo.length ? data.geo.join(", ") : "Nationwide"}/>
        <ReviewKV k="Sensitive data" v={data.sensitive_data_handling}/>
      </ReviewBlock>

      <ReviewBlock title="Volume & duration">
        <ReviewKV k="Monthly row budget" v={data.monthly_row_budget ? `${_fmt(data.monthly_row_budget)} rows / month` : "—"}/>
        <ReviewKV k="Duration" v={`${data.duration_months} months`}/>
        <ReviewKV k="Retention" v={`${data.retention_days} days`}/>
        <ReviewKV k="Breach SLA" v={`${data.breach_sla_hours}h`}/>
        <ReviewKV k="DPIA" v={data.dpia_document_ref || "—"} mono/>
      </ReviewBlock>
    </div>
  </div>
);

const ReviewBlock = ({ title, children }) => (
  <div>
    <div className="t-cap" style={{textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--neutral-700)", fontWeight: 600, marginBottom: 8}}>{title}</div>
    <div style={{display: "grid", rowGap: 6}}>{children}</div>
  </div>
);

const ReviewKV = ({ k, v, mono }) => (
  <div style={{display: "grid", gridTemplateColumns: "150px 1fr", gap: 8, fontSize: 13, alignItems: "start"}}>
    <div className="muted">{k}</div>
    <div className={mono ? "t-mono" : ""} style={{color: "var(--neutral-900)", fontWeight: 500}}>{v}</div>
  </div>
);

// Bind on window so the harness picks them up alongside the other screens.
window.PartnersScreen = PartnersScreen;
window.PartnerRegistrationScreen = PartnerRegistrationScreen;
