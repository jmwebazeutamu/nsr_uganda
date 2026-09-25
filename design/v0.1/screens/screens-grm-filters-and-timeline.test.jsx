/* QA P3.13 and P3.14 — two claims the workbench made that were not
 * true of the data behind them.
 *
 * "Assigned to me" tested `assigned_to !== ""`. That is assigned to
 * ANYONE. On a queue where most cases have an owner it matched nearly
 * all of them, and the number on the chip was computed from the same
 * predicate — so the count agreed with the wrong list and nothing
 * looked inconsistent.
 *
 * The timeline was reconstructed from the grievance's current state.
 * "Assigned to X" was stamped with `opened_at`, the time the case was
 * raised rather than handed over. Escalated, Resolved and Closed
 * carried the literal "—" where a timestamp belongs. And the order was
 * whatever order the builder pushed things in, so a task created
 * before an assignment appeared after it.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-grm.jsx"), "utf8",
);
const code = source
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").map(l => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n");

describe('"Assigned to me" means me', () => {
  it("compares the row's assignee with the signed-in user", () => {
    expect(code).toContain("r.assigned_to === me");
  });

  it("no longer matches every case that has an owner", () => {
    expect(code).not.toMatch(/predicate:\s*r\s*=>\s*r\.assigned_to\s*!==\s*""/);
  });

  it("matches nothing when nobody is signed in", () => {
    // Not everything: with no session, no case is mine.
    expect(code).toContain("Boolean(me) && r.assigned_to === me");
  });

  it("counts the chip with the predicate the list uses", () => {
    expect(code).toContain("allRows.filter(r => f.predicate(r, me.username))");
    expect(code).toContain("allRows.filter(r => def.predicate(r, me.username))");
  });

  it("recomputes when the signed-in user arrives", () => {
    // /me/ resolves after mount, so a memo keyed only on the rows
    // would keep the count it computed while me.username was "".
    expect(code).toMatch(/\[allRows, quickFilter, me\.username\]/);
  });

  it("stops a chip claiming to be about me when it is not", () => {
    // "Escalated — needs me" never checked who "me" was.
    expect(code).not.toContain("Escalated — needs me");
  });
});

describe("the timeline is the event log", () => {
  it("is built from the audit rows, not from the grievance", () => {
    expect(code).toContain("const _grmTimelineFor = (auditRows)");
    expect(code).toContain("const timeline = _grmTimelineFor(auditRaw);");
  });

  it("takes each event's own timestamp", () => {
    expect(code).toContain("at: _grmFmtTime(e.occurred_at)");
  });

  it("no longer stamps an assignment with the time the case opened", () => {
    expect(code).not.toMatch(/label:\s*`Assigned to \$\{g\.assigned_to\}`/);
  });

  it("no longer prints a dash where a timestamp belongs", () => {
    expect(code).not.toMatch(/at:\s*"—"/);
  });

  it("leaves reads out of the case history", () => {
    // Who glanced at the case is access, and belongs in the audit
    // drawer, which shows the chain unfiltered.
    expect(code).toContain('e.action !== "read" && e.action !== "list_read"');
  });

  it("says which empty it is", () => {
    expect(code).toContain("Loading the case history…");
    expect(code).toContain("No recorded events for this case yet.");
  });
});
