import { beforeAll, describe, expect, it } from "vitest";

let buildHouseholdListUrl;
let headSexOptions;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.window = globalThis;
  await import("./screens-registry.jsx");
  buildHouseholdListUrl = globalThis._buildHouseholdListUrl;
  headSexOptions = globalThis._registryHeadSexOptions;
});

describe("Registry household filter contracts", () => {
  it("sends the exact canonical Registry ID filter", () => {
    expect(buildHouseholdListUrl({ registry_id: "01CANONICALREGISTRYID" }, 1, 12))
      .toContain("registry_id=01CANONICALREGISTRYID");
  });

  it("renders head-sex options supplied by Reference Data", () => {
    const options = [{ code: "canonical-sex-code", label: "Registry-defined label" }];
    expect(headSexOptions({ allLists: { sex: options } })).toEqual(options);
  });
});
