import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-pmt-dashboard.jsx"),
  "utf8",
);

describe("PMT dashboard snapshot freshness", () => {
  it("renders only the server-provided snapshot freshness contract", () => {
    expect(source).toContain('takenAt: c.taken_at || ""');
    expect(source).toContain("isStale: !!c.is_stale");
    expect(source).toContain("staleAfterHours: c.stale_after_hours ?? null");
    expect(source).toContain('data-testid="pmt-snapshot-freshness"');
    expect(source).toContain("Snapshot last refreshed");
    expect(source).toContain("Snapshot stale");
  });

  it("does not invent a client-side refresh threshold", () => {
    expect(source).not.toMatch(/staleAfterHours:\s*\d+/);
  });
});
