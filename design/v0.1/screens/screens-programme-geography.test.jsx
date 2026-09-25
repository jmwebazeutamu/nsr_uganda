/* The programme geography tab reads GeographicUnit.
 *
 * It used to hold fourteen sub-region names typed into the file. The
 * registry holds eighteen, so five could never be shown as in scope;
 * one of the fourteen, "Sebei", is not a sub-region the registry has;
 * and the names were spelled for display ("West Nile") where the
 * registry stores "West_Nile", so even the overlap would not have
 * matched on equality.
 *
 * `p.geo` was never populated either — it defaulted to [] and nothing
 * assigned it — so the tab rendered every name as out-of-scope over a
 * denominator of 14 with no source.
 *
 * docs/ssot_register.md: "Geographic hierarchy and effective units come
 * from GeographicUnit.Level ... Never map geographic names or duplicate
 * the ladder", and "Persist and exchange canonical codes/identifiers,
 * not labels or list order."
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-programme-detail.jsx"),
  "utf8",
);
const code = source
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").map(l => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n");

describe("the sub-region list", () => {
  it("is fetched from the reference-data registry", () => {
    expect(code).toContain(
      "/api/v1/reference-data/geographic-units/?level=sub_region",
    );
  });

  it("no longer holds a list of names", () => {
    expect(code).not.toContain("allSubregions");
    for (const name of ["Karamoja", "Busoga", "Sebei", "Buganda South"]) {
      expect(code).not.toContain(`"${name}"`);
    }
  });

  it("shows only active units", () => {
    expect(code).toMatch(/status \|\| "active"\) === "active"/);
  });

  it("says nothing rather than guessing when the registry is unreachable", () => {
    // A geography picker that falls back to a plausible list is how
    // fourteen invented names came to be rendered as fact.
    expect(code).toContain('geoState === "offline"');
    expect(code).toContain("not shown rather than guessed at");
  });
});

describe("scope is matched on code, never on name", () => {
  it("builds the in-scope set from codes", () => {
    expect(code).toContain("inScopeCodes");
    expect(code).toMatch(/\(u && u\.code\) \|\| u/);
  });

  it("reads the canonical M2M, not a parallel list", () => {
    expect(code).toContain("p.geographic_units");
    expect(code).not.toMatch(/\bp\.geo\b/);
  });

  it("compares by code when rendering each row", () => {
    expect(code).toContain("inScopeCodes.has(code)");
  });
});

describe("the denominator comes from the registry", () => {
  it("counts the units it fetched", () => {
    expect(code).toContain("const total = subRegions.length;");
  });

  it("no longer claims a fixed fourteen", () => {
    expect(code).not.toContain("of 14");
  });
});
