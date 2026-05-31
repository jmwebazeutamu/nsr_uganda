/* global React,
   Icon, Chip, Field, Modal, Toast, AuditDrawer,
   ConsentStateChip, TicketStateChip, BasisChip,
   PURPOSES, PURPOSE_BY_CODE, WITHDRAWAL_REASONS,
   ConsentSectionLabel, StoryTag */
// NSR MIS — Consent Management · Screens 2 & 3
// Screen 2: Citizen consent dashboard  (US-065, US-S26-CONSENT-CITIZEN-VIEW)
// Screen 3: Withdrawal request flow    (US-S26-CONSENT-CITIZEN-WITHDRAW)
// Citizen portal (Release 3) + Parish Chief assisted access.
// Desktop primary state. Mobile card-stack is a later pass.

const { useState: useStateCD, useMemo: useMemoCD } = React;

/* ============================================================
   Sample household — the head and three members
   ============================================================ */
const HOUSEHOLD = {
  id: "HH-7411-0192",
  members: [
    { id: "M1", name: "Nakiru Christine", rel: "Self (head)", self: true, sex: "F", age: 41, initials: "NC" },
    { id: "M2", name: "Lokol Moses",      rel: "Spouse",      sex: "M", age: 45, initials: "LM" },
    { id: "M3", name: "Akiru Grace",      rel: "Daughter",    sex: "F", age: 17, initials: "AG" },
    { id: "M4", name: "Lomong Peter",     rel: "Son",         sex: "M", age: 12, initials: "LP" },
  ],
};

// Per-member consent state. Keyed by member id → purpose code → record.
const seedRecords = () => ({
  M1: {
    REGISTRATION:         { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Signature" },
    REFERRAL:             { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Signature" },
    PAYMENTS:             { state: "Granted", granted: "12 Jan 2026", last: "03 Mar 2026", channel: "Web" },
    COMMUNICATIONS_SMS:   { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Signature" },
    COMMUNICATIONS_USSD:  { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Signature" },
    RESEARCH:             { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Signature" },
    GRIEVANCE_CONTACT:    { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Signature" },
    ELIGIBILITY:          { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Web" },
    STATISTICS:           { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Public task" },
  },
  M2: {
    REGISTRATION:         { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Thumbprint" },
    REFERRAL:             { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Thumbprint" },
    PAYMENTS:             { state: "Withdrawn", granted: "12 Jan 2026", last: "18 Apr 2026", channel: "Web" },
    COMMUNICATIONS_SMS:   { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Thumbprint" },
    COMMUNICATIONS_USSD:  { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Thumbprint" },
    RESEARCH:             { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Thumbprint" },
    GRIEVANCE_CONTACT:    { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Thumbprint" },
    ELIGIBILITY:          { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Web" },
    STATISTICS:           { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Public task" },
  },
  M3: { /* minor — registration via guardian */
    REGISTRATION:         { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    REFERRAL:             { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    PAYMENTS:             { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    COMMUNICATIONS_SMS:   { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Guardian" },
    COMMUNICATIONS_USSD:  { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Guardian" },
    RESEARCH:             { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Guardian" },
    GRIEVANCE_CONTACT:    { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    ELIGIBILITY:          { state: "Pending re-consent", granted: "12 Jan 2026", last: "20 May 2026", channel: "Guardian" },
    STATISTICS:           { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Public task" },
  },
  M4: {
    REGISTRATION:         { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    REFERRAL:             { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    PAYMENTS:             { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    COMMUNICATIONS_SMS:   { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Guardian" },
    COMMUNICATIONS_USSD:  { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Guardian" },
    RESEARCH:             { state: "Refused", granted: "—",          last: "12 Jan 2026", channel: "Guardian" },
    GRIEVANCE_CONTACT:    { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    ELIGIBILITY:          { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Guardian" },
    STATISTICS:           { state: "Granted", granted: "12 Jan 2026", last: "12 Jan 2026", channel: "Public task" },
  },
});

/* Plain-language consequences of withdrawing each purpose */
const CONSEQUENCE = {
  REGISTRATION: "Withdrawing registration removes your whole household record from the NSR. You may lose access to programmes that rely on the registry. This is a serious step — the DPO will contact you before it takes effect.",
  REFERRAL: "NSR will stop sharing your record with new programmes. Active referrals will be notified that you have withdrawn.",
  PAYMENTS: "NSR will stop using your record to arrange payments. Any payment already scheduled will continue unless you contact the programme directly.",
  COMMUNICATIONS_SMS: "You will stop receiving SMS messages from NSR about your registration and benefits.",
  COMMUNICATIONS_USSD: "The *234# self-service menu will no longer show your record.",
  RESEARCH: "Your data will no longer be included in new research extracts. Extracts already shared cannot be recalled.",
  GRIEVANCE_CONTACT: "Grievance officers will no longer contact you about complaints. You can still file complaints in person.",
};

const sampleAudit = (member) => [
  { who: member.name, action: "withdrew PAYMENTS", detail: "via Web portal · ticket WD-2026-04417", time: "18 Apr 2026", audit: "AC-7C8810" },
  { who: "DPO Nabbanja", action: "confirmed withdrawal", detail: "PAYMENTS · within SLA (6 days)", time: "24 Apr 2026", audit: "AC-7C99A2", tone: "system" },
  { who: member.name, action: "updated PAYMENTS", detail: "re-granted via Web", time: "03 Mar 2026", audit: "AC-6B2201" },
  { who: "System", action: "captured consent", detail: "9 purposes at intake · Signature", time: "12 Jan 2026", audit: "AC-5A0010", tone: "system" },
];

/* ============================================================
   Withdrawal modal (Screen 3) — two steps
   ============================================================ */
const WithdrawalModal = ({ open, purposeCode, onClose, onComplete }) => {
  const [step, setStep] = useStateCD(1);
  const [reason, setReason] = useStateCD("");
  const [busy, setBusy] = useStateCD(false);
  const [error, setError] = useStateCD(false);
  const [ticket, setTicket] = useStateCD(null);

  React.useEffect(() => {
    if (open) { setStep(1); setReason(""); setBusy(false); setError(false); setTicket(null); }
  }, [open, purposeCode]);

  if (!open || !purposeCode) return null;
  const purpose = PURPOSE_BY_CODE[purposeCode];

  const submit = () => {
    setBusy(true); setError(false);
    setTimeout(() => {
      setBusy(false);
      // Idempotent submit; demo a successful ticket.
      const id = "WD-2026-0" + (4500 + Math.floor(Math.random() * 90));
      const deadline = "29 Jun 2026";
      setTicket({ id, deadline });
      setStep(2);
    }, 650);
  };

  const titleByStep = step === 1 ? "Withdraw your consent" : "Request received";

  return (
    <Modal open={open} onClose={onClose} title={titleByStep} width={520}
      footer={step === 1 ? <>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-danger" onClick={submit} disabled={busy}>
          {busy ? "Submitting…" : "Submit withdrawal request"}
        </button>
      </> : <>
        <button className="btn"><Icon name="print" size={14}/> Print / save</button>
        <button className="btn btn-primary" onClick={() => { onComplete?.(purposeCode, ticket); onClose?.(); }}>Done</button>
      </>}>
      {step === 1 ? (
        <div className="col gap-4">
          {error && (
            <div className="row gap-2" style={{
              padding: "10px 12px", background: "var(--accent-danger-bg)",
              border: "1px solid rgba(169,50,38,0.25)", borderRadius: "var(--radius-default)",
            }}>
              <Icon name="alert" size={16} color="var(--accent-danger)"/>
              <div className="t-bodysm" style={{ flex: 1 }}>We couldn't reach the server. Your request was not sent.
                It is safe to try again — you will not create a duplicate.</div>
              <button className="btn btn-sm btn-danger" onClick={submit}><Icon name="refresh" size={13}/> Retry</button>
            </div>
          )}
          <div className="row gap-3" style={{ alignItems: "center" }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>{purpose.name}</div>
            <span className="t-mono t-cap">{purpose.code}</span>
            <div style={{ flex: 1 }}/>
            <BasisChip basis={purpose.basis}/>
          </div>
          <div className="t-cap">Current statement: <strong style={{ color: "var(--neutral-700)" }}>v3 — Active</strong> (effective 12 Jan 2026)</div>

          <div style={{
            padding: "14px 16px", background: "var(--accent-quality-bg)",
            border: "1px solid rgba(184,116,26,0.25)", borderRadius: "var(--radius-default)",
            display: "flex", gap: 10,
          }}>
            <Icon name="info" size={17} color="var(--accent-quality)" style={{ flexShrink: 0, marginTop: 1 }}/>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 3 }}>What happens if you withdraw</div>
              <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>{CONSEQUENCE[purposeCode]}</div>
            </div>
          </div>

          <Field label="Reason (optional)" hint="You do not have to give a reason. It helps us improve the service.">
            <select className="field-select" value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">Prefer not to say</option>
              {WITHDRAWAL_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </Field>

          <div className="t-cap row gap-2" style={{ color: "var(--neutral-500)" }}>
            <Icon name="clock" size={13}/> The Data Protection Officer must review and decide within 30 days.
          </div>
        </div>
      ) : (
        <div className="col gap-4">
          <div className="row gap-3" style={{
            padding: "14px 16px", background: "var(--accent-data-bg)",
            border: "1px solid rgba(46,125,50,0.25)", borderRadius: "var(--radius-default)", alignItems: "center",
          }}>
            <Icon name="checkCircle" size={22} color="var(--accent-data)"/>
            <div>
              <div style={{ fontWeight: 600 }}>Your withdrawal request was received</div>
              <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>Ticket <span className="t-mono">{ticket.id}</span> · {purpose.name}</div>
            </div>
          </div>

          {/* 30-day statutory clock */}
          <div className="card" style={{ boxShadow: "none", border: "1px solid var(--neutral-200)" }}>
            <div className="card-body" style={{ padding: 16 }}>
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
                <span className="t-cap">STATUTORY REVIEW CLOCK</span>
                <TicketStateChip state="In DPO review" size="sm"/>
              </div>
              <div className="row gap-3" style={{ alignItems: "baseline" }}>
                <span style={{ fontSize: 30, fontWeight: 700, letterSpacing: "-0.02em" }} className="t-num">30</span>
                <span className="muted">days to decision</span>
                <div style={{ flex: 1 }}/>
                <div style={{ textAlign: "right" }}>
                  <div className="t-cap">Decision due by</div>
                  <div style={{ fontWeight: 600 }}>{ticket.deadline}</div>
                </div>
              </div>
              <div style={{ marginTop: 12, height: 6, background: "var(--neutral-200)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: "4%", height: "100%", background: "var(--accent-update)" }}/>
              </div>
            </div>
          </div>

          <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
            <strong>Next:</strong> the Data Protection Officer reviews your request and confirms within 30 days.
            You will receive an SMS when the decision is made. This request now appears on your dashboard as
            <span style={{ whiteSpace: "nowrap" }}> <TicketStateChip state="In DPO review" size="sm"/></span>.
          </div>
        </div>
      )}
    </Modal>
  );
};

/* ============================================================
   MAIN — Citizen consent dashboard
   ============================================================ */
const CitizenConsentScreen = () => {
  const [memberId, setMemberId] = useStateCD("M1");
  const [records, setRecords] = useStateCD(seedRecords);
  const [withdrawCode, setWithdrawCode] = useStateCD(null);
  const [showAudit, setShowAudit] = useStateCD(false);
  const [toast, setToast] = useStateCD("");

  const member = HOUSEHOLD.members.find(m => m.id === memberId);
  const memberRecords = records[memberId] || {};

  const onWithdrawComplete = (code) => {
    setRecords(r => ({
      ...r,
      [memberId]: { ...(r[memberId] || {}), [code]: { ...((r[memberId] || {})[code] || {}), state: "Pending review", last: "30 May 2026", channel: "Web" } },
    }));
    setToast(`Withdrawal request submitted for ${PURPOSE_BY_CODE[code].name}.`);
  };

  return (
    <div>
      {/* Portal header */}
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
        <div>
          <div className="page-eyebrow row gap-2" style={{ display: "flex", alignItems: "center" }}>
            MY CONSENT &nbsp;<StoryTag>US-S26-CONSENT-CITIZEN-VIEW</StoryTag>
          </div>
          <h1 className="t-h1" style={{ margin: 0 }}>Your consent records</h1>
          <div className="page-sub">Household <span className="t-mono">{HOUSEHOLD.id}</span> · you can view and change consent for everyone you are responsible for.</div>
        </div>
        <div className="row gap-2" style={{
          padding: "6px 12px", borderRadius: 999, background: "var(--accent-system-bg)",
          border: "1px solid rgba(55,71,79,0.2)", fontSize: 12.5, color: "var(--neutral-700)",
        }}>
          <Icon name="user" size={14} color="var(--accent-system)"/>
          Signed in as <strong>Nakiru Christine</strong> · head
        </div>
      </div>

      {/* Member selector */}
      <div className="card card-body" style={{ marginBottom: 16 }}>
        <ConsentSectionLabel hint="Choose whose consent you want to view. As head you can act for every member.">Household member</ConsentSectionLabel>
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          {HOUSEHOLD.members.map(m => {
            const active = m.id === memberId;
            return (
              <button key={m.id} onClick={() => setMemberId(m.id)} style={{
                display: "flex", alignItems: "center", gap: 10, textAlign: "left",
                padding: "8px 14px 8px 10px", borderRadius: "var(--radius-card)",
                border: `1.5px solid ${active ? "var(--accent-system)" : "var(--neutral-300)"}`,
                background: active ? "var(--accent-system-bg)" : "var(--neutral-0)", cursor: "pointer",
              }}>
                <span style={{
                  width: 34, height: 34, borderRadius: "50%",
                  background: active ? "var(--accent-system)" : "var(--neutral-100)",
                  color: active ? "var(--neutral-0)" : "var(--neutral-700)",
                  display: "grid", placeItems: "center", fontWeight: 700, fontSize: 12.5,
                }}>{m.initials}</span>
                <span>
                  <span style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>{m.self ? "You" : m.name}</span>
                  <span style={{ display: "block", fontSize: 12, color: "var(--neutral-500)" }}>{m.rel}{m.age < 18 ? " · minor" : ""}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Consent records table */}
      <div className="table-wrap">
        <div className="card-toolbar" style={{ justifyContent: "space-between" }}>
          <div className="row gap-2">
            <Icon name="shield" size={15} color="var(--accent-system)"/>
            <strong style={{ fontSize: 13.5 }}>{member.self ? "Your" : `${member.name}'s`} consent — {PURPOSES.length} purposes</strong>
          </div>
          <span className="t-cap">A green badge means active consent. Grey means it is off.</span>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: "30%" }}>Purpose</th>
              <th>Current state</th>
              <th>Lawful basis</th>
              <th>Granted on</th>
              <th>Last change</th>
              <th className="col-actions">Action</th>
            </tr>
          </thead>
          <tbody>
            {PURPOSES.map(p => {
              // Null-safe: a purpose may have no record yet (e.g. a newly
              // seeded purpose like ELIGIBILITY before capture) — render it as
              // not-yet-captured rather than crashing on rec.state.
              const rec = memberRecords[p.code] || { state: "Pending review", granted: "—", last: "—", channel: "—" };
              const canWithdraw = p.withdrawable && rec.state === "Granted";
              const pending = rec.state === "Pending review";
              return (
                <tr key={p.code}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{p.name}</div>
                    <div className="t-cap" style={{ maxWidth: 320 }}>{p.blurb}</div>
                  </td>
                  <td>
                    {pending ? <TicketStateChip state="In DPO review" size="sm"/> : <ConsentStateChip state={rec.state} size="sm"/>}
                  </td>
                  <td><BasisChip basis={p.basis} title={p.basisNote}/></td>
                  <td className="t-num muted">{rec.granted}</td>
                  <td className="t-num muted">{rec.last}</td>
                  <td className="col-actions">
                    {canWithdraw ? (
                      <button className="btn btn-sm btn-ghost" style={{ color: "var(--accent-danger)" }}
                        onClick={() => setWithdrawCode(p.code)}>Withdraw</button>
                    ) : pending ? (
                      <span className="t-cap" style={{ color: "var(--accent-update)" }}>Awaiting decision</span>
                    ) : !p.withdrawable && rec.state === "Granted" ? (
                      <span title={p.basisNote} style={{ display: "inline-flex", alignItems: "center", gap: 5, cursor: "help", color: "var(--neutral-300)", fontSize: 13 }}>
                        <Icon name="lock" size={13} color="var(--neutral-300)"/> Withdraw
                      </span>
                    ) : (
                      <span className="t-cap" style={{ color: "var(--neutral-300)" }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer: audit-trail link */}
      <div className="row" style={{ justifyContent: "space-between", marginTop: 14, flexWrap: "wrap", gap: 8 }}>
        <button className="btn btn-ghost" onClick={() => setShowAudit(true)} style={{ color: "var(--primary-700)" }}>
          <Icon name="history" size={14}/> View full consent history for {member.self ? "yourself" : member.name}
        </button>
        <div className="t-cap row gap-2" style={{ color: "var(--neutral-500)" }}>
          <Icon name="lock" size={13}/> Some purposes are required by law and cannot be switched off. Contact the DPO to ask about these.
        </div>
      </div>

      <WithdrawalModal open={!!withdrawCode} purposeCode={withdrawCode}
        onClose={() => setWithdrawCode(null)} onComplete={onWithdrawComplete}/>
      <AuditDrawer open={showAudit} onClose={() => setShowAudit(false)}
        events={sampleAudit(member)} title={`${member.self ? "Your" : member.name} · consent history`}/>
      <Toast message={toast} onDone={() => setToast("")}/>
    </div>
  );
};

window.CitizenConsentScreen = CitizenConsentScreen;
