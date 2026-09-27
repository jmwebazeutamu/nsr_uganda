import { beforeAll, describe, expect, it } from "vitest";

let canDiscardPmtDraft;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.Chip = () => null;
  globalThis.PageHeader = () => null;
  globalThis.window = globalThis;

  await import("./screens-pmt-configuration.jsx");
  ({ canDiscardPmtDraft } = globalThis);
});

describe("canDiscardPmtDraft", () => {
  it("offers discard only for an unsubmitted canonical draft", () => {
    expect(canDiscardPmtDraft({ status: "draft" })).toBe(true);
    expect(canDiscardPmtDraft({ status: "pending_approval" })).toBe(false);
    expect(canDiscardPmtDraft({ status: "active" })).toBe(false);
    expect(canDiscardPmtDraft({ status: "rejected" })).toBe(false);
    expect(canDiscardPmtDraft(null)).toBe(false);
  });
});

/* The Variables table's two derived cells.
 *
 * A variable is named for the questionnaire field it scores, so the
 * binding must be recoverable from the name alone — that is the whole
 * reason for the `field__qualifier` spelling. And the Value cell has to
 * show what the variable actually tests, which is the thing the old
 * table never showed at all.
 */
describe("pcfgVariableField", () => {
  it("reads the field off the path, which is authoritative", () => {
    expect(pcfgVariableField({
      name: "anything_at_all",
      feature: { path: "head_member.education.highest_grade" },
    })).toBe("highest_grade");
  });

  it("falls back to the name when there is no path", () => {
    expect(pcfgVariableField({ name: "floor_material__tiles_terrazzo" }))
      .toBe("floor_material");
  });

  it("leaves an unqualified derived name alone", () => {
    expect(pcfgVariableField({ name: "member_count" })).toBe("member_count");
  });
});

describe("pcfgVariableValue", () => {
  const catalogue = {
    highest_grade: {
      field: "highest_grade",
      options: [
        { code: "17", label: "Professional Certificate" },
        { code: "19", label: "First Degree" },
        { code: "23", label: "PhD" },
      ],
    },
  };

  it("shows codes with their Reference Data labels", () => {
    const cell = pcfgVariableValue({
      name: "highest_grade__tertiary",
      feature: { type: "membership", path: "x.highest_grade", operand: ["17", "19", "23"] },
    }, catalogue);
    expect(cell).toContain("PhD");
    expect(cell).toContain("Professional Certificate");
  });

  it("shows the raw codes when no catalogue is loaded", () => {
    // Honest rather than blank: inventing a label for 17 is the defect
    // the whole canonical-binding exercise exists to stop.
    const cell = pcfgVariableValue({
      feature: { type: "membership", path: "x.highest_grade", operand: ["17", "19"] },
    }, {});
    expect(cell).toContain("17");
    expect(cell).toContain("19");
  });

  it("marks an inequality as a negation, not a match", () => {
    const cell = pcfgVariableValue({
      feature: { type: "inequality", path: "dwelling.tenure", operand: "11" },
    }, {});
    expect(cell.startsWith("not ")).toBe(true);
  });

  it("describes a ratio by its two operands", () => {
    expect(pcfgVariableValue({
      name: "rooms_per_capita",
      feature: { type: "ratio", numerator: "dwelling.total_rooms", denominator: "member_count" },
    }, {})).toBe("dwelling.total_rooms / member_count");
  });

  it("describes a collection feature by what it filters", () => {
    const cell = pcfgVariableValue({
      name: "owns_television",
      feature: { type: "presence_in_collection", collection: "assets", filter: { asset_type__in: ["tv"] } },
    }, {});
    expect(cell).toContain("tv");
  });

  it("never claims a value for a variable that tests nothing", () => {
    expect(pcfgVariableValue({ name: "member_count", feature: { type: "direct" } }, {}))
      .toBe("—");
  });
});
