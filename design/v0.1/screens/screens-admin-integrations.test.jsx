/* The integrations screen knows nothing about any integration.
 *
 * STAAC_GRM appeared under Connector runs and no screen said how it
 * got there. The fix is a screen — and the trap is a screen that
 * knows STAAC has a bearer token, Kobo has a Knox token and UBOS has
 * neither, because then adding a connector means editing JSX and the
 * screen's idea of what exists drifts from the register's.
 *
 * So these assert the absence of knowledge: no integration named, no
 * action list of its own, no readiness text written here.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const raw = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-admin.jsx"), "utf8",
);
// Only the integrations section; the rest of the admin screen names
// plenty of things legitimately.
const section = raw.slice(
  raw.indexOf("// ── Integrations tab"),
  raw.indexOf("// ── Main screen"),
);
const code = section
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").map(l => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n");

describe("the list comes from the register", () => {
  it("reads every integration from one endpoint", () => {
    expect(code).toContain("/api/v1/dih/source-systems/integrations/");
  });

  it("renders the server's readiness lines, not its own", () => {
    expect(code).toContain("integration.checks");
    expect(code).toContain("c.ok");
  });

  it("posts to the url the server named for the action", () => {
    expect(code).toContain("actions[spec.key]");
    expect(code).toContain("_intPost(action.url, action.body");
  });

  it("offers only the actions the server says exist", () => {
    expect(code).toContain("_INT_ACTIONS.filter(a => actions[a.key])");
  });
});

describe("the screen names no integration", () => {
  for (const name of ["STAAC", "staac", "KOBO", "Kobo", "UBOS", "NIRA"]) {
    it(`does not mention ${name}`, () => {
      expect(code).not.toContain(name);
    });
  }

  it("builds the credential form from the fields the server sends", () => {
    // Not keyed by integration, and no longer keyed by a form NAME
    // either: name, label, type and help all come from the adapter,
    // so a partner needing a client id and a secret needs no change
    // here.
    expect(code).toContain("credential.fields");
    expect(code).toContain("fields.map(f =>");
    expect(code).toContain("f.label");
    expect(code).toContain("f.help");
  });

  it("offers no form where the server sends no save url", () => {
    // Better the note saying where the credential lives than a form
    // that posts nowhere.
    expect(code).toContain("if (!save || fields.length === 0)");
  });

  it("omits a blank secret instead of sending an empty one", () => {
    // So the server can tell "keep the stored one" from "clear it".
    expect(code).toContain('f.type === "password" && !String(v || "").trim()');
  });

  it("hardcodes no source code, kind or endpoint besides the list", () => {
    const urls = code.match(/"\/api\/v1\/[^"]+"/g) || [];
    expect(urls).toEqual(['"/api/v1/dih/source-systems/integrations/"']);
  });
});

describe("what an operator is told", () => {
  it("says a dry run writes nothing", () => {
    expect(code).toContain("writes nothing");
    expect(code).toContain("Nothing was written.");
  });

  it("shows unwired sources rather than hiding them", () => {
    // Absent reads as "does not exist", which is the wrong answer for
    // a source that is registered and simply not configured.
    expect(code).toContain("Registered, not wired");
  });

  it("marks a dry run's run record as such in the history", () => {
    expect(code).toContain('r.run_type === "test"');
  });
});
