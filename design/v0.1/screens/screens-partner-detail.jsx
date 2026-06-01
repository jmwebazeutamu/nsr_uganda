/* global React, Icon, Chip, KPI, Sparkline, PageHeader, Modal, Field, Toast, PartnerMark, useApi, nsrApi, ScopeEditModal */
// NSR MIS — Partner detail (US-S23-018, live-wired)
//   PartnerDetailScreen  — full read view for one partner
//
// Pattern matches HouseholdScreen: header card + tabs. Reads data
// from the API endpoints landed in US-S23-008 through 010:
//
//   GET /api/v1/partners/{id}/
//   GET /api/v1/dsas/?partner={id}        (embeds signatures)
//   GET /api/v1/partners/{id}/usage/?days=30
//   GET /api/v1/partners/{id}/activity/
//
// Tabs that need endpoints we haven't shipped yet (Programmes list
// detail, Contacts list, Documents, Audit) render empty states with
// a stub note rather than mock data — every value visible on the
// screen reads from the live registry.

const { useState: useStatePD, useMemo: useMemoPD } = React;

/* ============================================================
   PARTNER_FALLBACK — shape contract the tabs render from.
   Empty values render as muted placeholders; live data is
   projected on top of this baseline in _buildDetail() below.
   ============================================================ */
const PARTNER_FALLBACK = {
  code: "—",
  name: "Loading…",
  type: "—",
  sector: "—",
  tone: "neutral",
  status: "—",

  registration: "—",
  country: "—",
  website: "",
  email: "—",
  phone: "—",
  lead: "—",
  leadTitle: "—",
  joinedAt: "—",
  joinedAtRel: "",
  lastActivity: "—",

  rollup: {
    dsasActive: 0, dsasTotal: 0, daysToRenewal: null,
    programmes: 0, programmesActive: 0,
    contacts: 0, contactsVerified: 0,
    rows30d: 0, rows90d: 0,
    requests30d: 0, requests90d: 0,
    monthlyBudget: 0,
    budgetUsedPct: 0,
    spark30d: Array(30).fill(0),
  },

  dsas: [],
  programmes: [],
  contacts: [],
  topRequests: [],
  activity: [],
  compliance: {
    dpia: "", dpiaSize: "", dpiaUpdated: "",
    cert: "", classification: "",
    retention: 0, breach: 0,
    subProcessors: [],
    attestations: [],
  },
  documents: [],
  audit: [],
};


/* ============================================================
   Project API responses onto the fallback shape.

   /api/v1/partners/{id}/                    identity
   /api/v1/dsas/?partner={id}                DSAs (embeds signatures)
   /api/v1/partners/{id}/usage/?days=30      usage strip
   /api/v1/partners/{id}/activity/           audit-projection feed

   Tabs that need endpoints we have not yet shipped (Programmes,
   Contacts, Documents, Audit chain) render empty states until
   their data layer lands.
   ============================================================ */

const _pdFmtDate = (iso) => (iso || "").slice(0, 10);
const _pdDaysUntil = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d - today) / 86400000);
};

const _pdHumanRel = (iso) => {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const days = Math.round(ms / 86400000);
  if (days < 0)   return "in the future";
  if (days <= 1)  return "today";
  if (days < 30)  return days + "d ago";
  if (days < 365) return Math.round(days/30) + "mo ago";
  const y = Math.floor(days/365);
  const m = Math.round((days % 365)/30);
  return m ? y + "y " + m + "mo ago" : y + "y ago";
};

const _projectDsa = (d) => ({
  id: d.id,
  ref: d.reference, version: d.version,
  status: d.status_label || d.status || "-",
  status_code: d.status,
  _raw: d,                          // raw API payload for the scope-edit modal pre-fill
  programme: (d.programmes && d.programmes.length)
    ? (d.programmes.length + " programme" + (d.programmes.length === 1 ? "" : "s"))
    : "-",
  effFrom: _pdFmtDate(d.effective_from) || "-",
  effTo: _pdFmtDate(d.effective_to) || "-",
  daysToExpire: _pdDaysUntil(d.effective_to),
  monthlyBudget: d.monthly_row_budget || 0,
  used30d: 0,
  entities: Object.entries(d.entities_scope || {})
    .filter(([, v]) => v).map(([k]) => k),
  fieldGroups: Object.entries(d.field_scope || {})
    .filter(([, v]) => v).map(([k]) => k),
  geo: [],
  sensitive: d.sensitive_data_handling || "none",
  sensitive_label: d.sensitive_data_handling_label,
  retention: d.retention_days || 0,
  breach: d.breach_sla_hours || 0,
  classification: d.classification || "-",
  signatures: (d.signatures || [])
    .slice()
    .sort((a, b) => a.sequence_order - b.sequence_order)
    .map(s => ({
      role: s.signer_role_label || s.signer_role,
      name: s.signer_name || s.signer_email,
      at: s.signed_at
        ? _pdFmtDate(s.signed_at)
        : (s.docusign_envelope_id ? "envelope sent" : "Queued"),
      status: s.status_label || s.status || "Pending",
      status_code: s.status,
    })),
});

// Project an apps.partners ProgrammeSerializer payload onto the row
// shape the Programmes tab + Overview tile expect. Labels resolve
// via the *_label fields auto-attached by the serializer.
const _projectProgramme = (pr) => ({
  id: pr.id,
  code: pr.code || "",
  name: pr.name || "—",
  kind: pr.kind_label || pr.kind || "—",
  kind_code: pr.kind || "",
  status: pr.status_label || pr.status || "—",
  status_code: pr.status || "",
  // Free-text scope on the model; falls back to a dash so the row
  // tile doesn't render "—" beside an unrelated chip.
  scope: pr.scope_text || "national",
  benef: pr.beneficiary_estimate || pr.cohort_target || 0,
  start: pr.start_month || (pr.start_date || "—"),
  end: pr.end_date
    || (pr.duration_months ? `${pr.duration_months}mo` : "—"),
  cashRail: pr.channel || "—",
  targeting: pr.unit_of_enrolment_label || pr.unit_of_enrolment || "—",
  cycle: pr.disbursement_cycle_label || pr.disbursement_cycle || "—",
  dsa_reference: pr.dsa_reference || "",
});

const _projectActivity = (e) => ({
  who: (e.partner || "-").toUpperCase().slice(0, 4),
  action: (e.kind || "").replace(/_/g, " "),
  detail: e.detail || e.related_object_type || "",
  // ISO date only — the activity rail had "2026-05-22 14:35" before;
  // wall-clock precision lives in the audit chain, not the rail.
  time: _pdFmtDate(e.occurred_at) || "",
  tone: e.severity_tone || "neutral",
  chip: e.kind || "",
});

const _buildDetail = ({ partner, dsasList, usage, activity, programmesList }) => {
  const p = JSON.parse(JSON.stringify(PARTNER_FALLBACK));
  if (!partner) return p;

  p.code = partner.code; p.name = partner.name;
  p.type = partner.type_label || partner.type;
  p.sector = partner.sector_label || partner.sector;
  p.tone = partner.tone || "neutral";
  p.status = partner.status_label || partner.status;
  p.registration = partner.registration_no || "-";
  p.country = partner.country || "-";
  p.website = partner.website || "";
  p.email = partner.primary_email || "-";
  p.phone = "-";
  p.lead = "-";
  p.leadTitle = "-";
  p.joinedAt = _pdFmtDate(partner.created_at) || "-";
  p.joinedAtRel = _pdHumanRel(partner.created_at);
  // ISO date only — was "2026-05-22 14:35 EAT". Per the app-wide
  // date-formatting policy the header line shows the date and lets
  // the audit timeline carry the wall-clock detail.
  p.lastActivity = _pdFmtDate(partner.last_activity_at) || "-";

  const dsas = (dsasList || []).map(_projectDsa);
  p.dsas = dsas;

  const usageItems = (usage && usage.items) ? usage.items : [];
  const days = 30;
  const spark = new Array(days).fill(0);
  if (usageItems.length) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    for (const it of usageItems) {
      const d = new Date(it.day); d.setHours(0, 0, 0, 0);
      const offset = Math.round((today - d) / 86400000);
      const idx = days - 1 - offset;
      if (idx >= 0 && idx < days) spark[idx] = it.rows_delivered || 0;
    }
  }
  const rows30d = spark.reduce((a, b) => a + b, 0);
  const requests30d = usageItems.reduce((a, it) => a + (it.requests_count || 0), 0);
  const monthlyBudget = dsas.reduce(
    (a, d) => a + (d.status_code === "active" ? (d.monthlyBudget || 0) : 0),
    0,
  );
  const dsasActive = dsas.filter(d => d.status_code === "active").length;
  const daysToRenewal = dsas
    .map(d => d.daysToExpire)
    .filter(v => v != null && v >= 0)
    .sort((a, b) => a - b)[0];

  const programmes = (programmesList || []).map(_projectProgramme);
  p.programmes = programmes;

  p.rollup = {
    dsasActive, dsasTotal: dsas.length,
    daysToRenewal: daysToRenewal == null ? null : daysToRenewal,
    programmes: programmes.length,
    programmesActive: programmes.filter(
      pr => pr.status_code === "active",
    ).length,
    contacts: 0, contactsVerified: 0,
    rows30d, rows90d: 0,
    requests30d, requests90d: 0,
    monthlyBudget,
    budgetUsedPct: monthlyBudget > 0
      ? Math.round(rows30d / monthlyBudget * 100)
      : 0,
    spark30d: spark,
  };

  p.activity = (activity && activity.items ? activity.items : [])
    .slice(0, 20)
    .map(_projectActivity);

  const lead = dsas.find(d => d.status_code === "active") || dsas[0];
  if (lead) {
    p.compliance = {
      ...p.compliance,
      classification: lead.classification,
      retention: lead.retention,
      breach: lead.breach,
    };
  }
  return p;
};

/* ============================================================
   helpers shared inside this file
   ============================================================ */
const pdfmt = (n) => {
  if (n >= 1000000) return (n/1000000).toFixed(2) + "M";
  if (n >= 1000)    return (n/1000).toFixed(1) + "k";
  return String(n);
};

const DSA_TONE = { Active:"data", Renewing:"quality", Draft:"update", Expired:"neutral", Suspended:"danger" };
const SIG_TONE = { Signed:"data", Sent:"quality", Queued:"neutral", Declined:"danger" };
const PROG_TONE= { Active:"data", Closing:"update", Draft:"neutral", Closed:"neutral" };

const TabHeaderPD = ({ title, sub, action }) => (
  <div style={{padding:'16px 20px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', gap:12}}>
    <div>
      <h3 className="t-h3" style={{margin:0}}>{title}</h3>
      {sub && <div className="t-cap mt-1">{sub}</div>}
    </div>
    {action}
  </div>
);

const KVCardPD = ({ title, rows, tint, action }) => (
  <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0, borderLeft: tint ? `3px solid var(--accent-${tint})` : '1px solid var(--neutral-200)'}}>
    <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', gap:8, fontSize:14, fontWeight:600}}>
      <span>{title}</span>{action}
    </div>
    <div style={{padding:'10px 16px'}}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{display:'grid', gridTemplateColumns:'140px 1fr', gap:8, padding:'5px 0', fontSize:13, borderTop: i === 0 ? 'none' : '1px solid var(--neutral-200)'}}>
          <div className="muted">{k}</div>
          <div style={{color:'var(--neutral-900)', fontWeight:500, overflowWrap:'anywhere'}}>{v}</div>
        </div>
      ))}
    </div>
  </div>
);

const FactPD = ({ label, big, sub }) => (
  <div style={{minWidth:0}}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm" style={{fontWeight:600, fontSize:15, marginTop:2, color:'var(--neutral-900)', overflowWrap:'anywhere'}}>{big}</div>
    {sub && <div className="t-cap mt-1">{sub}</div>}
  </div>
);

/* ============================================================
   TABS list
   ============================================================ */
// Tab counts now derive from the live `p` projection at render
// time (lifted into the component below). The const PD_TABS array
// stays for the stepper's iteration order; counts are computed
// inline.
const PD_TABS = [
  { id: "over",  label: "Overview" },
  { id: "dsa",   label: "DSAs" },
  { id: "prog",  label: "Programmes" },
  { id: "con",   label: "Contacts" },
  { id: "use",   label: "Usage" },
  { id: "act",   label: "Activity" },
  { id: "cmpl",  label: "Compliance" },
  { id: "docs",  label: "Documents" },
  { id: "aud",   label: "Audit" },
];

/* ============================================================
   PartnerDetailScreen — live wiring (US-S23-018)

   Accepts { partnerId, onBack }. Fetches the partner identity,
   DSA list with embedded signatures, 30-day usage strip, and
   the activity projection in parallel. Builds the `p` shape the
   tab components expect via _buildDetail.
   ============================================================ */
const PartnerDetailScreen = ({ partnerId, onBack, onRegisterProgramme, onNavigate }) => {
  const [partnerResp, partnerMeta] = useApi(
    partnerId ? `/api/v1/partners/${partnerId}/` : null,
  );
  const [dsasResp, dsasMeta] = useApi(
    partnerId ? `/api/v1/dsas/?partner=${partnerId}` : null,
  );
  const [usageResp] = useApi(
    partnerId ? `/api/v1/partners/${partnerId}/usage/?days=30` : null,
  );
  const [activityResp] = useApi(
    partnerId ? `/api/v1/partners/${partnerId}/activity/` : null,
  );
  // Programmes for this partner — list endpoint takes a partner=
  // filter (see apps.partners.api.ProgrammeViewSet.get_queryset). The
  // Programmes tab + Overview tile + DSA-card Programmes-count chip
  // all read off this.
  const [programmesResp, programmesMeta] = useApi(
    partnerId ? `/api/v1/programmes/?partner=${partnerId}&page_size=200` : null,
  );

  const p = useMemoPD(
    () => _buildDetail({
      partner: partnerResp,
      dsasList: dsasResp ? (dsasResp.results || dsasResp) : null,
      usage: usageResp,
      activity: activityResp,
      programmesList: programmesResp
        ? (programmesResp.results || programmesResp)
        : null,
    }),
    [partnerResp, dsasResp, usageResp, activityResp, programmesResp],
  );

  const [tab, setTab] = useStatePD("over");
  const [toast, setToast] = useStatePD("");
  // ScopeEditDsa is the raw DSA payload being scope-edited; null
  // when the modal is closed. ADR-0016 §"Decision 2" gates editing
  // to draft + active rows only.
  const [scopeEditDsa, setScopeEditDsa] = useStatePD(null);
  // US-S11-036 — Edit + Delete CRUD affordances on the Partner detail.
  // Backend ModelViewSet has supported PATCH + DELETE forever; the
  // console only just gets the buttons. Delete is FK-PROTECTED at
  // the model level (PartnerContact / DataSharingAgreement / Programme
  // all point at Partner with on_delete=PROTECT), so the endpoint
  // 4xxs cleanly when downstream rows exist. The confirm modal warns
  // the operator before they discover that the hard way.
  const [editOpen, setEditOpen] = useStatePD(false);
  const [deleteOpen, setDeleteOpen] = useStatePD(false);
  const _SCOPE_EDITABLE = new Set(["draft", "active"]);
  const openScopeEditor = (projectedDsa) => {
    if (!projectedDsa || !_SCOPE_EDITABLE.has(projectedDsa.status_code)) return;
    setScopeEditDsa(projectedDsa._raw || null);
  };
  const onScopeEditSuccess = (result, { cloned }) => {
    if (cloned && result?.reference) {
      setToast(`Cloned to ${result.reference} v${result.version} (draft) — dispatch the new draft for sign-off.`);
    } else if (result?.reference) {
      setToast(`Scope updated on ${result.reference} v${result.version}.`);
    } else {
      setToast("Scope updated.");
    }
    setScopeEditDsa(null);
    dsasMeta.refresh && dsasMeta.refresh();
  };

  const tabCounts = {
    dsa: p.dsas.length,
    prog: p.programmes.length,
    con: p.contacts.length,
    docs: p.documents.length,
  };

  const budgetPct = p.rollup.monthlyBudget
    ? Math.round(p.rollup.rows30d / p.rollup.monthlyBudget * 100)
    : 0;
  const overBudget = p.rollup.monthlyBudget > 0
    && p.rollup.rows30d > p.rollup.monthlyBudget;
  const nextRenewalDsa = p.dsas
    .filter(d => d.daysToExpire != null && d.daysToExpire >= 0)
    .sort((a, b) => a.daysToExpire - b.daysToExpire)[0];

  if (!partnerId) {
    return (
      <div className="page">
        <PageHeader eyebrow="PARTNERS" title="No partner selected"/>
        <div className="card" style={{padding: 20}} className="muted">
          Open a partner from the Partners table to see its detail view.
        </div>
      </div>
    );
  }
  if (partnerMeta.loading) {
    return (
      <div className="page">
        <PageHeader eyebrow="PARTNERS" title="Loading…"/>
      </div>
    );
  }
  if (partnerMeta.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="PARTNERS" title="Could not load partner"
          sub={partnerMeta.error}/>
        <div style={{padding: 20}}>
          <button className="btn" onClick={onBack}>
            <Icon name="chevronLeft" size={14}/> Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">

      {/* Eyebrow + title */}
      <PageHeader
        back={{ label: "Partners", onClick: onBack }}
        eyebrow={<>PARTNERS · <span className="t-mono">{p.code}</span> · §11.6</>}
        title={<>{p.name} <Chip tone="data" style={{marginLeft:8, verticalAlign:'2px'}}>{p.status}</Chip></>}
        sub={<>{p.type} · {p.sector} · lead {p.lead} · last activity {p.lastActivity}</>}
        right={(() => {
          const hasEditable = p.dsas.some(d => _SCOPE_EDITABLE.has(d.status_code));
          const noDsas = p.dsas.length === 0;
          // When the partner has no DSA (or only terminal ones), the
          // "Edit scope" affordance is meaningless — surface the
          // create-wizard path instead so the operator isn't dead-ended.
          return <>
            <button className="btn"><Icon name="download" size={14}/> Export partner record</button>
            <button className="btn" onClick={() => setEditOpen(true)}
                    title="Edit name, type, status, contact info (PATCH /api/v1/partners/{id}/)">
              <Icon name="edit" size={14}/> Edit
            </button>
            <button className="btn"
                    style={{color:"var(--accent-danger)"}}
                    onClick={() => setDeleteOpen(true)}
                    title="Refuses if any DSA, Programme, or Contact exists for this partner">
              <Icon name="trash" size={14}/> Delete
            </button>
            {noDsas || !hasEditable ? (
              <button className="btn btn-primary"
                      onClick={() => onNavigate && onNavigate("dsa-new", { partnerId: p.id })}
                      title={noDsas
                        ? "This partner has no DSA yet — create one"
                        : "All DSAs are in terminal status — create a new one"}>
                <Icon name="plus" size={14}/> New DSA
              </button>
            ) : (
              <button className="btn btn-primary"
                      onClick={() => {
                        // Prefer active; otherwise pick the newest draft.
                        const target = p.dsas.find(d => d.status_code === "active")
                          || p.dsas.find(d => d.status_code === "draft");
                        openScopeEditor(target);
                      }}
                      title="Edit the scope on this partner's active or draft DSA">
                <Icon name="edit" size={14}/> Edit DSA scope
              </button>
            )}
            <button className="btn btn-ghost"><Icon name="moreH" size={14}/></button>
          </>;
        })()}
      />

      {/* Header summary card */}
      <div className="card" style={{padding:0, marginBottom:16}}>

        {/* row 1 — 5 quick facts */}
        <div style={{padding:'18px 20px', display:'grid', gridTemplateColumns:'auto 2fr 1.4fr 1.4fr 1.2fr', gap:24, alignItems:'flex-start'}}>
          <PartnerMark code={p.code} tone={p.tone} size={64}/>
          <div style={{minWidth:0}}>
            <div className="t-cap">Legal identity</div>
            <div style={{fontWeight:600, fontSize:16, color:'var(--neutral-900)', marginTop:2}}>{p.name}</div>
            <div className="t-bodysm muted" style={{marginTop:2}}>{p.type} · {p.sector}</div>
            <div className="t-cap mt-2">{p.registration}</div>
            <div className="t-cap">{p.country}</div>
          </div>
          <FactPD label="Lead" big={p.lead} sub={p.leadTitle}/>
          <FactPD label="Primary contact"
                  big={<span className="t-mono" style={{fontSize:13.5}}>{p.email}</span>}
                  sub={<><span className="t-mono">{p.phone}</span> · <a href={`https://${p.website}`} className="t-bodysm" style={{color:'var(--primary-700)'}}>{p.website}</a></>}/>
          <FactPD label="Registered with NSR" big={p.joinedAt} sub={`${p.joinedAtRel} · partner since`}/>
        </div>

        {/* row 2 — sub-stats */}
        <div style={{borderTop:'1px solid var(--neutral-200)', background:'var(--neutral-50)', display:'grid', gridTemplateColumns:'repeat(5, 1fr)'}}>
          <SubStat label="Active DSAs"
            value={`${p.rollup.dsasActive} / ${p.rollup.dsasTotal}`}
            sub={nextRenewalDsa ? `Next renewal in ${nextRenewalDsa.daysToExpire}d` : "—"}
            tone="data"/>
          <SubStat label="Programmes"
            value={`${p.rollup.programmesActive} / ${p.rollup.programmes}`}
            sub="under DSA scope" tone="programme"/>
          <SubStat label="Rows · 30d"
            value={pdfmt(p.rollup.rows30d)}
            sub={<>of {pdfmt(p.rollup.monthlyBudget)} budget · <strong style={{color: overBudget ? 'var(--accent-danger)' : 'var(--accent-data)'}}>{budgetPct}%</strong></>}
            tone="data"
            after={<MiniUsageBar pct={budgetPct} over={overBudget}/>}/>
          <SubStat label="Requests · 30d"
            value={String(p.rollup.requests30d)}
            sub={`${p.rollup.requests90d} in last 90d`} tone="update"/>
          <SubStat label="Contacts"
            value={`${p.rollup.contactsVerified} / ${p.rollup.contacts}`}
            sub="NIN-verified" tone="identity" last/>
        </div>
      </div>

      {/* Tab bar */}
      <div role="tablist" style={{display:'flex', gap:0, borderBottom:'1px solid var(--neutral-300)', marginBottom:0, flexWrap:'wrap'}}>
        {PD_TABS.map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} role="tab" onClick={() => setTab(t.id)} style={{
              display:'inline-flex', alignItems:'center', gap:6,
              padding:'10px 16px', border:0, borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
              background:'transparent', cursor:'pointer',
              color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
              fontWeight: active ? 600 : 500, fontSize:13.5, marginBottom:-1,
            }}>
              {t.label}
              {tabCounts[t.id] !== undefined && (
                <span style={{display:'inline-grid', placeItems:'center', minWidth:18, height:18, padding:'0 5px', borderRadius:9, background: active ? 'var(--primary-100)' : 'var(--neutral-100)', color: active ? 'var(--primary-900)' : 'var(--neutral-700)', fontSize:11, fontWeight:600}}>{tabCounts[t.id]}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab body */}
      <div className="card" style={{borderTopLeftRadius:0, borderTopRightRadius:0, padding:0, marginTop:0}}>
        {tab === "over" && <PDOverview p={p}/>}
        {tab === "dsa"  && <PDDsas p={p} onToast={setToast} onRefresh={dsasMeta.refresh} onEditScope={openScopeEditor} onOpenDsa={(id) => onNavigate && onNavigate("dsa-detail", { dsaId: id })} onNewDsa={() => onNavigate && onNavigate("dsa-new", { partnerId: p.id })}/>}
        {tab === "prog" && <PDProgrammes p={p} onRegisterProgramme={onRegisterProgramme}/>}
        {tab === "con"  && <PDContacts p={p}/>}
        {tab === "use"  && <PDUsage p={p}/>}
        {tab === "act"  && <PDActivity p={p}/>}
        {tab === "cmpl" && <PDCompliance p={p}/>}
        {tab === "docs" && <PDDocuments p={p}/>}
        {tab === "aud"  && <PDAudit p={p}/>}
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read view (AC-DSA-SCOPE). Scope changes route through the DSA editor and require dual-approval (NSR Unit Lead + DPO).
      </div>

      <Toast message={toast} onDone={() => setToast("")}/>

      <ScopeEditModal
        open={!!scopeEditDsa}
        dsa={scopeEditDsa}
        onClose={() => setScopeEditDsa(null)}
        onSuccess={onScopeEditSuccess}/>

      <EditPartnerModal
        open={editOpen}
        partner={partnerResp}
        onClose={() => setEditOpen(false)}
        onSaved={(updated) => {
          setEditOpen(false);
          setToast(`Updated ${updated?.code || "partner"} — ${
            Object.keys(_diffShape(partnerResp, updated)).length || 0
          } field(s) saved.`);
          partnerMeta.refresh && partnerMeta.refresh();
        }}
        onError={(msg) => setToast(`Edit failed: ${msg}`)}/>

      <DeletePartnerConfirm
        open={deleteOpen}
        partner={partnerResp}
        rollup={p.rollup}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => {
          setDeleteOpen(false);
          setToast(`Deleted ${p.code} — audit chain preserved.`);
          // Pop back to the list since the detail can't render anymore.
          if (onBack) onBack();
        }}
        onError={(msg) => setToast(`Delete failed: ${msg}`)}/>
    </div>
  );
};


// Shallow shape diff so the Edit toast can report "N field(s) saved".
// Compares only top-level scalars between the old + new partner so
// it ignores label-attachments + relations.
const _diffShape = (before, after) => {
  const out = {};
  if (!before || !after) return out;
  for (const k of Object.keys(after)) {
    if (k.endsWith("_label") || k === "id") continue;
    if (before[k] !== after[k]) out[k] = after[k];
  }
  return out;
};


// ── EditPartnerModal (US-S11-036) ─────────────────────────────────────
// PATCHes the editable fields on /api/v1/partners/{id}/. Coded fields
// (type, sector, status) pull options from useChoiceList so the
// dropdown stays in sync with the ChoiceList seeds — no hardcoded
// option arrays.
const EditPartnerModal = ({ open, partner, onClose, onSaved, onError }) => {
  const [typeOpts]   = useChoiceList("partner_type");
  const [sectorOpts] = useChoiceList("partner_sector");
  const [statusOpts] = useChoiceList("partner_status");

  const [name, setName] = useStatePD("");
  const [code, setCode] = useStatePD("");
  const [type, setType] = useStatePD("");
  const [sector, setSector] = useStatePD("");
  const [status, setStatus] = useStatePD("");
  const [registrationNo, setRegistrationNo] = useStatePD("");
  const [country, setCountry] = useStatePD("");
  const [website, setWebsite] = useStatePD("");
  const [primaryEmail, setPrimaryEmail] = useStatePD("");
  const [note, setNote] = useStatePD("");
  const [submitting, setSubmitting] = useStatePD(false);

  // Seed the form from the current partner whenever the modal opens.
  React.useEffect(() => {
    if (!open || !partner) return;
    setName(partner.name || "");
    setCode(partner.code || "");
    setType(partner.type || "");
    setSector(partner.sector || "");
    setStatus(partner.status || "");
    setRegistrationNo(partner.registration_no || "");
    setCountry(partner.country || "");
    setWebsite(partner.website || "");
    setPrimaryEmail(partner.primary_email || "");
    setNote(partner.note || "");
  }, [open, partner]);

  if (!open || !partner) return null;

  const canSave = !submitting && name.trim() && code.trim();

  const save = async () => {
    if (!canSave) return;
    setSubmitting(true);
    try {
      const updated = await nsrApi.patch(`/api/v1/partners/${partner.id}/`, {
        name: name.trim(),
        code: code.trim(),
        type, sector, status,
        registration_no: registrationNo.trim(),
        country: country.trim(),
        website: website.trim(),
        primary_email: primaryEmail.trim(),
        note,
      });
      setSubmitting(false);
      onSaved(updated);
    } catch (err) {
      setSubmitting(false);
      const detail = (err && err.body && (err.body.detail
        || Object.values(err.body).flat().join(" · "))) || err.message;
      onError(detail);
    }
  };

  return (
    <Modal open={true} onClose={() => !submitting && onClose()}
           title={`Edit ${partner.code}`} size="md">
      <p className="t-bodysm muted" style={{marginTop:0, marginBottom:16}}>
        Patches the partner record. Coded fields (type, sector, status) are
        validated against their ChoiceLists server-side.
      </p>

      <div className="grid grid-2" style={{gap:12, marginBottom:12}}>
        <Field label="Code"><input value={code} onChange={e => setCode(e.target.value)} disabled={submitting}/></Field>
        <Field label="Name"><input value={name} onChange={e => setName(e.target.value)} disabled={submitting}/></Field>
      </div>

      <div className="grid grid-3" style={{gap:12, marginBottom:12}}>
        <Field label="Type">
          <select value={type} onChange={e => setType(e.target.value)} disabled={submitting}>
            {typeOpts.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Sector">
          <select value={sector} onChange={e => setSector(e.target.value)} disabled={submitting}>
            <option value="">—</option>
            {sectorOpts.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Status">
          <select value={status} onChange={e => setStatus(e.target.value)} disabled={submitting}>
            {statusOpts.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
      </div>

      <div className="grid grid-2" style={{gap:12, marginBottom:12}}>
        <Field label="Registration no"><input value={registrationNo} onChange={e => setRegistrationNo(e.target.value)} disabled={submitting}/></Field>
        <Field label="Country"><input value={country} onChange={e => setCountry(e.target.value)} disabled={submitting}/></Field>
      </div>

      <div className="grid grid-2" style={{gap:12, marginBottom:12}}>
        <Field label="Website"><input type="url" value={website} onChange={e => setWebsite(e.target.value)} disabled={submitting} placeholder="https://…"/></Field>
        <Field label="Primary email"><input type="email" value={primaryEmail} onChange={e => setPrimaryEmail(e.target.value)} disabled={submitting}/></Field>
      </div>

      <Field label="Note">
        <textarea value={note} onChange={e => setNote(e.target.value)} rows={2} disabled={submitting}/>
      </Field>

      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!canSave}
                title={!canSave ? "Code and name are required" : ""}>
          {submitting ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
};


// ── DeletePartnerConfirm (US-S11-036) ─────────────────────────────────
// Calls DELETE /api/v1/partners/{id}/. Backend FK is PROTECT so any
// DSA / Programme / Contact pointing at the partner causes a 4xx —
// the rollup numbers in the confirm pre-empt that hard-stop. Reason
// is captured client-side for the audit trail (the server doesn't
// require it but the modal does for forensic clarity).
const DeletePartnerConfirm = ({ open, partner, rollup, onClose, onDeleted, onError }) => {
  const [reason, setReason] = useStatePD("");
  const [submitting, setSubmitting] = useStatePD(false);
  React.useEffect(() => { if (open) setReason(""); }, [open]);
  if (!open || !partner) return null;

  // The hard-stop summary: surface the blocking counts the backend
  // would 4xx on, so operators don't get a vague error after typing
  // a reason.
  const blockers = [];
  if (rollup?.dsasTotal > 0) blockers.push(`${rollup.dsasTotal} DSA(s)`);
  if (rollup?.programmes > 0) blockers.push(`${rollup.programmes} programme(s)`);
  if (rollup?.contacts > 0) blockers.push(`${rollup.contacts} contact(s)`);

  const fire = async () => {
    setSubmitting(true);
    try {
      await nsrApi.delete(`/api/v1/partners/${partner.id}/`);
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
           title={`Delete ${partner.code}?`} size="sm">
      {blockers.length > 0 && (
        <div className="callout" style={{
          background:"var(--accent-danger-bg)", color:"var(--accent-danger)",
          padding:"10px 12px", borderRadius:4, marginBottom:12, fontSize:13,
        }}>
          <strong>Blocked by downstream rows:</strong> {blockers.join(" · ")}.
          The DELETE will 4xx until these are closed / re-assigned.
        </div>
      )}
      <p className="t-bodysm" style={{margin:"4px 0 12px"}}>
        Hard-deletes the Partner row. The audit chain survives the deletion;
        any AuditEvents already written remain queryable by partner code.
      </p>

      <Field label="Reason (audit only)">
        <textarea
          value={reason} onChange={e => setReason(e.target.value)}
          rows={2} disabled={submitting}
          placeholder="e.g. Partner withdrew from MGLSD — DSA closed 2026-04, no remaining commitments."
        />
      </Field>

      <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:16}}>
        <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
        <button
          className="btn"
          style={{background:"var(--accent-danger)", color:"white", borderColor:"var(--accent-danger)"}}
          onClick={fire}
          disabled={submitting || !reason.trim()}
        >
          {submitting ? "Deleting…" : "Delete partner"}
        </button>
      </div>
    </Modal>
  );
};

/* ---------- sub-stat tile in the header card ---------- */
const SubStat = ({ label, value, sub, tone, after, last }) => (
  <div style={{
    padding:'14px 20px',
    borderRight: last ? 'none' : '1px solid var(--neutral-200)',
    borderLeft: `3px solid var(--accent-${tone})`,
    background:'var(--neutral-50)',
  }}>
    <div className="t-cap">{label}</div>
    <div style={{fontSize:20, fontWeight:700, marginTop:2, color:'var(--neutral-900)', letterSpacing:'-0.01em'}}>{value}</div>
    <div className="t-cap mt-1">{sub}</div>
    {after && <div style={{marginTop:8}}>{after}</div>}
  </div>
);

const MiniUsageBar = ({ pct, over }) => (
  <div style={{height:5, background:'var(--neutral-200)', borderRadius:3, overflow:'hidden', position:'relative'}}>
    <div style={{width: Math.min(100,pct)+'%', height:'100%', background: over ? 'var(--accent-danger)' : pct>85 ? 'var(--accent-quality)' : 'var(--accent-data)'}}/>
    {over && <div style={{position:'absolute', inset:0, background:'repeating-linear-gradient(45deg,transparent,transparent 3px,rgba(255,255,255,0.35) 3px,rgba(255,255,255,0.35) 5px)'}}/>}
  </div>
);

/* ============================================================
   TAB BODIES
   ============================================================ */

/* ---------- Overview ---------- */
const PDOverview = ({ p }) => {
  const primary = p.dsas[0];
  const nextRenewal = p.dsas
    .filter(d => d.daysToExpire != null && d.daysToExpire >= 0)
    .sort((a, b) => a.daysToExpire - b.daysToExpire)[0];
  return (
  <div>
    <TabHeaderPD title="Overview"
      sub="Snapshot of the partner's current footprint inside NSR. Open any tab below for the full record."
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Snapshot PDF</button>}/>

    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>

      <KVCardPD title="Current DSAs" tint="data" action={<Chip size="sm" tone="data">{p.rollup.dsasActive} active</Chip>} rows={primary ? [
        ["Primary DSA",   <><span className="t-mono">{primary.ref}</span> · v{primary.version}</>],
        ["Status",        <Chip size="sm" tone={DSA_TONE[primary.status] || "neutral"}>{primary.status}</Chip>],
        ["Effective",     `${primary.effFrom} → ${primary.effTo}`],
        ["Monthly budget", primary.monthlyBudget ? `${pdfmt(primary.monthlyBudget)} rows / mo` : "—"],
        ["Used (30d)",    primary.monthlyBudget ? `${pdfmt(primary.used30d)} (${Math.round(primary.used30d / primary.monthlyBudget * 100)}%)` : "—"],
        ["Next renewal",  nextRenewal
          ? <><span style={{fontWeight:600}}>{nextRenewal.daysToExpire}d</span> · {nextRenewal.ref}</>
          : <span className="muted">—</span>],
      ] : [["", <span className="muted">No DSA yet — complete the registration wizard.</span>]]}/>

      <KVCardPD title="Compliance posture" tint="quality" rows={[
        ["DPIA",          p.compliance.dpia
          ? <><span className="t-mono">{p.compliance.dpia}</span>{p.compliance.dpiaUpdated ? ` · ${p.compliance.dpiaUpdated.split(" · ")[0]}` : ""}</>
          : <span className="muted">No DPIA attached</span>],
        ["Cert",          p.compliance.cert || <span className="muted">—</span>],
        ["Classification", p.compliance.classification || <span className="muted">—</span>],
        ["Retention",     p.compliance.retention ? `${p.compliance.retention} days post project close` : "—"],
        ["Breach SLA",    p.compliance.breach ? `${p.compliance.breach} hours from detection` : "—"],
        ["Sub-processors", `${p.compliance.subProcessors.length} disclosed`],
      ]}/>

      <KVCardPD title="Programmes" tint="programme" action={<Chip size="sm" tone="programme">{p.programmes.length}</Chip>} rows={p.programmes.length ? p.programmes.map(pr => [
        pr.name,
        <div className="row gap-2" style={{flexWrap:'wrap'}}>
          <Chip size="sm" tone="programme">{pr.kind}</Chip>
          <Chip size="sm" tone={PROG_TONE[pr.status] || "neutral"}>{pr.status}</Chip>
          <span className="t-cap">{pr.benef}</span>
        </div>,
      ]) : [["", <span className="muted">No programmes registered yet.</span>]]}/>

      <KVCardPD title="Key contacts" tint="identity" rows={p.contacts.length ? p.contacts.slice(0,4).map(c => [
        c.role,
        <div style={{minWidth:0}}>
          <div style={{fontWeight:500}}>{c.name} <Chip size="sm" tone="data" icon="checkCircle">verified</Chip></div>
          <div className="t-cap"><span className="t-mono">{c.email}</span> · {c.title}</div>
        </div>,
      ]) : [["", <span className="muted">Contacts endpoint not yet wired (US-S23 follow-up).</span>]]}/>

    </div>

    {/* Sparkline strip */}
    <div style={{padding:'4px 20px 20px'}}>
      <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:'14px 18px'}}>
        <div className="row gap-2" style={{justifyContent:'space-between', marginBottom:8}}>
          <strong className="t-bodysm">Rows delivered · last 30 days</strong>
          <span className="t-cap">{p.rollup.rows30d
            ? <>peak {pdfmt(Math.max(...p.rollup.spark30d))} rows · floor {pdfmt(Math.min(...p.rollup.spark30d))}</>
            : <span className="muted">no usage in window</span>}</span>
        </div>
        <BigSpark points={p.rollup.spark30d}/>
        <div className="row gap-2" style={{justifyContent:'space-between', marginTop:6}}>
          <span className="t-cap">30 days ago</span>
          <span className="t-cap">today</span>
        </div>
      </div>
    </div>
  </div>
  );
};

/* big sparkline area chart */
const BigSpark = ({ points }) => {
  const w = 1200, h = 80, pad = 2;
  const min = 0;
  const max = Math.max(...points) || 1;  // avoid divide-by-zero when no usage
  const step = (w - pad*2) / (points.length - 1);
  const pts = points.map((v, i) => [pad + i*step, pad + (h - pad*2) * (1 - (v-min)/(max-min))]);
  const path = pts.map(([x,y], i) => `${i===0?'M':'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = `${path} L${pts[pts.length-1][0]},${h} L${pts[0][0]},${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{width:'100%', height:80, display:'block'}}>
      <defs>
        <linearGradient id="pd-spark" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%"  stopColor="var(--accent-data)" stopOpacity="0.4"/>
          <stop offset="100%" stopColor="var(--accent-data)" stopOpacity="0.02"/>
        </linearGradient>
      </defs>
      <path d={fill} fill="url(#pd-spark)"/>
      <path d={path} fill="none" stroke="var(--accent-data)" strokeWidth="1.5"/>
    </svg>
  );
};

/* ---------- DSAs ---------- */
const _PD_SCOPE_EDITABLE = new Set(["draft", "active"]);
const PDDsas = ({ p, onToast, onRefresh, onEditScope, onOpenDsa, onNewDsa }) => {
  const [openIdx, setOpenIdx] = useStatePD(0);
  const [creating, setCreating] = useStatePD(false);

  const createDraftDsa = async () => {
    // If the host wired the standalone DSA wizard, route there so the
    // operator can set scope + sign-off contacts in one flow. The
    // inline draft-creation is a fallback for older mounts (kept so
    // PartnerDetailScreen still works in isolation).
    if (onNewDsa) {
      onNewDsa();
      return;
    }
    if (creating) return;
    setCreating(true);
    // Reference shape mirrors the partner-registration wizard's
    // convention: DSA-{partner.code}-{YYYY}-{seq}. The seq is the
    // count of existing DSAs +1 so we don't collide with the
    // wizard-created "...-DRAFT" placeholder.
    const seq = String((p.dsas?.length || 0) + 1).padStart(3, "0");
    const ref = `DSA-${p.code}-${new Date().getFullYear()}-${seq}`;
    try {
      const draft = await nsrApi.post("/api/v1/dsas/", {
        partner: p.id,
        reference: ref,
        status: "draft",
      });
      onToast && onToast(`Draft DSA ${draft.reference} created · open to set scope + submit for sign-off`);
      onRefresh && onRefresh();
    } catch (err) {
      onToast && onToast(`Couldn't create DSA: ${err.body?.detail || err.message || err}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <TabHeaderPD title={`Data Sharing Agreements — ${p.dsas.length}`}
        sub="Open any DSA to inspect its scope, signature chain, and version history. Scope edits route through the DSA editor (Sprint 27)."
        action={<>
          <button className="btn btn-sm"
                  onClick={() => onToast && onToast("DSA register export not yet wired (OI-S27 candidate).")}>
            <Icon name="download" size={13}/> Export DSA register
          </button>
          <button className="btn btn-sm btn-primary" onClick={createDraftDsa} disabled={creating}>
            <Icon name="plus" size={13}/> {creating ? "Creating…" : "New DSA"}
          </button>
        </>}/>

      <div>
        {p.dsas.length === 0 && (
          <div style={{padding:'24px 20px'}} className="muted t-bodysm">
            No DSAs on file. Use the wizard to create one.
          </div>
        )}
        {p.dsas.map((d, i) => {
          const open = i === openIdx;
          const usedPct = d.monthlyBudget
            ? Math.round(d.used30d / d.monthlyBudget * 100)
            : 0;
          return (
            <div key={d.ref} style={{borderBottom:'1px solid var(--neutral-200)'}}>

              {/* DSA row */}
              <div onClick={() => setOpenIdx(open ? -1 : i)} style={{padding:'16px 20px', display:'grid', gridTemplateColumns:'auto 1fr auto auto auto auto', gap:18, alignItems:'center', cursor:'pointer'}}>
                <Icon name={open ? "chevronDown" : "chevronRight"} size={14} color="var(--neutral-700)"/>
                <div style={{minWidth:0}}>
                  <div className="row gap-2">
                    <strong className="t-mono" style={{fontSize:13.5}}>{d.ref}</strong>
                    <Chip size="sm" tone="neutral">v{d.version}</Chip>
                  </div>
                  <div className="t-cap">{d.programme} · {d.effFrom} → {d.effTo}</div>
                </div>
                <div style={{minWidth:140}}>
                  <div className="row gap-2" style={{justifyContent:'space-between', marginBottom:2}}>
                    <span className="t-mono" style={{fontSize:12.5}}>{pdfmt(d.used30d)}</span>
                    <span className="t-cap">/ {pdfmt(d.monthlyBudget)}</span>
                  </div>
                  <MiniUsageBar pct={usedPct} over={d.used30d > d.monthlyBudget}/>
                </div>
                <div>
                  <div className="t-cap">Renews</div>
                  <div className="t-bodysm" style={{fontWeight:600, color: d.daysToExpire <= 60 ? 'var(--accent-quality)' : 'var(--neutral-900)'}}>{d.daysToExpire}d</div>
                </div>
                <div>
                  <SignProgress sigs={d.signatures}/>
                </div>
                <Chip tone={DSA_TONE[d.status]}>{d.status}</Chip>
              </div>

              {/* expanded */}
              {open && (
                <div style={{padding:'4px 20px 24px', background:'var(--neutral-50)', borderTop:'1px solid var(--neutral-200)'}}>
                  <div style={{display:'grid', gridTemplateColumns:'1.2fr 1fr', gap:16, paddingTop:16}}>

                    <KVCardPD title="Scope" tint="data" rows={[
                      ["Entities",      <div className="row-wrap">{d.entities.map(e => <Chip key={e} size="sm" tone="data">{e}</Chip>)}</div>],
                      ["Field groups",  <div className="row-wrap">{d.fieldGroups.map(f => <Chip key={f} size="sm">{f}</Chip>)}</div>],
                      ["Geography",     <div className="row-wrap">{d.geo.map(g => <Chip key={g} size="sm" tone="neutral">{g}</Chip>)}</div>],
                      ["Sensitive",     d.sensitive === "none" ? "Blocked — clause 4.2.b" : d.sensitive === "specific" ? "Specific clause" : "Case-by-case"],
                      ["Classification", d.classification],
                      ["Retention",     `${d.retention}d post project close`],
                      ["Breach SLA",    `${d.breach}h from detection`],
                    ]}/>

                    <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0}}>
                      <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', fontSize:14, fontWeight:600}}>Sign-off chain</div>
                      <div>
                        {d.signatures.map((s, j) => (
                          <div key={j} style={{display:'grid', gridTemplateColumns:'28px 1fr auto', gap:12, alignItems:'center', padding:'12px 16px', borderTop: j === 0 ? 'none' : '1px solid var(--neutral-200)'}}>
                            <span style={{
                              width:26, height:26, borderRadius:'50%', display:'grid', placeItems:'center',
                              fontSize:11, fontWeight:600,
                              background: s.status === "Signed" ? 'var(--primary-900)' : 'var(--neutral-100)',
                              color: s.status === "Signed" ? 'white' : 'var(--neutral-700)',
                              border: s.status === "Signed" ? 0 : '1px solid var(--neutral-300)',
                            }}>{s.status === "Signed" ? <Icon name="check" size={12}/> : j+1}</span>
                            <div>
                              <div className="t-bodysm" style={{fontWeight:500}}>{s.name}</div>
                              <div className="t-cap">{s.role} · {s.at}</div>
                            </div>
                            <Chip size="sm" tone={SIG_TONE[s.status]}>{s.status}</Chip>
                          </div>
                        ))}
                      </div>
                      <div style={{padding:'10px 16px', background:'var(--neutral-100)', borderTop:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:8}}>
                        <Icon name="file" size={13} color="var(--neutral-700)"/>
                        <span className="t-bodysm" style={{flex:1}}>Signed PDF in vault · <span className="t-mono">{d.ref}.pdf</span></span>
                        <button className="btn btn-sm btn-ghost">Preview</button>
                      </div>
                    </div>
                  </div>

                  <div className="row gap-2 mt-4" style={{justifyContent:'flex-end'}}>
                    {onOpenDsa && d.id && (
                      <button className="btn btn-sm btn-primary" onClick={() => onOpenDsa(d.id)}>
                        <Icon name="arrowRight" size={13}/> Open in workspace
                      </button>
                    )}
                    <button className="btn btn-sm"><Icon name="history" size={13}/> Version history</button>
                    <button className="btn btn-sm"
                            disabled={!_PD_SCOPE_EDITABLE.has(d.status_code)}
                            title={_PD_SCOPE_EDITABLE.has(d.status_code)
                              ? undefined
                              : `Scope edit not available in status "${d.status}". Only draft + active DSAs are editable (ADR-0016).`}
                            onClick={() => onEditScope && onEditScope(d)}>
                      <Icon name="edit" size={13}/> {d.status_code === "active" ? "Propose scope edit" : "Edit scope"}
                    </button>
                    <button className="btn btn-sm"><Icon name="refresh" size={13}/> Start renewal</button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* signature progress dots */
const SignProgress = ({ sigs }) => {
  const done = sigs.filter(s => s.status === "Signed").length;
  return (
    <div className="row gap-2">
      <div className="row gap-1">
        {sigs.map((s, i) => (
          <span key={i} style={{
            width:10, height:10, borderRadius:'50%',
            background: s.status === "Signed" ? 'var(--accent-data)' :
                        s.status === "Sent"   ? 'var(--accent-quality)' :
                        s.status === "Declined" ? 'var(--accent-danger)' :
                        'var(--neutral-300)',
          }}/>
        ))}
      </div>
      <span className="t-cap">{done}/{sigs.length}</span>
    </div>
  );
};

/* ---------- Programmes ---------- */
const PDProgrammes = ({ p, onRegisterProgramme }) => (
  <div>
    <TabHeaderPD title={`Programmes — ${p.programmes.length}`}
      sub="Each programme is M2M-scoped under a DSA (ADR-0011). Adding a programme requires the existing DSA to allow it; otherwise a new DSA is drafted."
      action={<button className="btn btn-sm btn-primary" onClick={onRegisterProgramme}><Icon name="plus" size={13}/> Add programme</button>}/>
    <div>
      {p.programmes.length === 0 && (
        <div style={{padding:'24px 20px'}} className="muted t-bodysm">
          No programmes yet for this partner. Click <strong>Add programme</strong> to launch the registration wizard (US-S25).
        </div>
      )}
      {p.programmes.map((pr, i) => (
        <div key={i} style={{padding:'18px 20px', borderBottom: i < p.programmes.length-1 ? '1px solid var(--neutral-200)' : 'none'}}>
          <div className="row gap-3" style={{alignItems:'flex-start', marginBottom:12}}>
            <div style={{width:36, height:36, borderRadius:6, background:'var(--accent-programme-bg)', color:'var(--accent-programme)', display:'grid', placeItems:'center', flexShrink:0}}>
              <Icon name="book" size={18}/>
            </div>
            <div style={{flex:1, minWidth:0}}>
              <div className="row gap-2">
                <strong style={{fontSize:15}}>{pr.name}</strong>
                <Chip size="sm" tone="programme">{pr.kind}</Chip>
                <Chip size="sm" tone={PROG_TONE[pr.status]}>{pr.status}</Chip>
              </div>
              <div className="t-cap mt-1">{pr.scope} · {pr.benef} · {pr.start} → {pr.end}</div>
            </div>
            <button className="btn btn-sm btn-ghost"><Icon name="edit" size={13}/></button>
            <button className="btn btn-sm btn-ghost"><Icon name="moreH" size={13}/></button>
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, paddingLeft:48}}>
            <Pill label="Cash rail" value={pr.cashRail} tone="data"/>
            <Pill label="Targeting" value={pr.targeting} tone="eligibility"/>
            <Pill label="Cycle" value={pr.cycle} tone="update"/>
            <Pill label="Under DSA"
              value={pr.dsa_reference
                || (p.dsas[0] && p.dsas[0].ref)
                || "—"}
              tone="programme"/>
          </div>
        </div>
      ))}
    </div>
  </div>
);

const Pill = ({ label, value, tone }) => (
  <div style={{padding:'8px 12px', border:'1px solid var(--neutral-200)', borderRadius:4, background:'var(--neutral-0)', borderLeft:`3px solid var(--accent-${tone})`}}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm" style={{fontWeight:500, marginTop:2}}>{value}</div>
  </div>
);

/* ---------- Contacts ---------- */
const PDContacts = ({ p }) => (
  <div>
    <TabHeaderPD title={`Contacts — ${p.contacts.length}`}
      sub="Four roles are mandatory per ADR-0012: Authorised Signatory · Data Steward · Partner DPO · IT/Security. NIN trio stored encrypted (ADR-0002)."
      action={<button className="btn btn-sm"><Icon name="plus" size={13}/> Add contact</button>}/>
    {p.contacts.length === 0 && (
      <div style={{padding:'24px 20px'}} className="muted t-bodysm">
        Contacts endpoint is not yet wired
        (PartnerContact list lands in a US-S23 follow-up). The model
        exists — add rows via /admin/partners/partnercontact/.
      </div>
    )}
    <div style={{padding:20, display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
      {p.contacts.map((c, i) => (
        <div key={i} className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0}}>
          <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between'}}>
            <div className="t-cap" style={{fontWeight:600, color:'var(--primary-900)', letterSpacing:'0.06em'}}>{c.role.toUpperCase()}</div>
            {c.verified && <Chip size="sm" tone="data" icon="checkCircle">NIN verified</Chip>}
          </div>
          <div style={{padding:14}}>
            <div className="row gap-3" style={{marginBottom:10}}>
              <div style={{width:40, height:40, borderRadius:'50%', background:'var(--neutral-100)', color:'var(--neutral-700)', display:'grid', placeItems:'center', fontWeight:600, fontSize:14, flexShrink:0}}>
                {c.name.split(" ").slice(0,2).map(n => n[0]).join("")}
              </div>
              <div style={{minWidth:0, flex:1}}>
                <div style={{fontWeight:600, fontSize:14}}>{c.name}</div>
                <div className="t-cap">{c.title}</div>
              </div>
              <button className="btn btn-sm btn-ghost"><Icon name="edit" size={13}/></button>
            </div>
            <div style={{display:'grid', gridTemplateColumns:'80px 1fr', gap:6, fontSize:13}}>
              <div className="muted">Email</div><div className="t-mono" style={{fontSize:12.5}}>{c.email}</div>
              <div className="muted">Phone</div><div className="t-mono" style={{fontSize:12.5}}>{c.phone}</div>
              <div className="muted">NIN</div><div className="t-mono" style={{fontSize:12.5}}>{c.ninLast4}</div>
            </div>
            <div className="mt-3" style={{padding:'8px 10px', background:'var(--neutral-50)', border:'1px dashed var(--neutral-300)', borderRadius:4, display:'flex', alignItems:'center', gap:8}}>
              <Icon name="file" size={14} color="var(--neutral-700)"/>
              <span className="t-bodysm" style={{flex:1}}>{c.doc}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  </div>
);

/* ---------- Usage ---------- */
const PDUsage = ({ p }) => {
  const max = Math.max(...p.rollup.spark30d) || 0;
  const dailyBudget = p.rollup.monthlyBudget
    ? Math.round(p.rollup.monthlyBudget / 30)
    : 0;
  const avg = p.rollup.requests30d
    ? Math.round(p.rollup.rows30d / p.rollup.requests30d)
    : 0;
  return (
    <div>
      <TabHeaderPD title="Usage — last 30 days"
        sub="Rows delivered per day. Quota budget is the partner's monthly DSA cap divided by 30. AC-DPO-VOL fires when 30d total exceeds budget."
        action={<>
          <select className="field-select btn-sm" style={{height:30, width:140}}><option>Last 30 days</option><option disabled>Last 90 days</option><option disabled>Year-to-date</option></select>
          <button className="btn btn-sm"><Icon name="download" size={13}/> Export CSV</button>
        </>}/>
      <div style={{padding:20}}>

        {/* chart */}
        <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:'18px 20px', marginBottom:16}}>
          <div className="row gap-3" style={{justifyContent:'space-between', marginBottom:12, alignItems:'flex-end'}}>
            <div>
              <div className="t-cap">TOTAL ROWS · 30D</div>
              <div style={{fontSize:24, fontWeight:700}}>{pdfmt(p.rollup.rows30d)}</div>
              <div className="t-cap mt-1">{p.rollup.requests30d} requests{avg ? ` · avg ${pdfmt(avg)} rows/request` : ""}</div>
            </div>
            <div className="row gap-4">
              <div><div className="t-cap">PEAK</div><div className="t-mono" style={{fontWeight:600, fontSize:15}}>{pdfmt(max)}</div></div>
              <div><div className="t-cap">BUDGET</div><div className="t-mono" style={{fontWeight:600, fontSize:15}}>{p.rollup.monthlyBudget ? pdfmt(p.rollup.monthlyBudget) : "—"}</div></div>
              <div><div className="t-cap">USED</div><div className="t-mono" style={{fontWeight:600, fontSize:15, color:'var(--accent-data)'}}>{p.rollup.budgetUsedPct}%</div></div>
            </div>
          </div>
          <UsageBars points={p.rollup.spark30d} budget={dailyBudget}/>
        </div>

        {/* top requests — placeholder until DRS exposes a structured
            delivery event (TODO in apps/partners/tasks.py rollup). */}
        <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:'14px 20px'}}>
          <strong className="t-bodysm">Top requests · last 30 days</strong>
          <div className="t-cap mt-1 muted">
            Per-request breakdown lands when DRS exposes a structured
            delivery event. Today the rollup reads aggregate counts from the
            AuditEvent reason text (see apps/partners/tasks.py).
          </div>
        </div>
      </div>
    </div>
  );
};

/* bar chart */
const UsageBars = ({ points, budget }) => {
  const max = Math.max(...points, budget) || 1;  // avoid div-by-zero
  return (
    <div style={{position:'relative', height:140}}>
      {/* budget line — hidden when there's no budget to compare against */}
      {budget > 0 && (
        <div style={{position:'absolute', left:0, right:0, top: (1 - budget/max) * 100 + '%', borderTop:'1px dashed var(--accent-quality)'}}>
          <span className="t-cap" style={{position:'absolute', right:0, top:-16, background:'white', padding:'1px 4px', color:'var(--accent-quality)', fontWeight:600}}>budget {pdfmt(budget)}/d</span>
        </div>
      )}
      <div style={{display:'flex', alignItems:'flex-end', gap:3, height:'100%'}}>
        {points.map((v, i) => {
          const h = (v/max) * 100;
          const over = v > budget;
          return (
            <div key={i} style={{flex:1, height:'100%', display:'flex', alignItems:'flex-end'}} title={`Day ${i+1}: ${pdfmt(v)} rows`}>
              <div style={{width:'100%', height: h + '%', background: over ? 'var(--accent-quality)' : 'var(--accent-data)', borderRadius:'2px 2px 0 0'}}/>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* ---------- Activity ---------- */
const PDActivity = ({ p }) => (
  <div>
    <TabHeaderPD title="Recent activity"
      sub="Partner-scoped audit feed. Sourced from /api/v1/partners/{id}/activity/ — tamper-evident chain."
      action={<>
        <select className="field-select btn-sm" style={{height:30, width:140}}><option>All actions</option><option>DRS only</option><option>DSA only</option><option>Compliance</option></select>
        <button className="btn btn-sm"><Icon name="download" size={13}/> Export</button>
      </>}/>
    <div>
      {p.activity.length === 0 && (
        <div style={{padding:'24px 20px'}} className="muted t-bodysm">
          No activity events on this partner yet.
        </div>
      )}
      {p.activity.map((a, i) => (
        <div key={i} className="row gap-3" style={{padding:'14px 20px', borderBottom: i < p.activity.length-1 ? '1px solid var(--neutral-200)' : 'none', alignItems:'flex-start'}}>
          <div style={{width:60, flexShrink:0}}>
            <Chip size="sm" tone={a.tone}>{a.who}</Chip>
          </div>
          <div style={{flex:1, minWidth:0}}>
            <div className="row gap-2">
              <strong className="t-body">{a.action}</strong>
            </div>
            <div className="t-bodysm muted" style={{marginTop:2}}>{a.detail}</div>
          </div>
          <div className="col" style={{alignItems:'flex-end', gap:6}}>
            <Chip tone={a.tone}>{a.chip}</Chip>
            <span className="t-cap">{a.time}</span>
          </div>
        </div>
      ))}
    </div>
  </div>
);

/* ---------- Compliance ---------- */
const PDCompliance = ({ p }) => (
  <div>
    <TabHeaderPD title="Compliance posture"
      sub="Per §6 of the Data Protection and Privacy Act 2019 (Uganda). DPIA must be ≤ 12 months old; cert verified out of band."
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Export attestation pack</button>}/>

    <div style={{padding:20, display:'grid', gridTemplateColumns:'1.2fr 1fr', gap:16}}>
      <KVCardPD title="Posture" tint="quality" rows={[
        ["DPIA",            <><span className="t-mono">{p.compliance.dpia}</span><div className="t-cap mt-1">{p.compliance.dpiaSize} · {p.compliance.dpiaUpdated}</div></>],
        ["Security cert",   p.compliance.cert],
        ["Classification",  p.compliance.classification],
        ["Retention",       `${p.compliance.retention} days post project close`],
        ["Breach SLA",      `${p.compliance.breach} hours from detection → NSR DPO`],
      ]}/>

      <div className="card" style={{boxShadow:'none', border:'1px solid var(--neutral-200)', padding:0}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', fontSize:14, fontWeight:600}}>Sub-processors disclosed</div>
        <div>
          {p.compliance.subProcessors.map((s, i) => (
            <div key={i} style={{padding:'10px 16px', display:'flex', alignItems:'center', gap:10, borderTop: i === 0 ? 'none' : '1px solid var(--neutral-200)'}}>
              <Icon name="database" size={14} color="var(--neutral-700)"/>
              <div style={{flex:1}}>
                <div className="t-bodysm" style={{fontWeight:500}}>{s.name}</div>
                <div className="t-cap">{s.role}</div>
              </div>
              {s.attested && <Chip size="sm" tone="data" icon="checkCircle">attested</Chip>}
            </div>
          ))}
        </div>
      </div>
    </div>

    <div style={{padding:'0 20px 20px'}}>
      <div className="card" style={{boxShadow:'none', border:'1px solid var(--accent-data)', borderLeft:'3px solid var(--accent-data)', padding:0}}>
        <div style={{padding:'12px 16px', borderBottom:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:8}}>
          <Icon name="shield" size={15} color="var(--accent-data)"/>
          <strong>Signed attestations</strong>
          <span className="t-cap">· captured at sign-off</span>
        </div>
        <div>
          {p.compliance.attestations.map((a, i) => (
            <div key={i} style={{padding:'12px 16px', display:'flex', alignItems:'flex-start', gap:10, borderTop: i === 0 ? 'none' : '1px solid var(--neutral-200)'}}>
              <Icon name="checkCircle" size={15} color="var(--accent-data)" style={{marginTop:2, flexShrink:0}}/>
              <div style={{flex:1}}>
                <div className="t-bodysm">{a.txt}</div>
                <div className="t-cap mt-1">{a.at}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  </div>
);

/* ---------- Documents ---------- */
const PDDocuments = ({ p }) => (
  <div>
    <TabHeaderPD title={`Documents — ${p.documents.length}`}
      sub="DSAs, DPIAs, certifications, authorisation letters. All file references resolve to the secure document vault."
      action={<button className="btn btn-sm"><Icon name="download" size={13}/> Download all (zip)</button>}/>
    {p.documents.length === 0 && (
      <div style={{padding:'24px 20px'}} className="muted t-bodysm">
        Document vault endpoint is not yet wired (DRS-O-02 / MinIO).
        DSA + DPIA reference strings live on the DSA row's
        dpia_document_ref + future SupportingDoc FK.
      </div>
    )}
    {p.documents.length > 0 && <table className="tbl">
      <thead><tr>
        <th>File</th>
        <th>Kind</th>
        <th>Size</th>
        <th>Uploaded</th>
        <th>By</th>
        <th className="col-actions"></th>
      </tr></thead>
      <tbody>
        {p.documents.map(d => (
          <tr key={d.name}>
            <td>
              <div className="row gap-2">
                <Icon name="file" size={14} color="var(--neutral-700)"/>
                <span className="t-mono" style={{fontSize:12.5}}>{d.name}</span>
              </div>
            </td>
            <td><Chip size="sm" tone={d.kind === "DSA" ? "data" : d.kind === "DPIA" ? "quality" : d.kind === "Cert" ? "identity" : "neutral"}>{d.kind}</Chip></td>
            <td className="t-cap">{d.size}</td>
            <td className="t-cap">{d.at}</td>
            <td className="t-cap">{d.actor}</td>
            <td className="col-actions">
              <button className="btn btn-sm btn-ghost" title="Preview"><Icon name="eye" size={13}/></button>
              <button className="btn btn-sm btn-ghost" title="Download"><Icon name="download" size={13}/></button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>}
  </div>
);

/* ---------- Audit ----------
   The Activity tab (PDActivity) renders the partner-scoped
   projection over AuditEvent. This Audit tab surfaces a raw, hash-
   chained view — the dedicated endpoint
   GET /api/v1/security/audit/?entity_type=partner&entity_id=...
   lands in a follow-up; for now this tab is a placeholder.
*/
const PDAudit = ({ p }) => (
  <div>
    <TabHeaderPD title="Audit chain"
      sub="Tamper-evident event chain · partner-scoped. The dedicated audit endpoint (apps.security) is a US-S23 follow-up; use the Activity tab for the projection-over-AuditEvent feed in the meantime."
      action={<button className="btn btn-sm" disabled><Icon name="download" size={13}/> Export chain</button>}/>
    <div style={{padding:'24px 20px'}} className="muted t-bodysm">
      No audit-chain payload yet — wire
      <span className="t-mono" style={{margin:'0 4px'}}>GET /api/v1/security/audit/?entity_type=partner&amp;entity_id={p.code}</span>
      in the follow-up. The hash-chained AuditEvent rows already exist for every DSA / signature transition;
      this tab just needs the join.
    </div>
  </div>
);

/* ============================================================
   Export
   ============================================================ */
Object.assign(window, { PartnerDetailScreen });
