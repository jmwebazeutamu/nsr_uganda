/* BUG-S27-020 — DRS Step 2 must resolve choice-list options for
 * every detail-entity coded field, not only geographic-units /
 * programmes. The wizard's enum dropdowns rendered empty for the
 * 20+ `choice_list?name=*` slugs introduced by US-S22-DE.
 *
 * Asserts:
 *   1. `_choiceListNameFor` parses choice_list slugs and rejects
 *      anything else.
 *   2. `_enrichFieldsWithOptions` maps both GeographicUnit
 *      (`{code,name}`) and ChoiceListBundle (`{code,label}`) rows
 *      onto the `{value,label}` shape the builder expects.
 *   3. `_resolveOptionsForSchema` makes ONE batched fetch to
 *      /choice-list-bundle/ regardless of how many coded fields
 *      the schema carries, in parallel with per-URL fetches for
 *      geographic / programme slugs, and distributes the results
 *      back into the cache under the slug keys the schema uses.
 *   4. Failed fetches resolve to empty arrays — the rest of the
 *      wizard keeps rendering rather than throwing.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

let _choiceListNameFor;
let _enrichFieldsWithOptions;
let _resolveOptionsForSchema;

beforeAll(async () => {
  // The screens-drs module body wires several primitives via
  // bare-identifier globals; stub them so the file evaluates clean.
  globalThis.PageHeader = () => null;
  globalThis.Field = () => null;
  globalThis.ReasonModal = () => null;
  globalThis.Toast = () => null;

  await import("./screens-drs-fieldselector.jsx");
  await import("./screens-drs-querybuilder.jsx");
  await import("./screens-drs.jsx");
  ({
    _choiceListNameFor,
    _enrichFieldsWithOptions,
    _resolveOptionsForSchema,
  } = globalThis);
});

// ───────────────────────────────────────────────────────────────
// _choiceListNameFor
// ───────────────────────────────────────────────────────────────

describe("_choiceListNameFor", () => {
  it("extracts the list name from a choice_list slug", () => {
    expect(_choiceListNameFor("choice_list?name=dwelling_tenure")).toBe("dwelling_tenure");
    expect(_choiceListNameFor("choice_list?name=wg_difficulty_level")).toBe("wg_difficulty_level");
  });

  it("returns null for non-choice_list slugs", () => {
    expect(_choiceListNameFor("geographic-units?level=region")).toBeNull();
    expect(_choiceListNameFor("programmes")).toBeNull();
    expect(_choiceListNameFor("")).toBeNull();
    expect(_choiceListNameFor(null)).toBeNull();
    expect(_choiceListNameFor(undefined)).toBeNull();
  });
});

// ───────────────────────────────────────────────────────────────
// _enrichFieldsWithOptions
// ───────────────────────────────────────────────────────────────

describe("_enrichFieldsWithOptions", () => {
  it("passes through fields that already have inline options", () => {
    const fields = [{
      key: "household.urban_rural", type: "enum",
      options: [{ value: "1", label: "Urban" }, { value: "2", label: "Rural" }],
    }];
    const out = _enrichFieldsWithOptions(fields, {});
    expect(out[0].options).toEqual(fields[0].options);
  });

  it("passes through fields without options_source", () => {
    const fields = [{ key: "household.id", type: "text" }];
    expect(_enrichFieldsWithOptions(fields, {})[0]).toEqual(fields[0]);
  });

  it("maps GeographicUnit rows ({code,name}) to {value,label}", () => {
    const fields = [{
      key: "household.sub_region_code", type: "enum",
      options_source: "geographic-units?level=sub_region",
    }];
    const cache = {
      "geographic-units?level=sub_region": [
        { code: "SR-KARAMOJA", name: "Karamoja" },
        { code: "SR-ACHOLI",   name: "Acholi" },
      ],
    };
    const out = _enrichFieldsWithOptions(fields, cache);
    expect(out[0].options).toEqual([
      { value: "SR-KARAMOJA", label: "Karamoja" },
      { value: "SR-ACHOLI",   label: "Acholi" },
    ]);
  });

  it("maps ChoiceListBundle rows ({code,label}) to {value,label}", () => {
    const fields = [{
      key: "household.dwelling.tenure", type: "enum",
      options_source: "choice_list?name=dwelling_tenure",
    }];
    const cache = {
      "choice_list?name=dwelling_tenure": [
        { code: "1", label: "Owner-occupied" },
        { code: "2", label: "Rented" },
        { code: "3", label: "Provided free" },
      ],
    };
    const out = _enrichFieldsWithOptions(fields, cache);
    expect(out[0].options).toEqual([
      { value: "1", label: "Owner-occupied" },
      { value: "2", label: "Rented" },
      { value: "3", label: "Provided free" },
    ]);
  });

  it("returns options:[] when the slug isn't resolved yet (no crash)", () => {
    const fields = [{
      key: "household.dwelling.tenure", type: "enum",
      options_source: "choice_list?name=dwelling_tenure",
    }];
    const out = _enrichFieldsWithOptions(fields, {});
    expect(out[0].options).toEqual([]);
  });

  it("filters out rows without a code (defensive)", () => {
    const fields = [{
      key: "x", type: "enum",
      options_source: "choice_list?name=foo",
    }];
    const cache = {
      "choice_list?name=foo": [
        { code: "ok", label: "OK" },
        { label: "missing-code" },
        { code: "", label: "blank" },
      ],
    };
    expect(_enrichFieldsWithOptions(fields, cache)[0].options).toEqual([
      { value: "ok", label: "OK" },
    ]);
  });

  it("returns [] for null / undefined schemaFields", () => {
    expect(_enrichFieldsWithOptions(null, {})).toEqual([]);
    expect(_enrichFieldsWithOptions(undefined, {})).toEqual([]);
  });
});

// ───────────────────────────────────────────────────────────────
// _resolveOptionsForSchema
// ───────────────────────────────────────────────────────────────

describe("_resolveOptionsForSchema", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock;
  });

  afterEach(() => {
    delete globalThis.fetch;
  });

  const okJson = (data) => Promise.resolve({
    ok: true, json: () => Promise.resolve(data),
  });

  it("returns {} when the schema has no fields with options_source", async () => {
    const out = await _resolveOptionsForSchema([
      { key: "x", type: "text" },
      { key: "y", type: "number" },
    ]);
    expect(out).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("batches every choice_list slug into ONE bundle fetch", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/choice-list-bundle/")) {
        return okJson({
          as_of: "2026-05-21", lang: "en",
          lists: [
            { list_name: "dwelling_tenure", version: 1,
              options: [{ code: "1", label: "Owner" }] },
            { list_name: "roof_material",   version: 1,
              options: [{ code: "a", label: "Iron sheets" }] },
            { list_name: "cooking_fuel",    version: 1,
              options: [{ code: "x", label: "Charcoal" }] },
          ],
        });
      }
      return okJson(null);
    });

    const schema = [
      { key: "h.d.tenure",       options_source: "choice_list?name=dwelling_tenure" },
      { key: "h.d.roof",         options_source: "choice_list?name=roof_material" },
      { key: "h.u.cooking_fuel", options_source: "choice_list?name=cooking_fuel" },
    ];
    const out = await _resolveOptionsForSchema(schema);

    // Exactly one HTTP call — not one per slug.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = fetchMock.mock.calls[0][0];
    expect(calledUrl).toContain("/choice-list-bundle/");
    expect(calledUrl).toContain("lists=");
    expect(calledUrl).toContain("dwelling_tenure");
    expect(calledUrl).toContain("roof_material");
    expect(calledUrl).toContain("cooking_fuel");

    // Cache distributed back under the schema's slug keys.
    expect(out["choice_list?name=dwelling_tenure"]).toEqual([{ code: "1", label: "Owner" }]);
    expect(out["choice_list?name=roof_material"]).toEqual([{ code: "a", label: "Iron sheets" }]);
    expect(out["choice_list?name=cooking_fuel"]).toEqual([{ code: "x", label: "Charcoal" }]);
  });

  it("dedupes choice_list slugs across many fields", async () => {
    fetchMock.mockImplementation(() => okJson({
      lists: [{ list_name: "yes_no", version: 1,
        options: [{ code: "1", label: "Yes" }, { code: "2", label: "No" }] }],
    }));

    const schema = [
      { key: "member.literacy_status_a", options_source: "choice_list?name=yes_no" },
      { key: "member.literacy_status_b", options_source: "choice_list?name=yes_no" },
      { key: "member.literacy_status_c", options_source: "choice_list?name=yes_no" },
    ];
    await _resolveOptionsForSchema(schema);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toMatch(/lists=yes_no(?:&|$)/);
  });

  it("issues per-URL fetches in parallel with the bundle fetch", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/choice-list-bundle/")) {
        return okJson({ lists: [{ list_name: "dwelling_tenure",
          options: [{ code: "1", label: "Owner" }] }] });
      }
      if (url.includes("level=sub_region")) {
        return okJson({ results: [{ code: "SR-KARAMOJA", name: "Karamoja" }] });
      }
      if (url.includes("/programmes/")) {
        return okJson({ results: [{ code: "OPM-PDM", name: "PDM" }] });
      }
      return okJson(null);
    });

    const schema = [
      { key: "h.subreg", options_source: "geographic-units?level=sub_region" },
      { key: "h.prog",   options_source: "programmes" },
      { key: "h.tenure", options_source: "choice_list?name=dwelling_tenure" },
    ];
    const out = await _resolveOptionsForSchema(schema);

    expect(fetchMock).toHaveBeenCalledTimes(3);   // 2 URL + 1 bundle
    expect(out["geographic-units?level=sub_region"]).toEqual([
      { code: "SR-KARAMOJA", name: "Karamoja" },
    ]);
    expect(out["programmes"]).toEqual([{ code: "OPM-PDM", name: "PDM" }]);
    expect(out["choice_list?name=dwelling_tenure"]).toEqual([{ code: "1", label: "Owner" }]);
  });

  it("survives a failed bundle fetch (returns [] for those slugs)", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/choice-list-bundle/")) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve(null) });
      }
      return okJson({ results: [{ code: "X", name: "X" }] });
    });
    const schema = [
      { key: "h.tenure", options_source: "choice_list?name=dwelling_tenure" },
      { key: "h.subreg", options_source: "geographic-units?level=sub_region" },
    ];
    const out = await _resolveOptionsForSchema(schema);
    // Bundle slugs absent → builderFields enrichment falls back to [].
    expect(out["choice_list?name=dwelling_tenure"]).toBeUndefined();
    // URL slug still resolved.
    expect(out["geographic-units?level=sub_region"]).toEqual([{ code: "X", name: "X" }]);
  });

  it("unknown URL slug is skipped (no map entry → no fetch)", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve(null) });
    const schema = [{ key: "x", options_source: "made-up?level=galactic" }];
    const out = await _resolveOptionsForSchema(schema);
    expect(out).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
