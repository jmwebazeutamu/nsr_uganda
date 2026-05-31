/* global React, ReactDOM, Icon,
   ConsentIntakeScreen, CitizenConsentScreen */
// NSR MIS — Citizen Consent Portal shell (US-CONSENT-03 + -05)
// =====================================================
// Mounts the two citizen-facing consent screens (intake capture + the
// per-member dashboard) behind a top nav, with a STUB auth context. The
// production Keycloak citizen realm + OIDC flow is a deferred follow-up
// (ADR-0024 D9); until it lands, window.__consentAuth supplies the signed-in
// member so the portal can swap in the real identity later without touching
// the screens.

const { useState: useStatePortal } = React;

// Stub auth context — the Keycloak adapter will replace this object with the
// real authenticated citizen. Shape is intentionally minimal.
const CONSENT_AUTH = (typeof window !== "undefined" && window.__consentAuth) || {
  memberId: "M1",
  displayName: "Demo Citizen (stub auth)",
  role: "citizen",
};

const PORTAL_TABS = [
  { id: "capture", label: "New consent capture", icon: "edit", screen: "ConsentIntakeScreen" },
  { id: "dashboard", label: "My consent", icon: "shield", screen: "CitizenConsentScreen" },
];

const ConsentPortalApp = () => {
  const initial = (typeof window !== "undefined" && window.__defaultScreen === "consent-citizen")
    ? "dashboard" : "capture";
  const [tab, setTab] = useStatePortal(initial);
  const has = (name) => typeof window[name] === "function";

  let body = null;
  if (tab === "capture" && has("ConsentIntakeScreen")) body = <ConsentIntakeScreen/>;
  else if (tab === "dashboard" && has("CitizenConsentScreen")) body = <CitizenConsentScreen/>;

  return (
    <div style={{ minHeight: "100vh", background: "var(--neutral-100)" }}>
      {/* Portal top bar with stub-auth identity */}
      <div style={{
        background: "var(--accent-system, #37474F)", color: "#fff",
        padding: "12px 24px", display: "flex", justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div className="row gap-2" style={{ fontWeight: 700 }}>
          <Icon name="shield" size={16} color="#fff"/> NSR Consent Portal
        </div>
        <div className="row gap-2" style={{ fontSize: 12.5, opacity: 0.9 }}>
          <Icon name="user" size={13} color="#fff"/>
          {CONSENT_AUTH.displayName} · member {CONSENT_AUTH.memberId}
        </div>
      </div>

      {/* Nav */}
      <div role="tablist" style={{
        display: "flex", gap: 0, borderBottom: "1px solid var(--neutral-200)",
        background: "var(--neutral-0)", padding: "0 24px",
      }}>
        {PORTAL_TABS.map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} role="tab" onClick={() => setTab(t.id)} style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "12px 16px", border: "none", background: "none",
              cursor: "pointer", fontSize: 13.5, fontWeight: active ? 700 : 500,
              color: active ? "var(--accent-system, #37474F)" : "var(--neutral-600)",
              borderBottom: active ? "2px solid var(--accent-system, #37474F)" : "2px solid transparent",
            }}>
              <Icon name={t.icon} size={14}/>{t.label}
            </button>
          );
        })}
      </div>

      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 24px 64px" }}>
        {body}
      </div>
    </div>
  );
};

if (typeof document !== "undefined" && document.getElementById("app")) {
  ReactDOM.createRoot(document.getElementById("app")).render(<ConsentPortalApp/>);
}

if (typeof window !== "undefined") {
  Object.assign(window, { ConsentPortalApp, CONSENT_AUTH });
}
