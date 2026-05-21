/* US-DR-EXT — cascading geographic dropdowns in DRS Step 2.
 *
 * Asserts the `_qbFilterGeoOptions` helper that QBValueEditor +
 * QBMultiSelect both call:
 *   1. Filters child geo options to those whose parent_code matches
 *      the pinned ancestor's value.
 *   2. Single-pinned ancestor narrows to one parent's children;
 *      multi-pinned ancestor unions across the pinned set.
 *   3. Non-geo enum fields pass through unchanged.
 *   4. Unpinned ancestor → no filter.
 *   5. Skipped intermediate level (region pinned, district editor) —
 *      no filter (district's IMMEDIATE parent is sub_region, which
 *      isn't pinned). This is the conservative choice; we cascade
 *      one level at a time.
 *   6. Defensive: empty options, options without parent_code,
 *      filter wipes the dropdown → fall back to unfiltered set.
 */

import { beforeAll, describe, expect, it } from "vitest";

let _qbFilterGeoOptions;
let _GEO_CHAIN;

beforeAll(async () => {
  // The querybuilder module touches React + Icon at module load.
  // The fieldselector + screens-drs modules also import each other
  // for the _GEO_CHAIN constant — load in the harness order.
  globalThis.PageHeader = () => null;
  globalThis.Field = () => null;
  globalThis.ReasonModal = () => null;
  globalThis.Toast = () => null;
  await import("./screens-drs-fieldselector.jsx");
  await import("./screens-drs-querybuilder.jsx");
  await import("./screens-drs.jsx");
  ({ _qbFilterGeoOptions, _GEO_CHAIN } = globalThis);
});

const regionPinSingle = (value) => ({
  "household.region_code": { kind: "single", value },
});
const regionPinMulti = (values) => ({
  "household.region_code": { kind: "multi", values },
});

const subRegionField = {
  key: "household.sub_region_code", type: "enum",
  options: [
    { value: "SR-BUGANDA-S", label: "Buganda South", parent_code: "R-CENTRAL" },
    { value: "SR-BUGANDA-N", label: "Buganda North", parent_code: "R-CENTRAL" },
    { value: "SR-ACHOLI",    label: "Acholi",         parent_code: "R-NORTHERN" },
    { value: "SR-KARAMOJA",  label: "Karamoja",       parent_code: "R-NORTHERN" },
  ],
};
const districtField = {
  key: "household.district_code", type: "enum",
  options: [
    { value: "DST-KAMPALA",   label: "Kampala",   parent_code: "SR-BUGANDA-S" },
    { value: "DST-KALANGALA", label: "Kalangala", parent_code: "SR-BUGANDA-S" },
    { value: "DST-GULU",      label: "Gulu",      parent_code: "SR-ACHOLI"    },
  ],
};
const regionField = {
  key: "household.region_code", type: "enum",
  options: [
    { value: "R-CENTRAL",  label: "Central" },
    { value: "R-NORTHERN", label: "Northern" },
  ],
};

describe("_qbFilterGeoOptions", () => {
  it("returns the full set when nothing is pinned", () => {
    const out = _qbFilterGeoOptions(subRegionField, {});
    expect(out.map(o => o.value)).toEqual([
      "SR-BUGANDA-S", "SR-BUGANDA-N", "SR-ACHOLI", "SR-KARAMOJA",
    ]);
  });

  it("narrows sub_region options to children of a single-pinned region", () => {
    const out = _qbFilterGeoOptions(subRegionField, regionPinSingle("R-CENTRAL"));
    expect(out.map(o => o.value).sort()).toEqual(["SR-BUGANDA-N", "SR-BUGANDA-S"]);
  });

  it("unions across a multi-pinned region", () => {
    const out = _qbFilterGeoOptions(
      subRegionField, regionPinMulti(["R-CENTRAL", "R-NORTHERN"]),
    );
    expect(out.map(o => o.value).sort()).toEqual([
      "SR-ACHOLI", "SR-BUGANDA-N", "SR-BUGANDA-S", "SR-KARAMOJA",
    ]);
  });

  it("cascades district when sub_region is pinned (full chain step)", () => {
    const pins = {
      "household.sub_region_code": { kind: "single", value: "SR-BUGANDA-S" },
    };
    const out = _qbFilterGeoOptions(districtField, pins);
    expect(out.map(o => o.value).sort()).toEqual(["DST-KALANGALA", "DST-KAMPALA"]);
  });

  it("does NOT cascade district when ONLY region is pinned (skipped level)", () => {
    // District's immediate parent in _GEO_CHAIN is sub_region. If
    // the user pins region without picking a sub_region, the
    // immediate-parent check returns the full district list.
    const out = _qbFilterGeoOptions(districtField, regionPinSingle("R-CENTRAL"));
    expect(out.map(o => o.value)).toEqual([
      "DST-KAMPALA", "DST-KALANGALA", "DST-GULU",
    ]);
  });

  it("passes non-geo enum fields through unchanged", () => {
    const sex = {
      key: "member.sex", type: "enum",
      options: [{ value: "F", label: "Female" }, { value: "M", label: "Male" }],
    };
    const out = _qbFilterGeoOptions(sex, regionPinSingle("R-CENTRAL"));
    expect(out).toEqual(sex.options);
  });

  it("passes region (top of chain) through unchanged", () => {
    const out = _qbFilterGeoOptions(regionField, regionPinSingle("R-CENTRAL"));
    expect(out).toEqual(regionField.options);
  });

  it("returns unfiltered options when the data has no parent_code linkage", () => {
    const noParent = {
      key: "household.sub_region_code", type: "enum",
      options: [
        { value: "SR-X", label: "X" },
        { value: "SR-Y", label: "Y" },
      ],
    };
    const out = _qbFilterGeoOptions(noParent, regionPinSingle("R-CENTRAL"));
    expect(out).toEqual(noParent.options);
  });

  it("handles empty options safely", () => {
    expect(_qbFilterGeoOptions({ key: "household.sub_region_code", type: "enum", options: [] }, regionPinSingle("R-CENTRAL"))).toEqual([]);
    expect(_qbFilterGeoOptions({ key: "household.sub_region_code", type: "enum" }, regionPinSingle("R-CENTRAL"))).toEqual([]);
  });

  it("does NOT crash on null / undefined pins", () => {
    expect(_qbFilterGeoOptions(subRegionField, null).length).toBe(4);
    expect(_qbFilterGeoOptions(subRegionField, undefined).length).toBe(4);
  });

  it("relies on _GEO_CHAIN — verify the chain is loaded", () => {
    // Sanity: the test depends on screens-drs.jsx exposing the
    // chain to globals; if that ever changes the cascade would
    // silently become a no-op.
    expect(Array.isArray(_GEO_CHAIN)).toBe(true);
    expect(_GEO_CHAIN[0]).toBe("household.region_code");
    expect(_GEO_CHAIN).toContain("household.sub_region_code");
    expect(_GEO_CHAIN).toContain("household.district_code");
  });
});
