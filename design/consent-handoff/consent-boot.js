/* NSR MIS — Consent preview boot diagnostic (plain JS, runs before Babel).
   Turns a blank screen into an actionable message: traps script errors and,
   if nothing has mounted shortly after load, explains why. Safe no-op once the
   React app renders normally. */
(function () {
  function show(title, msg) {
    var a = document.getElementById("app");
    if (!a) return;
    a.innerHTML =
      '<div style="max-width:720px;margin:48px auto;padding:24px 28px;' +
      'border:1px solid #BFBFBF;border-radius:8px;background:#fff;' +
      "font-family:Inter,system-ui,sans-serif;color:#212121\">" +
      '<div style="font-weight:700;color:#A93226;font-size:16px;margin-bottom:6px">' + title + "</div>" +
      '<pre style="white-space:pre-wrap;color:#444;font:12.5px/1.6 ui-monospace,monospace;margin:0">' +
      String(msg).replace(/[<>]/g, function (c) { return c === "<" ? "&lt;" : "&gt;"; }) + "</pre></div>";
  }
  window.addEventListener("error", function (e) {
    if (e && (e.message || e.filename)) {
      show("Consent preview — script error",
        (e.message || "Error") + "\n" + (e.filename || "") + " :" + (e.lineno || "?") + ":" + (e.colno || "?"));
    }
  }, true);
  window.addEventListener("unhandledrejection", function (e) {
    show("Consent preview — promise rejection", (e.reason && e.reason.message) || e.reason || "unknown");
  });
  window.addEventListener("load", function () {
    setTimeout(function () {
      var a = document.getElementById("app");
      if (a && a.childElementCount === 0) {
        show("Consent preview — nothing mounted",
          "The page loaded but no UI was rendered after 3s.\n\n" +
          "Likely causes:\n" +
          "  • A Babel compile error in one of the .jsx files (check the browser console).\n" +
          "  • The React/Babel CDN scripts were blocked or failed to load.\n" +
          "  • A screen component is undefined (ReactDOM.render produced empty output).\n\n" +
          "React loaded: " + (!!window.React) + "  ·  Babel loaded: " + (!!window.Babel) +
          "  ·  ConsentIntakeScreen: " + (typeof window.ConsentIntakeScreen) +
          "  ·  CitizenConsentScreen: " + (typeof window.CitizenConsentScreen) +
          "  ·  DpoWithdrawalQueueScreen: " + (typeof window.DpoWithdrawalQueueScreen));
      }
    }, 3000);
  });
})();
