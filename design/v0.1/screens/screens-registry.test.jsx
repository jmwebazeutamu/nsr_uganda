import { beforeAll, describe, expect, it } from "vitest";

let _buildHouseholdListUrl;
let _buildHouseholdAggregatesUrl;
let _registryPmtBandLabel;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.window = globalThis;
  await import("./screens-registry.jsx");
  ({ _buildHouseholdListUrl, _buildHouseholdAggregatesUrl, _registryPmtBandLabel } = globalThis);
});

describe("Registry household filters", () => {
  const filters = {
    head_sex: "canonical-sex-code",
    registered_from: "2026-01-01",
    registered_to: "2026-01-31",
  };

  it("sends canonical registration and head-sex filters to the list", () => {
    const url = _buildHouseholdListUrl(filters, 1, 12);
    expect(url).toContain("head_sex=canonical-sex-code");
    expect(url).toContain("registered_from=2026-01-01");
    expect(url).toContain("registered_to=2026-01-31");
  });

  it("sends the same filter contract to KPI aggregates", () => {
    const url = _buildHouseholdAggregatesUrl(filters);
    expect(url).toContain("head_sex=canonical-sex-code");
    expect(url).toContain("registered_from=2026-01-01");
    expect(url).toContain("registered_to=2026-01-31");
  });

  it("uses pmt_band rather than a legacy generic band query", () => {
    const url = _buildHouseholdListUrl({ pmt_band: "active-model-band" }, 1, 12);
    expect(url).toContain("pmt_band=active-model-band");
    expect(_registryPmtBandLabel("active_model_band")).toBe("Active Model Band");
  });
});
