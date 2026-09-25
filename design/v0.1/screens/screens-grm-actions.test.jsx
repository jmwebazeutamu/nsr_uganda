/* QA P3.15 and P3.16 — two buttons that did not do, or say, what they
 * were labelled.
 *
 * "Assign to me" opened the assignee picker. The operator had already
 * said who; being asked again is the one thing that button should not
 * have done. And it only appeared on an unassigned case, so taking one
 * over from someone else meant going through the picker and finding
 * your own name in it.
 *
 * The resolve dialog's confirm button said "Confirm approve". Nothing
 * was being approved. The label was derived from `intent`, which picks
 * the button's COLOUR — so every dialog tinted green claimed to
 * approve something, including UPD's "Release from hold".
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (p) => fs.readFileSync(path.join(process.cwd(), p), "utf8");
const strip = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").map(l => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n");

const grm = strip(read("design/v0.1/screens/screens-grm.jsx"));
const upd = strip(read("design/v0.1/screens/screens-upd.jsx"));
const components = strip(read("design/components.jsx"));

describe('"Assign to me" assigns', () => {
  it("posts the assignment instead of opening the picker", () => {
    expect(grm).toContain("body: { assigned_to: me.username }");
  });

  it("keeps a separate button for assigning to someone else", () => {
    expect(grm).toContain("Assign…");
    expect(grm).toContain('setModal("assign")');
  });

  it("acts on the open case, not on whatever is ticked", () => {
    // fire() reads the bulk selection by default. Taking one case
    // would otherwise take every row ticked for a bulk action.
    expect(grm).toContain("ids: [current.id]");
    expect(grm).toContain("const ids = opts.ids");
  });

  it("does not clear a selection it never read", () => {
    expect(grm).toContain("if (!opts.ids) setSelection(new Set());");
  });

  it("hides itself when the case is already mine", () => {
    expect(grm).toContain('current.assigned_to !== me.username');
  });

  it("appears on an assigned case, so it can be taken over", () => {
    // The old condition was `!current.assigned_to`, which meant
    // reassignment had to go through the picker.
    expect(grm).not.toContain("{!current.assigned_to && (");
  });

  it("asks the server what the case will accept", () => {
    expect(grm).toContain('_grmAllows(current, "assign")');
    expect(grm).toContain("allowed_actions: g.allowed_actions || null");
  });

  it("does not refuse on its own authority when the server has not answered", () => {
    // An offline preview row has no allowed_actions; the console must
    // not invent a state machine to fill the gap.
    expect(grm).toContain("if (!row.allowed_actions) return true;");
  });
});

describe("a confirm button says what it confirms", () => {
  it("takes its words from the caller, not from its colour", () => {
    expect(components).toContain("confirmLabel");
    expect(components).toMatch(/\{confirmLabel\s*\n?\s*\|\|/);
  });

  it.each([
    ["Resolve", grm],
    ["Escalate", grm],
  ])("names the GRM action: %s", (label, source) => {
    expect(source).toContain(`confirmLabel="${label}"`);
  });

  it("labels the GRM close dialog with what it closes", () => {
    expect(grm).toMatch(/confirmLabel=\{selection\.size > 1/);
  });

  it("stops UPD offering to approve a release from hold", () => {
    expect(upd).toContain('confirmLabel="Release"');
    expect(upd).toContain('confirmLabel="Hold"');
  });

  it("leaves a genuine approval saying approve", () => {
    // The default still reads from intent, so the UPD and DRS approve
    // dialogs are unchanged.
    expect(components).toContain("'Confirm approve'");
  });
});
