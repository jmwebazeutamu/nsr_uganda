/* global React, Icon, Toggle, BasisChip,
   PURPOSES, REGISTRATION_STATEMENT_EN, REFUSAL_REASONS */
// NSR MIS — Consent capture block (US-CONSENT-03)
// =====================================================
// The per-purpose consent capture embedded in the household capture form,
// replacing the legacy single Yes/No toggle. Produces a `consent_block`
// object the intake payload carries → captured as ConsentRecords at promotion
// (apps.consent.services.capture_intake_consent). Reuses the consent-shared
// vocabulary so the form and the registry agree on purposes + bases.

const { useState: useStateCB } = React;

// Build the default block: REGISTRATION granted by default (operator flips to
// Refused if declined); non-consent bases (public task / statistical) apply;
// optional consent purposes follow their `defaultOn`.
const defaultConsentBlock = () => {
  const block = { _method: "DIGITAL", _witness_name: "", _witness_role: "", _refusal_reason: "" };
  (window.PURPOSES || []).forEach(p => {
    if (p.code === "REGISTRATION") block[p.code] = "GRANTED";
    else if (p.basis !== "Consent") block[p.code] = "GRANTED";
    else block[p.code] = p.defaultOn ? "GRANTED" : "";
  });
  return block;
};

const CB_METHODS = [
  ["DIGITAL", "Digital"], ["SIGNATURE", "Signature"],
  ["THUMBPRINT", "Thumbprint"], ["VERBAL_WITNESSED", "Verbal (witnessed)"],
];

const ConsentCaptureBlock = ({ value, onChange }) => {
  const v = value || defaultConsentBlock();
  const set = (patch) => onChange && onChange({ ...v, ...patch });
  const purposes = window.PURPOSES || [];
  const optional = purposes.filter(p => p.basis === "Consent" && p.code !== "REGISTRATION");
  const reg = v.REGISTRATION;
  const needWitness = v._method === "VERBAL_WITNESSED" && reg === "GRANTED";
  const statement = (window.REGISTRATION_STATEMENT_EN || [
    "I, the respondent, consent to the collection and processing of my household's data by MGLSD under the Data Protection and Privacy Act 2019 of Uganda.",
  ]);

  return (
    <div className="tint-update" style={{ padding: 16, borderRadius: 6, borderLeft: "3px solid var(--accent-update)" }}>
      {statement.map((para, i) => (
        <p key={i} style={{ margin: i ? "8px 0 0" : "0 0 12px", fontSize: 13, lineHeight: 1.6 }}>
          {i === 0 ? `"${para}` : para}{i === statement.length - 1 ? '"' : ""}
        </p>
      ))}

      {/* Registration — the required gate */}
      <div style={{ marginTop: 14, fontWeight: 600, fontSize: 13 }}>
        Registration consent <span style={{ color: "var(--accent-danger)" }}>*</span>
      </div>
      <div className="seg" style={{ marginTop: 6 }}>
        <button className={reg === "GRANTED" ? "on" : ""} onClick={() => set({ REGISTRATION: "GRANTED" })}>
          <Icon name="check" size={12}/> Yes — consented
        </button>
        <button className={reg === "REFUSED" ? "on" : ""} onClick={() => set({ REGISTRATION: "REFUSED" })}>No — refused</button>
      </div>

      {reg === "REFUSED" && (
        <div style={{ marginTop: 12 }}>
          <div className="t-cap" style={{ marginBottom: 4 }}>Reason for refusal</div>
          <select className="field-select" value={v._refusal_reason || ""} onChange={e => set({ _refusal_reason: e.target.value })}>
            <option value="">Select a reason…</option>
            {(window.REFUSAL_REASONS || []).map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <div className="t-cap row gap-2" style={{ marginTop: 8, color: "var(--accent-danger)" }}>
            <Icon name="alert" size={13}/> Refusing registration ends the intake — no registry record is created.
          </div>
        </div>
      )}

      {reg === "GRANTED" && (
        <>
          <div style={{ marginTop: 16, fontWeight: 600, fontSize: 13 }}>Optional purposes</div>
          <div className="t-cap" style={{ marginBottom: 8 }}>The respondent can opt in or out of each.</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {optional.map(p => (
              <div key={p.code} className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{p.name}</div>
                  <div className="t-cap" style={{ maxWidth: 360 }}>{p.blurb}</div>
                </div>
                <Toggle on={v[p.code] === "GRANTED"} ariaLabel={p.name}
                  onChange={(on) => set({ [p.code]: on ? "GRANTED" : "REFUSED" })}/>
              </div>
            ))}
          </div>

          <div className="divider mt-4" style={{ margin: "14px 0" }}/>
          <div className="row gap-3" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <div className="t-cap" style={{ marginBottom: 4 }}>Capture method</div>
              <select className="field-select" value={v._method || "DIGITAL"} onChange={e => set({ _method: e.target.value })}>
                {CB_METHODS.map(([val, lab]) => <option key={val} value={val}>{lab}</option>)}
              </select>
            </div>
            {needWitness && (
              <>
                <div>
                  <div className="t-cap" style={{ marginBottom: 4 }}>Witness name *</div>
                  <input className="field-input" value={v._witness_name || ""} onChange={e => set({ _witness_name: e.target.value })}/>
                </div>
                <div>
                  <div className="t-cap" style={{ marginBottom: 4 }}>Witness role *</div>
                  <input className="field-input" value={v._witness_role || ""} onChange={e => set({ _witness_role: e.target.value })}/>
                </div>
              </>
            )}
          </div>
          {needWitness && (
            <div className="t-cap row gap-2" style={{ marginTop: 8, color: "var(--neutral-500)" }}>
              <Icon name="info" size={13}/> Verbal-witnessed consent requires a witness name and role (AC-CONSENT-METHOD-VALID).
            </div>
          )}
        </>
      )}
    </div>
  );
};

Object.assign(window, { ConsentCaptureBlock, defaultConsentBlock });
