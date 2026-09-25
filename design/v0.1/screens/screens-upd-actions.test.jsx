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
});
