/* Render test for ConsentStatusCard — the per-purpose consent detail card
 * shown on the Household detail Consent tab. Mocks the matrix endpoint and
 * asserts the card renders a row per purpose with the right state labels. */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const MATRIX = {
  member_id: "M-HEAD",
  purposes: [
    { purpose_code: "REGISTRATION", name: "Registration", lawful_basis: "CONSENT", withdrawable: true, state: "GRANTED", state_label: "Granted", captured_at: "2026-05-30T10:00:00Z" },
    { purpose_code: "ELIGIBILITY", name: "Eligibility assessment", lawful_basis: "CONSENT", withdrawable: true, state: "WITHDRAWN", state_label: "Withdrawn", captured_at: "2026-05-31T09:00:00Z" },
    { purpose_code: "RESEARCH", name: "Research", lawful_basis: "CONSENT", withdrawable: true, state: null, state_label: null, captured_at: null },
    { purpose_code: "STATISTICS", name: "National statistics", lawful_basis: "STATISTICAL_EXEMPTION", withdrawable: false, state: "GRANTED", state_label: "Granted", captured_at: "2026-05-30T10:00:00Z" },
  ],
};

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => globalThis.React.createElement("span", null, children);
  globalThis.window = globalThis;
  await import("./consent-shared.jsx");        // real ConsentStateChip + vocab
  await import("./consent-badge-cluster.jsx"); // ConsentStatusCard under test
});

beforeEach(() => {
  globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(MATRIX) }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ConsentStatusCard", () => {
  it("renders a row per purpose with the right state", async () => {
    render(globalThis.React.createElement(globalThis.ConsentStatusCard, { memberId: "M-HEAD" }));
    await waitFor(() => expect(screen.getByText("Registration")).toBeTruthy());
    expect(screen.getByText("Eligibility assessment")).toBeTruthy();
    // Withdrawn + Granted state labels surface (via ConsentStateChip).
    expect(screen.getAllByText(/Granted/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Withdrawn/)).toBeTruthy();
    // Un-captured purpose shows "Not captured".
    expect(screen.getByText(/Not captured/)).toBeTruthy();
    // Lawful-basis label maps the enum.
    expect(screen.getByText("Statistical exemption")).toBeTruthy();
  });

  it("shows an empty-state note when the endpoint errors (module dark)", async () => {
    // Fresh member id so the 60s matrix cache from the prior test doesn't hit.
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 503 }));
    render(globalThis.React.createElement(globalThis.ConsentStatusCard, { memberId: "M-ERR" }));
    await waitFor(() => expect(screen.getByText(/No per-purpose consent on record/i)).toBeTruthy());
  });
});
