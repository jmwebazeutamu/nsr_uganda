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

// Build the default block.
//
// Every CONSENT-basis purpose starts UNSET (""), including REGISTRATION.
// DPPA 2019 §1 defines consent as a "freely given, specific, informed and
// unambiguous indication" by the data subject — a pre-ticked box is an
// indication by the form designer, not by the respondent, so a default of
// GRANTED records consent nobody gave. Opening a fresh capture used to
// show "✓ Yes — consented" already selected plus four optional purposes
// already ON.
//
// Purposes on a non-consent lawful basis (public task, statistical
// exemption) are NOT consent and do not have an unset state — they apply
// by law and are shown as such. They stay GRANTED.
//
// `defaultOn` is retained on the purpose vocabulary because the citizen
// portal uses it to order and recommend purposes; it no longer pre-grants
// anything at capture. See ADR-0031.
const defaultConsentBlock = () => {
  const block = { _method: "DIGITAL", _witness_name: "", _witness_role: "", _refusal_reason: "" };
  (window.PURPOSES || []).forEach(p => {
    block[p.code] = p.basis === "Consent" ? "" : "GRANTED";
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
                  <div style={{ fontWeight: 600, fontSize: 13 }}>
                    {p.name}
                    {!v[p.code] && (
                      <span className="t-cap" style={{ marginLeft: 8, color: "var(--neutral-500)", fontWeight: 500 }}>
                        not asked
                      </span>
                    )}
                  </div>
                  <div className="t-cap" style={{ maxWidth: 360 }}>{p.blurb}</div>
                </div>
                {/* Three states, not two: unset ("not asked"), granted,
                    refused. A plain on/off toggle cannot represent "the
                    respondent was never asked", which is the state a
                    fresh form is actually in. */}
                <div className="seg" role="group" aria-label={p.name}>
                  <button className={v[p.code] === "GRANTED" ? "on" : ""}
                    aria-pressed={v[p.code] === "GRANTED"}
                    onClick={() => set({ [p.code]: "GRANTED" })}>Yes</button>
                  <button className={v[p.code] === "REFUSED" ? "on" : ""}
                    aria-pressed={v[p.code] === "REFUSED"}
                    onClick={() => set({ [p.code]: "REFUSED" })}>No</button>
                </div>
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
