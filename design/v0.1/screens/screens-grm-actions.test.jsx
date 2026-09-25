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


describe("a bulk dialog names what it will change", () => {
  it("passes the targeted ids, not the row open in the panel", () => {
    // Every dialog said "Action will be applied to <current.id>" even
    // with twelve rows ticked. That is not vague — it names the wrong
    // thing, and the operator confirms it.
    expect(grm).not.toContain("recordLabel={current?.id}");
    expect((grm.match(/recordLabels=\{targetIds\}/g) || [])).toHaveLength(3);
  });

  it("computes the target list once, where fire() reads it", () => {
    // A dialog that derived its own list could name a different set
    // from the one the action touches, which is the bug in a new
    // place.
    expect(grm).toContain("const ids = opts.ids || targetIds;");
    expect((grm.match(/const targetIds = /g) || [])).toHaveLength(1);
  });

  it("declares the target list above the function that reads it", () => {
    // Babel-standalone rewrites const to var, so a forward reference
    // reads undefined instead of throwing — the trap this file
    // documents elsewhere.
    expect(grm.indexOf("const targetIds = "))
      .toBeLessThan(grm.indexOf("const fire = (kind"));
  });
});

describe("the console offers only what the server would accept", () => {
  it.each(["escalate", "close", "add_task", "open_change_request"])(
    "gates %s on the server's answer", (action) => {
      expect(grm).toContain(`_grmAllows(current, "${action}")`);
    },
  );

  it("no longer reads the tier to decide whether escalation is possible", () => {
    // L4 is the top of the ladder and the server says so.
    expect(grm).not.toContain('current.tier !== "l4_nsr_unit"');
  });

  it("keeps the reason visible when open tasks are what block resolve", () => {
    // Hiding it there would take away the only place that says why.
    expect(grm).toContain("const heldByTasks = !allowed && openTasks > 0;");
    expect(grm).toContain("open task(s)");
  });

  it("hides resolve outright when the case is past resolving", () => {
    expect(grm).toContain("if (!allowed && !heldByTasks) return null;");
  });

  it("acts on the open case when opening an update from it", () => {
    expect(grm).toContain('fire("open-change-request", {');
    expect(grm).toMatch(/open-change-request", \{\s*\n?\s*ids: \[current\.id\]/);
  });
});


describe("a closed case is read-only on screen too", () => {
  it("replaces the note composer with why it is gone", () => {
    // A box you can type a paragraph into and lose is worse than no
    // box: the endpoint refuses it, and the draft goes nowhere.
    expect(grm).toContain('_grmAllows(current, "comment") ? (');
    expect(grm).toContain("This case is closed and");
    expect(grm).toContain("raise a new grievance");
  });

  it("says nothing was recorded rather than inviting a note", () => {
    expect(grm).toContain("Nothing was recorded on this case.");
  });

  it("withholds task controls on a closed case", () => {
    expect(grm).toMatch(/canTransition = \(isMine \|\| me\.is_officer\)\s*\n\s*&& _grmAllows\(current, "add_task"\)/);
  });

  it("gets the answer from the server, not from the status string", () => {
    // allowed_actions returns [] for a closed case, so no ACTION is
    // gated on the status here. Rendering still reads it — the
    // CLOSING block only makes sense on a closed case — which is a
    // different thing from deciding what is permitted.
    const gates = grm.match(/_grmAllows\(current, "[a-z_]+"\)/g) || [];
    expect(gates.length).toBeGreaterThanOrEqual(6);
    expect(grm).not.toMatch(
      /disabled=\{[^}]*current\.status === "closed"/,
    );
  });
});
