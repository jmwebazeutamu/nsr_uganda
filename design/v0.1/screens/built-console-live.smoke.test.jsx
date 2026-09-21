/* The BUILT console — the exact files the browser is served — against
 * the real API.
 *
 * Every other suite imports the JSX as ES MODULES, where each file's
 * top-level scope is its own. The browser loads them as CLASSIC
 * SCRIPTS sharing one global scope, and the build additionally
 * downlevels them through Babel preset-env to ES5. Neither difference
 * is cosmetic, and one of them hid a crash:
 *
 *   household-review.jsx declared `ReviewSection`.
 *   app-change-request.jsx declares a DIFFERENT `ReviewSection`,
 *   taking { scope, member, rows, ... }, and loads 13 files later.
 *   So every <ReviewSection> in the household review resolved to that
 *   one, whose first statement is `const fieldCount = rows.length`.
 *
 * Opening a detailed review crashed the screen. 55 unit tests, a
 * stubbed screen crawl and a live crawl of the JSX all passed, because
 * in every one of them the collision cannot occur.
 *
 * design/v0.1/no-duplicate-globals.test.js now catches that specific
 * class statically and needs no server. This suite is the backstop for
 * everything the build does that static analysis cannot see.
 *
 * Skipped unless NSR_LIVE_SESSION names a session key and the console
 * has been built, so CI stays green. Run it with:
 *
 *   node scripts/build_console.mjs
 *   NSR_LIVE_SESSION=<key> npx vitest run \
 *     design/v0.1/screens/built-console-live.smoke.test.jsx
 *
 * Mint a key with SessionStore() in manage.py shell. Writes are
 * refused inside the harness — a crash hunt must not mutate the dev
 * registry. */
import { beforeAll, describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const BUILD = path.join(ROOT, "static", "console");
const ORIGIN = process.env.NSR_LIVE_ORIGIN || "http://localhost:8005";
const SESSION = process.env.NSR_LIVE_SESSION || "";
const realFetch = globalThis.fetch;

const crashed = () => /SCREEN CRASHED|Something went wrong rendering/i.test(document.body.textContent || "");
const msg = () => {
  const t = document.body.textContent || "";
  const m = t.match(/(TypeError:[^]{0,200}|Cannot read[^]{0,200}|Minified React error[^]{0,200})/i);
  return m ? m[0].replace(/\s+/g," ").trim() : "(no message on the card)";
};

const BUILT = fs.existsSync(path.join(BUILD, "manifest.json"));

describe.skipIf(!SESSION || !BUILT)("built console, DIH detailed review", () => {
  beforeAll(async () => {
    const React = await import("react").then(m=>m.default||m);
    const ReactDOMClient = await import("react-dom/client");
    const ReactDOM = await import("react-dom").then(m=>m.default||m);
    globalThis.React = React;
    globalThis.ReactDOM = { ...ReactDOM, createRoot: ReactDOMClient.createRoot };
    globalThis.window = globalThis;
    globalThis.fetch = async (url, init={}) => {
      const method = (init.method||"GET").toUpperCase();
      const target = String(url).startsWith("http") ? String(url) : ORIGIN + String(url);
      if (method !== "GET") return new Response(JSON.stringify({detail:"blocked"}),{status:405,headers:{"Content-Type":"application/json"}});
      return realFetch(target, { ...init, headers: {...(init.headers||{}), Cookie:`sessionid=${SESSION}`}, redirect:"follow" });
    };
    document.body.innerHTML = '<div id="app"></div>';
    const scripts = JSON.parse(fs.readFileSync(path.join(BUILD, "manifest.json"), "utf8")).scripts;
    // Classic scripts: they declare globals and rely on sharing one
    // scope, which is what the browser gives them. indirect eval puts
    // them in the global scope here too.
    const geval = eval;
    for (const name of scripts) {
      if (/app\.js$/.test(name)) continue;        // the shell mounts itself
      geval(fs.readFileSync(path.join(BUILD, "js", name), "utf8"));
    }
    await new Promise(r=>setTimeout(r,200));
  });

  it("opens every record's detailed review", async () => {
    const settle = (ms=300) => new Promise(r=>setTimeout(r,ms));
    const { render } = await import("@testing-library/react");
    const { DIHScreen, ErrorBoundary } = globalThis;
    expect(DIHScreen, "DIHScreen not defined by the built bundle").toBeTruthy();
    render(ErrorBoundary
      ? React.createElement(ErrorBoundary, null, React.createElement(DIHScreen))
      : React.createElement(DIHScreen));
    await settle(1200);
    expect(crashed() ? `queue: ${msg()}` : null).toBeNull();

    const rowCount = document.querySelectorAll("tbody tr").length;
    console.log("built bundle — rows:", rowCount);
    expect(rowCount).toBeGreaterThan(0);

    const failures = [];
    for (let i = 0; i < rowCount; i++) {
      const rows = [...document.querySelectorAll("tbody tr")];
      if (!rows[i]) break;
      const who = (rows[i].textContent || "").trim().slice(0, 40);
      rows[i].click(); await settle(180);
      if (crashed()) { failures.push(`row ${i} (${who}) select — ${msg()}`); break; }
      const btn = [...document.querySelectorAll("button")].find(b => /detailed review/i.test(b.textContent||""));
      if (!btn) continue;
      btn.click(); await settle(350);
      if (crashed()) { failures.push(`row ${i} (${who}) REVIEW — ${msg()}`); break; }
      const close = [...document.querySelectorAll("button")].find(b => /^close$/i.test((b.textContent||"").trim()));
      if (close) { close.click(); await settle(120); }
    }
    expect(failures, `\n${failures.join("\n")}`).toEqual([]);
  }, 180000);
});
