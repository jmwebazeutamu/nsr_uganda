/* US-S27-002 — scope-edit-modal unit tests (ADR-0016)
 *
 * Covers:
 *   1. Pre-fill from the DSA prop on open: scalar fields + checkboxes
 *      + geographic-scope chips.
 *   2. Submit calls onSubmit with the buildEditScopePayload shape.
 *   3. Draft success: onSuccess receives { cloned: false }.
 *   4. Active success: server returns a new id → onSuccess receives
 *      { cloned: true }.
 *   5. 400 error: ScopeEditError detail rendered in the banner; modal
 *      stays open; busy clears.
 *   6. Busy state disables submit + Cancel; ESC is ignored while busy.
 *   7. Blocked status (pending_signature) renders the banner + disables
 *      every input + the submit button.
 *   8. Geographic chips: × removes; payload omits the removed id.
 *   9. Pure helpers (buildEditScopePayload, formatScopeError).
 *
 * Component-under-test uses React, Icon, Chip, Modal as globals
 * (Babel-standalone in the browser harness). vitest.setup.js binds
 * them on globalThis before the test file evaluates; the dynamic
 * import below runs the modal's module body which attaches helpers
 * to window.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let ScopeEditModal;
let buildEditScopePayload;
let formatScopeError;
let ENTITY_KEYS;
let FIELD_GROUP_KEYS;

beforeAll(async () => {
  await import("./scope-edit-modal.jsx");
  ({
    ScopeEditModal,
    buildEditScopePayload,
    formatScopeError,
    ScopeEditModal_ENTITY_KEYS: ENTITY_KEYS,
    ScopeEditModal_FIELD_GROUP_KEYS: FIELD_GROUP_KEYS,
  } = globalThis);
});

afterEach(() => {
  cleanup();
});

// ───────────────────────────────────────────────────────────────
// Fixtures
// ───────────────────────────────────────────────────────────────

const draftDsa = (over = {}) => ({
  id: "01HXY7K3B2N9PVQE4M6FZRWS18",
  reference: "DSA-OPM-2026-001",
  version: 1,
  status: "draft",
  entities_scope: { household: true, member: true },
  field_scope: { Identifiers: true, PMT: true },
  monthly_row_budget: 250000,
  sensitive_data_handling: "none",
  retention_days: 180,
  classification: "Internal-MDA",
  dpia_document_ref: "DPIA-OPM-2026-001",
  breach_sla_hours: 72,
  geographic_scope: [
    "01HZA1111111111111111111GU1",
    "01HZA2222222222222222222GU2",
  ],
  ...over,
});

const activeDsa = (over = {}) => draftDsa({
  id: "01HXY7K3B2N9PVQE4M6FZRWS18",
  status: "active",
  ...over,
});

const defaultProps = (over = {}) => ({
  open: true,
  onClose: () => {},
  dsa: draftDsa(),
  me: { username: "florence" },
  onSubmit: vi.fn(async (id, payload) => ({
    id,
    reference: "DSA-OPM-2026-001",
    version: 1,
    status: "draft",
    ...payload,
  })),
  onSuccess: vi.fn(),
  ...over,
});

// ───────────────────────────────────────────────────────────────
// 1. Pre-fill from props
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal pre-fill", () => {
  it("populates scalar fields, sensitivity, checkboxes, and geo chips from the DSA on open", () => {
    render(<ScopeEditModal {...defaultProps()}/>);

    // Title shows the reference + version
    expect(screen.getByRole("dialog"))
      .toHaveAttribute("aria-label", "Edit DSA scope — DSA-OPM-2026-001 v1");

    // Scalar inputs (by placeholder so we don't fight label DOM)
    const monthly = screen.getByPlaceholderText("e.g. 250000");
    const retention = screen.getByPlaceholderText("e.g. 180");
    const breach = screen.getByPlaceholderText("e.g. 72");
    const classification = screen.getByPlaceholderText("e.g. Internal-MDA");
    const dpia = screen.getByPlaceholderText("DPIA-OPM-2026-001");
    expect(monthly).toHaveValue(250000);
    expect(retention).toHaveValue(180);
    expect(breach).toHaveValue(72);
    expect(classification).toHaveValue("Internal-MDA");
    expect(dpia).toHaveValue("DPIA-OPM-2026-001");

    // Entity checkboxes — household + member checked, referral + grievance unchecked
    const checkboxes = screen.getAllByRole("checkbox");
    const byLabel = Object.fromEntries(
      checkboxes.map(cb => [cb.closest("label")?.textContent?.trim(), cb]),
    );
    expect(byLabel["Household"]).toBeChecked();
    expect(byLabel["Member"]).toBeChecked();
    expect(byLabel["Referral"]).not.toBeChecked();
    expect(byLabel["Grievance"]).not.toBeChecked();

    // Field-group checkboxes — Identifiers + PMT checked
    expect(byLabel["Identifiers"]).toBeChecked();
    expect(byLabel["PMT inputs"]).toBeChecked();
    expect(byLabel["Health"]).not.toBeChecked();

    // Geographic chips
    const chips = screen.getByTestId("geo-chips");
    expect(chips.querySelectorAll("span[role], span:not([data-modal-title])").length)
      .toBeGreaterThanOrEqual(2);
    expect(chips.textContent).toContain("01HZA111…");
    expect(chips.textContent).toContain("01HZA222…");
  });

  it("renders an empty-state when geographic scope is empty", () => {
    render(<ScopeEditModal {...defaultProps({ dsa: draftDsa({ geographic_scope: [] }) })}/>);
    expect(screen.queryByTestId("geo-chips")).toBeNull();
    expect(screen.getByText(/No geographic units pinned/i)).toBeInTheDocument();
  });
});


// ───────────────────────────────────────────────────────────────
// 2. + 3. Submit, draft path (in-place)
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal submit — draft path", () => {
  it("posts the buildEditScopePayload shape and calls onSuccess({ cloned: false })", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async (id, payload) => ({
      id,                  // same id → in-place update
      reference: "DSA-OPM-2026-001",
      version: 1,
      status: "draft",
      ...payload,
    }));
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    render(<ScopeEditModal {...defaultProps({
      dsa: draftDsa(),
      onSubmit,
      onSuccess,
      onClose,
    })}/>);

    await user.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const [calledId, calledPayload] = onSubmit.mock.calls[0];
    expect(calledId).toBe("01HXY7K3B2N9PVQE4M6FZRWS18");
    expect(calledPayload).toMatchObject({
      entities_scope: { household: true, member: true },
      field_scope: { Identifiers: true, PMT: true },
      monthly_row_budget: 250000,
      sensitive_data_handling: "none",
      retention_days: 180,
      classification: "Internal-MDA",
      dpia_document_ref: "DPIA-OPM-2026-001",
      breach_sla_hours: 72,
      geographic_scope_ids: [
        "01HZA1111111111111111111GU1",
        "01HZA2222222222222222222GU2",
      ],
    });

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [resultArg, metaArg] = onSuccess.mock.calls[0];
    expect(resultArg.id).toBe("01HXY7K3B2N9PVQE4M6FZRWS18");
    expect(metaArg).toEqual({ cloned: false });
    expect(onClose).toHaveBeenCalled();
  });

  it("submit label says 'Save changes' for a draft DSA", () => {
    render(<ScopeEditModal {...defaultProps({ dsa: draftDsa() })}/>);
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save & clone/i })).toBeNull();
  });
});


// ───────────────────────────────────────────────────────────────
// 4. Active path → server clones to v+1, modal reports cloned=true
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal submit — active path", () => {
  it("treats a new id in the response as a clone and reports { cloned: true }", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => ({
      id: "01CLONEDV2NEWNEWNEWNEWNEW",
      reference: "DSA-OPM-2026-001",
      version: 2,
      status: "draft",
    }));
    const onSuccess = vi.fn();
    render(<ScopeEditModal {...defaultProps({
      dsa: activeDsa(),
      onSubmit,
      onSuccess,
    })}/>);

    // Active DSA → submit label is 'Save & clone to v+1'
    const submitBtn = screen.getByRole("button", { name: /Save & clone to v\+1/i });
    expect(submitBtn).toBeInTheDocument();
    await user.click(submitBtn);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [resultArg, metaArg] = onSuccess.mock.calls[0];
    expect(resultArg.id).toBe("01CLONEDV2NEWNEWNEWNEWNEW");
    expect(resultArg.version).toBe(2);
    expect(metaArg).toEqual({ cloned: true });
  });

  it("shows a footer hint explaining active → v+1 cloning", () => {
    render(<ScopeEditModal {...defaultProps({ dsa: activeDsa() })}/>);
    expect(screen.getByText(/active/i)).toBeInTheDocument();
    expect(screen.getByText(/draft for re-sign/i)).toBeInTheDocument();
  });
});


// ───────────────────────────────────────────────────────────────
// 5. 400 errors surface in the banner
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal error handling", () => {
  it("renders the ScopeEditError detail from a 400 response and keeps the modal open", async () => {
    const user = userEvent.setup();
    const err = new Error("HTTP 400");
    err.status = 400;
    err.body = { detail: "DSA cannot be scope-edited in status 'expired'." };
    const onSubmit = vi.fn(async () => { throw err; });
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    render(<ScopeEditModal {...defaultProps({ onSubmit, onSuccess, onClose })}/>);

    await user.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => {
      expect(screen.getByTestId("scope-edit-error"))
        .toHaveTextContent("DSA cannot be scope-edited in status 'expired'.");
    });
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // Submit re-enabled after the failure clears busy
    expect(screen.getByRole("button", { name: /Save changes/i })).not.toBeDisabled();
  });
});


// ───────────────────────────────────────────────────────────────
// 6. Busy state — Cancel disabled, ESC ignored
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal busy state", () => {
  it("disables Cancel + Save while a submit is in-flight, and ignores Escape", async () => {
    const user = userEvent.setup();
    let resolveSubmit;
    const onSubmit = vi.fn(() => new Promise((res) => { resolveSubmit = res; }));
    const onClose = vi.fn();
    render(<ScopeEditModal {...defaultProps({ onSubmit, onClose })}/>);

    await user.click(screen.getByRole("button", { name: /Save changes/i }));
    // While busy, both buttons are disabled
    expect(screen.getByRole("button", { name: /Saving…/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Cancel$/i })).toBeDisabled();

    // ESC during busy → onClose NOT called
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    // Resolve the submit and let the success branch run
    resolveSubmit({ id: "01HXY7K3B2N9PVQE4M6FZRWS18", reference: "X", version: 1 });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});


// ───────────────────────────────────────────────────────────────
// 7. Blocked status banner + locked inputs
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal blocked-status guard", () => {
  it("renders a refusal banner and disables every input when status is unhandled", () => {
    render(<ScopeEditModal {...defaultProps({
      dsa: draftDsa({ status: "pending_signature" }),
    })}/>);

    expect(screen.getByText(/cannot be scope-edited/i)).toBeInTheDocument();
    // Submit + every checkbox + every text input is disabled
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled();
    for (const cb of screen.getAllByRole("checkbox")) {
      expect(cb).toBeDisabled();
    }
    expect(screen.getByPlaceholderText("e.g. 250000")).toBeDisabled();
  });
});


// ───────────────────────────────────────────────────────────────
// 8. Geographic chip removal
// ───────────────────────────────────────────────────────────────

describe("ScopeEditModal geographic chip removal", () => {
  it("removing a chip omits that id from the submit payload", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async (id, payload) => ({
      id, reference: "X", version: 1, ...payload,
    }));
    render(<ScopeEditModal {...defaultProps({ onSubmit })}/>);

    // First geographic chip × button
    const removeBtns = screen.getAllByRole("button", { name: /Remove geographic unit/i });
    expect(removeBtns).toHaveLength(2);
    await user.click(removeBtns[0]);

    await user.click(screen.getByRole("button", { name: /Save changes/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const [, payload] = onSubmit.mock.calls[0];
    expect(payload.geographic_scope_ids).toEqual([
      "01HZA2222222222222222222GU2",
    ]);
  });
});


// ───────────────────────────────────────────────────────────────
// 9. Pure helpers
// ───────────────────────────────────────────────────────────────

describe("buildEditScopePayload", () => {
  it("coerces string number fields to integers", () => {
    const form = {
      entities_scope: { household: true },
      field_scope: { PMT: true },
      monthly_row_budget: "150000",
      sensitive_data_handling: "specific",
      retention_days: "365",
      classification: "Public",
      dpia_document_ref: "",
      breach_sla_hours: "24",
      geographic_scope_ids: ["a", "b"],
    };
    expect(buildEditScopePayload(form)).toEqual({
      entities_scope: { household: true },
      field_scope: { PMT: true },
      monthly_row_budget: 150000,
      sensitive_data_handling: "specific",
      retention_days: 365,
      classification: "Public",
      dpia_document_ref: "",
      breach_sla_hours: 24,
      geographic_scope_ids: ["a", "b"],
    });
  });

  it("treats blank numeric strings as 0", () => {
    const out = buildEditScopePayload({
      entities_scope: {}, field_scope: {},
      monthly_row_budget: "", retention_days: "", breach_sla_hours: "",
      sensitive_data_handling: "none",
      classification: "", dpia_document_ref: "",
      geographic_scope_ids: [],
    });
    expect(out.monthly_row_budget).toBe(0);
    expect(out.retention_days).toBe(0);
    expect(out.breach_sla_hours).toBe(0);
  });

  it("preserves unknown keys in entities_scope and field_scope (round-trip)", () => {
    const out = buildEditScopePayload({
      entities_scope: { household: true, custom_entity: true },
      field_scope: { PMT: true, UNDOCUMENTED_GROUP: false },
      monthly_row_budget: "0", retention_days: "0", breach_sla_hours: "0",
      sensitive_data_handling: "none",
      classification: "", dpia_document_ref: "",
      geographic_scope_ids: [],
    });
    expect(out.entities_scope).toEqual({ household: true, custom_entity: true });
    expect(out.field_scope).toEqual({ PMT: true, UNDOCUMENTED_GROUP: false });
  });
});

describe("formatScopeError", () => {
  it("returns body.detail when the server set it (ScopeEditError shape)", () => {
    expect(formatScopeError({ body: { detail: "Active DSAs cannot be patched in place." } }))
      .toBe("Active DSAs cannot be patched in place.");
  });
  it("falls back to err.message when body has no detail", () => {
    expect(formatScopeError({ message: "Network unreachable" }))
      .toBe("Network unreachable");
  });
  it("returns 'Unknown error.' for null/undefined", () => {
    expect(formatScopeError(null)).toBe("Unknown error.");
  });
});


// ───────────────────────────────────────────────────────────────
// Helper-catalogue sanity (so tests don't pin stale labels)
// ───────────────────────────────────────────────────────────────

describe("catalogue helpers", () => {
  it("ENTITY_KEYS covers the four canonical entity flags", () => {
    expect(ENTITY_KEYS.map(e => e.key).sort()).toEqual(
      ["grievance", "household", "member", "referral"],
    );
  });
  it("FIELD_GROUP_KEYS includes Identifiers + PMT (cross-referenced by AC-DPO-VOL)", () => {
    const keys = FIELD_GROUP_KEYS.map(f => f.key);
    expect(keys).toContain("Identifiers");
    expect(keys).toContain("PMT");
  });
});
