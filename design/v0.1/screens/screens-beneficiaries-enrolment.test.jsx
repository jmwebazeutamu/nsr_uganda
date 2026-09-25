/* Direct household enrolment regression contract.
 *
 * The browser screen must remain a projection of the server policy: it may
 * filter the already-approved candidate list for usability, but it must not
 * fabricate candidates or create one request per household.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-beneficiaries.jsx"),
  "utf8",
);

describe("Beneficiaries direct household enrolment", () => {
  it("opens a server-backed eligible-household selection flow", () => {
    expect(source).toContain("DirectEnrolmentPanel");
    expect(source).toContain("/api/v1/ref/enrolments/eligible-households/");
    expect(source).toContain("Filter eligible households by ID, head or location");
  });

  it("submits one selected batch and consumes its server summary", () => {
    expect(source).toContain("/api/v1/ref/enrolments/enrol-direct/");
    expect(source).toContain("household_ids:selected");
    expect(source).toContain("body.summary?.created_count");
  });

  it("makes an atomic failure explicit and shows server rejection reasons", () => {
    expect(source).toContain("body.rejections");
    expect(source).toContain("No eligible households match.");
  });

  it("does not retain the beneficiary exited-chart fixture", () => {
    expect(source).not.toContain("rows={DEMO_BENEFICIARIES.filter");
  });
});
