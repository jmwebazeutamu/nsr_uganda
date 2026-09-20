/* The Admin Console against the real dev API.
 *
 * Synthetic stubs kept producing crashes that were the stub's fault —
 * a row without `list_name`, a body whose text() and json() disagreed.
 * The reported crash (React #310) did not reproduce against them, and
 * it would not: it needs the shapes and volumes the real endpoints
 * return.
 *
 * So this proxies every request to the dev server on :8005 with a real
 * session, and crawls. Writes are refused inside the proxy — a crash
 * hunt must not mutate the dev registry — so any POST a screen fires on
 * mount is answered 405 and the screen's own error path handles it,
 * which is itself worth exercising.
 *
 * Skipped unless NSR_LIVE_SESSION names a session key, so CI (which has
 * no server) stays green.
 */

import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ORIGIN = process.env.NSR_LIVE_ORIGIN || "http://localhost:8005";
const SESSION = process.env.NSR_LIVE_SESSION || "";
const MANIFEST = process.env.NSR_LIVE_SHELL || "nsr-mis-admin-console.html";

const realFetch = globalThis.fetch;
let navButtons = [];
const requests = [];

const crashed = () =>
  /SCREEN CRASHED|Something went wrong rendering this view/i.test(document.body.textContent || "");
const crashMessage = () => {
  const text = document.body.textContent || "";
  const m = text.match(/(Minified React error[^]{0,160}|Rendered (more|fewer) hooks[^]{0,160}|TypeError:[^]{0,160})/i);
  return m ? m[0].replace(/\s+/g, " ").trim() : "(the card showed no message)";
};

describe.skipIf(!SESSION)(`${MANIFEST} against ${ORIGIN}`, () => {
  beforeAll(async () => {
    const React = await import("react").then(m => m.default || m);
    const ReactDOMClient = await import("react-dom/client");
    const ReactDOM = await import("react-dom").then(m => m.default || m);
    globalThis.React = React;
    globalThis.ReactDOM = { ...ReactDOM, createRoot: ReactDOMClient.createRoot };
    globalThis.window = globalThis;

    globalThis.fetch = async (url, init = {}) => {
      const method = (init.method || "GET").toUpperCase();
      const target = String(url).startsWith("http") ? String(url) : ORIGIN + String(url);
      if (method !== "GET") {
        // Read-only by construction.
        return new Response(JSON.stringify({ detail: "blocked by the crash harness" }),
          { status: 405, headers: { "Content-Type": "application/json" } });
      }
      requests.push(target);
      return realFetch(target, {
        ...init,
        headers: { ...(init.headers || {}), Cookie: `sessionid=${SESSION}` },
        redirect: "follow",
      });
    };

    document.body.innerHTML = '<div id="app"></div>';
    const html = fs.readFileSync(path.join(DESIGN, MANIFEST), "utf8");
    for (const [, src] of html.matchAll(/src="([^"]+\.jsx)"/g)) {
      await import(/* @vite-ignore */ path.join(DESIGN, src.replace(/^\.\//, "")));
    }
    await new Promise(r => setTimeout(r, 400));
    navButtons = [...document.querySelectorAll(".nav-item")];
  });

  afterAll(() => { globalThis.fetch = realFetch; vi.restoreAllMocks(); });

  it("reaches the dev server", () => {
    expect(requests.length, "no request left the harness — is :8005 up?").toBeGreaterThan(0);
  });

  it("mounts and opens every screen, tab and row", async () => {
    const failures = [];
    const settle = (ms = 120) => new Promise(r => setTimeout(r, ms));
    const DESTRUCTIVE = /sign out|logout|reject|delete|promote|archive|merge|approve|submit|revoke|quarantine/i;

    if (crashed()) failures.push(`first render — ${crashMessage()}`);

    for (const navButton of navButtons) {
      const label = (navButton.textContent || "").trim();
      navButton.click();
      await settle(250);
      if (crashed()) {
        failures.push(`${label} — ${crashMessage()}`);
        navButtons[0].click(); await settle();
        continue;
      }
      const main = document.querySelector("main") || document.body;
      const targets = [
        ...main.querySelectorAll('[role="tab"]'),
        ...main.querySelectorAll("tbody tr"),
        ...[...main.querySelectorAll("button")].filter(b => !DESTRUCTIVE.test(b.textContent || "")),
      ].slice(0, 30);
      for (const el of targets) {
        const what = (el.textContent || el.tagName).trim().slice(0, 40);
        try { el.click(); } catch { /* detached */ }
        await settle();
        if (crashed()) {
          failures.push(`${label} > ${what} — ${crashMessage()}`);
          navButton.click(); await settle();
        }
      }
    }
    expect(failures, `crashes found:\n${failures.join("\n")}`).toEqual([]);
  }, 120000);
});
