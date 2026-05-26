/* US-S11-021 — "Run connector" modal unit tests.
 *
 * Covers:
 *   1. Modal renders the Kobo source as selectable and the rest as
 *      "(coming soon)" disabled options.
 *   2. Default state: dry-run unchecked; Submit reads "Run pull".
 *   3. Toggling dry-run flips the Submit label to "Run dry-run".
 *   4. Submit fires onSubmit with the picked source id + dry_run flag.
 *   5. Cancel button calls onClose.
 *   6. While submitting, Submit and Cancel are disabled.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

afterEach(() => {
  cleanup();
});

const defaultProps = (over = {}) => ({
  sources: MOCK_SOURCE_SYSTEMS,
  submitting: false,
  onClose: () => {},
  onSubmit: () => {},
  ...over,
});

describe("RunConnectorModal", () => {
  it("renders the Kobo source as the default selection, others disabled", () => {
    render(<RunConnectorModal {...defaultProps()} />);
    const select = screen.getByRole("combobox");
    // Default value is the first active Kobo source.
    const koboOption = MOCK_SOURCE_SYSTEMS.find(s => s.kind === "kobo");
    expect(select.value).toBe(koboOption.id);
    // Non-Kobo options carry the "(coming soon)" suffix and are
    // marked disabled so the operator can't pick them yet.
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

  it("submit fires onSubmit with sourceId + dryRun", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<RunConnectorModal {...defaultProps({ onSubmit })} />);
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Run dry-run/ }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const koboOption = MOCK_SOURCE_SYSTEMS.find(s => s.kind === "kobo");
    expect(onSubmit).toHaveBeenCalledWith({
      sourceId: koboOption.id, dryRun: true,
    });
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
    const submit = screen.getByRole("button", { name: /Running/ });
    const cancel = screen.getByRole("button", { name: /Cancel/ });
    expect(submit.disabled).toBe(true);
    expect(cancel.disabled).toBe(true);
  });

  it("backdrop click invokes onClose; form click does not", () => {
    const onClose = vi.fn();
    const { container } = render(
      <RunConnectorModal {...defaultProps({ onClose })} />,
    );
    // Backdrop is the outermost div with role=dialog.
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
    onClose.mockClear();
    // Clicking the form itself should NOT close (stopPropagation).
    fireEvent.click(container.querySelector("form"));
    expect(onClose).not.toHaveBeenCalled();
  });
});
