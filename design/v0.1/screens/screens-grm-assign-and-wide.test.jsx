/* QA P2.10 and P3.12 — two things the GRM workbench got wrong about
 * where something belongs.
 *
 * The assignee picker searched the whole user directory. Every
 * account, active or not, whatever their role or their area. An L3
 * District case could be handed to an enumerator in another
 * sub-region: someone with neither the authority to decide it nor the
 * scope to open it. They would get the email, follow the link, and be
 * refused their own work.
 *
 * And in wide view the split grid collapses to one column so the list
 * gets the full width. The case panel, still the second grid child,
 * went underneath it — several screens down on a full queue. It was
 * reported as missing, and for any practical purpose it was.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (p) => fs.readFileSync(path.join(process.cwd(), p), "utf8");
const grm = read("design/v0.1/screens/screens-grm.jsx");
const picker = read("design/v0.1/components/search-picker.jsx");

describe("the assignee picker asks the case, not the directory", () => {
  it("points at the grievance's own candidate list", () => {
    expect(grm).toMatch(/grievances\/\$\{[^}]+\}\/assignable\//);
  });

  it("uses it for tasks as well as for the case", () => {
    // A task is work at the case's tier, so it takes the case's rule.
    const hits = grm.match(/assignable\//g) || [];
    expect(hits.length).toBeGreaterThanOrEqual(2);
  });

  it("says why the list is short rather than showing an empty box", () => {
    expect(grm).toContain("Nobody holds this tier's role");
  });

  it("does not claim an eligible list for a mixed bulk selection", () => {
    // Cases at different tiers or about different households have no
    // single answer; the server checks each one and reports refusals.
    expect(grm).toContain("oneKindOfTarget");
    expect(grm).toContain("different tiers or about different");
  });

  it("leaves the admin directory search alone", () => {
    // Granting a scope IS choosing someone who does not have one, so
    // that surface must keep searching everybody.
    expect(picker).toContain('endpoint = USER_SEARCH_API');
  });

  it("reads both list shapes rather than forking the component", () => {
    expect(picker).toContain("u.roles || u.groups");
    expect(picker).toContain("value?.username === u.username");
  });
});

describe("wide view keeps the case panel reachable", () => {
  it("renders the panel once, from one definition", () => {
    expect(grm).toContain("const casePanel = current ? (");
    expect((grm.match(/\{!wide\.isWide && casePanel\}/g) || [])).toHaveLength(1);
  });

  it("puts it in a drawer when the list is full width", () => {
    expect(grm).toMatch(/wide\.isWide && \(/);
    expect(grm).toContain('className={`drawer ${caseDrawer && current');
  });

  it("opens it when a row is picked", () => {
    expect(grm).toContain("setSelectedRow(r.id); setCaseDrawer(true);");
  });

  it("offers a way back once it has been closed", () => {
    expect(grm).toContain("Open case");
  });

  it("does not strand the drawer when wide view is turned off", () => {
    expect(grm).toContain("if (!wide.isWide) setCaseDrawer(false);");
  });
});
