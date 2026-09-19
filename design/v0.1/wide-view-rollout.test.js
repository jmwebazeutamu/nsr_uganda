/* Every screen the shell offers a wide view for must implement one.
 *
 * `WIDE_SCREENS` in app.jsx is a promise: open `?wide=<id>` and you get
 * that list without the nav and masthead. The screen keeps its half of
 * the promise by calling `useWideView` with the same id and rendering
 * `WideViewButtons`, or the entry is a window that opens on a screen
 * with no way back to normal width and no button to press.
 *
 * The ids are the app shell's own screen ids, so a rename on one side
 * and not the other produces a pop-out that renders "No wide view for
 * this screen" — which is exactly the failure this catches.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP = fs.readFileSync(path.join(DESIGN, "app.jsx"), "utf8");

/** The ids registered in app.jsx's WIDE_SCREENS map. */
const registered = () => {
  const block = APP.slice(
    APP.indexOf("const WIDE_SCREENS = {"),
    APP.indexOf("// Records a wide list can open"),
  );
  return [...block.matchAll(/^\s{2}"?([a-z-]+)"?:\s*\{/gm)].map(m => m[1]);
};

/**
 * Does this source claim that wide-view id?
 *
 * Usually it is a literal `useWideView("dedup")`. The registry screen
 * picks its id from the active tab —
 * `useWideView(view === "members" ? "registry-members" : "registry")` —
 * so a caller is a file that calls the hook and names the id, not one
 * that spells the whole call out.
 */
const claims = (src, id) =>
  /useWideView\(/.test(src) && src.includes(`"${id}"`);

/** Files the operator console ships, as source text. */
const consoleSources = () => {
  const html = fs.readFileSync(path.join(DESIGN, "nsr-mis-console.html"), "utf8");
  return [...html.matchAll(/src="([^"]+\.jsx)"/g)]
    .map(([, src]) => src.replace(/^\.\//, ""))
    .map(rel => ({ rel, src: fs.readFileSync(path.join(DESIGN, rel), "utf8") }));
};

describe("wide-view rollout", () => {
  const ids = registered();

  it("registers the lists the ADR names", () => {
    expect(new Set(ids)).toEqual(new Set([
      "dih", "registry", "registry-members", "dedup",
      "grm", "drs", "beneficiaries", "partners",
    ]));
  });

  it.each(ids)("%s — a screen calls useWideView with that id", (id) => {
    const callers = consoleSources().filter(({ src }) => claims(src, id));
    expect(
      callers.map(c => c.rel),
      `No shipped screen calls useWideView("${id}"). The shell offers a `
      + "wide window for it, so the window would open on a screen that "
      + "renders at normal width with no way to exit.",
    ).not.toEqual([]);
  });

  it.each(ids)("%s — that screen renders the buttons", (id) => {
    const caller = consoleSources().find(({ src }) => claims(src, id));
    expect(caller, `nothing claims the id "${id}"`).toBeTruthy();
    expect(
      caller.src.includes("<WideViewButtons"),
      `${caller.rel} calls useWideView but renders no WideViewButtons, so `
      + "there is no way into the wide view from the screen itself.",
    ).toBe(true);
  });

  it.each(ids)("%s — that screen wraps itself in WideShell", (id) => {
    // Without the shell the maximise button sets state that nothing
    // renders: the overlay is what makes it full-viewport.
    const caller = consoleSources().find(({ src }) => claims(src, id));
    expect(caller.src).toContain("<WideShell");
  });

  it("loads the module before every screen that calls it", () => {
    const html = fs.readFileSync(path.join(DESIGN, "nsr-mis-console.html"), "utf8");
    const order = [...html.matchAll(/src="([^"]+\.jsx)"/g)].map(m => m[1]);
    const moduleAt = order.findIndex(s => s.includes("wide-view"));
    expect(moduleAt).toBeGreaterThanOrEqual(0);
    const callers = consoleSources()
      .filter(({ src }) => /useWideView\("/.test(src))
      .map(({ rel }) => order.findIndex(s => s.endsWith(rel) || rel.endsWith(s)));
    for (const at of callers) {
      expect(at).toBeGreaterThan(moduleAt);
    }
  });

  it("declares every hook above its component's early returns", () => {
    // The real risk in this rollout. `useWideView` placed below an
    // early return parses fine and then changes hook order between
    // renders, which React reports as a different component — a
    // failure that only appears on the branch that returns early, so
    // the screen works until the day it is loading or empty.
    const offenders = [];
    for (const { rel, src } of consoleSources()) {
      const lines = src.split("\n");
      const hookAt = lines.findIndex(l => l.includes("useWideView("));
      if (hookAt === -1) continue;
      // The component this hook belongs to: the nearest declaration above it.
      let declAt = hookAt;
      while (declAt >= 0 && !/^const [A-Z][A-Za-z]*\s*=\s*\(?/.test(lines[declAt])) declAt -= 1;
      const between = lines.slice(declAt + 1, hookAt);
      const earlyReturn = between.findIndex(l => /^  return[\s(]/.test(l));
      if (earlyReturn !== -1) {
        offenders.push(`${rel}: useWideView at line ${hookAt + 1} is below a `
          + `top-level return at line ${declAt + 2 + earlyReturn}`);
      }
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });

  it("gives every detail target a renderer", () => {
    // A row click in a popped-out list navigates within that window.
    // Any target without an entry renders an explanation instead, so
    // these three are the ones that actually work.
    const block = APP.slice(APP.indexOf("const WIDE_DETAILS = {"));
    for (const target of ["household", "registry-member-detail", "partner-detail"]) {
      expect(block).toContain(`${target.includes("-") ? `"${target}"` : target}:`);
    }
  });
});
