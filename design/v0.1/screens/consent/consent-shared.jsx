/* global React, Icon, Chip */
// NSR MIS — Consent Management · shared vocabulary & data
// =====================================================
// Module family: SEC (security). Accent: --accent-system (#37474F)
// on --accent-system-bg (#F0F4F8).
//
// The base <Chip> in components.jsx maps labels → tones via CHIP_MAP,
// but several consent labels collide with existing ones ("Open" →
// grievance tone, "Active" absent, etc). To keep the exact consent
// vocabulary from the brief AND control colour precisely, the consent
// chips below pass an EXPLICIT tone to <Chip> rather than relying on
// label lookup. Status colour is never the only cue — the label is
// always present (WCAG 2.1 AA, brief §9).

const { useState: useStateCS } = React;

/* ---------- Consent state (per record) ---------- */
const CONSENT_STATE_TONE = {
  "Granted":             "data",     // --accent-data
  "Refused":             "danger",   // --accent-danger
  "Withdrawn":           "neutral",  // --neutral-700 on --neutral-100
  "Pending review":      "quality",  // --accent-quality
  "Pending re-consent":  "update",   // --accent-update
};
const ConsentStateChip = ({ state, size }) => (
  <Chip tone={CONSENT_STATE_TONE[state] || "neutral"} size={size}>{state}</Chip>
);

/* ---------- Withdrawal ticket state ---------- */
const TICKET_STATE_TONE = {
  "Open":                  "update",
  "In DPO review":         "quality",
  "Confirmed":             "data",
  "Public-task override":  "identity",
  "Clarification requested":"quality",
  "Closed":                "neutral",
};
const TicketStateChip = ({ state, size }) => (
  <Chip tone={TICKET_STATE_TONE[state] || "neutral"} size={size}>{state}</Chip>
);

/* ---------- Statement version / purpose lifecycle ---------- */
const LIFECYCLE_TONE = {
  "Draft":      "neutral",
  "Active":     "data",
  "Superseded": "neutral",
  "Retired":    "neutral",
};
const LifecycleChip = ({ state, size }) => (
  <Chip tone={LIFECYCLE_TONE[state] || "neutral"} size={size}>{state}</Chip>
);

/* ---------- Lawful basis (read-only metadata, not status) ----------
   Rendered as a quiet outline chip so it reads as a property, not a
   live state. Six options from DPPA 2019. */
const LAWFUL_BASES = [
  "Consent", "Public task", "Contract",
  "Vital interest", "Legal obligation", "Statistical exemption",
];
const BasisChip = ({ basis, title }) => (
  <span
    title={title}
    style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      height: 20, padding: "0 8px",
      fontSize: 11.5, fontWeight: 600, lineHeight: 1,
      color: "var(--neutral-700)",
      background: "var(--neutral-0)",
      border: "1px solid var(--neutral-300)",
      borderRadius: 4, whiteSpace: "nowrap",
    }}>
    <Icon name={basis === "Consent" ? "check" : "shield"} size={11}
          color="var(--neutral-500)"/>
    {basis}
  </span>
);

/* ---------- Languages (English + 6 Ugandan) ----------
   English carries real copy this pass; the rest are functional
   switcher targets with placeholder bodies. */
const LANGUAGES = [
  { code: "en",  label: "English",     native: "English",    ready: true  },
  { code: "lg",  label: "Luganda",     native: "Luganda",    ready: false },
  { code: "nyn", label: "Runyankole",  native: "Runyankole", ready: false },
  { code: "ach", label: "Acholi",      native: "Acholi",     ready: false },
  { code: "xog", label: "Lusoga",      native: "Lusoga",     ready: false },
  { code: "lgg", label: "Lugbara",     native: "Lugbara",    ready: false },
  { code: "teo", label: "Ateso",       native: "Ateso",      ready: false },
];

/* ---------- The 9 purposes (from consent_management_scope.md) ---------- */
const PURPOSES = [
  {
    code: "REGISTRATION", name: "Registration",
    basis: "Consent", withdrawable: true, defaultOn: true, primary: true,
    blurb: "Create and maintain your household's record in the National Social Registry.",
  },
  {
    // CONSENT-O-01 (locked 2026-05-30, ADR-0024): ELIGIBILITY is the purpose
    // PMT recompute gates on (US-CONSENT-12). It replaces the designer's
    // inferred IDENTITY_VERIFICATION, which the DPIA treats as a public-task
    // activity (IDV/NIRA), not a consent purpose.
    code: "ELIGIBILITY", name: "Eligibility assessment",
    basis: "Consent", withdrawable: true, defaultOn: true, optional: true,
    blurb: "Use your record to compute your household's eligibility score (PMT) for social programmes.",
  },
  {
    code: "REFERRAL", name: "Programme referral",
    basis: "Consent", withdrawable: true, defaultOn: true, optional: true,
    blurb: "Share your record with social programmes you may be eligible for.",
  },
  {
    code: "PAYMENTS", name: "Payments",
    basis: "Consent", withdrawable: true, defaultOn: true, optional: true,
    blurb: "Use your record to deliver cash or in-kind transfers to your household.",
  },
  {
    code: "COMMUNICATIONS_SMS", name: "SMS notifications",
    basis: "Consent", withdrawable: true, defaultOn: false, optional: true,
    blurb: "Receive SMS messages about your registration status and benefits.",
  },
  {
    code: "COMMUNICATIONS_USSD", name: "USSD self-service",
    basis: "Consent", withdrawable: true, defaultOn: false, optional: true,
    blurb: "Check your status yourself using the *234# USSD menu on any phone.",
  },
  {
    code: "RESEARCH", name: "Research",
    basis: "Consent", withdrawable: true, defaultOn: false, optional: true,
    blurb: "Allow de-identified use of your data for approved policy research.",
  },
  {
    code: "GRIEVANCE_CONTACT", name: "Grievance contact",
    basis: "Consent", withdrawable: true, defaultOn: true, optional: true,
    blurb: "Let grievance officers contact you about complaints you file.",
  },
  {
    code: "STATISTICS", name: "National statistics",
    basis: "Statistical exemption", withdrawable: false, defaultOn: true,
    blurb: "Produce anonymous national poverty statistics with UBOS.",
    basisNote: "Statistical exemption under DPPA 2019 §7(2)(e). Not withdrawable.",
  },
];
const PURPOSE_BY_CODE = Object.fromEntries(PURPOSES.map(p => [p.code, p]));

/* ---------- Refusal reasons (controlled list) ---------- */
const REFUSAL_REASONS = [
  "Citizen declined without stating a reason",
  "Citizen wants to consult household head first",
  "Citizen objects to data sharing with programmes",
  "Citizen does not trust digital records",
  "Language barrier — could not obtain informed consent",
  "Citizen is not the eligible respondent",
  "Other (see note)",
];

/* ---------- Withdrawal reasons (optional, citizen-facing) ---------- */
const WITHDRAWAL_REASONS = [
  "I no longer want to take part",
  "I have privacy concerns",
  "I have moved out of the programme area",
  "I receive support elsewhere",
  "Prefer not to say",
];

/* ---------- Plain-language statement copy (English, v3) ---------- */
const REGISTRATION_STATEMENT_EN = [
  "The National Social Registry (NSR) is run by the Ministry of Gender, Labour and Social Development. We are asking to record information about you and the people in your household so that government and partner programmes can find and support families who need help.",
  "We will keep your information safe and use it only for the purposes you agree to below. You can change your mind later. Withdrawing your consent will not affect support you are already receiving.",
  "Your information is protected under the Data Protection and Privacy Act, 2019. You have the right to see your record, ask us to correct it, and ask us to stop using it for any purpose that depends on your consent.",
];

/* ---------- Small presentational helpers shared across screens ---------- */

// Reusable section heading inside cards
const ConsentSectionLabel = ({ children, hint }) => (
  <div style={{ marginBottom: 12 }}>
    <div style={{
      fontSize: 12, fontWeight: 700, letterSpacing: "0.06em",
      textTransform: "uppercase", color: "var(--neutral-500)",
    }}>{children}</div>
    {hint && <div className="t-bodysm muted" style={{ marginTop: 4 }}>{hint}</div>}
  </div>
);

// Anchor-story annotation pill (design-review aid; brief asks each
// screen to be annotated with the user story it anchors).
const StoryTag = ({ children }) => (
  <span style={{
    display: "inline-flex", alignItems: "center", gap: 6,
    height: 22, padding: "0 8px",
    fontSize: 11, fontWeight: 600,
    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
    color: "var(--accent-system)", background: "var(--accent-system-bg)",
    border: "1px dashed rgba(55,71,79,0.4)", borderRadius: 4,
  }}>
    <Icon name="git" size={11}/>{children}
  </span>
);

// iOS-style toggle switch tuned to the token palette
const Toggle = ({ on, onChange, disabled, ariaLabel }) => (
  <button
    role="switch" aria-checked={on} aria-label={ariaLabel}
    disabled={disabled}
    onClick={() => !disabled && onChange?.(!on)}
    style={{
      position: "relative", width: 40, height: 22, flex: "0 0 40px",
      borderRadius: 999, border: "1px solid",
      borderColor: on ? "var(--accent-data)" : "var(--neutral-300)",
      background: disabled ? "var(--neutral-100)" : on ? "var(--accent-data)" : "var(--neutral-200)",
      cursor: disabled ? "not-allowed" : "pointer",
      transition: "background-color .12s ease, border-color .12s ease",
      opacity: disabled ? 0.6 : 1, padding: 0,
    }}>
    <span style={{
      position: "absolute", top: 2, left: on ? 20 : 2,
      width: 16, height: 16, borderRadius: "50%",
      background: "var(--neutral-0)",
      boxShadow: "0 1px 2px rgba(0,0,0,0.25)",
      transition: "left .12s ease",
    }}/>
  </button>
);

/* ---------- Export ---------- */
Object.assign(window, {
  ConsentStateChip, TicketStateChip, LifecycleChip, BasisChip,
  LAWFUL_BASES, LANGUAGES, PURPOSES, PURPOSE_BY_CODE,
  REFUSAL_REASONS, WITHDRAWAL_REASONS, REGISTRATION_STATEMENT_EN,
  ConsentSectionLabel, StoryTag, Toggle,
  CONSENT_STATE_TONE, TICKET_STATE_TONE,
});
