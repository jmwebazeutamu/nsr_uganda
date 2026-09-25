/* The case number, on screen.
 *
 * `01M3AT4JSSXFYG02CXC8S6K20X` is a fine primary key and an impossible
 * thing to read back to a citizen over the phone. Every surface that
 * showed it now leads with GRM-7K4P-2QX9 instead — the list, the case
 * panel, the confirmation dialogs, the bulk-failure list, the toasts
 * and the CSV.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const grm = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-grm.jsx"), "utf8",
)
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").map(l => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n");

describe("the console shows the case number", () => {
  it("carries it through the view mapper", () => {
    expect(grm).toContain("reference: g.reference || g.id");
  });

  it("leads each queue row with it", () => {
    expect(grm).toMatch(/\{r\.reference\}/);
  });

  it("makes it the headline of the case panel", () => {
    expect(grm).toMatch(/\{current\.reference\}/);
  });

  it("keeps the ULID visible underneath", () => {
    // It is still the record's identity and still what every URL and
    // audit row carries; hiding it would make those unmatchable.
    expect(grm).toMatch(/\{current\.id\}/);
  });

  it("names cases by number in a confirmation dialog", () => {
    expect(grm).toContain("recordLabels={targetRefs(targetIds)}");
    expect(grm).toContain("const targetRefs = (ids) =>");
  });

  it("names them in the bulk-failure list", () => {
    expect(grm).toContain("targetRefs([f.id])[0]");
  });

  it("puts the number in the toast, not eight characters of ULID", () => {
    expect(grm).toContain("${g.reference || g.id} opened.");
    expect(grm).not.toContain("g.id.slice(0, 8)");
  });

  it("leads the CSV export with it", () => {
    expect(grm).toContain('["reference", "id", "category"');
  });
});

describe("an operator can look a case up by its number", () => {
  it("has somewhere to type it", () => {
    expect(grm).toContain("Case number — GRM-2026-0001");
  });

  it("asks the server rather than matching in the browser", () => {
    // The normalisation — O for 0, I and l for 1, optional prefix and
    // dashes — is the same code the reference was generated with. A
    // second copy in JavaScript is how the two come to disagree.
    expect(grm).toContain("const findByReference = () =>");
    expect(grm).toMatch(/grievances\/\?q=\$\{encodeURIComponent\(q\)\}/);
  });

  it("opens the case when the number matches exactly one", () => {
    expect(grm).toContain("if (list.length === 1) setCaseDrawer(true);");
  });

  it("says so when nothing matches, rather than emptying the queue", () => {
    expect(grm).toContain("No case matches");
  });

  it("can be cleared back to the full queue", () => {
    expect(grm).toContain('setCaseSearch(""); refresh();');
  });
});
