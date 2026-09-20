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
  const body = { results: [], count: 0, versions: [], items: [], data: [] };
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

  beforeAll(async () => {
    document.body.innerHTML = '<div id="app"></div>';
    await installBrowserGlobals();
    for (const rel of scriptsInOrder(manifest)) {
      await import(/* @vite-ignore */ path.join(DESIGN, rel));
    }
    await new Promise(r => setTimeout(r, 50));
    navButtons = [...document.querySelectorAll(".nav-item")];
  });

  afterAll(() => { vi.restoreAllMocks(); });

  describe(manifest, () => {
    it("mounts without crashing", () => {
      expect(crashed() ? crashMessage() : null, "the shell crashed on first render").toBeNull();
    });

    it("renders a navigation", () => {
      expect(navButtons.length).toBeGreaterThan(5);
    });

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
