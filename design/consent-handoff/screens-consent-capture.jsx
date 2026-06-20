/* global React,
   Icon, Chip, Field, Modal, Toast, PageHeader, AuditDrawer,
   ConsentStateChip, BasisChip, LANGUAGES, PURPOSES,
   REFUSAL_REASONS, REGISTRATION_STATEMENT_EN,
   ConsentSectionLabel, StoryTag, Toggle */
// NSR MIS — Consent Management · Screen 1
// Intake consent capture (Web variant, desktop primary state).
// Anchors: US-010, US-S26-CONSENT-CAPTURE-CAPI, US-S26-CONSENT-CAPTURE-WEB
// The CAPI one-question-per-screen tablet layout is a later pass.

const { useState: useStateIC, useRef: useRefIC, useEffect: useEffectIC, useMemo: useMemoIC } = React;

/* ============================================================
   Signature pad — pointer drawing on a canvas (CAPI parity),
   with a Web fallback to upload an image of a wet signature.
   ============================================================ */
const SignaturePad = ({ onChange }) => {
  const canvasRef = useRefIC(null);
  const drawing = useRefIC(false);
  const last = useRefIC({ x: 0, y: 0 });
  const [hasInk, setHasInk] = useStateIC(false);

  useEffectIC(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ratio = window.devicePixelRatio || 1;
    c.width = c.offsetWidth * ratio;
    c.height = c.offsetHeight * ratio;
    const ctx = c.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.strokeStyle = "#1F3864";
  }, []);

  const pos = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return { x: t.clientX - r.left, y: t.clientY - r.top };
  };
  const start = (e) => { e.preventDefault(); drawing.current = true; last.current = pos(e); };
  const move = (e) => {
    if (!drawing.current) return;
    e.preventDefault();
    const ctx = canvasRef.current.getContext("2d");
    const p = pos(e);
    ctx.beginPath();
    ctx.moveTo(last.current.x, last.current.y);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    last.current = p;
    if (!hasInk) { setHasInk(true); onChange?.(true); }
  };
  const end = () => { drawing.current = false; };
  const clear = () => {
    const c = canvasRef.current;
    c.getContext("2d").clearRect(0, 0, c.width, c.height);
    setHasInk(false); onChange?.(false);
  };

  return (
    <div className="col gap-2">
      <div style={{ position: "relative" }}>
        <canvas ref={canvasRef}
          onMouseDown={start} onMouseMove={move} onMouseUp={end} onMouseLeave={end}
          onTouchStart={start} onTouchMove={move} onTouchEnd={end}
          style={{
            width: "100%", height: 132, touchAction: "none",
            background: "var(--neutral-0)",
            border: "1px dashed var(--neutral-300)",
            borderRadius: "var(--radius-default)", cursor: "crosshair",
            display: "block",
          }}/>
        {!hasInk && (
          <div style={{
            position: "absolute", inset: 0, display: "grid", placeItems: "center",
            pointerEvents: "none", color: "var(--neutral-300)",
          }}>
            <div className="col gap-1" style={{ alignItems: "center" }}>
              <Icon name="edit" size={20} color="var(--neutral-300)"/>
              <span className="t-bodysm">Citizen signs here</span>
            </div>
          </div>
        )}
        <div style={{
          position: "absolute", bottom: 8, left: 12, right: 12,
          borderBottom: "1px solid var(--neutral-300)",
        }}/>
      </div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="t-cap">Black ink · drawn on device</span>
        <div className="row gap-2">
          <label className="btn btn-sm" style={{ cursor: "pointer" }}>
            <Icon name="download" size={13}/> Upload image
            <input type="file" accept="image/*" hidden
              onChange={(e) => { if (e.target.files?.length) { setHasInk(true); onChange?.(true); } }}/>
          </label>
          <button className="btn btn-sm btn-ghost" onClick={clear} disabled={!hasInk}>
            <Icon name="x" size={13}/> Clear
          </button>
        </div>
      </div>
    </div>
  );
};

/* ============================================================
   Selectable card — used for Yes/No and capture-method radios
   ============================================================ */
const RadioCard = ({ checked, onSelect, icon, title, sub, tone, disabled }) => {
  const accent = tone === "danger" ? "var(--accent-danger)"
    : tone === "data" ? "var(--accent-data)" : "var(--accent-system)";
  return (
    <button
      role="radio" aria-checked={checked} disabled={disabled}
      onClick={() => !disabled && onSelect?.()}
      style={{
        display: "flex", alignItems: "flex-start", gap: 12, textAlign: "left",
        width: "100%", padding: "12px 14px",
        border: `1.5px solid ${checked ? accent : "var(--neutral-300)"}`,
        background: checked ? (tone === "danger" ? "var(--accent-danger-bg)"
          : tone === "data" ? "var(--accent-data-bg)" : "var(--accent-system-bg)") : "var(--neutral-0)",
        borderRadius: "var(--radius-default)",
        cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        transition: "border-color .1s ease, background-color .1s ease",
      }}>
      <span style={{
        flex: "0 0 18px", width: 18, height: 18, marginTop: 1, borderRadius: "50%",
        border: `2px solid ${checked ? accent : "var(--neutral-300)"}`,
        display: "grid", placeItems: "center",
      }}>
        {checked && <span style={{ width: 9, height: 9, borderRadius: "50%", background: accent }}/>}
      </span>
      {icon && <Icon name={icon} size={18} color={checked ? accent : "var(--neutral-500)"} style={{ marginTop: 1 }}/>}
      <span style={{ flex: 1 }}>
        <span style={{ display: "block", fontWeight: 600, fontSize: 14, color: "var(--neutral-900)" }}>{title}</span>
        {sub && <span style={{ display: "block", fontSize: 12.5, color: "var(--neutral-500)", marginTop: 2 }}>{sub}</span>}
      </span>
    </button>
  );
};

/* ============================================================
   Optional-purpose toggle row
   ============================================================ */
const PurposeToggleRow = ({ purpose, on, onChange }) => (
  <div className="row" style={{
    alignItems: "flex-start", gap: 12, padding: "12px 0",
    borderTop: "1px solid var(--neutral-200)",
  }}>
    <Toggle on={on} onChange={onChange} ariaLabel={`${purpose.name} consent`}/>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div className="row gap-2" style={{ flexWrap: "wrap" }}>
        <span style={{ fontWeight: 600, fontSize: 13.5 }}>{purpose.name}</span>
        <Chip tone="neutral" size="sm">Optional</Chip>
        <BasisChip basis={purpose.basis}/>
      </div>
      <div className="t-bodysm muted" style={{ marginTop: 3, maxWidth: 560 }}>{purpose.blurb}</div>
    </div>
    <span className="t-cap t-mono" style={{ marginTop: 3, color: "var(--neutral-300)" }}>{purpose.code}</span>
  </div>
);

/* ============================================================
   Refusal modal — controlled reason list + note, ends intake
   ============================================================ */
const RefuseModal = ({ open, onClose, onConfirm }) => {
  const [reason, setReason] = useStateIC("");
  const [note, setNote] = useStateIC("");
  useEffectIC(() => { if (open) { setReason(""); setNote(""); } }, [open]);
  const needNote = reason === "Other (see note)";
  const canSubmit = reason && (!needNote || note.trim().length >= 4);
  return (
    <Modal open={open} onClose={onClose} title="Record declined consent" width={460}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger" disabled={!canSubmit}
          onClick={() => onConfirm?.({ reason, note })}>
          End intake — declined
        </button>
      </>}>
      <div className="col gap-4">
        <div className="t-bodysm" style={{
          padding: "10px 12px", background: "var(--accent-danger-bg)",
          border: "1px solid rgba(169,50,38,0.2)", borderRadius: "var(--radius-default)",
          color: "var(--neutral-900)", display: "flex", gap: 8,
        }}>
          <Icon name="alert" size={15} color="var(--accent-danger)" style={{ flexShrink: 0, marginTop: 1 }}/>
          <span>No personal data has been captured. Recording a refusal ends this intake with a
            <strong> Declined consent</strong> outcome and writes to the audit chain.</span>
        </div>
        <Field label="Reason for refusal" required hint="Reason is written to the audit chain.">
          <select className="field-select" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Select a reason…</option>
            {REFUSAL_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>
        <Field label="Note" required={needNote}
          hint={needNote ? "Required when reason is “Other”." : "Optional context for the audit record."}>
          <textarea className="field-textarea" rows={3} value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Add any context that helps the DPO understand the refusal."/>
        </Field>
      </div>
    </Modal>
  );
};

/* ============================================================
   Sample audit events for the intake audit surface
   ============================================================ */
const INTAKE_AUDIT = [
  { who: "System", action: "loaded statement", detail: "REGISTRATION v3 (Active) · language English", time: "Just now", audit: "AC-9F2201", tone: "system" },
  { who: "Akello P.", action: "opened consent capture", detail: "EA-7411-002 · household head intake", time: "09:14", audit: "AC-9F21F8" },
];

/* ============================================================
   MAIN — Intake consent capture
   ============================================================ */
const ConsentIntakeScreen = () => {
  const [lang, setLang] = useStateIC("en");
  const [registration, setRegistration] = useStateIC(null); // "yes" | "no" | null
  const optionalPurposes = useMemoIC(() => PURPOSES.filter(p => p.optional), []);
  const [opt, setOpt] = useStateIC(() =>
    Object.fromEntries(optionalPurposes.map(p => [p.code, p.defaultOn])));
  const [method, setMethod] = useStateIC(null); // signature|thumbprint|verbal|digital
  const [witnessName, setWitnessName] = useStateIC("");
  const [witnessRole, setWitnessRole] = useStateIC("");
  const [captured, setCaptured] = useStateIC(false);
  const [showRefuse, setShowRefuse] = useStateIC(false);
  const [showAudit, setShowAudit] = useStateIC(false);
  const [toast, setToast] = useStateIC("");
  const [submitted, setSubmitted] = useStateIC(false);  // "captured" | "declined"
  const [declineReason, setDeclineReason] = useStateIC("");
  const [showErrors, setShowErrors] = useStateIC(false);

  const langObj = LANGUAGES.find(l => l.code === lang);
  const grantedCount = 1 + optionalPurposes.filter(p => opt[p.code]).length; // REGISTRATION + opted-in
  const methodCaptureOK = method === "verbal"
    ? (witnessName.trim() && witnessRole.trim())
    : method === "digital" ? true
    : captured; // signature / thumbprint need a capture
  const valid = registration === "yes" && method && methodCaptureOK;

  const errors = {
    method: showErrors && !method ? "Select how consent was captured." : "",
    witness: showErrors && method === "verbal" && !(witnessName.trim() && witnessRole.trim())
      ? "Witness name and role are required for verbal-witnessed consent." : "",
    capture: showErrors && (method === "signature" || method === "thumbprint") && !captured
      ? "Capture the citizen's mark before continuing." : "",
    registration: showErrors && registration !== "yes"
      ? "Select Yes to record consent, or use Refuse to end the intake." : "",
  };

  const onContinue = () => {
    if (!valid) { setShowErrors(true); return; }
    setSubmitted("captured");
    setToast("Consent captured — proceeding to personal-data capture.");
  };
  const onRefuseConfirm = ({ reason }) => {
    setShowRefuse(false);
    setDeclineReason(reason);
    setSubmitted("declined");
  };

  /* ----- Outcome screens ----- */
  if (submitted) {
    const declined = submitted === "declined";
    return (
      <OutcomeCard declined={declined} reason={declineReason} grantedCount={grantedCount}
        method={method} onReset={() => {
          setSubmitted(false); setRegistration(null); setMethod(null);
          setCaptured(false); setWitnessName(""); setWitnessRole(""); setShowErrors(false);
        }}/>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow={<>INTAKE · STEP 1 OF 7 · CONSENT &nbsp;<StoryTag>US-S26-CONSENT-CAPTURE-WEB</StoryTag></>}
        title="Capture consent"
        sub={<>Before any personal data · Household head intake · EA <span className="t-mono">EA-7411-002</span>, Tapac, Moroto · Enumerator <strong>Akello P.</strong></>}
        right={<>
          <button className="btn" onClick={() => setShowAudit(true)}><Icon name="history" size={14}/> Audit chain</button>
          <button className="btn btn-ghost"><Icon name="x" size={14}/> Cancel intake</button>
        </>}/>

      {/* Slim intake progress */}
      <div className="card" style={{ padding: "10px 16px", marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1, height: 6, background: "var(--neutral-200)", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ width: "14%", height: "100%", background: "var(--accent-system)" }}/>
        </div>
        <span className="t-cap" style={{ whiteSpace: "nowrap" }}>Consent → Identity → Household → Members → Assets → Review → Submit</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 20, alignItems: "start" }}>
        {/* ============ MAIN COLUMN ============ */}
        <div className="col gap-4" style={{ paddingBottom: 8 }}>

          {/* Statement card */}
          <div className="card">
            <div className="card-header">
              <div className="row gap-3">
                <h3 className="t-h3">Registration consent statement</h3>
                <Chip tone="data" size="sm">v3 · Active</Chip>
                <span className="t-cap">Effective 12 Jan 2026</span>
              </div>
              {/* Language switcher */}
              <div className="row gap-2">
                <Icon name="message" size={14} color="var(--neutral-500)"/>
                <select className="field-select" style={{ height: 30, width: "auto", paddingRight: 28 }}
                  value={lang} onChange={(e) => setLang(e.target.value)}>
                  {LANGUAGES.map(l => (
                    <option key={l.code} value={l.code}>{l.label}{l.ready ? "" : " — draft"}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="card-body" style={{ paddingTop: 18, paddingBottom: 18 }}>
              {langObj.ready ? (
                <div style={{
                  fontFamily: "var(--font-serif, Georgia, 'Times New Roman', serif)",
                  fontSize: 16, lineHeight: "26px", color: "var(--neutral-900)",
                  maxWidth: 640, textWrap: "pretty",
                }}>
                  {REGISTRATION_STATEMENT_EN.map((p, i) => (
                    <p key={i} style={{ margin: i === 0 ? "0 0 14px" : "0 0 14px" }}>{p}</p>
                  ))}
                </div>
              ) : (
                <div className="row gap-3" style={{
                  padding: "16px 18px", background: "var(--accent-quality-bg)",
                  border: "1px solid rgba(184,116,26,0.25)", borderRadius: "var(--radius-default)",
                  maxWidth: 640,
                }}>
                  <Icon name="alert" size={18} color="var(--accent-quality)"/>
                  <div className="t-bodysm">
                    The <strong>{langObj.label}</strong> translation of statement v3 is still in draft.
                    Read the statement aloud in {langObj.label} from the printed field guide, or switch to a published language.
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Primary Yes / No */}
          <div className="card card-body">
            <ConsentSectionLabel hint="Required. Registration is the basis for the entire record.">
              Does the citizen consent to registration?
            </ConsentSectionLabel>
            <div className="grid grid-2" style={{ gap: 12 }}>
              <RadioCard checked={registration === "yes"} onSelect={() => setRegistration("yes")}
                tone="data" icon="checkCircle"
                title="Yes — I consent to registration"
                sub="Record may be created and maintained in the NSR."/>
              <RadioCard checked={registration === "no"} onSelect={() => setRegistration("no")}
                tone="danger" icon="xCircle"
                title="No — I do not consent"
                sub="Use Refuse below to end the intake."/>
            </div>
            {errors.registration && <div className="field-error" style={{ marginTop: 8 }}>{errors.registration}</div>}
          </div>

          {/* Optional purposes */}
          <div className="card card-body">
            <ConsentSectionLabel hint="The citizen may grant or decline each of these. They can change any of them later.">
              Optional purposes
            </ConsentSectionLabel>
            <div>
              {optionalPurposes.map(p => (
                <PurposeToggleRow key={p.code} purpose={p}
                  on={!!opt[p.code]} onChange={(v) => setOpt(s => ({ ...s, [p.code]: v }))}/>
              ))}
            </div>
            <div className="row gap-2 t-cap" style={{ marginTop: 12, color: "var(--neutral-500)" }}>
              <Icon name="info" size={13}/>
              Identity verification and national statistics rely on a public-task basis and are not optional.
            </div>
          </div>

          {/* Capture method */}
          <div className="card card-body">
            <ConsentSectionLabel hint="How did the citizen express their decision?">
              Capture method
            </ConsentSectionLabel>
            <div className="grid grid-2" style={{ gap: 12 }}>
              <RadioCard checked={method === "signature"} onSelect={() => { setMethod("signature"); setCaptured(false); }}
                icon="edit" title="Signature" sub="Citizen signs on the device"/>
              <RadioCard checked={method === "thumbprint"} onSelect={() => { setMethod("thumbprint"); setCaptured(false); }}
                icon="user" title="Thumbprint" sub="Captured with fingerprint reader"/>
              <RadioCard checked={method === "verbal"} onSelect={() => { setMethod("verbal"); setCaptured(false); }}
                icon="message" title="Verbal — witnessed" sub="Spoken consent, witness recorded"/>
              <RadioCard checked={method === "digital"} onSelect={() => { setMethod("digital"); setCaptured(true); }}
                icon="phone" title="Digital" sub="OTP / e-signature on citizen's phone"/>
            </div>
            {errors.method && <div className="field-error" style={{ marginTop: 8 }}>{errors.method}</div>}

            {/* Method-specific reveal */}
            {(method === "signature") && (
              <div style={{ marginTop: 16 }}>
                <SignaturePad onChange={setCaptured}/>
                {errors.capture && <div className="field-error" style={{ marginTop: 6 }}>{errors.capture}</div>}
              </div>
            )}
            {(method === "thumbprint") && (
              <div style={{ marginTop: 16 }}>
                <div className="row gap-3" style={{
                  padding: 16, border: "1px dashed var(--neutral-300)",
                  borderRadius: "var(--radius-default)", background: "var(--neutral-50)",
                }}>
                  <div style={{
                    width: 52, height: 52, borderRadius: "50%", display: "grid", placeItems: "center",
                    background: captured ? "var(--accent-data-bg)" : "var(--neutral-100)",
                    border: `1px solid ${captured ? "var(--accent-data)" : "var(--neutral-300)"}`,
                  }}>
                    <Icon name={captured ? "checkCircle" : "user"} size={24}
                      color={captured ? "var(--accent-data)" : "var(--neutral-500)"}/>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                      {captured ? "Thumbprint captured" : "Place the citizen's right thumb on the reader"}
                    </div>
                    <div className="t-cap">{captured ? "Quality: 86 · stored encrypted" : "Hold steady until the reader beeps"}</div>
                  </div>
                  <button className={`btn ${captured ? "" : "btn-primary"} btn-sm`} onClick={() => setCaptured(c => !c)}>
                    {captured ? "Re-capture" : "Capture thumbprint"}
                  </button>
                </div>
                {errors.capture && <div className="field-error" style={{ marginTop: 6 }}>{errors.capture}</div>}
              </div>
            )}
            {(method === "verbal") && (
              <div className="field-row" style={{ marginTop: 16 }}>
                <Field label="Witness name" required error={errors.witness && !witnessName.trim() ? errors.witness : ""}>
                  <input className="field-input" value={witnessName}
                    onChange={(e) => setWitnessName(e.target.value)} placeholder="e.g. Okello James"/>
                </Field>
                <Field label="Witness role" required>
                  <select className="field-select" value={witnessRole} onChange={(e) => setWitnessRole(e.target.value)}>
                    <option value="">Select role…</option>
                    <option>Parish Chief</option>
                    <option>LC1 Chairperson</option>
                    <option>Community Development Officer</option>
                    <option>Village Health Team member</option>
                    <option>Family member (adult)</option>
                  </select>
                </Field>
                {errors.witness && (witnessName.trim() && !witnessRole) &&
                  <div className="field-error" style={{ gridColumn: "1 / -1" }}>{errors.witness}</div>}
              </div>
            )}
            {(method === "digital") && (
              <div className="row gap-3" style={{ marginTop: 16,
                padding: 14, background: "var(--accent-system-bg)",
                border: "1px solid rgba(55,71,79,0.18)", borderRadius: "var(--radius-default)" }}>
                <Icon name="phone" size={18} color="var(--accent-system)"/>
                <div className="t-bodysm">A one-time code will be sent to the citizen's phone. They confirm on their own
                  device; the signed token is attached to this record automatically.</div>
              </div>
            )}
          </div>
        </div>

        {/* ============ RIGHT RAIL ============ */}
        <div className="col gap-4" style={{ position: "sticky", top: 16 }}>
          {/* Who is consenting */}
          <div className="card card-body">
            <ConsentSectionLabel>Who is consenting</ConsentSectionLabel>
            <div className="row gap-3" style={{ alignItems: "center" }}>
              <div style={{
                width: 40, height: 40, borderRadius: "50%", background: "var(--primary-100)",
                color: "var(--primary-900)", display: "grid", placeItems: "center", fontWeight: 700,
              }}>NK</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>Nakiru Christine</div>
                <div className="t-cap">Household head · proposed</div>
              </div>
              <Chip tone="update" size="sm">Provisional</Chip>
            </div>
            <div className="divider"/>
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", rowGap: 7, columnGap: 12, fontSize: 13 }}>
              <dt className="muted">Registry ID</dt><dd style={{ margin: 0 }} className="t-mono">— pending —</dd>
              <dt className="muted">Parish</dt><dd style={{ margin: 0 }}>Tapac, Moroto</dd>
              <dt className="muted">Enumerator</dt><dd style={{ margin: 0 }}>Akello P. (CDO)</dd>
              <dt className="muted">Date</dt><dd style={{ margin: 0 }}>30 May 2026</dd>
            </dl>
          </div>

          {/* Live consent summary */}
          <div className="card card-body">
            <ConsentSectionLabel>This session</ConsentSectionLabel>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
              <span className="t-bodysm muted">Registration</span>
              {registration === "yes" ? <ConsentStateChip state="Granted" size="sm"/>
                : registration === "no" ? <ConsentStateChip state="Refused" size="sm"/>
                : <Chip tone="neutral" size="sm">Not yet</Chip>}
            </div>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
              <span className="t-bodysm muted">Optional purposes granted</span>
              <strong className="t-num">{optionalPurposes.filter(p => opt[p.code]).length} / {optionalPurposes.length}</strong>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="t-bodysm muted">Capture method</span>
              <span style={{ fontWeight: 600, fontSize: 13, textTransform: "capitalize" }}>
                {method ? method.replace("_", " ") : "—"}
              </span>
            </div>
            <div className="divider"/>
            <div className="row gap-2 t-cap" style={{ color: "var(--neutral-500)" }}>
              <Icon name="shield" size={13}/> Recorded to audit chain on continue.
            </div>
          </div>

          {/* DPPA note */}
          <div style={{
            padding: "12px 14px", background: "var(--accent-system-bg)",
            border: "1px solid rgba(55,71,79,0.18)", borderRadius: "var(--radius-card)",
            display: "flex", gap: 10,
          }}>
            <Icon name="lock" size={16} color="var(--accent-system)" style={{ flexShrink: 0, marginTop: 1 }}/>
            <div className="t-cap" style={{ color: "var(--neutral-700)", lineHeight: "16px" }}>
              Protected under the Data Protection &amp; Privacy Act, 2019. Consent precedes all personal-data capture.
            </div>
          </div>
        </div>
      </div>

      {/* Sticky action bar */}
      <div className="action-bar" style={{ marginTop: 20, marginLeft: -24, marginRight: -24 }}>
        <div className="ab-info">
          {valid
            ? <span className="row gap-2"><Icon name="checkCircle" size={15} color="var(--accent-data)"/> Ready — {grantedCount} purpose{grantedCount === 1 ? "" : "s"} granted</span>
            : "Consent is recorded before any personal data · written to the audit chain"}
        </div>
        <div style={{ flex: 1 }}/>
        <button className="btn btn-danger" onClick={() => setShowRefuse(true)}>
          <Icon name="xCircle" size={14}/> Refuse
        </button>
        <button className="btn btn-primary" onClick={onContinue} disabled={showErrors && !valid}>
          Capture consent and continue <Icon name="arrowRight" size={14}/>
        </button>
      </div>

      <RefuseModal open={showRefuse} onClose={() => setShowRefuse(false)} onConfirm={onRefuseConfirm}/>
      <AuditDrawer open={showAudit} onClose={() => setShowAudit(false)} events={INTAKE_AUDIT} title="Consent capture · audit"/>
      <Toast message={toast} onDone={() => setToast("")}/>
    </div>
  );
};

/* ============================================================
   Outcome card — captured / declined terminal states
   ============================================================ */
const OutcomeCard = ({ declined, reason, grantedCount, method, onReset }) => (
  <div style={{ maxWidth: 620, margin: "48px auto" }}>
    <div className="card card-body" style={{ textAlign: "center", padding: 40 }}>
      <div style={{
        width: 64, height: 64, borderRadius: "50%", margin: "0 auto 16px", display: "grid", placeItems: "center",
        background: declined ? "var(--accent-danger-bg)" : "var(--accent-data-bg)",
      }}>
        <Icon name={declined ? "xCircle" : "checkCircle"} size={34}
          color={declined ? "var(--accent-danger)" : "var(--accent-data)"}/>
      </div>
      <h2 className="t-h2" style={{ marginBottom: 6 }}>{declined ? "Consent declined" : "Consent captured"}</h2>
      <div className="muted" style={{ marginBottom: 18 }}>
        {declined
          ? "The intake has ended. No personal data was captured."
          : "Proceeding to identity and personal-data capture."}
      </div>
      <div style={{
        textAlign: "left", display: "inline-block", padding: "14px 18px", minWidth: 320,
        background: "var(--neutral-50)", border: "1px solid var(--neutral-200)", borderRadius: "var(--radius-default)",
      }}>
        {declined ? (
          <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", rowGap: 8, columnGap: 16, fontSize: 13.5 }}>
            <dt className="muted">Outcome</dt><dd style={{ margin: 0 }}><Chip tone="danger" size="sm">Declined consent</Chip></dd>
            <dt className="muted">Reason</dt><dd style={{ margin: 0 }}>{reason}</dd>
            <dt className="muted">Audit ID</dt><dd style={{ margin: 0 }} className="t-mono">AC-9F2240</dd>
          </dl>
        ) : (
          <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", rowGap: 8, columnGap: 16, fontSize: 13.5 }}>
            <dt className="muted">Purposes granted</dt><dd style={{ margin: 0 }}><strong>{grantedCount}</strong> of 9</dd>
            <dt className="muted">Capture method</dt><dd style={{ margin: 0, textTransform: "capitalize" }}>{method}</dd>
            <dt className="muted">Audit ID</dt><dd style={{ margin: 0 }} className="t-mono">AC-9F2240</dd>
          </dl>
        )}
      </div>
      <div className="row gap-3" style={{ justifyContent: "center", marginTop: 24 }}>
        <button className="btn" onClick={onReset}><Icon name="chevronLeft" size={14}/> Back to consent</button>
        {!declined && <button className="btn btn-primary">Continue to identity <Icon name="arrowRight" size={14}/></button>}
      </div>
    </div>
  </div>
);

window.ConsentIntakeScreen = ConsentIntakeScreen;
