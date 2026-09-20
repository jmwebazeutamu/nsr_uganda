/* Mount a console shell in jsdom and open every screen in its nav.
 *
 * Not a test file — `smokeTest(manifest)` is called by one per shell.
 *
 * Why this exists: an operator hit "Something went wrong rendering this
 * view" with no indication of which screen tripped it. The error
 * boundary catches the throw, so nothing in CI noticed, and reading the
 * source found nothing — the crash needed the app actually rendering.
 * This loads a shell's own scripts in manifest order, mounts it, and
 * clicks each nav entry, which is the sequence a person does.
 *
 * It found three things on its first run: a home-screen KPI block that
 * called .toLocaleString() on a field the payload need not contain, a
 * chatbot list that called .map on a non-list, and a consent guard
 * pasted inside a useEffect.
 */

import { expect, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const scriptsInOrder = (manifest) => {
  const html = fs.readFileSync(path.join(DESIGN, manifest), "utf8");
  return [...html.matchAll(/src="([^"]+\.jsx)"/g)].map(([, src]) => src.replace(/^\.\//, ""));
};

const installBrowserGlobals = async () => {
  const React = await import("react").then(m => m.default || m);
  const ReactDOMClient = await import("react-dom/client");
  const ReactDOM = await import("react-dom").then(m => m.default || m);
  globalThis.React = React;
  globalThis.ReactDOM = { ...ReactDOM, createRoot: ReactDOMClient.createRoot };
  globalThis.window = globalThis;

  // Everything answers empty. nsrApi reads text() and parses it while
  // the screens' own fetches read json(), so the two must agree — an
  // earlier version of this stub disagreed and "found" a bug that was
  // its own.
  // Empty lists only.
  //
  // A populated variant was tried and removed: one generic row cannot
  // satisfy every screen's expected payload, so six screens "crashed"
  // on a missing field and the file reported the stub's problems as the
  // product's. Data-shaped crashes — and the hook faults that only
  // appear once real rows arrive — belong to the live crawl, which
  // proxies to the dev API and found the one this harness exists for.
  const body = {
    results: [], count: 0, versions: [], items: [], data: [],
    households_total: 0, stages_pending_promotion: 0, households_with_pmt: 0,
  };
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }));
};

// The boundary renders "SCREEN CRASHED" / "Something went wrong
// rendering this view" (v0.1/components/error-boundary.jsx). Read the
// whole document: the text is split across elements, and a first
// version of this check looked only at leaf nodes, so it reported a
// clean run over a screen that had visibly crashed.
const crashed = () =>
  /SCREEN CRASHED|Something went wrong rendering this view/i.test(
    document.body.textContent || "",
  );

const crashMessage = () => {
  const text = document.body.textContent || "";
  const m = text.match(/(Minified React error[^]{0,140}|Rendered (more|fewer) hooks[^]{0,140}|TypeError:[^]{0,140})/i);
  return m ? m[0].replace(/\s+/g, " ").trim() : "(the card showed no message)";
};

/** Register the cases for one shell. */
export const smokeTest = ({ manifest, describe, beforeAll, afterAll, it }) => {
  let navButtons = [];
  let unreachable = [];

  beforeAll(async () => {
    document.body.innerHTML = '<div id="app"></div>';
    await installBrowserGlobals();

    // The shell is the last script and mounts on import, so everything
    // it names must exist first. In the browser that is automatic:
    // classic scripts share one global scope, so every top-level
    // `const` is visible to later files. Vitest imports them as ES
    // modules, where only what a file assigns to `window` escapes — so
    // a screen whose file never does that would throw "X is not
    // defined" while App renders, above the error boundary, taking the
    // whole harness down for a reason no operator can ever see.
    //
    // Stub those, and say which they were: they are covered by the
    // static hook scan and by the live crawl, not by this one.
    const files = scriptsInOrder(manifest);
    const shell = files[files.length - 1];
    for (const rel of files.slice(0, -1)) {
      await import(/* @vite-ignore */ path.join(DESIGN, rel));
    }
    const shellSrc = fs.readFileSync(path.join(DESIGN, shell), "utf8");
    unreachable = [...new Set(
      [...shellSrc.matchAll(/<([A-Z]\w+)[\s/>]/g)].map(m => m[1]),
    )].filter(name => typeof globalThis[name] === "undefined");
    for (const name of unreachable) {
      globalThis[name] = () => null;
    }
    await import(/* @vite-ignore */ path.join(DESIGN, shell));
    await new Promise(r => setTimeout(r, 50));
    navButtons = [...document.querySelectorAll(".nav-item")];
  }, 120000);

  afterAll(() => { vi.restoreAllMocks(); });

  describe(manifest, () => {
    it("mounts without crashing", () => {
      expect(crashed() ? crashMessage() : null, "the shell crashed on first render").toBeNull();
    });

    it("renders a navigation", () => {
      expect(navButtons.length).toBeGreaterThan(5);
    });

    it("reports which screens this harness cannot reach", () => {
      // Not a failure — a statement of coverage. These screens are
      // exercised by the live crawl and by the static hook scan; they
      // are simply invisible to an ES-module import.
      if (unreachable.length) {
        // eslint-disable-next-line no-console
        console.info(`${manifest}: not reachable as modules — ${unreachable.join(", ")}`);
      }
      expect(Array.isArray(unreachable)).toBe(true);
    });

    it.skipIf(!process.env.NSR_DEEP_CRAWL)(
      "opens every tab and row inside each screen without crashing", async () => {
      // Nav clicks alone reach the first render of each screen. A hook
      // fault that needs a selection — a detail panel, a second tab —
      // only shows up when something inside the screen is clicked, so
      // this goes one level deeper on each.
      const failures = [];
      const settle = () => new Promise(r => setTimeout(r, 5));
      const DESTRUCTIVE = /sign out|logout|reject|delete|promote|archive|merge|approve|submit|revoke|quarantine/i;

      for (const navButton of navButtons) {
        const screenLabel = (navButton.textContent || "").trim();
        navButton.click();
        await settle();
        if (crashed()) { failures.push(`${screenLabel} — ${crashMessage()}`); navButtons[0].click(); await settle(); continue; }

        const main = document.querySelector("main") || document.body;
        const targets = [
          ...main.querySelectorAll('[role="tab"]'),
          ...main.querySelectorAll("tbody tr"),
          ...[...main.querySelectorAll("button")].filter(
            b => !DESTRUCTIVE.test(b.textContent || "") && !b.closest(".nav-item"),
          ),
        ].slice(0, 20);

        for (const el of targets) {
          const what = (el.textContent || el.tagName).trim().slice(0, 40);
          try { el.click(); } catch { /* detached by an earlier click */ }
          await settle();
          if (crashed()) {
            failures.push(`${screenLabel} > ${what} — ${crashMessage()}`);
            navButton.click();          // reset this screen and carry on
            await settle();
          }
        }
      }
      expect(failures, `crashes found:\n${failures.join("\n")}`).toEqual([]);
      // Clicking every tab and row in every screen is minutes of work
      // when the suite runs these files in parallel; the default 5s
      // budget fails it for being slow rather than for finding
      // anything.
      }, 180000);

    it("opens every screen in the nav without crashing", async () => {
      const failures = [];
      for (const button of navButtons) {
        const label = (button.textContent || "").trim();
        button.click();
        await new Promise(r => setTimeout(r, 30));
        if (crashed()) {
          failures.push(`${label} \u2014 ${crashMessage()}`);
          // One bad screen must not mask the rest.
          navButtons[0].click();
          await new Promise(r => setTimeout(r, 30));
        }
      }
      expect(failures, `screens that crashed:\n${failures.join("\n")}`).toEqual([]);
    });
  });
};
