/* The GRM audit drawer reads the chain; the Updates link points at the
 * update that exists.
 *
 * Both defects were the same shape: the screen made up a value it could
 * have asked for. The drawer told a story about the case from its
 * current state — "Via parish channel", "System GRM · SLA breach
 * auto-escalator · 48h later", audit ids of the form
 * A-2026-05-<tail>-001 — and "Open linked UPD" built an id by
 * concatenating the literal "01HXYUPD" with the tail of the grievance
 * id, then navigated to it.
 *
 * Source-level assertions rather than renders: the fabrications were
 * string literals, and a literal is what has to stay gone.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (p) => fs.readFileSync(path.join(process.cwd(), p), "utf8");

// Comments are stripped before the "no longer invents" checks. The
// removals are documented in the very comments that would otherwise
// trip them, and a guard a comment can fail is a guard people delete.
const code = (source) => source
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n")
  .map(line => line.replace(/(^|\s)\/\/.*$/, "$1"))
  .join("\n");

const grm = code(read("design/v0.1/screens/screens-grm.jsx"));
const upd = code(read("design/v0.1/screens/screens-upd.jsx"));
const components = code(read("design/components.jsx"));

describe("the audit drawer shows the real chain", () => {
  it("fetches the case's events from the server", () => {
    expect(grm).toContain("/audit/`");
    expect(grm).toContain("setAuditRaw");
  });

  it("builds drawer rows out of audit fields, not the grievance's state", () => {
    expect(grm).toContain("e.actor_id");
    expect(grm).toContain("e.occurred_at");
    expect(grm).toContain("e.self_hash");
  });

  it.each([
    ["Via parish channel", /Via \$\{[^}]*parish channel/],
    ["a synthesised audit id", /A-2026-\d\d-/],
    ["an invented auto-escalator", /auto-escalator/],
  ])("no longer invents %s", (_label, pattern) => {
    expect(grm).not.toMatch(pattern);
  });

  it("only asks for the chain when the drawer is open", () => {
    // Fetching per selected row would put a request behind every
    // arrow-key press down the queue, and each one writes a read event.
    expect(grm).toContain("if (!auditOpen || !selectedRow)");
  });
});

describe("the drawer's filters act on the events it was given", () => {
  it("derives the actor and action options from the events", () => {
    expect(components).toMatch(/events\.map\(e => e\.who\)/);
    expect(components).toMatch(/events\.map\(e => e\.action\)/);
  });

  it("actually narrows the list", () => {
    expect(components).toMatch(/events\.filter\(/);
  });
});
