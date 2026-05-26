/* US-S11-021 + US-S11-022 — "Run connector" modal unit tests.
 *
 * Covers the modal's two responsibilities:
 *   - Source picker (S11-021).
 *   - Form picker fed by /api/v1/dih/source-systems/{id}/forms/
 *     (S11-022 — the fix for the 2026-05-26 wrong-form pull).
 *
 * The modal fires `fetch` on mount and on every source change to load
 * the form list. Tests stub that fetch with vi.fn() so we can assert
 * behaviour under both happy-path (forms returned) and silent-fail
 * (network down, file:// preview) shapes.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let RunConnectorModal;
let MOCK_SOURCE_SYSTEMS;

beforeAll(async () => {
  // Stub the design-harness globals that screens-admin.jsx references
  // at top level (Icon/Chip/PageHeader/Toast — bare identifiers that
  // would ReferenceError under jsdom unless attached to globalThis).
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon       = () => null;
  globalThis.Chip       = () => null;
  globalThis.PageHeader = () => null;
  globalThis.Toast      = () => null;
  globalThis.window = globalThis;

  await import("./screens-admin.jsx");
  ({ RunConnectorModal, MOCK_SOURCE_SYSTEMS } = globalThis);
});

beforeEach(() => {
  // Default: fetch fails so the form picker stays empty and the
  // existing source-picker assertions are unaffected. Tests that
  // exercise the picker override this with vi.fn().mockResolvedValue.
  globalThis.fetch = vi.fn().mockRejectedValue(new Error("network"));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const defaultProps = (over = {}) => ({
  sources: MOCK_SOURCE_SYSTEMS,
  submitting: false,
  onClose: () => {},
  onSubmit: () => {},
  ...over,
});

const _kobo = () => MOCK_SOURCE_SYSTEMS.find(s => s.kind === "kobo");

describe("RunConnectorModal — source picker", () => {
  it("renders the Kobo source as the default selection, others disabled", () => {
    render(<RunConnectorModal {...defaultProps()} />);
    const select = screen.getAllByRole("combobox")[0];
    expect(select.value).toBe(_kobo().id);
    MOCK_SOURCE_SYSTEMS.filter(s => s.kind !== "kobo").forEach(s => {
      const opt = Array.from(select.options).find(o => o.value === s.id);
      expect(opt.textContent).toMatch(/coming soon/);
      expect(opt.disabled).toBe(true);
    });
  });

  it("submit label reflects dry-run toggle", async () => {
    const user = userEvent.setup();
    render(<RunConnectorModal {...defaultProps()} />);
    expect(screen.getByRole("button", { name: /Run pull/ })).toBeTruthy();
    await user.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: /Run dry-run/ })).toBeTruthy();
  });

  it("submit is disabled when no form is loaded (US-S11-027)", async () => {
    // Default fetch stub rejects, so formUid stays "". Without the
    // disabled-when-!formUid guard, clicking submit would post an
    // empty form_uid and hit the same upstream failure server-side.
    const onSubmit = vi.fn();
    render(<RunConnectorModal {...defaultProps({ onSubmit })} />);
    // Wait for the catch branch to settle so formsLoading clears.
    await new Promise(r => setTimeout(r, 0));
    const submit = screen.getByRole("button", { name: /Run pull/ });
    expect(submit.disabled).toBe(true);
  });

  it("Cancel calls onClose without firing onSubmit", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    render(<RunConnectorModal {...defaultProps({ onClose, onSubmit })} />);
    await user.click(screen.getByRole("button", { name: /Cancel/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables Submit + Cancel while submitting", () => {
    render(<RunConnectorModal {...defaultProps({ submitting: true })} />);
    expect(screen.getByRole("button", { name: /Running/ }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: /Cancel/ }).disabled).toBe(true);
  });

  it("backdrop click invokes onClose; form click does not", () => {
    const onClose = vi.fn();
    const { container } = render(
      <RunConnectorModal {...defaultProps({ onClose })} />,
    );
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
    onClose.mockClear();
    fireEvent.click(container.querySelector("form"));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("RunConnectorModal — form picker (US-S11-022)", () => {
  const _formsResponse = [
    { uid: "form-A", name: "Pilot v2", asset_type: "survey", deployed: true },
    { uid: "form-B", name: "v1 legacy", asset_type: "survey", deployed: true },
    { uid: "form-C", name: "Draft",    asset_type: "survey", deployed: false },
  ];

  const _stubFormsFetch = (forms) => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => forms,
    });
  };

  it("shows the form dropdown with deployed forms only, default = first when no pin", async () => {
    _stubFormsFetch(_formsResponse);
    render(<RunConnectorModal {...defaultProps()} />);
    await waitFor(() => {
      // The form-picker label appears once /forms/ resolves.
      expect(screen.getByText(/^Form/)).toBeTruthy();
    });
    // Two combos now: source + form. Form is the second.
    const combos = screen.getAllByRole("combobox");
    expect(combos.length).toBe(2);
    const formSelect = combos[1];
    expect(formSelect.value).toBe("form-A");
    // Draft form is filtered out client-side.
    const optionUids = Array.from(formSelect.options).map(o => o.value);
    expect(optionUids).toEqual(["form-A", "form-B"]);
  });

  it("defaults the dropdown to the pinned form, not forms[0] (US-S11-026)", async () => {
    // Same response shape as _formsResponse but FORM-B is pinned.
    // The modal should default to FORM-B regardless of position.
    _stubFormsFetch([
      { uid: "form-A", name: "Pilot v2", asset_type: "survey", deployed: true,
        pinned: false },
      { uid: "form-B", name: "v1 legacy", asset_type: "survey", deployed: true,
        pinned: true },
      { uid: "form-C", name: "Draft", asset_type: "survey", deployed: false,
        pinned: false },
    ]);
    render(<RunConnectorModal {...defaultProps()} />);
    await waitFor(() => screen.getByText(/^Form/));
    const combos = screen.getAllByRole("combobox");
    const formSelect = combos[1];
    expect(formSelect.value).toBe("form-B");
    // The pinned option carries the ✓ marker in its display text.
    const pinnedOption = Array.from(formSelect.options).find(o => o.value === "form-B");
    expect(pinnedOption.textContent).toMatch(/^✓/);
  });

  it("passes the chosen form_uid through onSubmit", async () => {
    _stubFormsFetch(_formsResponse);
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<RunConnectorModal {...defaultProps({ onSubmit })} />);
    await waitFor(() => screen.getByText(/^Form/));
    const combos = screen.getAllByRole("combobox");
    const formSelect = combos[1];
    await user.selectOptions(formSelect, "form-B");
    await user.click(screen.getByRole("button", { name: /Run pull/ }));
    expect(onSubmit).toHaveBeenCalledWith({
      sourceId: _kobo().id, dryRun: false, formUid: "form-B",
    });
  });

  it("hides the picker when /forms/ silently fails (file:// preview)", async () => {
    // Default beforeEach stub rejects — assert the picker stays hidden.
    render(<RunConnectorModal {...defaultProps()} />);
    // Wait one tick so the catch branch runs and clears the spinner.
    await new Promise(r => setTimeout(r, 0));
    expect(screen.queryByText(/^Form/)).toBeNull();
  });

  it("shows the inline error when /forms/ returns 4xx", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "KOBO-PILOT: token rejected" }),
    });
    render(<RunConnectorModal {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getByText(/token rejected/)).toBeTruthy();
    });
  });

  it("Retry button re-fetches /forms/ after an upstream 5xx (US-S11-027)", async () => {
    // First call: 503 (Kobo Toolbox down). Second call (Retry): 200
    // with a form. After Retry, the inline error clears and the
    // form dropdown shows the form.
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "upstream 503 on GET assets.json" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { uid: "form-back", name: "Now back", asset_type: "survey",
            deployed: true, pinned: true },
        ],
      });
    globalThis.fetch = fetchMock;
    const user = userEvent.setup();
    render(<RunConnectorModal {...defaultProps()} />);
    await waitFor(() => screen.getByText(/upstream 503/));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(screen.queryByText(/upstream 503/)).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // Form dropdown now reflects the form returned on retry.
    const combos = screen.getAllByRole("combobox");
    expect(combos[1].value).toBe("form-back");
  });
});
