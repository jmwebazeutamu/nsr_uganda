/* BUG-S27-029 — PreviewStep header used to render hardcoded
 * "47,233 matched" + "a4e9d2f1…b7c3" no matter what the operator
 * built. The replacement helpers must:
 *
 *   _drsQueryHash         — deterministic 8-hex digest of fields +
 *                           criteria tree (FNV-1a). Same input →
 *                           same output, no matter the field order.
 *   _drsEstimateMatched   — heuristic that returns the full
 *                           registry size with no rules and shrinks
 *                           toward the floor (120) as rules pile up.
 */

import { beforeAll, describe, expect, it } from "vitest";

let _drsQueryHash;
let _drsEstimateMatched;
let _DRS_REGISTRY_TOTAL;
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
    _drsEstimateMatched,
    _DRS_REGISTRY_TOTAL,
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


describe("_drsEstimateMatched", () => {
  it("returns the full registry size when there are no rules", () => {
    // `qbNewGroup("AND", catalogue)` always seeds with a default
    // rule; the no-rules case is the literal hand-built empty group.
    expect(_drsEstimateMatched(null)).toBe(_DRS_REGISTRY_TOTAL);
    const empty = { id: "g", kind: "group", combinator: "AND", rules: [] };
    expect(_drsEstimateMatched(empty)).toBe(_DRS_REGISTRY_TOTAL);
  });

  it("shrinks the estimate as rule count grows", () => {
    const oneRule = {
      id: "g", kind: "group", combinator: "AND", rules: [
        { id: "r", kind: "rule", field: "household.sub_region_code", op: "any", value: ["KARAMOJA"] },
      ],
    };
    const twoRules = {
      ...oneRule,
      rules: [
        ...oneRule.rules,
        { id: "r2", kind: "rule", field: "household.programme_codes", op: "any", value: ["PDM"] },
      ],
    };
    const e1 = _drsEstimateMatched(oneRule);
    const e2 = _drsEstimateMatched(twoRules);
    expect(e1).toBeLessThan(_DRS_REGISTRY_TOTAL);
    expect(e2).toBeLessThan(e1);
  });

  it("never drops below the 120-row floor", () => {
    // Twenty rules — the heuristic caps at 8 anyway, so this also
    // exercises the cap. Should still floor at 120.
    const manyRules = {
      id: "g", kind: "group", combinator: "AND",
      rules: Array.from({ length: 20 }, (_, i) => ({
        id: `r${i}`, kind: "rule", field: "household.sub_region_code",
        op: "any", value: [`SR-${i}`],
      })),
    };
    expect(_drsEstimateMatched(manyRules)).toBeGreaterThanOrEqual(120);
  });
});
