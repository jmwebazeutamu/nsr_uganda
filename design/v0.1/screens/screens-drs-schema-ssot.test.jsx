import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (name) => fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens", name), "utf8",
);

const builder = read("screens-drs-querybuilder.jsx");
const wizard = read("screens-drs.jsx");

describe("DRS builder schema SSOT", () => {
  it("does not embed field, geography, programme, PMT, or demographic fallback choices", () => {
    expect(builder).toContain("const QB_FIELDS = [];");
    expect(builder).toContain("const QB_RECIPES = [];");
    for (const staleValue of ["SR-KARAMOJA", "OPM-PDM", "Poorest 20%", 'value:"F"']) {
      expect(builder).not.toContain(staleValue);
    }
  });

  it("surfaces schema failure instead of silently substituting browser fixtures", () => {
    expect(wizard).toContain("const [schemaError, setSchemaError]");
    expect(wizard).toContain("no local field or choice fallback is used");
    expect(wizard).not.toContain("hardcoded FIELDS mock");
  });
});
