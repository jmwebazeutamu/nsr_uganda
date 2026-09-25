import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const screen = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-programmes.jsx"), "utf8",
);

describe("Programmes enrolment count projection", () => {
  it("uses the API's canonical enrolment count rather than a planning estimate", () => {
    expect(screen).toContain("enrolled: pr.enrolment_count || 0");
    expect(screen).not.toContain("enrolled: pr.beneficiary_estimate || 0");
  });

  it("drives the KPI from the server aggregate and removes the deferred copy", () => {
    expect(screen).toContain("const enrolmentCount = aggResp?.enrolment_count ?? 0;");
    expect(screen).toContain("value={enrolmentCount.toLocaleString()}");
    expect(screen).not.toContain("lands when ProgrammeEnrolment aggregation ships");
  });
});
