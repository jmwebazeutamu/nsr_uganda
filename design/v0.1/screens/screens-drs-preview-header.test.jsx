/* BUG-S27-029 — PreviewStep header used to render hardcoded
 * "47,233 matched" + "a4e9d2f1…b7c3" no matter what the operator
 * built. The replacement helpers must:
 *
 *   _drsQueryHash         — deterministic 8-hex digest of fields +
 *                           criteria tree (FNV-1a). Same input →
 *                           same output, no matter the field order.
 * Estimates are server-derived; no client-side estimate helper exists.
 */

import { beforeAll, describe, expect, it } from "vitest";

let _drsQueryHash;
let qbNewGroup, qbNewRule;

beforeAll(async () => {
  // screens-drs evaluates against several global UI primitives; stub
  // them so the module body doesn't blow up under jsdom.
  globalThis.PageHeader = () => null;
  globalThis.Field      = () => null;
  globalThis.ReasonModal = () => null;
  globalThis.Toast      = () => null;
  globalThis.Modal      = () => null;
  globalThis.Icon       = () => null;
  globalThis.Chip       = () => null;
  globalThis.Sparkline  = () => null;
  globalThis.PartnerMark = () => null;
  globalThis.useChoiceList = () => ({ choices: [], loading: false });
  globalThis.window = globalThis;

  await import("./screens-drs-fieldselector.jsx");
  await import("./screens-drs-querybuilder.jsx");
  await import("./screens-drs.jsx");

  ({
    _drsQueryHash,
    qbNewGroup,
    qbNewRule,
  } = globalThis);
});


describe("_drsQueryHash", () => {
  it("returns the same digest for identical inputs", () => {
    const tree = { id: "g1", kind: "group", combinator: "AND", rules: [
      { id: "r1", kind: "rule", field: "household.sub_region_code", op: "any", value: ["KARAMOJA"] },
    ]};
    const a = _drsQueryHash(tree, ["household.id", "household.sub_region_code"]);
    const b = _drsQueryHash(tree, ["household.id", "household.sub_region_code"]);
    expect(a).toBe(b);
    expect(a).toMatch(/^[0-9a-f]{8}$/);
  });

  it("is independent of field order — sort canonicalises input", () => {
    const tree = { id: "g1", kind: "group", combinator: "AND", rules: [] };
    const a = _drsQueryHash(tree, ["household.id", "household.sub_region_code"]);
    const b = _drsQueryHash(tree, ["household.sub_region_code", "household.id"]);
    expect(a).toBe(b);
  });

  it("differs when the tree differs", () => {
    const t1 = { id: "g1", kind: "group", combinator: "AND", rules: [
      { id: "r", kind: "rule", field: "household.sub_region_code", op: "any", value: ["KARAMOJA"] },
    ]};
    const t2 = { id: "g1", kind: "group", combinator: "AND", rules: [
      { id: "r", kind: "rule", field: "household.sub_region_code", op: "any", value: ["BUSOGA"] },
    ]};
    expect(_drsQueryHash(t1, [])).not.toBe(_drsQueryHash(t2, []));
  });

  it("differs when the selected fields differ", () => {
    const tree = null;
    expect(_drsQueryHash(tree, ["a"])).not.toBe(_drsQueryHash(tree, ["b"]));
  });

  it("handles null tree without throwing", () => {
    expect(() => _drsQueryHash(null, [])).not.toThrow();
    expect(_drsQueryHash(null, [])).toMatch(/^[0-9a-f]{8}$/);
  });
});
