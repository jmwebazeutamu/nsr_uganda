import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (name) => fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens", name), "utf8",
);

const registration = read("screens-programme-new.jsx");
const detail = read("screens-programme-detail.jsx");
const configuration = read("screens-pmt-configuration.jsx");

describe("PMT policy SSOT", () => {
  it("does not ship calibration variables, weights, or transforms as UI fallback data", () => {
    expect(configuration).not.toContain("PCFG_VARIABLES_V1");
    expect(configuration).not.toContain("PCFG_TRANSFORMS");
    expect(configuration).toContain("Array.isArray(selected?.variables)");
  });

  it("does not estimate programme reach from browser-side PMT or composition factors", () => {
    for (const source of [registration, detail]) {
      expect(source).not.toMatch(/PMT_BAND_(META|ALIASES|LABEL|NOTE)|_PMT_FRACTION|COMP_FACTOR|_COMP_FRACTION/);
      expect(source).not.toContain("12100000");
    }
    expect(registration).toContain("No browser-side eligibility estimate is shown.");
    expect(detail).toContain("/api/v1/ref/enrolments/eligible-households/");
  });

  it("retains ChoiceOption codes unchanged until the server resolves their canonical bindings", () => {
    expect(registration).toContain("pmt_bands:         data.pmt_bands,");
    expect(detail).toContain("pmt_bands: _csvToList(pmtBandsCsv),");
  });
});
