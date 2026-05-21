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
  ({ PreviewStep, _previewCell } = globalThis);
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
