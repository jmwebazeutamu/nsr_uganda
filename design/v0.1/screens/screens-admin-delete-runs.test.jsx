/* US-S11-023 — delete-runs confirm modal + run-date column.
 *
 * Covers:
 *   1. _formatRunDate handles null/garbage/valid ISO strings and
 *      renders the EAT (UTC+3) timezone the audit chain expects.
 *   2. _runApiToRow forwards started_at so the table can render it.
 *   3. DeleteRunsConfirmModal: lists the rows, requires a reason,
 *      fires onConfirm with the trimmed reason on submit; cancel
 *      fires onClose; submit-with-empty-reason is a no-op.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let DeleteRunsConfirmModal;
let _formatRunDate;
let _runApiToRow;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon       = () => null;
  globalThis.Chip       = () => null;
  globalThis.PageHeader = () => null;
  globalThis.Toast      = () => null;
  globalThis.window = globalThis;

  await import("./screens-admin.jsx");
  ({ DeleteRunsConfirmModal, _formatRunDate, _runApiToRow } = globalThis);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("_formatRunDate", () => {
  it("returns em-dash for null / undefined / empty / garbage", () => {
    expect(_formatRunDate(null)).toBe("—");
    expect(_formatRunDate(undefined)).toBe("—");
    expect(_formatRunDate("")).toBe("—");
    expect(_formatRunDate("not a date")).toBe("—");
  });

  it("renders a valid ISO timestamp in EAT", () => {
    // 2026-05-26T19:10:00Z is 22:10 EAT (UTC+3).
    const out = _formatRunDate("2026-05-26T19:10:00Z");
    expect(out).toMatch(/26 May 2026/);
    expect(out).toMatch(/22:10/);
    expect(out).toMatch(/EAT$/);
  });
});

describe("_runApiToRow", () => {
  it("forwards started_at to the row shape", () => {
    const row = _runApiToRow({
      id: "01RUN", started_at: "2026-05-26T19:10:00Z",
      finished_at: "2026-05-26T19:22:00Z", status: "succeeded",
      records_landed: 50, records_staged: 0, records_promoted: 0,
      records_quarantined: 50, records_rejected: 0,
      source_code: "KOBO-PILOT",
    });
    expect(row.started_at).toBe("2026-05-26T19:10:00Z");
    expect(row.duration).toBe("12m");
  });

  it("returns null for malformed rows so the table render survives", () => {
    expect(_runApiToRow(null)).toBeNull();
    expect(_runApiToRow({})).toBeNull();
  });
});

describe("DeleteRunsConfirmModal", () => {
  const rows = [
    { id: "01KSK5D5DWB1KQR0N63Z1QQ4ZY", connector: "KOBO-PILOT", status: "succeeded" },
    { id: "01KSK5A1AAA2KQR0N63Z1QQ4ZY", connector: "KOBO-PILOT", status: "failed" },
  ];
  const defaultProps = (over = {}) => ({
    rows, submitting: false,
    onClose: () => {}, onConfirm: () => {},
    ...over,
  });

  it("lists every targeted row and the count in the header", () => {
    render(<DeleteRunsConfirmModal {...defaultProps()} />);
    expect(screen.getByText(/Delete 2 connector runs\?/)).toBeTruthy();
    expect(screen.getByText(/01KSK5D5DWB1KQR0N63Z1QQ4ZY/)).toBeTruthy();
    expect(screen.getByText(/01KSK5A1AAA2KQR0N63Z1QQ4ZY/)).toBeTruthy();
  });

  it("singular 'run' when only one row is targeted", () => {
    render(<DeleteRunsConfirmModal {...defaultProps({ rows: [rows[0]] })} />);
    expect(screen.getByText(/Delete 1 connector run\?/)).toBeTruthy();
  });

  it("Delete button is disabled until a reason is typed", async () => {
    const user = userEvent.setup();
    render(<DeleteRunsConfirmModal {...defaultProps()} />);
    const btn = screen.getByRole("button", { name: /Delete 2/ });
    expect(btn.disabled).toBe(true);
    await user.type(screen.getByPlaceholderText(/wrong Kobo form/), "cleanup");
    expect(btn.disabled).toBe(false);
  });

  it("submit fires onConfirm with the trimmed reason", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<DeleteRunsConfirmModal {...defaultProps({ onConfirm })} />);
    await user.type(
      screen.getByPlaceholderText(/wrong Kobo form/),
      "   wrong form selected   ",
    );
    await user.click(screen.getByRole("button", { name: /Delete 2/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith("wrong form selected");
  });

  it("Cancel calls onClose without firing onConfirm", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    render(<DeleteRunsConfirmModal {...defaultProps({ onClose, onConfirm })} />);
    await user.click(screen.getByRole("button", { name: /Cancel/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons while submitting", () => {
    render(<DeleteRunsConfirmModal {...defaultProps({ submitting: true })} />);
    expect(screen.getByRole("button", { name: /Deleting/ }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: /Cancel/ }).disabled).toBe(true);
  });

  it("backdrop click closes when not submitting; locked while submitting", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <DeleteRunsConfirmModal {...defaultProps({ onClose })} />,
    );
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
    onClose.mockClear();
    rerender(<DeleteRunsConfirmModal {...defaultProps({ onClose, submitting: true })} />);
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });
});
