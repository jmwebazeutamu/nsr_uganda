/* BUG-S27-033 — partner detail rail showed "Criteria renderer not
 * loaded" because _drsRenderCriteriaNode wasn't on window. While
 * fixing the export, the operator phrasing also got translated from
 * raw QB tokens ("Region IN R-CENTRAL") to natural language
 * ("Region is one of R-CENTRAL").
 *
 * Asserts:
 *   1. The renderer + both helpers are exported on globalThis after
 *      screens-drs.jsx evaluates — the partner panel reads them off
 *      window so a missing export silently bricks the criteria card.
 *   2. _drsHumanOp maps every QB op the wizard emits to a phrase
 *      (single-item arrays collapse to "is" rather than "is one of").
 *   3. _drsHumanValue collapses arrays / between / lastN cleanly.
 */

import { beforeAll, describe, expect, it } from "vitest";

let _drsRenderCriteriaNode;
let _drsHumanOp;
let _drsHumanValue;

beforeAll(async () => {
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
    _drsRenderCriteriaNode,
    _drsHumanOp,
    _drsHumanValue,
  } = globalThis);
});


describe("exports", () => {
  it("registers the renderer + both phrasers on window", () => {
    // The partner detail rail (screens-partner-drs.jsx) reads these
    // off the global surface — a missing export bricks the criteria
    // card silently. Pin all three so a future Object.assign drop
    // is caught here, not in production.
    expect(typeof _drsRenderCriteriaNode).toBe("function");
    expect(typeof _drsHumanOp).toBe("function");
    expect(typeof _drsHumanValue).toBe("function");
  });
});


describe("_drsHumanOp", () => {
  it.each([
    ["eq",         null,       "is"],
    ["ne",         null,       "is not"],
    ["gt",         null,       "is greater than"],
    ["gte",        null,       "is at least"],
    ["lt",         null,       "is less than"],
    ["lte",        null,       "is at most"],
    ["between",    null,       "is between"],
    ["contains",   null,       "contains"],
    ["startswith", null,       "starts with"],
    ["endswith",   null,       "ends with"],
    ["isnull",     null,       "is empty"],
    ["isnotnull",  null,       "is set"],
    ["true",       null,       "is yes"],
    ["false",      null,       "is no"],
    ["lastN",      null,       "in the last"],
  ])("maps %s → %s", (op, value, expected) => {
    expect(_drsHumanOp(op, value)).toBe(expected);
  });

  it("collapses single-item arrays to 'is' for in/any", () => {
    expect(_drsHumanOp("in", ["X"])).toBe("is");
    expect(_drsHumanOp("any", ["X"])).toBe("is");
  });

  it("uses 'is one of' for multi-item in arrays", () => {
    expect(_drsHumanOp("in",  ["X", "Y"])).toBe("is one of");
    expect(_drsHumanOp("any", ["X", "Y"])).toBe("is any of");
  });

  it("collapses single-item arrays to 'is not' for nin/none", () => {
    expect(_drsHumanOp("nin",  ["X"])).toBe("is not");
    expect(_drsHumanOp("none", ["X"])).toBe("is not");
  });

  it("falls back to the raw op when unknown", () => {
    expect(_drsHumanOp("matrix", null)).toBe("matrix");
    expect(_drsHumanOp("", null)).toBe("?");
  });
});


describe("_drsHumanValue", () => {
  it("returns (empty) for null / undefined / empty string", () => {
    expect(_drsHumanValue("eq", null)).toBe("(empty)");
    expect(_drsHumanValue("eq", undefined)).toBe("(empty)");
    expect(_drsHumanValue("eq", "")).toBe("(empty)");
  });

  it("collapses a single-element array to just the value", () => {
    expect(_drsHumanValue("in", ["R-CENTRAL"])).toBe("R-CENTRAL");
  });

  it("joins short arrays with commas", () => {
    expect(_drsHumanValue("in", ["A", "B", "C"])).toBe("A, B, C");
  });

  it("truncates long arrays with 'and N more'", () => {
    const eight = ["A", "B", "C", "D", "E", "F", "G", "H"];
    expect(_drsHumanValue("in", eight)).toBe("A, B, C, D, E, F and 2 more");
  });

  it("formats between as 'X and Y'", () => {
    expect(_drsHumanValue("between", [10, 20])).toBe("10 and 20");
  });

  it("formats lastN as 'n unit'", () => {
    expect(_drsHumanValue("lastN", { n: 30, unit: "days" })).toBe("30 days");
  });

  it("passes scalars through as strings", () => {
    expect(_drsHumanValue("eq", "R-CENTRAL")).toBe("R-CENTRAL");
    expect(_drsHumanValue("gt", 42)).toBe("42");
  });
});
