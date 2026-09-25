import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-dih.jsx"), "utf8",
);

describe("DIH geography display", () => {
  it("uses the server-projected labels and does not render the parish code", () => {
    expect(source).toContain('const parishLabel = _placeLine(geo);');
    expect(source).toContain("labels.parish");
    expect(source).not.toContain("geo.parish ||");
    expect(source).not.toContain("${labels.parish} (${geo.parish})");
    expect(source).not.toContain("const REGION_CODES =");
    expect(source).toContain("regionName = geoLabels.region || \"Unmapped region\"");
    expect(source.indexOf("labels.district")).toBeLessThan(source.indexOf("labels.county"));
    expect(source.indexOf("labels.county")).toBeLessThan(source.indexOf("labels.sub_county"));
    expect(source.indexOf("labels.sub_county")).toBeLessThan(source.indexOf("labels.parish"));
    expect(source.indexOf("labels.parish")).toBeLessThan(source.indexOf("labels.village"));
  });
});
