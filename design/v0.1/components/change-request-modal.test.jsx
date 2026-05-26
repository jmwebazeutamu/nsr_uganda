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

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

// Advance the wizard to the Fields step (step 2). Idempotent —
// silently no-ops if we're already past step 1.
const goToFieldsStep = async (user) => {
  const next = screen.queryByRole("button", { name: /Next →/i });
  if (next && !next.disabled) await user.click(next);
};

// Click Next repeatedly until the Submit button is reachable
// (i.e. we're on the Review step). Used by tests that need to
// exercise the final submission gate.
const advanceToReview = async (user) => {
  for (let i = 0; i < 6; i++) {
    const next = screen.queryByRole("button", { name: /Next →/i });
    if (!next || next.disabled) break;
    await user.click(next);
  }
};

// Click Back repeatedly until step 1 is visible — used by tests
// that need to access controls only rendered on step 1 after
// having navigated forward.
const goBackTo1 = async (user) => {
  for (let i = 0; i < 6; i++) {
    const back = screen.queryByRole("button", { name: /^← Back/i });
    if (!back || back.disabled) break;
    await user.click(back);
  }
};

// Seed a valid step-2 (one phone row + value) and advance to the
// Evidence step so tests that target file upload UI can find it.
const goToEvidenceStep = async (user) => {
  await addRowViaComposer(user, "iden", "phone");
  const phoneInput = screen.getAllByPlaceholderText("New value")[0];
  fireEvent.change(phoneInput, { target: { value: "+256 700 000 000" } });
  await user.click(screen.getByRole("button", { name: /Next →/i })); // → step 3
};

// Append a row via the composer add-UX. Uses category + field
// VALUES (the catalog keys) so it's robust against label wording.
// Auto-navigates to the Fields step before opening the composer
// so test bodies don't have to scaffold the wizard.
const addRowViaComposer = async (user, categoryKey, fieldKey) => {
  await goToFieldsStep(user);
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
  it("Next is disabled on step 2 with no rows", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    // Step 1 → Next to step 2; with zero rows step 2's Next stays off.
    await goToFieldsStep(user);
    const next = screen.getByRole("button", { name: /Next →/i });
    expect(next).toBeDisabled();
  });

  it("submit stays disabled at review with a short note", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    const valueInputs = screen.getAllByPlaceholderText("New value");
    await user.type(valueInputs[valueInputs.length - 1], "+256 700 000 000");
    // step 2 → 3
    await user.click(screen.getByRole("button", { name: /Next →/i }));
    const note = screen.getByPlaceholderText(/Why this change/);
    await user.type(note, "hi");
    // step 3 → 4
    await user.click(screen.getByRole("button", { name: /Next →/i }));
    expect(screen.getByRole("button", { name: /Create & submit/i })).toBeDisabled();
  });

  it("submit enables exactly at the boundary (1 row with value + note ≥ 6 chars)", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    const valueInputs = screen.getAllByPlaceholderText("New value");
    await user.type(valueInputs[valueInputs.length - 1], "+256 700 000 000");
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → step 3
    const note = screen.getByPlaceholderText(/Why this change/);
    await user.type(note, "valid"); // 5 chars
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → step 4
    expect(screen.getByRole("button", { name: /Create & submit/i })).toBeDisabled();
    // Back to step 3, append a 6th char.
    await user.click(screen.getByRole("button", { name: /^← Back/i }));
    await user.type(screen.getByPlaceholderText(/Why this change/), "X");
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → step 4
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
    // member_dob is now a member-scope field, so entity must flip
    // and a member must be selected before the row can be added.
    const user = userEvent.setup();
    const members = [{ id: "01HMEM0000000000000000ONE0", name: "T", line: 1 }];
    render(
      <ChangeRequestModal
        {...defaultProps({
          members,
          memberValues: { "01HMEM0000000000000000ONE0": { "rost.member_dob": "2018-04-08" } },
        })}
      />,
    );
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "member" } });
    fireEvent.change(screen.getByTestId("member-picker-select"), {
      target: { value: "01HMEM0000000000000000ONE0" },
    });
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
// 2c. Member picker (slice 2)
// ───────────────────────────────────────────────────────────────

const SAMPLE_MEMBERS = [
  { id: "01HMEM0000000000000000HEAD", name: "Lokol Naume",  line: 1, relationship: "Head",     dob: "1980-04-15", sex: "Female" },
  { id: "01HMEM0000000000000000SPOU", name: "Lokol Peter",  line: 2, relationship: "Spouse",   dob: "1978-09-22", sex: "Male" },
  { id: "01HMEM0000000000000000CHLD", name: "Lokol Sarah",  line: 3, relationship: "Daughter", dob: "2014-02-08", sex: "Female" },
];

describe("member picker", () => {
  it("hides the picker strip when entity=household", () => {
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS })} />);
    expect(screen.queryByTestId("member-picker-strip")).not.toBeInTheDocument();
  });

  it("shows the picker strip when entity is switched to member", () => {
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS })} />);
    const entitySelect = screen.getByLabelText("Entity");
    fireEvent.change(entitySelect, { target: { value: "member" } });
    expect(screen.getByTestId("member-picker-strip")).toBeInTheDocument();
    expect(screen.getByTestId("member-picker-select")).toBeInTheDocument();
  });

  it("renders the member info card after selecting", () => {
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS })} />);
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "member" } });
    fireEvent.change(screen.getByTestId("member-picker-select"), {
      target: { value: SAMPLE_MEMBERS[2].id },
    });
    const card = screen.getByTestId("member-info-card");
    expect(card).toHaveTextContent("Lokol Sarah");
    expect(card).toHaveTextContent("Daughter");
    expect(card).toHaveTextContent("2014-02-08");
  });

  it("filters the composer to member-scope categories when entity=member", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS })} />);
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "member" } });
    fireEvent.change(screen.getByTestId("member-picker-select"), {
      target: { value: SAMPLE_MEMBERS[1].id },
    });
    await goToFieldsStep(user);
    await user.click(screen.getByText("Add a field change"));
    const selects = screen.getAllByRole("combobox");
    // Last two selects = composer cat + field.
    const catSelect = selects[selects.length - 2];
    // Household-only categories must NOT be options (loc, hous, food).
    const optionValues = Array.from(catSelect.options).map(o => o.value);
    expect(optionValues).not.toContain("loc");
    expect(optionValues).not.toContain("hous");
    expect(optionValues).not.toContain("food");
    // Member-scope categories present.
    expect(optionValues).toContain("hd");
    expect(optionValues).toContain("ed");
    expect(optionValues).toContain("emp");
  });

  it("Next on step 1 stays disabled until a member is selected", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS })} />);
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "member" } });
    expect(screen.getByRole("button", { name: /Next →/i })).toBeDisabled();
    fireEvent.change(screen.getByTestId("member-picker-select"), {
      target: { value: SAMPLE_MEMBERS[1].id },
    });
    expect(screen.getByRole("button", { name: /Next →/i })).not.toBeDisabled();
  });

  it("payload includes member_id when entity=member", async () => {
    const onSubmit = vi.fn(async () => ({
      cr_id: "01CR", audit_id: "A-1", routed_to: "CDO (parish)",
    }));
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS, onSubmit })} />);
    // Step 1: target = member, pick a member.
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "member" } });
    fireEvent.change(screen.getByTestId("member-picker-select"), {
      target: { value: SAMPLE_MEMBERS[2].id },
    });
    // Step 2: add a member-scope row.
    await addRowViaComposer(user, "hd", "chronic");
    const valueSelect = screen.getAllByRole("combobox").find(
      el => Array.from(el.options).some(o => o.value === "yes"),
    );
    fireEvent.change(valueSelect, { target: { value: "yes" } });
    // Step 3: note.
    await user.click(screen.getByRole("button", { name: /Next →/i }));
    fireEvent.change(screen.getByPlaceholderText(/Why this change/i), {
      target: { value: "Diagnosed during clinic visit last week." },
    });
    // Step 4: review + submit.
    await user.click(screen.getByRole("button", { name: /Next →/i }));
    await user.click(screen.getByRole("button", { name: /Create & submit/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.entity).toBe("member");
    expect(payload.member_id).toBe(SAMPLE_MEMBERS[2].id);
  });

  it("payload omits member_id when entity=household", async () => {
    const onSubmit = vi.fn(async () => ({
      cr_id: "01CR", audit_id: "A-1", routed_to: "CDO (parish)",
    }));
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ members: SAMPLE_MEMBERS, onSubmit })} />);
    await addRowViaComposer(user, "iden", "phone");
    const phoneInput = screen.getAllByPlaceholderText("New value")[0];
    fireEvent.change(phoneInput, { target: { value: "+256 700 111 222" } });
    await user.click(screen.getByRole("button", { name: /Next →/i }));
    fireEvent.change(screen.getByPlaceholderText(/Why this change/i), {
      target: { value: "Phone updated per field visit." },
    });
    await user.click(screen.getByRole("button", { name: /Next →/i }));
    await user.click(screen.getByRole("button", { name: /Create & submit/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].member_id).toBeUndefined();
  });

  it("uses per-member currentValues when a member is selected", async () => {
    const user = userEvent.setup();
    render(
      <ChangeRequestModal
        {...defaultProps({
          members: SAMPLE_MEMBERS,
          memberValues: {
            [SAMPLE_MEMBERS[2].id]: { "hd.chronic": "no" },
          },
        })}
      />,
    );
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "member" } });
    fireEvent.change(screen.getByTestId("member-picker-select"), {
      target: { value: SAMPLE_MEMBERS[2].id },
    });
    await addRowViaComposer(user, "hd", "chronic");
    const chip = screen.getByTestId("current-hd-chronic");
    expect(chip).toHaveTextContent("current: no");
  });
});

// ───────────────────────────────────────────────────────────────
// 2d. Supporting documents (slice 3)
// ───────────────────────────────────────────────────────────────

const fileOf = (name, type, sizeBytes) => {
  // jsdom doesn't preserve File.size from byte arrays the way browsers
  // do, but the modal reads file.size before encoding so the bytes
  // must be real here.
  const bytes = new Uint8Array(sizeBytes);
  return new File([bytes], name, { type });
};

describe("supporting documents", () => {
  it("renders the documents strip and accepts a PDF upload", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await goToEvidenceStep(user);
    expect(screen.getByTestId("documents-strip")).toBeInTheDocument();
    const input = screen.getByTestId("documents-input");
    const f = fileOf("clinic.pdf", "application/pdf", 1024);
    await act(async () => {
      fireEvent.change(input, { target: { files: [f] } });
      // Flush the readAsBase64 promise chain.
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(screen.getByTestId("documents-list")).toBeInTheDocument();
    expect(screen.getByTestId("document-row-0")).toHaveTextContent("clinic.pdf");
  });

  it("rejects unsupported MIME types client-side", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await goToEvidenceStep(user);
    const input = screen.getByTestId("documents-input");
    const f = fileOf("evil.exe", "application/x-msdownload", 100);
    await act(async () => {
      fireEvent.change(input, { target: { files: [f] } });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(screen.queryByTestId("documents-list")).not.toBeInTheDocument();
    expect(screen.getByText(/Unsupported type/i)).toBeInTheDocument();
  });

  it("rejects files over the 5 MB cap", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await goToEvidenceStep(user);
    const input = screen.getByTestId("documents-input");
    const f = fileOf("huge.pdf", "application/pdf", 5 * 1024 * 1024 + 1);
    await act(async () => {
      fireEvent.change(input, { target: { files: [f] } });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(screen.queryByTestId("documents-list")).not.toBeInTheDocument();
    expect(screen.getByText(/over the 5 MB per-file limit/i)).toBeInTheDocument();
  });

  it("rejects a fourth document", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await goToEvidenceStep(user);
    const input = screen.getByTestId("documents-input");
    fireEvent.change(input, { target: { files: [
      fileOf("a.pdf", "application/pdf", 100),
      fileOf("b.pdf", "application/pdf", 100),
      fileOf("c.pdf", "application/pdf", 100),
    ] } });
    await waitFor(() =>
      expect(screen.getByTestId("document-row-2")).toBeInTheDocument(),
    );
    fireEvent.change(input, { target: { files: [fileOf("d.pdf", "application/pdf", 100)] } });
    await waitFor(() =>
      expect(screen.getByText(/At most 3 documents/i)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("document-row-3")).not.toBeInTheDocument();
  });

  it("removes a document via the row's remove button", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await goToEvidenceStep(user);
    const input = screen.getByTestId("documents-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [fileOf("x.pdf", "application/pdf", 100)] } });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(screen.getByTestId("document-row-0")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Remove x.pdf"));
    expect(screen.queryByTestId("document-row-0")).not.toBeInTheDocument();
  });

  it("payload includes documents[] when submitted", async () => {
    const onSubmit = vi.fn(async () => ({
      cr_id: "01CR", audit_id: "A-1", routed_to: "CDO (parish)",
    }));
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ onSubmit })} />);
    await goToEvidenceStep(user);
    const input = screen.getByTestId("documents-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [fileOf("receipt.pdf", "application/pdf", 256)] } });
      await new Promise((r) => setTimeout(r, 0));
    });
    fireEvent.change(screen.getByPlaceholderText(/Why this change/i), {
      target: { value: "Phone updated per field visit." },
    });
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → step 4
    await user.click(screen.getByRole("button", { name: /Create & submit/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.documents).toBeDefined();
    expect(payload.documents).toHaveLength(1);
    expect(payload.documents[0].filename).toBe("receipt.pdf");
    expect(payload.documents[0].content_type).toBe("application/pdf");
    expect(typeof payload.documents[0].data_base64).toBe("string");
    expect(payload.documents[0].data_base64.length).toBeGreaterThan(0);
  });

  it("payload omits documents when none uploaded", async () => {
    const onSubmit = vi.fn(async () => ({
      cr_id: "01CR", audit_id: "A-1", routed_to: "CDO (parish)",
    }));
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps({ onSubmit })} />);
    await goToEvidenceStep(user);
    fireEvent.change(screen.getByPlaceholderText(/Why this change/i), {
      target: { value: "Phone updated per field visit." },
    });
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → step 4
    await user.click(screen.getByRole("button", { name: /Create & submit/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].documents).toBeUndefined();
  });
});

// ───────────────────────────────────────────────────────────────
// 3. PMT chip + Force-PMT toggle
// ───────────────────────────────────────────────────────────────

describe("PMT chip + Force PMT", () => {
  it("starts at cosmetic with Force-PMT enabled and unchecked", () => {
    render(<ChangeRequestModal {...defaultProps()} />);
    // The chip lives in two places on step 1 (target strip + sticky
    // summary) — target the sticky one explicitly.
    expect(screen.getByTestId("summary-pmt-chip")).toHaveTextContent("cosmetic");
    const force = screen.getByLabelText(/Force PMT/i);
    expect(force).not.toBeChecked();
    expect(force).not.toBeDisabled();
  });

  it("Force-PMT toggled alone flips the chip to pmt_relevant", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await user.click(screen.getByLabelText(/Force PMT/i));
    expect(screen.getByTestId("summary-pmt-chip")).toHaveTextContent("pmt_relevant");
  });

  it("Adding a PMT field auto-derives pmt_relevant AND disables Force-PMT", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "hous", "roof");
    // Chip lives in the sticky summary, visible from every step.
    expect(screen.getByTestId("summary-pmt-chip")).toHaveTextContent("pmt_relevant");
    // Force-PMT only renders on step 1 — navigate back.
    await goBackTo1(user);
    const force = screen.getByLabelText(/Force PMT/i);
    expect(force).toBeChecked();
    expect(force).toBeDisabled();
  });

  it("Adding a non-PMT field leaves the chip as cosmetic", async () => {
    const user = userEvent.setup();
    render(<ChangeRequestModal {...defaultProps()} />);
    await addRowViaComposer(user, "iden", "phone");
    expect(screen.getByTestId("summary-pmt-chip")).toHaveTextContent("cosmetic");
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
    await goToFieldsStep(user);
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
    // Get into a valid state and step through the wizard to submit.
    await addRowViaComposer(user, "iden", "phone");
    const valueInputs = screen.getAllByPlaceholderText("New value");
    await user.type(valueInputs[valueInputs.length - 1], "+256 700 000 000");
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → 3
    const note = screen.getByPlaceholderText(/Why this change/);
    await user.type(note, "submitting now");
    await user.click(screen.getByRole("button", { name: /Next →/i })); // → 4
    await user.click(screen.getByRole("button", { name: /Create & submit/i }));

    // Now busy. ESC should be a no-op.
    fireEvent.keyDown(window, { key: "Escape" });
    expect(closeCount).toBe(0);

    // Resolve so cleanup is clean.
    resolve({ cr_id: "x", audit_id: "y", routed_to: "CDO (parish)" });
  });
});
