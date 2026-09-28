import { beforeAll, describe, expect, it } from "vitest";
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

let _pmtProjectFindings;

beforeAll(async () => {
  // Source-text assertions above are enough for a contract of literals;
  // the projection below has behaviour, so it is executed rather than
  // grepped for.
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = () => null;
  globalThis.KPI = () => null;
  globalThis.PageHeader = () => null;
  globalThis.useChoiceList = () => [[], { allLists: {}, loading: false, error: null }];
  globalThis.useApi = () => [null, {}];
  globalThis.useWideView = () => ({ isWide: false });
  await import("./screens-pmt-dashboard.jsx");
  ({ _pmtProjectFindings } = globalThis);
});

/* The variable-findings panel's projection.
 *
 * A variable that never fires has influence exactly 0, so it can never
 * appear in variables_top — which is ordered by influence. The findings
 * list is a separate server payload for exactly that reason, and the
 * screen must read it as given rather than deriving anything.
 */
describe("_pmtProjectFindings", () => {
  it("carries the server's finding code and tone unchanged", () => {
    const [row] = _pmtProjectFindings([{
      variable: "floor_material__tiles_terrazzo",
      finding: "never_fires",
      finding_tone: "danger",
      weight: 0.326,
      fire_rate: 0,
      sample_size: 361,
      nonzero_count: 0,
    }]);
    expect(row.finding).toBe("never_fires");
    expect(row.tone).toBe("danger");
    expect(row.nonzeroCount).toBe(0);
    expect(row.sampleSize).toBe(361);
  });

  it("does not invent a tone when the server omits one", () => {
    // Neutral is the server's own default for an unmapped code; the
    // screen must not pick a colour of its own.
    const [row] = _pmtProjectFindings([{ variable: "x", finding: "never_fires" }]);
    expect(row.tone).toBe("neutral");
  });

  it("is empty when the server reports nothing", () => {
    expect(_pmtProjectFindings(undefined)).toEqual([]);
    expect(_pmtProjectFindings([])).toEqual([]);
  });
});
