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
let _inferImplicitGeoPins;
let _buildGeoPathsForRows;
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
  ({
    PreviewStep, _previewCell, _buildPinMap,
    _inferImplicitGeoPins, _buildGeoPathsForRows,
  } = globalThis);
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

// ───────────────────────────────────────────────────────────────
// BUG-S27-024 — implicit pinning of geographic descendants
// ───────────────────────────────────────────────────────────────

describe("_inferImplicitGeoPins", () => {
  const regionField = {
    key: "household.region_code", type: "enum",
    options: [
      { value: "R-CENTRAL", label: "Central" },
      { value: "R-NORTHERN", label: "Northern" },
    ],
  };
  const subRegionField = {
    key: "household.sub_region_code", type: "enum",
    options: [
      { value: "SR-BUGANDA-SOUTH", label: "Buganda South", parent_code: "R-CENTRAL" },
      { value: "SR-BUGANDA-NORTH", label: "Buganda North", parent_code: "R-CENTRAL" },
      { value: "SR-ACHOLI",        label: "Acholi",         parent_code: "R-NORTHERN" },
      { value: "SR-KARAMOJA",      label: "Karamoja",       parent_code: "R-NORTHERN" },
    ],
  };
  const districtField = {
    key: "household.district_code", type: "enum",
    options: [
      { value: "DST-KAMPALA", label: "Kampala", parent_code: "SR-BUGANDA-SOUTH" },
      { value: "DST-MUKONO",  label: "Mukono",  parent_code: "SR-BUGANDA-SOUTH" },
      { value: "DST-GULU",    label: "Gulu",    parent_code: "SR-ACHOLI" },
    ],
  };
  const cat = {
    "household.region_code":     regionField,
    "household.sub_region_code": subRegionField,
    "household.district_code":   districtField,
  };

  it("infers a sub_region pin from a region single-pin", () => {
    const explicit = {
      "household.region_code": { kind: "single", value: "R-CENTRAL" },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: subRegionField },
    ];
    const out = _inferImplicitGeoPins(explicit, cols, cat);
    expect(out["household.sub_region_code"]).toEqual({
      kind: "multi",
      values: ["SR-BUGANDA-SOUTH", "SR-BUGANDA-NORTH"],
      implicit: true,
    });
    // Explicit pin untouched.
    expect(out["household.region_code"]).toEqual(explicit["household.region_code"]);
  });

  it("propagates down the chain — region → sub_region → district", () => {
    const explicit = {
      "household.region_code": { kind: "single", value: "R-CENTRAL" },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: subRegionField },
      { key: "household.district_code",   field: districtField },
    ];
    const out = _inferImplicitGeoPins(explicit, cols, cat);
    expect(out["household.district_code"]).toEqual({
      kind: "multi",
      values: ["DST-KAMPALA", "DST-MUKONO"],
      implicit: true,
    });
  });

  it("explicit child pin is NOT overwritten by the inferrer", () => {
    const explicit = {
      "household.region_code":     { kind: "single", value: "R-CENTRAL" },
      "household.sub_region_code": { kind: "single", value: "SR-BUGANDA-SOUTH" },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: subRegionField },
    ];
    const out = _inferImplicitGeoPins(explicit, cols, cat);
    expect(out["household.sub_region_code"]).toEqual(explicit["household.sub_region_code"]);
    expect(out["household.sub_region_code"].implicit).toBeUndefined();
  });

  it("multi-pinned parent unions descendants", () => {
    const explicit = {
      "household.region_code": { kind: "multi", values: ["R-CENTRAL", "R-NORTHERN"] },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: subRegionField },
    ];
    const out = _inferImplicitGeoPins(explicit, cols, cat);
    expect(out["household.sub_region_code"].values.sort()).toEqual([
      "SR-ACHOLI", "SR-BUGANDA-NORTH", "SR-BUGANDA-SOUTH", "SR-KARAMOJA",
    ]);
  });

  it("no descendant column selected → no implicit pin added", () => {
    const explicit = {
      "household.region_code": { kind: "single", value: "R-CENTRAL" },
    };
    const cols = [{ key: "household.region_code", field: regionField }];
    const out = _inferImplicitGeoPins(explicit, cols, cat);
    expect(Object.keys(out)).toEqual(["household.region_code"]);
  });

  it("parent not pinned → no implicit pin on the child", () => {
    const cols = [
      { key: "household.sub_region_code", field: subRegionField },
    ];
    const out = _inferImplicitGeoPins({}, cols, cat);
    expect(out["household.sub_region_code"]).toBeUndefined();
  });

  it("child options without parent_code → no spurious pin", () => {
    const noParentField = {
      key: "household.sub_region_code", type: "enum",
      options: [
        { value: "SR-BUGANDA-SOUTH", label: "Buganda South" },
        { value: "SR-ACHOLI",        label: "Acholi" },
      ],
    };
    const explicit = {
      "household.region_code": { kind: "single", value: "R-CENTRAL" },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: noParentField },
    ];
    const out = _inferImplicitGeoPins(explicit, cols, {
      ...cat, "household.sub_region_code": noParentField,
    });
    expect(out["household.sub_region_code"]).toBeUndefined();
  });
});

describe("PreviewStep with geographic implicit pins", () => {
  const regionField = {
    key: "household.region_code", label: "Region", type: "enum", sensitivity: "Public",
    options: [
      { value: "R-CENTRAL", label: "Central" },
      { value: "R-NORTHERN", label: "Northern" },
    ],
  };
  const subRegionField = {
    key: "household.sub_region_code", label: "Sub-region", type: "enum", sensitivity: "Public",
    options: [
      { value: "SR-BUGANDA-SOUTH", label: "Buganda South", parent_code: "R-CENTRAL" },
      { value: "SR-BUGANDA-NORTH", label: "Buganda North", parent_code: "R-CENTRAL" },
      { value: "SR-ACHOLI",        label: "Acholi",         parent_code: "R-NORTHERN" },
      { value: "SR-KARAMOJA",      label: "Karamoja",       parent_code: "R-NORTHERN" },
    ],
  };
  const cat = {
    "household.region_code":     regionField,
    "household.sub_region_code": subRegionField,
  };
  const tree = {
    id: "g", kind: "group", combinator: "AND",
    rules: [
      { id: "r1", kind: "rule", field: "household.region_code",
        op: "eq", value: "R-CENTRAL" },
    ],
  };

  it("never renders sub-regions that don't descend from the pinned region", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.sub_region_code"]}
      catalogueByKey={cat}
      tree={tree}/>);
    // Acholi + Karamoja are Northern — must not appear in any body cell.
    const cells = document.querySelectorAll("tbody td");
    const subRegions = Array.from(cells).map(c => c.textContent);
    expect(subRegions).not.toContain("Acholi");
    expect(subRegions).not.toContain("Karamoja");
  });

  it("only renders sub-regions descending from the pinned region", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.sub_region_code"]}
      catalogueByKey={cat}
      tree={tree}/>);
    // Every sub_region cell must be one of Buganda North / Buganda South.
    const cells = Array.from(document.querySelectorAll("tbody td"))
      .filter(td => td.previousElementSibling); // skip the first column
    const subRegionCells = cells.map(c => c.textContent);
    for (const v of subRegionCells) {
      expect(["Buganda South", "Buganda North"]).toContain(v);
    }
  });

  it("implicit pins surface a 'scoped' chip, not 'filtered'", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.sub_region_code"]}
      catalogueByKey={cat}
      tree={tree}/>);
    // Explicit pin on Region → "filtered". Implicit pin on Sub-region → "scoped".
    expect(screen.getByText("filtered")).toBeInTheDocument();
    expect(screen.getByText("scoped")).toBeInTheDocument();
  });

  it("toolbar copy reports pinned and scoped counts separately", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.sub_region_code"]}
      catalogueByKey={cat}
      tree={tree}/>);
    expect(screen.getByText(/1 column pinned by your Step-2 filter/)).toBeInTheDocument();
    expect(screen.getByText(/1 column scoped to the pinned region/)).toBeInTheDocument();
  });
});

// ───────────────────────────────────────────────────────────────
// BUG-S27-025 — coherent geographic path per preview row
// ───────────────────────────────────────────────────────────────

describe("_buildGeoPathsForRows", () => {
  const regionField = {
    key: "household.region_code", type: "enum",
    options: [
      { value: "R-CENTRAL",  label: "Central" },
      { value: "R-NORTHERN", label: "Northern" },
    ],
  };
  const subRegionField = {
    key: "household.sub_region_code", type: "enum",
    options: [
      { value: "SR-BUGANDA-S", label: "Buganda South", parent_code: "R-CENTRAL"  },
      { value: "SR-BUGANDA-N", label: "Buganda North", parent_code: "R-CENTRAL"  },
      { value: "SR-ACHOLI",    label: "Acholi",        parent_code: "R-NORTHERN" },
    ],
  };
  const districtField = {
    key: "household.district_code", type: "enum",
    options: [
      // Buganda South districts
      { value: "DST-KAMPALA",   label: "Kampala",   parent_code: "SR-BUGANDA-S" },
      { value: "DST-KALANGALA", label: "Kalangala", parent_code: "SR-BUGANDA-S" },
      // Buganda North districts
      { value: "DST-LUWEERO",   label: "Luweero",   parent_code: "SR-BUGANDA-N" },
      { value: "DST-NAKASEKE",  label: "Nakaseke",  parent_code: "SR-BUGANDA-N" },
      // Acholi districts
      { value: "DST-GULU",      label: "Gulu",      parent_code: "SR-ACHOLI"    },
    ],
  };
  const countyField = {
    key: "household.county_code", type: "enum",
    options: [
      // under Kampala
      { value: "C-KCCA",      label: "KCCA",       parent_code: "DST-KAMPALA"   },
      // under Kalangala
      { value: "C-BUJUMBA",   label: "Bujumba",    parent_code: "DST-KALANGALA" },
      { value: "C-KYAMUSWA",  label: "Kyamuswa",   parent_code: "DST-KALANGALA" },
      // under Luweero
      { value: "C-BAMUNANIKA",label: "Bamunanika", parent_code: "DST-LUWEERO"   },
      // under Gulu (should never appear when Central is pinned)
      { value: "C-AYAGO",     label: "Ayago",      parent_code: "DST-GULU"      },
    ],
  };
  const catalogue = {
    "household.region_code":     regionField,
    "household.sub_region_code": subRegionField,
    "household.district_code":   districtField,
    "household.county_code":     countyField,
  };

  it("each row's district descends from that row's sub_region", () => {
    const pins = {
      "household.region_code":     { kind: "single", value: "R-CENTRAL" },
      "household.sub_region_code": { kind: "multi",  values: ["SR-BUGANDA-S", "SR-BUGANDA-N"], implicit: true },
      "household.district_code":   { kind: "multi",  values: ["DST-KAMPALA", "DST-KALANGALA", "DST-LUWEERO", "DST-NAKASEKE"], implicit: true },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: subRegionField },
      { key: "household.district_code",   field: districtField },
    ];
    const paths = _buildGeoPathsForRows(pins, cols, catalogue, 10);
    expect(paths).toHaveLength(10);
    for (const path of paths) {
      const subRegion = path["household.sub_region_code"];
      const district  = path["household.district_code"];
      const dOpt = districtField.options.find(o => o.value === district);
      expect(dOpt).toBeTruthy();
      expect(dOpt.parent_code).toBe(subRegion);
    }
  });

  it("each row's county descends from that row's district (full chain)", () => {
    const pins = {
      "household.region_code":     { kind: "single", value: "R-CENTRAL" },
      "household.sub_region_code": { kind: "multi",  values: ["SR-BUGANDA-S", "SR-BUGANDA-N"], implicit: true },
      "household.district_code":   { kind: "multi",  values: ["DST-KAMPALA", "DST-KALANGALA", "DST-LUWEERO", "DST-NAKASEKE"], implicit: true },
      "household.county_code":     { kind: "multi",  values: ["C-KCCA", "C-BUJUMBA", "C-KYAMUSWA", "C-BAMUNANIKA"], implicit: true },
    };
    const cols = [
      { key: "household.region_code",     field: regionField },
      { key: "household.sub_region_code", field: subRegionField },
      { key: "household.district_code",   field: districtField },
      { key: "household.county_code",     field: countyField },
    ];
    const paths = _buildGeoPathsForRows(pins, cols, catalogue, 10);
    for (const path of paths) {
      const district = path["household.district_code"];
      const county   = path["household.county_code"];
      const cOpt = countyField.options.find(o => o.value === county);
      expect(cOpt).toBeTruthy();
      expect(cOpt.parent_code).toBe(district);
      // And nothing under Gulu/Acholi sneaks in.
      expect(county).not.toBe("C-AYAGO");
    }
  });

  it("pinned region propagates to every row", () => {
    const pins = {
      "household.region_code": { kind: "single", value: "R-CENTRAL" },
    };
    const cols = [{ key: "household.region_code", field: regionField }];
    const paths = _buildGeoPathsForRows(pins, cols, catalogue, 4);
    expect(paths.every(p => p["household.region_code"] === "R-CENTRAL")).toBe(true);
  });

  it("missing intermediate column breaks the chain cleanly", () => {
    // User selected region + district but skipped sub_region.
    const pins = {
      "household.region_code":   { kind: "single", value: "R-CENTRAL" },
      "household.district_code": { kind: "multi",  values: ["DST-KAMPALA", "DST-KALANGALA"], implicit: true },
    };
    const cols = [
      { key: "household.region_code",   field: regionField },
      { key: "household.district_code", field: districtField },
    ];
    const paths = _buildGeoPathsForRows(pins, cols, catalogue, 5);
    // District still gets a value (from the pin), just not chained
    // through the missing sub_region.
    for (const p of paths) {
      expect(p["household.region_code"]).toBe("R-CENTRAL");
      expect(["DST-KAMPALA", "DST-KALANGALA"]).toContain(p["household.district_code"]);
    }
  });

  it("returns [] when rowCount=0; empty paths {} for no geo cols", () => {
    expect(_buildGeoPathsForRows({}, [], catalogue, 0)).toEqual([]);
    expect(_buildGeoPathsForRows({}, [{ key: "household.id", field: { key: "household.id", type: "text" } }], catalogue, 3))
      .toEqual([{}, {}, {}]);
  });
});

describe("PreviewStep renders coherent geographic chain", () => {
  // Tiny catalogue covering the chain — region pinned to Central,
  // every other geo level inferred via parent_code.
  const regionField = {
    key: "household.region_code", label: "Region", type: "enum", sensitivity: "Public",
    options: [
      { value: "R-CENTRAL",  label: "Central" },
      { value: "R-NORTHERN", label: "Northern" },
    ],
  };
  const subRegionField = {
    key: "household.sub_region_code", label: "Sub-region", type: "enum", sensitivity: "Public",
    options: [
      { value: "SR-BUGANDA-S", label: "Buganda South", parent_code: "R-CENTRAL"  },
      { value: "SR-BUGANDA-N", label: "Buganda North", parent_code: "R-CENTRAL"  },
      { value: "SR-ACHOLI",    label: "Acholi",        parent_code: "R-NORTHERN" },
    ],
  };
  const districtField = {
    key: "household.district_code", label: "District", type: "enum", sensitivity: "Public",
    options: [
      { value: "DST-KAMPALA",   label: "Kampala",   parent_code: "SR-BUGANDA-S" },
      { value: "DST-KALANGALA", label: "Kalangala", parent_code: "SR-BUGANDA-S" },
      { value: "DST-LUWEERO",   label: "Luweero",   parent_code: "SR-BUGANDA-N" },
      { value: "DST-GULU",      label: "Gulu",      parent_code: "SR-ACHOLI"    },
    ],
  };
  const cat = {
    "household.region_code":     regionField,
    "household.sub_region_code": subRegionField,
    "household.district_code":   districtField,
  };
  const tree = {
    id: "g", kind: "group", combinator: "AND",
    rules: [
      { id: "r1", kind: "rule", field: "household.region_code",
        op: "eq", value: "R-CENTRAL" },
    ],
  };

  it("every row's District descends from that row's Sub-region", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.sub_region_code", "household.district_code"]}
      catalogueByKey={cat}
      tree={tree}/>);
    // Cross-check each row: District's option must have
    // parent_code === Sub-region's value-of-label.
    const labelToValue = {
      Central: "R-CENTRAL",
      "Buganda South": "SR-BUGANDA-S",
      "Buganda North": "SR-BUGANDA-N",
      Acholi: "SR-ACHOLI",
      Kampala: "DST-KAMPALA",
      Kalangala: "DST-KALANGALA",
      Luweero: "DST-LUWEERO",
      Gulu: "DST-GULU",
    };
    const rows = document.querySelectorAll("tbody tr");
    expect(rows.length).toBeGreaterThan(0);
    for (const tr of rows) {
      const tds = tr.querySelectorAll("td");
      const subRegionLabel = tds[1].textContent;
      const districtLabel  = tds[2].textContent;
      const subRegionVal = labelToValue[subRegionLabel];
      const districtVal  = labelToValue[districtLabel];
      const dOpt = districtField.options.find(o => o.value === districtVal);
      expect(dOpt).toBeTruthy();
      expect(dOpt.parent_code).toBe(subRegionVal);
    }
  });

  it("never renders a district from outside the pinned region (Gulu absent)", () => {
    render(<PreviewStep
      selected={["household.region_code", "household.sub_region_code", "household.district_code"]}
      catalogueByKey={cat}
      tree={tree}/>);
    const text = document.querySelector("tbody").textContent;
    expect(text).not.toContain("Gulu");
    expect(text).not.toContain("Acholi");
  });
});
