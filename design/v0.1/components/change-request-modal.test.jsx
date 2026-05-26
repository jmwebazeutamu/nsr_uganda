/* US-S22-003e — change-request-modal unit tests
 *
 * Covers the six points from the modal spec:
 *   1. Submit disabled until valid; enabled at the boundary.
 *   2. Adding a row groups it correctly; second row in same category joins.
 *   3. PMT chip flips to pmt_relevant when a PMT field is added; Force-PMT
 *      toggle works standalone; checkbox disabled when auto-derived.
 *   4. Already-added fields are disabled in the picker.
 *   5. Routing matrix returns the expected reviewer for every
 *      (change_type, pmt) combination.
 *   6. ESC closes the modal.
 *
 * The component-under-test uses `React`, `Icon`, `Chip`, `Modal` as
 * globals (it ships via Babel-standalone in the browser harness).
 * vitest.setup.js binds those on globalThis before this file is
 * evaluated; the dynamic import below then runs the modal's module
 * body which destructures React + attaches helpers to window.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let ChangeRequestModal;
let routeFor;
let derivePmt;
let CR_CATEGORIES;
let CR_FIELDS_FLAT;
let CR_ROUTING;

beforeAll(async () => {
  // Module body runs once; `Object.assign(window, …)` exposes the
  // helpers on globalThis under the harness names.
  await import("./change-request-modal.jsx");
  ({
    ChangeRequestModal,
    routeFor,
    derivePmt,
    CR_CATEGORIES,
    CR_FIELDS_FLAT,
    CR_ROUTING,
  } = globalThis);
});

afterEach(() => {
  cleanup();
});

// ───────────────────────────────────────────────────────────────
// Helpers
// ───────────────────────────────────────────────────────────────

const defaultProps = (over = {}) => ({
  open: true,
  onClose: () => {},
  household: null,
  householdId: "01HXY7K3B2N9PVQE4M6FZRWS18",
  me: { username: "florence" },
  addUx: "composer",
  onSubmit: async () => ({
    cr_id: "01CRTEST", audit_id: "A-TEST", routed_to: "CDO (parish)",
  }),
  ...over,
});

// Append a row via the composer add-UX. Uses category + field
// VALUES (the catalog keys) so it's robust against label wording.
const addRowViaComposer = async (user, categoryKey, fieldKey) => {
  await user.click(screen.getByText("Add a field change"));
  const selects = screen.getAllByRole("combobox");
  // The two newly-rendered selects are appended to the end of the
  // accessible-roles list; pick the last two.
  const catSelect = selects[selects.length - 2];
  const fldSelect = selects[selects.length - 1];
  fireEvent.change(catSelect, { target: { value: categoryKey } });
  fireEvent.change(fldSelect, { target: { value: fieldKey } });
  await user.click(screen.getByRole("button", { name: /^Add$/ }));
};

// ───────────────────────────────────────────────────────────────
// 5. Routing matrix
// ───────────────────────────────────────────────────────────────

describe("routeFor", () => {
  it("returns CDO (parish) for cosmetic correction/life_event/verification", () => {
    expect(routeFor("correction", false)).toBe("CDO (parish)");
    expect(routeFor("life_event", false)).toBe("CDO (parish)");
    expect(routeFor("verification", false)).toBe("CDO (parish)");
  });

  it("returns M&E Officer for PMT-relevant correction/life_event/verification", () => {
    expect(routeFor("correction", true)).toBe("M&E Officer");
    expect(routeFor("life_event", true)).toBe("M&E Officer");
    expect(routeFor("verification", true)).toBe("M&E Officer");
  });

  it("returns CDO + receiving CDO for cosmetic address_move", () => {
    expect(routeFor("address_move", false)).toBe("CDO + receiving CDO");
  });

  it("returns District M&E for PMT address_move + roster_change + asset_change", () => {
    expect(routeFor("address_move", true)).toBe("District M&E");
    expect(routeFor("roster_change", true)).toBe("District M&E");
    expect(routeFor("asset_change", true)).toBe("District M&E");
  });

  it("returns CDO (parish) for cosmetic roster_change + asset_change", () => {
    expect(routeFor("roster_change", false)).toBe("CDO (parish)");
    expect(routeFor("asset_change", false)).toBe("CDO (parish)");
  });

  it("covers every (change_type, pmt) combination in the spec", () => {
    const types = [
      "correction", "life_event", "verification",
      "address_move", "roster_change", "asset_change",
    ];
    for (const ct of types) {
      expect(routeFor(ct, false)).not.toBe("—");
      expect(routeFor(ct, true)).not.toBe("—");
    }
  });
});

describe("derivePmt", () => {
  it("returns false when no row is PMT-relevant", () => {
    expect(derivePmt([{ category: "iden", field: "phone" }])).toBe(false);
  });

  it("returns true when any row is PMT-relevant", () => {
    expect(derivePmt([
      { category: "iden", field: "phone" },
      { category: "hous", field: "roof" },
    ])).toBe(true);
  });

  it("returns true for a single PMT row", () => {
    expect(derivePmt([{ category: "hous", field: "roof" }])).toBe(true);
  });

  it("returns false on an empty rows array", () => {
    expect(derivePmt([])).toBe(false);
  });
});

// ───────────────────────────────────────────────────────────────
// 1. Submit disabled until valid
// ───────────────────────────────────────────────────────────────

describe("submit enable boundary", () => {
  it("submit is disabled on open (no rows, no note)", () => {
    render(<ChangeRequestModal {...defaultProps()} />);
    const submit = screen.getByRole("button", { name: /Create & submit/i });
    expect(submit).toBeDisabled();
  });

  it("submit stays disabled with valid rows but a short note", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    const valueInputs = screen.getAllByPlaceholderText("New value");
    await user.type(valueInputs[valueInputs.length - 1], "+256 700 000 000");
    const note = screen.getByPlaceholderText(/Why this change/);
    await user.type(note, "hi");
    expect(screen.getByRole("button", { name: /Create & submit/i })).toBeDisabled();
  });

  it("submit enables exactly at the boundary (1 row with value + note ≥ 6 chars)", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    const valueInputs = screen.getAllByPlaceholderText("New value");
    await user.type(valueInputs[valueInputs.length - 1], "+256 700 000 000");
    const note = screen.getByPlaceholderText(/Why this change/);
    await user.type(note, "valid"); // 5 chars — still under
    expect(screen.getByRole("button", { name: /Create & submit/i })).toBeDisabled();
    await user.type(note, "X"); // 6th char crosses the boundary
    expect(screen.getByRole("button", { name: /Create & submit/i })).toBeEnabled();
  });
});

// ───────────────────────────────────────────────────────────────
// 2. Grouping: second row in same category joins the existing group
// ───────────────────────────────────────────────────────────────

describe("row grouping", () => {
  it("groups two Housing rows under a single Housing strip", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "hous", "roof");
    await addRowViaComposer(user, "hous", "wall");

    // Exactly one group strip for Housing & Assets.
    const headings = screen.getAllByText("Housing & Assets");
    // One in the category strip; the inner row labels are different.
    expect(headings.length).toBe(1);

    // Both fields visible.
    expect(screen.getByText("Roof material")).toBeInTheDocument();
    expect(screen.getByText("Wall material")).toBeInTheDocument();

    // Count chip(s) read "2 fields" — both the toolbar summary and
    // the group strip surface this, so allow >= 1 match.
    expect(screen.getAllByText(/2 fields/).length).toBeGreaterThanOrEqual(1);
  });

  it("creates separate groups for distinct categories", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    await addRowViaComposer(user, "hous", "roof");

    // Two distinct category strips.
    expect(screen.getByText("Identification")).toBeInTheDocument();
    expect(screen.getByText("Housing & Assets")).toBeInTheDocument();
  });
});

// ───────────────────────────────────────────────────────────────
// 2b. Current-value display (slice 1 — gap from product review)
// ───────────────────────────────────────────────────────────────

describe("current value display", () => {
  it("shows 'current —' placeholder when currentValues has no entry", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    const chip = screen.getByTestId("current-iden-phone");
    expect(chip).toHaveTextContent("current —");
  });

  it("renders the current value when provided in currentValues", async () => {
    const user = userEvent.setup();
    render(
      <ChangeRequestModal
        {...defaultProps({ currentValues: { "iden.phone": "+256 700 123 456" } })}
      />,
    );
    await addRowViaComposer(user, "iden", "phone");
    const chip = screen.getByTestId("current-iden-phone");
    expect(chip).toHaveTextContent("current: +256 700 123 456");
  });

  it("formats a date current value", async () => {
    const user = userEvent.setup();
    render(
      <ChangeRequestModal
        {...defaultProps({ currentValues: { "rost.member_dob": "2018-04-08" } })}
      />,
    );
    await addRowViaComposer(user, "rost", "member_dob");
    const chip = screen.getByTestId("current-rost-member_dob");
    expect(chip).toHaveTextContent("current: 8 Apr 2018");
  });

  it("truncates long strings past 28 chars", async () => {
    const user = userEvent.setup();
    const long = "A very long current value that should be truncated for display";
    render(
      <ChangeRequestModal
        {...defaultProps({ currentValues: { "iden.head_name": long } })}
      />,
    );
    await addRowViaComposer(user, "iden", "head_name");
    const chip = screen.getByTestId("current-iden-head_name");
    expect(chip.textContent).toMatch(/^current: .{1,27}…$/);
  });

  it("treats empty string the same as missing", async () => {
    const user = userEvent.setup();
    render(
      <ChangeRequestModal
        {...defaultProps({ currentValues: { "iden.phone": "" } })}
      />,
    );
    await addRowViaComposer(user, "iden", "phone");
    const chip = screen.getByTestId("current-iden-phone");
    expect(chip).toHaveTextContent("current —");
  });
});

// ───────────────────────────────────────────────────────────────
// 3. PMT chip + Force-PMT toggle
// ───────────────────────────────────────────────────────────────

describe("PMT chip + Force PMT", () => {
  it("starts at cosmetic with Force-PMT enabled and unchecked", () => {
    render(<ChangeRequestModal {...defaultProps()} />);
    expect(screen.getByText("cosmetic")).toBeInTheDocument();
    const force = screen.getByLabelText(/Force PMT/i);
    expect(force).not.toBeChecked();
    expect(force).not.toBeDisabled();
  });

  it("Force-PMT toggled alone flips the chip to pmt_relevant", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await user.click(screen.getByLabelText(/Force PMT/i));
    expect(screen.getByText("pmt_relevant")).toBeInTheDocument();
  });

  it("Adding a PMT field auto-derives pmt_relevant AND disables Force-PMT", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "hous", "roof");
    expect(screen.getByText("pmt_relevant")).toBeInTheDocument();
    const force = screen.getByLabelText(/Force PMT/i);
    expect(force).toBeChecked();
    expect(force).toBeDisabled();
  });

  it("Adding a non-PMT field leaves the chip as cosmetic", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    expect(screen.getByText("cosmetic")).toBeInTheDocument();
  });
});

// ───────────────────────────────────────────────────────────────
// 4. Already-added fields disabled in the picker
// ───────────────────────────────────────────────────────────────

describe("already-added fields disabled", () => {
  it("composer disables the field option once a row is added", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");

    // Reopen composer; the Phone option should now be disabled.
    await user.click(screen.getByText("Add a field change"));
    const selects = screen.getAllByRole("combobox");
    const catSelect = selects[selects.length - 2];
    const fldSelect = selects[selects.length - 1];
    fireEvent.change(catSelect, { target: { value: "iden" } });
    // The Phone option text now reads "Phone (added)".
    expect(within(fldSelect).getByText(/^Phone \(added\)$/)).toBeInTheDocument();
    // And is marked disabled.
    expect(within(fldSelect).getByText(/^Phone \(added\)$/)).toBeDisabled();
  });

  it("picker disables the add-button for already-added fields", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ addUx: "picker" })} />);
    // Open the picker and search.
    await user.click(screen.getByText("Search registry fields to add…"));
    const searchInput = screen.getByPlaceholderText(/Search by category/);
    await user.type(searchInput, "Phone");
    // Add the first match (Phone).
    const addBtns = screen.getAllByLabelText(/Add Phone/);
    await user.click(addBtns[0]);

    // Now the same option's add button should be disabled.
    const stillThere = screen.getAllByLabelText(/Add Phone/);
    expect(stillThere[0]).toBeDisabled();
  });
});

// ───────────────────────────────────────────────────────────────
// 6. ESC closes the modal
// ───────────────────────────────────────────────────────────────

describe("ESC closes", () => {
  it("fires onClose when Escape is pressed", () => {
    let closed = 0;
    render(<ChangeRequestModal {...defaultProps({ onClose: () => { closed += 1; } })} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(closed).toBe(1);
  });

  it("does NOT fire onClose on Escape while busy", async () => {
    // Submit a slow promise; while busy the close should be blocked.
    // We simulate "busy" by making onSubmit hang; ESC during the hang
    // should be a no-op.
    const user = userEvent.setup();
    let closeCount = 0;
    let resolve;
    const hangingSubmit = () => new Promise((r) => { resolve = r; });
    render(
      <ChangeRequestModal
        {...defaultProps({
          onClose: () => { closeCount += 1; },
          onSubmit: hangingSubmit,
        })}
      />,
    );
    // Get into a valid state.
    await addRowViaComposer(user, "iden", "phone");
    const valueInputs = screen.getAllByPlaceholderText("New value");
    await user.type(valueInputs[valueInputs.length - 1], "+256 700 000 000");
    const note = screen.getByPlaceholderText(/Why this change/);
    await user.type(note, "submitting now");
    await user.click(screen.getByRole("button", { name: /Create & submit/i }));

    // Now busy. ESC should be a no-op.
    fireEvent.keyDown(window, { key: "Escape" });
    expect(closeCount).toBe(0);

    // Resolve so cleanup is clean.
    resolve({ cr_id: "x", audit_id: "y", routed_to: "CDO (parish)" });
  });
});
