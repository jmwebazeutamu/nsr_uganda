/* global React,
   Icon, Chip, KPI, Field, Modal, Toast, PageHeader, AuditDrawer, ActionBar,
   ConsentStateChip, TicketStateChip, BasisChip,
   PURPOSE_BY_CODE, ConsentSectionLabel, StoryTag */
// NSR MIS — Consent Management · Screen 4
// DPO withdrawal review queue (US-S26-CONSENT-DPO-WITHDRAWAL-QUEUE)
// Queue + three-column detail, mirroring the 11.3 DIH review pattern.

const { useState: useStateDQ, useMemo: useMemoDQ } = React;

const SLA_DAYS = 30;

/* ---------- Queue rows ---------- */
const TICKETS = [
  { id: "WD-2026-04420", hh: "HH-7411-0231", member: "Nakato Sarah",  purpose: "REFERRAL",            channel: "USSD", daysOpen: 27, state: "In DPO review", assignee: "You",          referrals: 0, smsSubs: 1, extracts: 0, origin: "Citizen" },
  { id: "WD-2026-04450", hh: "HH-8821-0144", member: "Auma Florence", purpose: "RESEARCH",            channel: "Web",  daysOpen: 28, state: "Open",          assignee: "—",            referrals: 0, smsSubs: 0, extracts: 2, origin: "Citizen" },
  { id: "WD-2026-04417", hh: "HH-7411-0192", member: "Lokol Moses",   purpose: "PAYMENTS",            channel: "Web",  daysOpen: 4,  state: "Open",          assignee: "—",            referrals: 1, smsSubs: 1, extracts: 0, origin: "Citizen" },
  { id: "WD-2026-04422", hh: "HH-7411-0250", member: "Mugisha James", purpose: "ELIGIBILITY",          channel: "Web", daysOpen: 8,  state: "In DPO review", assignee: "You",          referrals: 0, smsSubs: 0, extracts: 0, origin: "Citizen" },
  { id: "WD-2026-04431", hh: "HH-3920-1101", member: "Okello Peter",  purpose: "REFERRAL",            channel: "OPM-PDM", daysOpen: 2, state: "Open",        assignee: "—",            referrals: 0, smsSubs: 0, extracts: 0, origin: "Bulk DIH" },
  { id: "WD-2026-04432", hh: "HH-3920-1102", member: "Adong Mary",    purpose: "REFERRAL",            channel: "OPM-PDM", daysOpen: 2, state: "Open",        assignee: "—",            referrals: 0, smsSubs: 0, extracts: 0, origin: "Bulk DIH" },
  { id: "WD-2026-04433", hh: "HH-3920-1108", member: "Ojok Samuel",   purpose: "REFERRAL",            channel: "OPM-PDM", daysOpen: 2, state: "Open",        assignee: "—",            referrals: 0, smsSubs: 0, extracts: 0, origin: "Bulk DIH" },
  { id: "WD-2026-04409", hh: "HH-5510-0307", member: "Akello Grace",  purpose: "COMMUNICATIONS_SMS",  channel: "Web",  daysOpen: 11, state: "Clarification requested", assignee: "You",  referrals: 0, smsSubs: 1, extracts: 0, origin: "Citizen" },
  { id: "WD-2026-04398", hh: "HH-6620-0091", member: "Tumusiime John",purpose: "PAYMENTS",            channel: "Parish desk", daysOpen: 19, state: "Confirmed", assignee: "Nabbanja S.", referrals: 0, smsSubs: 0, extracts: 0, origin: "Citizen" },
];

const QUICK_FILTERS = [
  { id: "sla", label: "SLA breach risk (under 5 days)", icon: "clock",  tone: "danger" },
  { id: "publicTask", label: "Public-task purposes",     icon: "lock",   tone: "identity" },
  { id: "bulk", label: "Bulk DIH-origin",                icon: "inbox",  tone: "update" },
];

const remaining = (t) => SLA_DAYS - t.daysOpen;
// Null-safe purpose lookup — a ticket may reference a purpose code not in the
// current catalogue (vocabulary drift); fall back to a Consent-basis default
// rather than crashing.
const purposeOf = (code) => PURPOSE_BY_CODE[code] || { name: code, basis: "Consent", withdrawable: true };
const isPublicTask = (t) => purposeOf(t.purpose).basis !== "Consent";
const isOpenState = (t) => t.state === "Open" || t.state === "In DPO review" || t.state === "Clarification requested";

/* ============================================================
   Decision panel (Column 3)
   ============================================================ */
const DECISIONS = [
  { id: "confirm",  label: "Confirm withdrawal",   icon: "checkCircle", tone: "data",     hint: "Set the consent record to Withdrawn and stop downstream use." },
  { id: "override", label: "Override (public task)",icon: "lock",       tone: "identity", hint: "Keep processing under a public-task basis; record the override." },
  { id: "clarify",  label: "Request clarification", icon: "message",    tone: "quality",  hint: "Send the citizen an SMS asking for more detail." },
  { id: "hold",     label: "Hold for clarification",icon: "pause",      tone: "quality",  hint: "Pause the SLA clock pending internal input." },
];

const DecisionPanel = ({ ticket, onDecide }) => {
  const [choice, setChoice] = useStateDQ(isPublicTask(ticket) ? "override" : "confirm");
  const [note, setNote] = useStateDQ("");
  const [doc, setDoc] = useStateDQ(false);
  const decided = !isOpenState(ticket);
  const canApply = !decided && choice && note.trim().length >= 6;

  return (
    <div className="col gap-4">
      {isPublicTask(ticket) && (
        <div className="row gap-2" style={{
          padding: "9px 11px", background: "var(--accent-identity-bg)",
          border: "1px solid rgba(106,27,154,0.25)", borderRadius: "var(--radius-default)",
        }}>
          <Icon name="lock" size={15} color="var(--accent-identity)"/>
          <div className="t-cap" style={{ color: "var(--neutral-700)" }}>
            This purpose runs on a <strong>{purposeOf(ticket.purpose).basis}</strong> basis. Confirming withdrawal is
            not normally available — use <strong>Override</strong> and cite the DPPA provision.
          </div>
        </div>
      )}
      <div className="col gap-2">
        {DECISIONS.map(d => {
          const active = choice === d.id;
          const accent = `var(--accent-${d.tone === "data" ? "data" : d.tone})`;
          const disabled = d.id === "confirm" && isPublicTask(ticket);
          return (
            <button key={d.id} role="radio" aria-checked={active} disabled={decided || disabled}
              onClick={() => setChoice(d.id)} style={{
                display: "flex", gap: 10, alignItems: "flex-start", textAlign: "left", width: "100%",
                padding: "10px 12px", borderRadius: "var(--radius-default)",
                border: `1.5px solid ${active ? accent : "var(--neutral-300)"}`,
                background: active ? `var(--accent-${d.tone === "data" ? "data" : d.tone}-bg)` : "var(--neutral-0)",
                cursor: (decided || disabled) ? "not-allowed" : "pointer", opacity: disabled ? 0.45 : 1,
              }}>
              <Icon name={d.icon} size={16} color={active ? accent : "var(--neutral-500)"} style={{ marginTop: 1 }}/>
              <span style={{ flex: 1 }}>
                <span style={{ display: "block", fontWeight: 600, fontSize: 13 }}>{d.label}</span>
                <span style={{ display: "block", fontSize: 12, color: "var(--neutral-500)", marginTop: 1 }}>{d.hint}</span>
              </span>
            </button>
          );
        })}
      </div>

      <Field label="Decision reason" required hint="Written to the audit chain (min 6 chars).">
        <textarea className="field-textarea" rows={3} value={note} disabled={decided}
          onChange={(e) => setNote(e.target.value)}
          placeholder={choice === "override" ? "e.g. Processing continues under DPPA 2019 §7(2)(b)(i); citizen notified." : "Explain the decision for the audit record."}/>
      </Field>

      <div className="col gap-2">
        <label className="field-label">Decision document</label>
        <label className="row gap-2" style={{
          padding: "10px 12px", border: "1px dashed var(--neutral-300)", borderRadius: "var(--radius-default)",
          cursor: decided ? "not-allowed" : "pointer", background: "var(--neutral-50)",
        }}>
          <Icon name={doc ? "checkCircle" : "download"} size={15} color={doc ? "var(--accent-data)" : "var(--neutral-500)"}/>
          <span className="t-bodysm" style={{ flex: 1 }}>{doc ? "decision-letter.pdf attached" : "Attach signed decision letter (optional)"}</span>
          <input type="file" hidden disabled={decided} onChange={(e) => setDoc(!!e.target.files?.length)}/>
        </label>
      </div>

      {/* Signature line */}
      <div>
        <div className="t-cap" style={{ marginBottom: 4 }}>Decided by</div>
        <div style={{
          padding: "10px 12px", border: "1px solid var(--neutral-200)", borderRadius: "var(--radius-default)",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <div style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--primary-100)", color: "var(--primary-900)", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 12 }}>SN</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>Nabbanja Sarah</div>
            <div className="t-cap">Data Protection Officer · NSR</div>
          </div>
          <Icon name="shield" size={15} color="var(--accent-system)"/>
        </div>
      </div>

      {decided ? (
        <div className="row gap-2 t-bodysm" style={{ color: "var(--neutral-500)" }}>
          <Icon name="info" size={14}/> This ticket is {ticket.state.toLowerCase()} — no further decision required.
        </div>
      ) : (
        <button className={`btn ${choice === "override" ? "btn-primary" : choice === "confirm" ? "btn-success" : "btn-warn"}`}
          disabled={!canApply} onClick={() => onDecide?.(choice, note)} style={{ justifyContent: "center" }}>
          <Icon name="check" size={15}/> Apply decision
        </button>
      )}
    </div>
  );
};

/* ============================================================
   MAIN — DPO withdrawal queue
   ============================================================ */
const DpoWithdrawalQueueScreen = () => {
  const [rows, setRows] = useStateDQ(TICKETS);
  const [selectedId, setSelectedId] = useStateDQ(TICKETS[0].id);
  const [quick, setQuick] = useStateDQ(null);
  const [sel, setSel] = useStateDQ(new Set());
  const [auditOpen, setAuditOpen] = useStateDQ(false);
  const [toast, setToast] = useStateDQ("");

  const filtered = useMemoDQ(() => rows.filter(t => {
    if (quick === "sla") return isOpenState(t) && remaining(t) < 5;
    if (quick === "publicTask") return isPublicTask(t);
    if (quick === "bulk") return t.origin === "Bulk DIH";
    return true;
  }), [rows, quick]);

  const current = useMemoDQ(() => rows.find(t => t.id === selectedId), [rows, selectedId]);
  const purpose = current ? purposeOf(current.purpose) : null;

  // Bulk eligibility: Confirm only, same Consent-basis purpose, zero active referrals, open state.
  const selRows = rows.filter(t => sel.has(t.id));
  const bulkPurposes = new Set(selRows.map(t => t.purpose));
  const bulkEligible = selRows.length > 0
    && bulkPurposes.size === 1
    && selRows.every(t => isOpenState(t) && t.referrals === 0 && !isPublicTask(t));
  const bulkReason = selRows.length === 0 ? ""
    : bulkPurposes.size > 1 ? "Tickets must share one purpose"
    : selRows.some(t => t.referrals > 0) ? "Some tickets have active referrals"
    : selRows.some(t => isPublicTask(t)) ? "Public-task tickets need individual override"
    : selRows.some(t => !isOpenState(t)) ? "Some tickets are already decided"
    : selRows.length > 50 ? "Maximum 50 per batch" : "";

  const toggleSel = (id) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const applyDecision = (choice) => {
    const map = { confirm: "Confirmed", override: "Public-task override", clarify: "Clarification requested", hold: "In DPO review" };
    setRows(rs => rs.map(t => t.id === selectedId ? { ...t, state: map[choice], assignee: "You" } : t));
    setToast(`${current.id} — ${map[choice].toLowerCase()}.`);
  };
  const applyBulk = () => {
    setRows(rs => rs.map(t => sel.has(t.id) ? { ...t, state: "Confirmed", assignee: "You" } : t));
    setToast(`${selRows.length} tickets confirmed (${[...bulkPurposes][0]}).`);
    setSel(new Set());
  };

  const auditEvents = current ? [
    { who: current.member, action: "requested withdrawal", detail: `${purpose.name} · via ${current.channel}`, time: `${current.daysOpen}d ago`, audit: "AC-7C8810" },
    { who: "System", action: "opened ticket", detail: `SLA clock started · ${SLA_DAYS}-day statutory deadline`, time: `${current.daysOpen}d ago`, audit: "AC-7C8811", tone: "system" },
    { who: "System", action: "computed impact", detail: `${current.referrals} active referral(s) · ${current.smsSubs} SMS subscription(s) · ${current.extracts} pending extract(s)`, time: `${current.daysOpen}d ago`, audit: "AC-7C8812", tone: "system" },
  ] : [];

  return (
    <div style={{ position: "relative" }}>
      <PageHeader
        eyebrow={<>SEC · CONSENT · WITHDRAWAL QUEUE &nbsp;<StoryTag>US-S26-CONSENT-DPO-WITHDRAWAL-QUEUE</StoryTag></>}
        title={<span className="row gap-3">DPO withdrawal queue <Chip tone="quality">{rows.filter(isOpenState).length} open</Chip></span>}
        sub={<>Statutory decision window is <strong>30 days</strong> from request. Confirm, override, or ask the citizen for clarification.</>}
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history" size={14}/> Audit</button>
          <button className="btn"><Icon name="download" size={14}/> Export</button>
        </>}/>

      {/* KPI strip */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <KPI title="Open tickets" value={rows.filter(isOpenState).length} foot="across all purposes"/>
        <KPI title="SLA breach risk" value={rows.filter(t => isOpenState(t) && remaining(t) < 5).length} trend="down" trendValue="under 5 days" foot="needs action"/>
        <KPI title="Avg days to decision" value="8.4" suffix="d" trend="up" trendValue="within SLA"/>
        <KPI title="Bulk DIH-origin" value={rows.filter(t => t.origin === "Bulk DIH" && isOpenState(t)).length} foot="batch-eligible"/>
      </div>

      {/* Quick filters */}
      <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        {QUICK_FILTERS.map(q => {
          const active = quick === q.id;
          return (
            <button key={q.id} onClick={() => setQuick(active ? null : q.id)} style={{
              display: "inline-flex", alignItems: "center", gap: 7, height: 30, padding: "0 12px",
              borderRadius: 999, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
              border: `1px solid ${active ? `var(--accent-${q.tone})` : "var(--neutral-300)"}`,
              background: active ? `var(--accent-${q.tone}-bg)` : "var(--neutral-0)",
              color: active ? `var(--accent-${q.tone})` : "var(--neutral-700)",
            }}>
              <Icon name={q.icon} size={13}/> {q.label}
            </button>
          );
        })}
        <div style={{ flex: 1 }}/>
        {["Purpose", "Sub-region", "Days in SLA", "Channel", "State"].map(f => (
          <button key={f} className="btn btn-sm"><Icon name="chevronDown" size={13}/> {f}</button>
        ))}
      </div>

      {/* Bulk bar */}
      {sel.size > 0 && (
        <div className="row" style={{
          gap: 12, marginBottom: 12, padding: "10px 14px", borderRadius: "var(--radius-default)",
          background: bulkEligible ? "var(--accent-data-bg)" : "var(--neutral-100)",
          border: `1px solid ${bulkEligible ? "rgba(46,125,50,0.3)" : "var(--neutral-300)"}`,
        }}>
          <Icon name={bulkEligible ? "checkCircle" : "info"} size={16} color={bulkEligible ? "var(--accent-data)" : "var(--neutral-500)"}/>
          <span className="t-bodysm" style={{ flex: 1 }}>
            <strong>{sel.size} selected.</strong>{" "}
            {bulkEligible
              ? `Eligible for bulk Confirm — all share ${[...bulkPurposes][0]} with zero active referrals.`
              : `Bulk Confirm unavailable: ${bulkReason}.`}
            {bulkEligible && selRows.length > 1000 && " Over 1,000 — a second approver is required."}
          </span>
          <button className="btn btn-sm btn-ghost" onClick={() => setSel(new Set())}>Clear</button>
          <button className="btn btn-sm btn-success" disabled={!bulkEligible} onClick={applyBulk}>
            <Icon name="check" size={13}/> Confirm {sel.size} {selRows.length > 1000 ? "(needs 2nd approver)" : ""}
          </button>
        </div>
      )}

      {/* Queue table */}
      <div className="table-wrap" style={{ marginBottom: 20 }}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>Ticket</th>
              <th>Household / Member</th>
              <th>Purpose</th>
              <th>Captured via</th>
              <th>Days open / SLA</th>
              <th>State</th>
              <th>Assigned</th>
              <th className="col-actions">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(t => {
              const rem = remaining(t);
              const risk = isOpenState(t) && rem < 5;
              const eligibleForSelect = isOpenState(t) && t.referrals === 0 && !isPublicTask(t);
              return (
                <tr key={t.id} className={t.id === selectedId ? "selected" : ""} style={{ cursor: "pointer" }}
                  onClick={() => setSelectedId(t.id)}>
                  <td onClick={(e) => { e.stopPropagation(); if (eligibleForSelect) toggleSel(t.id); }}>
                    <input type="checkbox" checked={sel.has(t.id)} readOnly disabled={!eligibleForSelect}/>
                  </td>
                  <td className="col-id">{t.id}</td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{t.member}</div>
                    <div className="t-cap t-mono">{t.hh}</div>
                  </td>
                  <td>
                    <div className="row gap-2">
                      <span style={{ fontWeight: 500 }}>{purposeOf(t.purpose).name}</span>
                    </div>
                    <BasisChip basis={purposeOf(t.purpose).basis}/>
                  </td>
                  <td>{t.channel}{t.origin === "Bulk DIH" && <div className="t-cap">Bulk DIH</div>}</td>
                  <td>
                    <div className="row gap-2">
                      <span className="t-num" style={{ fontWeight: 600, color: risk ? "var(--accent-danger)" : "var(--neutral-900)" }}>
                        {t.daysOpen}<span className="muted" style={{ fontWeight: 400 }}>/{SLA_DAYS}d</span>
                      </span>
                      {risk && <Chip tone="danger" size="sm">{rem}d left</Chip>}
                    </div>
                    <div style={{ marginTop: 4, height: 4, width: 92, background: "var(--neutral-200)", borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ width: `${Math.min(100, (t.daysOpen / SLA_DAYS) * 100)}%`, height: "100%", background: risk ? "var(--accent-danger)" : "var(--accent-update)" }}/>
                    </div>
                  </td>
                  <td><TicketStateChip state={t.state} size="sm"/></td>
                  <td className="t-bodysm">{t.assignee}</td>
                  <td className="col-actions">
                    <button className="btn btn-sm btn-ghost" onClick={(e) => { e.stopPropagation(); setSelectedId(t.id); }}>Review</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ===== Three-column detail ===== */}
      {current && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 340px", gap: 16 }}>
          {/* Column 1 — consent record history */}
          <div className="card">
            <div className="card-header"><h3 className="t-h3">Consent record history</h3><span className="t-cap t-mono">{current.member}</span></div>
            <div className="card-body col gap-3">
              <div className="row gap-2" style={{ flexWrap: "wrap" }}>
                <span style={{ fontWeight: 600 }}>{purpose.name}</span>
                <BasisChip basis={purpose.basis} title={purpose.basisNote}/>
                <span className="t-mono t-cap">{purpose.code}</span>
              </div>
              <div className="col gap-0" style={{ borderLeft: "2px solid var(--neutral-200)", paddingLeft: 14, marginLeft: 4 }}>
                {[
                  { state: "Pending review", label: "Withdrawal requested", when: `${current.daysOpen}d ago`, via: current.channel },
                  { state: "Granted", label: "Re-granted via Web", when: "03 Mar 2026", via: "Web" },
                  { state: "Granted", label: "Captured at intake", when: "12 Jan 2026", via: "Signature" },
                ].map((h, i) => (
                  <div key={i} style={{ position: "relative", paddingBottom: 14 }}>
                    <span style={{ position: "absolute", left: -21, top: 2, width: 10, height: 10, borderRadius: "50%", background: i === 0 ? "var(--accent-quality)" : "var(--accent-data)", border: "2px solid var(--neutral-0)" }}/>
                    <div className="row gap-2"><ConsentStateChip state={h.state} size="sm"/><span className="t-bodysm" style={{ fontWeight: 500 }}>{h.label}</span></div>
                    <div className="t-cap">{h.when} · via {h.via} · statement v3</div>
                  </div>
                ))}
              </div>
              <button className="btn btn-sm btn-ghost" style={{ alignSelf: "flex-start" }} onClick={() => setAuditOpen(true)}>
                <Icon name="history" size={13}/> Full audit chain
              </button>
            </div>
          </div>

          {/* Column 2 — impact summary */}
          <div className="card">
            <div className="card-header"><h3 className="t-h3">Impact of withdrawal</h3>
              <span className="t-cap">{current.referrals + current.smsSubs + current.extracts === 0 ? "No downstream effects" : "Review before deciding"}</span>
            </div>
            <div className="card-body col gap-3">
              <ImpactRow icon="users" label="Active programme referrals"
                value={current.referrals} ok={current.referrals === 0}
                detail={current.referrals ? "PSSG cash transfer · enrolled. Programme will be notified." : "No active referrals depend on this consent."}/>
              <ImpactRow icon="message" label="SMS subscriptions"
                value={current.smsSubs} ok={current.smsSubs === 0}
                detail={current.smsSubs ? "Will be unsubscribed on confirm." : "None active."}/>
              <ImpactRow icon="database" label="Pending DRS extracts"
                value={current.extracts} ok={current.extracts === 0}
                detail={current.extracts ? "Open data requests that include this record will exclude it on next run." : "No pending extracts."}/>
              <div className="divider"/>
              <div className="row gap-2 t-bodysm" style={{ color: current.referrals === 0 ? "var(--accent-data)" : "var(--accent-quality)" }}>
                <Icon name={current.referrals === 0 ? "checkCircle" : "alert"} size={15}/>
                {current.referrals === 0
                  ? "Safe to confirm — no active referrals block this withdrawal."
                  : "Has an active referral — confirm only after notifying the programme."}
              </div>
            </div>
          </div>

          {/* Column 3 — decision */}
          <div className="card">
            <div className="card-header"><h3 className="t-h3">Decision</h3><TicketStateChip state={current.state} size="sm"/></div>
            <div className="card-body">
              <DecisionPanel ticket={current} onDecide={applyDecision}/>
            </div>
          </div>
        </div>
      )}

      {/* Sticky action bar */}
      <div style={{ margin: "16px -24px 0", position: "sticky", bottom: 0, zIndex: 20 }}>
        <ActionBar left={current ? <>Reviewing <span className="t-mono" style={{ color: "var(--neutral-900)" }}>{current.id}</span> · {current.member} · {remaining(current)} days to SLA deadline</> : "Select a ticket"}>
          <button className="btn"><Icon name="message" size={14}/> Message citizen</button>
          <button className="btn btn-ghost" onClick={() => setAuditOpen(true)}><Icon name="history" size={14}/> Audit chain</button>
        </ActionBar>
      </div>

      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} events={auditEvents}
        title={current ? `Audit · ${current.id}` : "Audit"}/>
      <Toast message={toast} onDone={() => setToast("")}/>
    </div>
  );
};

const ImpactRow = ({ icon, label, value, ok, detail }) => (
  <div className="row gap-3" style={{ alignItems: "flex-start" }}>
    <div style={{
      width: 32, height: 32, borderRadius: "var(--radius-default)", flexShrink: 0,
      background: ok ? "var(--neutral-100)" : "var(--accent-quality-bg)",
      display: "grid", placeItems: "center",
    }}>
      <Icon name={icon} size={16} color={ok ? "var(--neutral-500)" : "var(--accent-quality)"}/>
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span style={{ fontWeight: 600, fontSize: 13.5 }}>{label}</span>
        <strong className="t-num" style={{ color: ok ? "var(--neutral-500)" : "var(--accent-quality)" }}>{value}</strong>
      </div>
      <div className="t-cap" style={{ marginTop: 2 }}>{detail}</div>
    </div>
  </div>
);

window.DpoWithdrawalQueueScreen = DpoWithdrawalQueueScreen;
