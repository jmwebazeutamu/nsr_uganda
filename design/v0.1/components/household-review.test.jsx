/* The detailed household review.
 *
 * The property everything else rests on: NOTHING IS DROPPED. This is
 * the screen an operator opens to find what the rules missed, so a
 * field it silently omits is precisely where an anomaly hides. The
 * coverage cases below run over REAL payloads of both shapes — scrubbed
 * of personal data, shape untouched — because the two producers write
 * incompatible structures under one name and a model built against
 * either is blind to the other.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAYLOADS = JSON.parse(fs.readFileSync(
  path.join(HERE, "..", "data", "fixtures", "canonical-payloads.json"), "utf8"));

let buildReviewModel, reviewCoverage, HouseholdReview, isEditablePath,
    notEditableReason, composition, humaniseKey, resolveField;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = ({ name }) => React.createElement("i", { "data-icon": name });
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.useChoiceList = () => [[{ code: "1", label: "Owner occupied" }], { loading: false }];
  await import("./household-review-model.jsx");
  await import("./household-review.jsx");
  ({ buildReviewModel, reviewCoverage, HouseholdReview, isEditablePath,
     notEditableReason, composition, humaniseKey, resolveField } = globalThis);
});

afterEach(() => cleanup());

const SHAPES = Object.keys(PAYLOADS);


/* ═══════════════════════════════════════════════════════════════════
   The property: nothing is dropped
   ═══════════════════════════════════════════════════════════════════ */

describe("coverage", () => {
  it.each(SHAPES)("shows every field the %s payload holds", (shape) => {
    const { missing, inPayload } = reviewCoverage(PAYLOADS[shape]);
    expect(inPayload.length).toBeGreaterThan(50);   // a real payload
    expect(missing, `${missing.length} fields would be invisible:\n`
      + missing.slice(0, 20).join("\n")).toHaveLength(0);
  });

  it("puts an unrecognised top-level section somewhere visible", () => {
    // A questionnaire that grows a section must not vanish from the one
    // screen built for seeing everything.
    const model = buildReviewModel({
      members: [],
      some_future_module: { a_new_question: "42", another: "x" },
    });
    const paths = model.other.map(r => r.path);
    expect(paths).toContain("some_future_module.a_new_question");
    expect(paths).toContain("some_future_module.another");
  });

  it("keeps an empty value rather than discarding the field", () => {
    // "Asked and left blank" and "never asked" are different facts, and
    // a review that drops the blank one hides the more interesting.
    const model = buildReviewModel({
      members: [], housing: { dwelling: { roof_material: "" } },
    });
    const row = model.sections.flatMap(s => s.rows)
      .find(r => r.path === "housing.dwelling.roof_material");
    expect(row).toBeTruthy();
    expect(row.empty).toBe(true);
  });

  it.each(SHAPES)("finds the members in the %s shape", (shape) => {
    expect(buildReviewModel(PAYLOADS[shape]).members.length).toBeGreaterThan(0);
  });

  it("reads per-member detail from either shape", () => {
    // Kobo hangs it on the member; the wizard keys it by line number.
    const onMember = buildReviewModel({
      members: [{ line_number: 1, health: { chronic_illness_flag: "1" } }],
    });
    const keyed = buildReviewModel({
      members: [{ line_number: 1 }],
      health: { 1: { health: { chronic_illness_flag: "1" } } },
    });
    for (const model of [onMember, keyed]) {
      const rows = model.members[0].detail.flatMap(d => d.rows);
      expect(rows.some(r => r.key === "chronic_illness_flag")).toBe(true);
    }
  });

  it("survives a malformed payload instead of blanking the screen", () => {
    for (const bad of [null, undefined, {}, { members: "nope" }, []]) {
      expect(() => buildReviewModel(bad)).not.toThrow();
    }
  });
});


/* ═══════════════════════════════════════════════════════════════════
   Composition — the flags an operator verifies
   ═══════════════════════════════════════════════════════════════════ */

describe("household composition", () => {
  // What /api/v1/intake/field-dictionary/ serves, read from the active
  // DQA rules' parameters. These were literals inside composition() until
  // the registry-lookup change; the panel now draws the same boundaries
  // the engine enforces. elderly_min_age is deliberately absent from the
  // registry — see the "missing thresholds" block below.
  const THRESHOLDS = {
    head_min_age: 12, child_max_age: 17, orphan_max_age: 18,
    elderly_min_age: 60,
  };
  const flags = (members, thresholds = THRESHOLDS) =>
    Object.fromEntries(composition(members, thresholds).map(f => [f.label, f.value]));

  it("counts the roster, not the reported size", () => {
    expect(flags([{ line_number: 1 }, { line_number: 2 }])["Household size"]).toBe(2);
  });

  it("identifies a child-headed household", () => {
    const f = flags([{ is_head: true, age_years: 15 }, { age_years: 8 }]);
    expect(f["Child-headed"]).toBe("yes");
    expect(f["Elderly-headed"]).toBe("no");
  });

  it("identifies an elderly-headed household", () => {
    expect(flags([{ is_head: true, age_years: 71 }])["Elderly-headed"]).toBe("yes");
  });

  it("accepts either way of designating the head", () => {
    // Connectors set is_head; some sources code relationship 01.
    expect(flags([{ relationship_to_head: "01", age_years: 40 }])["Head's age"]).toBe(40);
  });

  it("says 'unknown', never a default, when there is no age", () => {
    const f = flags([{ is_head: true }]);
    expect(f["Head's age"]).toBe("unknown");
    expect(f["Child-headed"]).toBe("unknown");
    expect(f["Elderly-headed"]).toBe("unknown");
  });

  it("says when no head is designated at all", () => {
    expect(flags([{ age_years: 40 }])["Head of household"]).toBe("none designated");
  });

  it("does not hide members whose age is missing from the counts", () => {
    // A ratio computed over 2 of 5 members, presented as though it were
    // over 5, is worse than no ratio.
    const f = flags([
      { is_head: true, age_years: 40 }, { age_years: 8 }, {}, {}, {},
    ]);
    expect(String(f["Members under 18"])).toContain("age unknown");
    expect(String(f["Dependency ratio"])).toBeTruthy();
  });

  it("does not divide by zero when nobody is working age", () => {
    const f = flags([{ is_head: true, age_years: 80 }, { age_years: 6 }]);
    expect(f["Dependency ratio"]).toBe("no working-age members");
  });
});


/* ═══════════════════════════════════════════════════════════════════
   Editability — honest, not optimistic
   ═══════════════════════════════════════════════════════════════════ */

describe("what may be corrected", () => {
  it.each([
    "gps_lat", "address_narrative",
    "members.0.surname", "members.0.health.chronic_illness_flag",
    "health.1.chronic_illness_flag", "housing.dwelling.roof_material",
    "housing.tenure", "agriculture.land_ownership",
    "food_security.fies.i1_fies", "interview.respondent_phone",
  ])("offers %s", (p) => expect(isEditablePath(p)).toBe(true));

  it.each([
    "members.0.nin", "members.0.nin_last4", "housing.nin",
    "geographic.region", "geographic.parish",
    "consent", "consent_block.REGISTRATION", "urban_rural",
    "interview.consent",
    "housing.assets.0.count", "_source_keys.kobo_uuid",
  ])("refuses %s", (p) => expect(isEditablePath(p)).toBe(false));

  it.each([
    ["geographic.region", /re-capture only/],
    ["members.0.nin", /legal identity/],
    ["consent_block.REGISTRATION", /legal and PMT meaning/],
    ["housing.assets.0.count", /added and removed/],
    ["_source_keys.kobo_uuid", /append-only/],
  ])("explains why %s cannot be corrected", (p, pattern) => {
    // A field that is simply greyed out teaches an operator that the
    // screen is broken. One that says why teaches them the policy.
    expect(notEditableReason(p)).toMatch(pattern);
  });
});


/* ═══════════════════════════════════════════════════════════════════
   Rendering
   ═══════════════════════════════════════════════════════════════════ */

describe("the review", () => {
  it.each(SHAPES)("renders the %s payload without crashing", (shape) => {
    render(<HouseholdReview payload={PAYLOADS[shape]}/>);
    expect(screen.getByText("Household composition")).toBeTruthy();
    expect(screen.getByText("Members")).toBeTruthy();
  });

  it("offers inputs only for correctable fields", () => {
    render(<HouseholdReview payload={PAYLOADS.wizard} canEdit onEdit={() => {}}/>);
    // Open every section so the rows are in the DOM.
    for (const b of screen.getAllByRole("button")) fireEvent.click(b);
    const inputs = [...document.querySelectorAll("input")];
    expect(inputs.length).toBeGreaterThan(0);
    for (const input of inputs) {
      const label = input.getAttribute("aria-label") || "";
      const path = (label.match(/\(([^)]+)\)$/) || [])[1];
      expect(isEditablePath(path), `offered an input for ${path}`).toBe(true);
    }
  });

  it("renders nothing editable when the record is not editable", () => {
    render(<HouseholdReview payload={PAYLOADS.wizard}
      canEdit={false} editBlockedReason="cleared its gates"/>);
    for (const b of screen.getAllByRole("button")) fireEvent.click(b);
    expect(document.querySelectorAll("input")).toHaveLength(0);
    expect(screen.getByText(/cleared its gates/)).toBeTruthy();
  });

  it("names every input, so the path is recoverable by a screen reader", () => {
    render(<HouseholdReview payload={PAYLOADS.wizard} canEdit onEdit={() => {}}/>);
    for (const b of screen.getAllByRole("button")) fireEvent.click(b);
    for (const input of document.querySelectorAll("input")) {
      expect(input.getAttribute("aria-label")).toBeTruthy();
    }
  });

  it("marks an edited field and shows the new value", () => {
    render(<HouseholdReview payload={PAYLOADS.wizard} canEdit onEdit={() => {}}
      draft={{ "housing.dwelling.roof_material": "99" }}/>);
    for (const b of screen.getAllByRole("button")) fireEvent.click(b);
    expect(screen.getAllByText("edited").length).toBeGreaterThan(0);
  });

  it("shows the lineage section for a record that has one", () => {
    render(<HouseholdReview payload={PAYLOADS.kobo}/>);
    expect(screen.getByText("Source lineage")).toBeTruthy();
  });

  it.each([null, undefined, {}])("says nothing at all for %o", (empty) => {
    render(<HouseholdReview payload={empty}/>);
    expect(screen.getByText("No record loaded.")).toBeTruthy();
  });

  it("still renders a record that arrived carrying almost nothing", () => {
    // An empty payload and a sparse one are different. A record with
    // one field is a record, and hiding it behind "no record loaded"
    // would conceal exactly the kind of anomaly this screen is for.
    render(<HouseholdReview payload={{ members: [], urban_rural: "1" }}/>);
    expect(screen.queryByText("No record loaded.")).toBeNull();
    expect(screen.getByText("Household composition")).toBeTruthy();
  });
});


describe("labels", () => {
  it("humanises a key it has never seen rather than showing it raw", () => {
    expect(humaniseKey("some_brand_new_question")).toBe("Some brand new question");
  });

  it("uses the known label where there is one", () => {
    expect(humaniseKey("roof_material")).toBe("Roof material");
  });
});


/* ═══════════════════════════════════════════════════════════════════
   The field vocabulary comes from the registry
   ═══════════════════════════════════════════════════════════════════
   This module used to carry a 39-entry label map and a 27-entry
   field-to-choice-list map — a second vocabulary for fields the
   instrument already defines. The registry codes a question by its
   place on the form (g6_wall_material) and the payload names the fact
   (wall_material); nothing kept the two in step, which is the seventh
   time this project has found two vocabularies for one concept drifting
   apart.

   These assert on the drift directly: a label must come from the served
   dictionary, and a field the dictionary does not define must be VISIBLY
   unmapped rather than quietly title-cased into something plausible. */

describe("field vocabulary", () => {
  // Shaped exactly like /api/v1/intake/field-dictionary/.
  const DICT = {
    form_version: 1,
    fields: {
      wall_material: {
        label: "Main wall material", question_label: "G6. Main wall material",
        choice_list: "wall_material", question_name: "g6_wall_material",
        section: "G", type: "select_one", source: "instrument",
      },
      land_title: {
        label: "Title deed with household member name?",
        question_label: "H8. Title deed with household member name?",
        choice_list: "title_deed", question_name: "h8_title_deed",
        section: "H", type: "select_one", source: "instrument",
      },
      gps_lat: {
        label: "Latitude", question_label: "Latitude", choice_list: null,
        question_name: "", section: "", type: "", source: "capture-metadata",
      },
    },
    thresholds: { head_min_age: 12, child_max_age: 17, orphan_max_age: 18,
                  elderly_min_age: null },
    missing_thresholds: { elderly_min_age: "Define AC-ELDERLY-HEAD.min_age." },
    conflicts: [],
  };

  it("takes the label from the dictionary, not from this file", () => {
    const f = resolveField("wall_material", DICT);
    expect(f.label).toBe("Main wall material");
    expect(f.choiceList).toBe("wall_material");
    expect(f.missing).toBe(false);
  });

  it("resolves fields no prefix-stripping heuristic could reach", () => {
    // h8_title_deed -> land_title. Stripping "h8_" gives "title_deed",
    // which is not the payload key; the mapping has to be stated, and
    // this is the test that says so.
    expect(resolveField("land_title", DICT).label)
      .toBe("Title deed with household member name?");
  });

  it("marks a field the registry does not define as unmapped", () => {
    const f = resolveField("some_new_question", DICT);
    expect(f.missing).toBe(true);
    expect(f.choiceList).toBeNull();
  });

  it("says where a label came from, so 'not asked' is visible", () => {
    expect(resolveField("gps_lat", DICT).source).toBe("capture-metadata");
    expect(resolveField("wall_material", DICT).source).toBe("instrument");
  });

  it("reports everything as unmapped when no dictionary has loaded", () => {
    // The honest rendering of "the registry has not answered yet".
    expect(resolveField("wall_material", null).missing).toBe(true);
    expect(resolveField("wall_material", null).choiceList).toBeNull();
  });

  it("carries the dictionary's label and choice list onto the rows", () => {
    const model = buildReviewModel(
      { members: [], housing: { dwelling: { wall_material: "3" } } }, DICT,
    );
    const rows = model.sections.flatMap(s => s.rows || []);
    const row = rows.find(r => r.key === "wall_material");
    expect(row).toBeTruthy();
    expect(row.label).toBe("Main wall material");
    expect(row.choiceList).toBe("wall_material");
    expect(row.missing).toBe(false);
  });

  it("flags an unmapped field on the row rather than inventing a label", () => {
    const model = buildReviewModel(
      { members: [], housing: { dwelling: { newly_added_question: "7" } } }, DICT,
    );
    const rows = model.sections.flatMap(s => s.rows || []);
    const row = rows.find(r => r.key === "newly_added_question");
    expect(row).toBeTruthy();
    expect(row.missing).toBe(true);
    // Its code is NOT decoded — decoding it would need a choice list
    // nobody has declared.
    expect(row.choiceList).toBeNull();
  });

  it("still shows every field when the dictionary is missing entirely", () => {
    // Degraded, never blank: an operator with no dictionary must still
    // see the record, just unlabelled.
    const { missing } = reviewCoverage(PAYLOADS[SHAPES[0]]);
    expect(missing).toHaveLength(0);
  });
});


describe("missing thresholds", () => {
  const flags = (members, thresholds) =>
    Object.fromEntries(composition(members, thresholds).map(f => [f.label, f.value]));

  it("omits the elderly band rather than assuming 60", () => {
    // 60 was a literal with nothing behind it. Until a rule defines the
    // boundary the panel must decline to draw it.
    const f = flags([{ is_head: true, age_years: 71 }], {
      head_min_age: 12, child_max_age: 17, orphan_max_age: 18,
      elderly_min_age: null,
    });
    expect(f["Elderly-headed"]).toBe("not configured");
    expect(f["Dependency ratio"]).toBe("not configured");
  });

  it("names the parameter that would close the gap", () => {
    const rows = composition([{ is_head: true, age_years: 71 }], {
      orphan_max_age: 18, elderly_min_age: null,
    });
    const elderly = rows.find(r => r.label === "Elderly-headed");
    expect(elderly.detail).toContain("AC-ELDERLY-HEAD");
  });

  it("labels the count rows with the boundary actually in force", () => {
    // The row used to say "Members under 18" whatever the rule said.
    const rows = composition([{ is_head: true, age_years: 40 }], {
      head_min_age: 12, child_max_age: 17, orphan_max_age: 21,
      elderly_min_age: 65,
    });
    expect(rows.some(r => r.label === "Members under 21")).toBe(true);
    expect(rows.some(r => r.label === "Members 65 and over")).toBe(true);
  });
});
