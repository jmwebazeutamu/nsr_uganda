/* BUG-S27-019 — Step 4 (Preview) must reflect the ordered field
 * selection from Step 3, not a hardcoded 10-column household layout.
 *
 * Asserts:
 *   1. _previewCell respects sensitivity (Sensitive → masked,
 *      Personal phone → last-4 only, Sensitive nin_last4 → last-4).
 *   2. _previewCell respects type (bool / date / number / enum).
 *   3. PreviewStep renders columns in the selected order with the
 *      catalogue's labels, including dotted-key sub-headers.
 *   4. PreviewStep shows an empty state when nothing is selected.
 *   5. PreviewStep flags unknown fields (selected key not in
 *      catalogue) instead of silently dropping them.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

let PreviewStep;
let _previewCell;
let _buildPinMap;
// Pulled from screens-drs-fieldselector via dynamic import so the
// shared screens-drs module body can also evaluate without throwing
// on missing primitives.
beforeAll(async () => {
  // The shared components.jsx isn't a module — wire the few
  // primitives the file body / PreviewStep render touches as
  // globals before evaluating the module.
  globalThis.PageHeader = ({ eyebrow, title, sub, right }) =>
    React.createElement("header",
      { "data-eyebrow": eyebrow },
      title, sub, right);
  globalThis.Field = ({ label, hint, children }) =>
    React.createElement("label", { "data-field-label": label, "data-field-hint": hint }, children);
  globalThis.ReasonModal = () => null;
  globalThis.Toast = () => null;

  await import("./screens-drs-fieldselector.jsx");
  await import("./screens-drs-querybuilder.jsx");
  await import("./screens-drs.jsx");
  ({ PreviewStep, _previewCell, _buildPinMap } = globalThis);
});

afterEach(() => {
  cleanup();
});

const F = (over) => ({
  group: "Identifiers", key: "household.id", label: "Registry ID",
  sensitivity: "Public", type: "text", ...over,
});

// ───────────────────────────────────────────────────────────────
// _previewCell — sensitivity gates
// ───────────────────────────────────────────────────────────────

describe("_previewCell sensitivity", () => {
  it("masks Sensitive columns by default", () => {
    expect(_previewCell("household.gps_lat", F({ key: "household.gps_lat", sensitivity: "Sensitive", type: "number" }), 0))
      .toBe("[masked]");
    expect(_previewCell("member.nin_hash", F({ key: "member.nin_hash", sensitivity: "Sensitive", type: "text" }), 3))
      .toBe("[masked]");
  });

  it("reveals last-4 for Sensitive *_last4 columns", () => {
    const v = _previewCell("member.nin_last4",
      F({ key: "member.nin_last4", sensitivity: "Sensitive", type: "text" }), 0);
    expect(v).toMatch(/^[0-9A-F]{4}$/);
  });

  it("masks Personal phone numbers to last-4", () => {
    const v = _previewCell("member.telephone_1",
      F({ key: "member.telephone_1", sensitivity: "Personal", type: "text" }), 0);
    expect(v).toMatch(/^\+256 ••• ••\d{4}$/);
  });
});

// ───────────────────────────────────────────────────────────────
// _previewCell — type dispatch
// ───────────────────────────────────────────────────────────────

describe("_previewCell type dispatch", () => {
  it("bool → Yes / No", () => {
    const f = F({ key: "household.is_deleted", type: "bool" });
    expect(["Yes", "No"]).toContain(_previewCell("household.is_deleted", f, 0));
    expect(["Yes", "No"]).toContain(_previewCell("household.is_deleted", f, 4));
  });

  it("date → YYYY-MM-DD", () => {
    const v = _previewCell("household.created_at",
      F({ key: "household.created_at", type: "date" }), 0);
    expect(v).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("enum with options → human label, not raw value", () => {
    const f = F({ key: "household.urban_rural", type: "enum",
      options: [{ value: "1", label: "Urban" }, { value: "2", label: "Rural" }] });
    expect(["Urban", "Rural"]).toContain(_previewCell("household.urban_rural", f, 0));
    expect(["Urban", "Rural"]).toContain(_previewCell("household.urban_rural", f, 1));
  });

  it("number for *_pmt_score → 0-1 float", () => {
    const v = _previewCell("household.current_pmt_score",
      F({ key: "household.current_pmt_score", type: "number" }), 0);
    expect(parseFloat(v)).toBeGreaterThan(0);
    expect(parseFloat(v)).toBeLessThan(1);
  });

  it("text household.id → ULID-shaped value", () => {
    const v = _previewCell("household.id", F({ key: "household.id" }), 0);
    expect(v).toMatch(/^01[A-Z0-9]{24}$/);
  });
});

// ───────────────────────────────────────────────────────────────
// PreviewStep — column ordering + empty state
// ───────────────────────────────────────────────────────────────

describe("PreviewStep", () => {
  const catalogue = {
    "household.id":               F({ key: "household.id", label: "Registry ID" }),
    "household.household_number": F({ key: "household.household_number", label: "Household number" }),
    "household.gps_lat":          F({ key: "household.gps_lat", label: "GPS latitude", sensitivity: "Sensitive", type: "number" }),
    "member.telephone_1":         F({ key: "member.telephone_1", label: "Telephone 1", sensitivity: "Personal" }),
  };

  it("renders empty state when nothing is selected", () => {
    render(<PreviewStep selected={[]} catalogueByKey={catalogue}/>);
    expect(screen.getByText(/Nothing to preview yet/)).toBeInTheDocument();
  });

  it("renders columns in selection order with catalogue labels", () => {
    render(<PreviewStep
      selected={["household.household_number", "household.id", "member.telephone_1"]}
      catalogueByKey={catalogue}/>);
    const headers = screen.getAllByRole("columnheader").map(h => h.textContent);
    // Each header contains BOTH the label and the dotted key.
    expect(headers[0]).toContain("Household number");
    expect(headers[0]).toContain("household.household_number");
    expect(headers[1]).toContain("Registry ID");
    expect(headers[2]).toContain("Telephone 1");
  });

  it("masks Sensitive columns and reveals last-4 for Personal phones", () => {
    render(<PreviewStep
      selected={["household.gps_lat", "member.telephone_1"]}
      catalogueByKey={catalogue}/>);
    expect(screen.getAllByText("[masked]").length).toBeGreaterThan(0);
    // At least one phone cell renders as the masked-last-4 pattern.
    const phoneCells = screen.getAllByText((_, node) =>
      node.tagName === "TD" && /\+256 ••• ••\d{4}/.test(node.textContent));
    expect(phoneCells.length).toBeGreaterThan(0);
  });

  it("warns when a selected key is not in the catalogue", () => {
    render(<PreviewStep
      selected={["household.id", "household.removed_field", "member.future_field"]}
      catalogueByKey={catalogue}/>);
    expect(screen.getByText(/not in current catalogue/)).toBeInTheDocument();
    expect(screen.getByText("household.removed_field")).toBeInTheDocument();
  });
});

// ───────────────────────────────────────────────────────────────
// BUG-S27-021 — WHERE-clause pinning
// ───────────────────────────────────────────────────────────────

describe("_buildPinMap", () => {
  const rule = (over) => ({ id: "r", kind: "rule", field: "x", op: "eq", value: "v", ...over });
  const group = (rules) => ({ id: "g", kind: "group", combinator: "AND", rules });

  it("pins eq + on to single values", () => {
    const tree = group([
      rule({ field: "h.region_code", op: "eq", value: "R-CENTRAL" }),
      rule({ field: "h.captured_date", op: "on", value: "2026-03-14" }),
    ]);
    expect(_buildPinMap(tree)).toEqual({
      "h.region_code":   { kind: "single", value: "R-CENTRAL" },
      "h.captured_date": { kind: "single", value: "2026-03-14" },
    });
  });

  it("pins true / false to boolean literals", () => {
    const tree = group([
      rule({ field: "h.has_disability", op: "true",  value: null }),
      rule({ field: "h.is_deleted",     op: "false", value: null }),
    ]);
    expect(_buildPinMap(tree)).toEqual({
      "h.has_disability": { kind: "single", value: true },
      "h.is_deleted":     { kind: "single", value: false },
    });
  });

  it("pins in / any / all to multi", () => {
    const tree = group([
      rule({ field: "h.sub_region_code", op: "in",  value: ["SR-KARAMOJA", "SR-ACHOLI"] }),
      rule({ field: "h.programme_codes", op: "any", value: ["OPM-PDM"] }),
    ]);
    expect(_buildPinMap(tree)).toEqual({
      "h.sub_region_code": { kind: "multi", values: ["SR-KARAMOJA", "SR-ACHOLI"] },
      "h.programme_codes": { kind: "multi", values: ["OPM-PDM"] },
    });
  });

  it("pins between to range", () => {
    const tree = group([rule({ field: "h.pmt_score", op: "between", value: ["0.2", "0.4"] })]);
    expect(_buildPinMap(tree)).toEqual({
      "h.pmt_score": { kind: "range", min: "0.2", max: "0.4" },
    });
  });

  it("ignores operators that don't fix a value", () => {
    const tree = group([
      rule({ field: "h.size", op: "gt", value: "5" }),
      rule({ field: "h.size", op: "lt", value: "9" }),
      rule({ field: "h.label", op: "contains", value: "Karamoja" }),
      rule({ field: "h.x", op: "set", value: null }),
      rule({ field: "h.y", op: "neq", value: "z" }),
    ]);
    expect(_buildPinMap(tree)).toEqual({});
  });

  it("ignores rules with empty values", () => {
    const tree = group([
      rule({ field: "h.k", op: "eq", value: "" }),
      rule({ field: "h.l", op: "eq", value: null }),
      rule({ field: "h.m", op: "in", value: [] }),
      rule({ field: "h.n", op: "between", value: ["", "5"] }),
    ]);
    expect(_buildPinMap(tree)).toEqual({});
  });

  it("walks nested groups", () => {
    const tree = group([
      rule({ field: "h.region_code", op: "eq", value: "R-CENTRAL" }),
      group([
        rule({ field: "h.size", op: "gt", value: "5" }),  // ignored
        rule({ field: "h.pmt_band", op: "eq", value: "Poorest 40%" }),
      ]),
    ]);
    expect(_buildPinMap(tree)).toEqual({
      "h.region_code": { kind: "single", value: "R-CENTRAL" },
      "h.pmt_band":    { kind: "single", value: "Poorest 40%" },
    });
  });

  it("returns {} for null / empty tree", () => {
    expect(_buildPinMap(null)).toEqual({});
    expect(_buildPinMap(undefined)).toEqual({});
    expect(_buildPinMap(group([]))).toEqual({});
  });
});

describe("_previewCell with a pin", () => {
  const enumField = (over) => ({
    key: "h.region_code", type: "enum", sensitivity: "Public",
    options: [
      { value: "R-CENTRAL", label: "Central" },
      { value: "R-EASTERN", label: "Eastern" },
    ],
    ...over,
  });

  it("renders the enum label for a single-pinned enum, same value every row", () => {
    const f = enumField();
    const pin = { kind: "single", value: "R-CENTRAL" };
    for (let i = 0; i < 10; i++) {
      expect(_previewCell("h.region_code", f, i, pin)).toBe("Central");
    }
  });

  it("cycles through pinned multi values", () => {
    const f = enumField();
    const pin = { kind: "multi", values: ["R-CENTRAL", "R-EASTERN"] };
    expect(_previewCell("h.region_code", f, 0, pin)).toBe("Central");
    expect(_previewCell("h.region_code", f, 1, pin)).toBe("Eastern");
    expect(_previewCell("h.region_code", f, 2, pin)).toBe("Central");
  });

  it("renders raw code when the pinned value isn't in field.options", () => {
    const f = enumField();
    const pin = { kind: "single", value: "R-UNKNOWN" };
    expect(_previewCell("h.region_code", f, 0, pin)).toBe("R-UNKNOWN");
  });

  it("renders Yes/No for boolean pin", () => {
    const f = { key: "h.is_deleted", type: "bool", sensitivity: "Internal" };
    expect(_previewCell("h.is_deleted", f, 0, { kind: "single", value: true  })).toBe("Yes");
    expect(_previewCell("h.is_deleted", f, 0, { kind: "single", value: false })).toBe("No");
  });

  it("renders numbers spread across a range pin", () => {
    const f = { key: "h.size", type: "number", sensitivity: "Public" };
    const pin = { kind: "range", min: "1", max: "10" };
    const first = _previewCell("h.size", f, 0, pin);
    const last  = _previewCell("h.size", f, 9, pin);
    expect(Number(first)).toBeGreaterThanOrEqual(1);
    expect(Number(last)).toBeLessThanOrEqual(10);
    // Spread, not constant.
    expect(Number(last)).toBeGreaterThan(Number(first));
  });

  it("Sensitive masking still wins over any pin", () => {
    const f = { key: "h.gps_lat", type: "number", sensitivity: "Sensitive" };
    const pin = { kind: "single", value: "2.5283" };
    expect(_previewCell("h.gps_lat", f, 0, pin)).toBe("[masked]");
  });

  it("falls through to the generator when no pin is supplied", () => {
    const f = { key: "h.size", type: "number", sensitivity: "Public" };
    const v0 = _previewCell("h.size", f, 0);
    const v1 = _previewCell("h.size", f, 1);
    expect(v0).not.toBe("");
    expect(v0).not.toBe("[masked]");
    expect(Number.isFinite(Number(v0)) || Number.isFinite(Number(v1))).toBe(true);
  });
});

describe("PreviewStep with a tree", () => {
  const cat = {
    "household.region_code": {
      key: "household.region_code", label: "Region", type: "enum",
      sensitivity: "Public",
      options: [
        { value: "R-CENTRAL", label: "Central" },
        { value: "R-EASTERN", label: "Eastern" },
        { value: "R-NORTHERN", label: "Northern" },
      ],
    },
    "household.id": {
      key: "household.id", label: "Registry ID", type: "text", sensitivity: "Public",
    },
  };
  const tree = {
    id: "g", kind: "group", combinator: "AND",
    rules: [
      { id: "r1", kind: "rule", field: "household.region_code",
        op: "eq", value: "R-CENTRAL" },
    ],
  };

  it("every Region cell shows 'Central' when the tree pins R-CENTRAL", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.id"]}
      catalogueByKey={cat}
      tree={tree}/>);
    // Find every body cell in the Region column — there should be
    // 10 of them and every one should read "Central".
    const regionCells = screen.getAllByText("Central");
    expect(regionCells.length).toBeGreaterThanOrEqual(10);
  });

  it("flags pinned columns with a 'filtered' chip in the header", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.id"]}
      catalogueByKey={cat}
      tree={tree}/>);
    expect(screen.getByText("filtered")).toBeInTheDocument();
  });

  it("toolbar copy reports how many columns are pinned", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.id"]}
      catalogueByKey={cat}
      tree={tree}/>);
    expect(screen.getByText(/1 column pinned by your Step-2 filter/)).toBeInTheDocument();
  });

  it("unconstrained columns continue to vary across rows", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.id"]}
      catalogueByKey={cat}
      tree={tree}/>);
    // Each Registry ID cell comes from a 10-element bank — distinct.
    const idCells = screen.getAllByText((_, node) =>
      node.tagName === "TD" && /^01[A-Z0-9]{24}$/.test(node.textContent));
    const distinct = new Set(idCells.map(c => c.textContent));
    expect(distinct.size).toBeGreaterThanOrEqual(5);
  });
});
