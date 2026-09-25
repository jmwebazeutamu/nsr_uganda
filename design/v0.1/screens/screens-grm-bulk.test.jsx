/* QA P1.1 and P3.21 — what a bulk action tells you, and whether it
 * should have been offered at all.
 *
 * A bulk action fans out to one POST per row. When some refused, the
 * toast read "7/12 succeeded" followed by the first two reasons, with
 * no ids attached — so five cases had not moved and the operator had
 * no way to tell which five except by reading the queue again.
 *
 * And bulk Close was live whenever anything was ticked. Close applies
 * to a RESOLVED case, so on a queue of open ones the button worked,
 * the dialog asked for a reason and a note, and every single row came
 * back refused.
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

describe("a bulk action says which rows refused", () => {
  it("keeps the per-row outcome, not just a tally", () => {
    expect(grm).toContain("setBulkResult({");
    expect(grm).toMatch(/ok: ids\.filter\(id => !failed\.has\(id\)\)/);
    expect(grm).toContain("failed: failures,");
  });

  it("renders every refusal with its id and its reason", () => {
    expect(grm).toContain("bulkResult.failed.map(f => (");
    expect(grm).toContain('{" — "}{f.detail}');
  });

  it("no longer prints two reasons with no ids attached", () => {
    expect(grm).not.toContain("failures.slice(0, 2)");
  });

  it("lets the operator open a refused case from the list", () => {
    // Otherwise the id is a string to copy and hunt for.
    expect(grm).toContain("setSelectedRow(f.id); setCaseDrawer(true);");
  });

  it("can be dismissed", () => {
    expect(grm).toContain("setBulkResult(null)");
  });

  it("uses the shape the UPD workbench already uses", () => {
    // One way of reporting a bulk outcome across the console, not two.
    for (const source of [grm, upd]) {
      expect(source).toContain("last bulk:");
      expect(source).toContain("Dismiss");
    }
  });

  it("clears the previous result before acting again", () => {
    // A stale panel beside a fresh toast is worse than no panel.
    expect(grm).toMatch(/setBusy\(true\);\s*\n\s*setBulkResult\(null\);/);
  });
});

describe("a bulk button offers only what it can do", () => {
  it("counts the selected rows the server would accept", () => {
    expect(grm).toContain("const bulkEligible = (action) =>");
    expect(grm).toContain('selectedRows.filter(r => _grmAllows(r, action)).length');
  });

  it("disables the action when none of them qualifies", () => {
    expect(grm).toContain("disabled={n === 0}");
  });

  it("says why it is disabled", () => {
    expect(grm).toContain("Close applies to a resolved case.");
    expect(grm).toContain("None of the selected cases will accept an assignment");
    expect(grm).toContain("None of the selected cases can be escalated");
  });

  it("says how many will move when only some will", () => {
    expect(grm).toMatch(/\{n\} of \{selection\.size\}/);
    expect(grm).toContain("will be skipped");
  });

  it("no longer offers all three whenever anything is ticked", () => {
    expect(grm).not.toMatch(
      /<button className="btn" onClick=\{\(\) => setModal\("close"\)\}>\s*\n\s*<Icon name="check"/,
    );
  });

  it("warns again in the dialog, where the operator has stopped", () => {
    expect(grm).toContain("const bulkNotice = (action) =>");
    expect(grm).toContain('notice={bulkNotice("escalate")}');
    expect(grm).toContain('notice={bulkNotice("close")}');
    expect(grm).toContain('bulkNotice("assign")');
  });

  it("attempts every ticked row rather than pre-filtering", () => {
    // allowed_actions came with the list and can be stale. Skipping a
    // row the server would have accepted is a silent omission, which
    // is worse than an attempt that is refused and reported.
    expect(grm).toContain("const ids = opts.ids || targetIds;");
    expect(grm).not.toContain("ids: targetIds.filter(");
  });
});
