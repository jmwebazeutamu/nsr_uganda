import { beforeAll, describe, expect, it } from "vitest";

let _projectDsa;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.Chip = () => null;
  globalThis.KPI = () => null;
  globalThis.Sparkline = () => null;
  globalThis.PageHeader = () => null;
  globalThis.Modal = () => null;
  globalThis.Field = () => null;
  globalThis.Toast = () => null;
  globalThis.PartnerMark = () => null;
  globalThis.useApi = () => [null, { loading: false, error: null, refresh: () => {} }];
  globalThis.nsrApi = { get: async () => null, post: async () => null };
  globalThis.ScopeEditModal = () => null;
  globalThis.window = globalThis;
  await import("./screens-partner-detail.jsx");
  ({ _projectDsa } = globalThis);
});

describe("_projectDsa", () => {
  it("carries canonical geographic scope details into the Partner DSA summary", () => {
    const dsa = _projectDsa({
      id: "01DSA", reference: "DSA-OPM-1", version: 1,
      geographic_scope: ["13530"],
      geographic_scope_details: [
        { id: "13530", code: "R-WESTERN", name: "Western", level: "region" },
      ],
    });
    expect(dsa.geo).toEqual(["Western · region"]);
  });

  it("does not invent a geographic scope when no canonical units are pinned", () => {
    expect(_projectDsa({}).geo).toEqual([]);
  });
});
