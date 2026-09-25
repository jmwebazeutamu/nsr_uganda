import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-upd.jsx"), "utf8",
);

describe("UPD reviewer action contract", () => {
  it("uses the API-provided allowed-actions policy for review buttons", () => {
    expect(source).toContain("current._raw.allowed_actions");
    expect(source).toContain('actionState("approve").allowed');
    expect(source).toContain('actionState("reject").allowed');
    expect(source).toContain('actionState("hold").allowed');
    expect(source).toContain('actionState("release").allowed');
  });

  it("shows the persisted reviewer or configured role, never the viewing user", () => {
    expect(source).toContain("current._raw.approver || current._raw.required_role");
    expect(source).not.toContain("reviewer: me?.username");
  });

  it("does not offer an unwired unchanged-fields control", () => {
    expect(source).not.toContain("Show unchanged fields");
    expect(source).not.toContain("const [showAll, setShowAll]");
    expect(source).toContain('"fields"} changed');
  });

  it("uses a responsive request-context layout rather than five narrow columns", () => {
    expect(source).toContain("flexWrap:'wrap'");
    expect(source).toContain("EVIDENCE PROVIDED");
    expect(source).toContain("ASSIGNMENT");
    expect(source).not.toContain("gridTemplateColumns:'1.4fr 1fr 1fr 1fr 1fr'");
  });

  it("keeps long evidence within its own request-context column", () => {
    expect(source).toContain("maxWidth:'100%'");
    expect(source).toContain("whiteSpace:'normal'");
    expect(source).toContain("overflowWrap:'anywhere'");
  });
});
