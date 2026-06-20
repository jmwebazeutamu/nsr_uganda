/* global React, ReactDOM,
   ConsentIntakeScreen, CitizenConsentScreen, DpoWithdrawalQueueScreen */
// NSR MIS — Consent Management app shell.
// Routes by window.__defaultScreen across the consent screens; each
// standalone preview loads only the screen module(s) it needs, so the
// router renders whichever component is actually defined.
//   "consent-intake"     → Intake consent capture (Screen 1)
//   "consent-citizen"    → Citizen consent dashboard (Screen 2 + 3)
//   "consent-dpo-queue"  → DPO withdrawal queue (Screen 4)

const initialConsentScreen =
  (typeof window !== "undefined" && window.__defaultScreen) || "consent-intake";

const ConsentApp = () => {
  const screen = initialConsentScreen;
  const has = (name) => typeof window[name] === "function";

  let body = null;
  if (screen === "consent-intake" && has("ConsentIntakeScreen")) body = <ConsentIntakeScreen/>;
  else if (screen === "consent-citizen" && has("CitizenConsentScreen")) body = <CitizenConsentScreen/>;
  else if (screen === "consent-dpo-queue" && has("DpoWithdrawalQueueScreen")) body = <DpoWithdrawalQueueScreen/>;
  // Fallback to the first available consent screen
  else if (has("ConsentIntakeScreen")) body = <ConsentIntakeScreen/>;
  else if (has("CitizenConsentScreen")) body = <CitizenConsentScreen/>;
  else if (has("DpoWithdrawalQueueScreen")) body = <DpoWithdrawalQueueScreen/>;

  return (
    <div style={{ minHeight: "100vh", background: "var(--neutral-100)" }}>
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 24px 64px" }}>
        {body}
      </div>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("app")).render(<ConsentApp/>);
