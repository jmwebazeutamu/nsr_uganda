/* Live-mode test for CitizenConsentScreen — when mounted with real household
 * members + window.nsrApi present, it reads each member's consent matrix and
 * withdraws against the live API (US-CONSENT-05/06). */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const MATRIX = {
  member_id: "M-HEAD",
  purposes: [
    { purpose_code: "REGISTRATION", name: "Registration", lawful_basis: "CONSENT", withdrawable: true, state: "GRANTED", state_label: "Granted", captured_at: "2026-05-30T10:00:00Z" },
    { purpose_code: "RESEARCH", name: "Research", lawful_basis: "CONSENT", withdrawable: true, state: null, state_label: null, captured_at: null },
  ],
};

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  const Pass = ({ children }) => globalThis.React.createElement(globalThis.React.Fragment, null, children);
  for (const name of [
    "Icon", "Chip", "KPI", "Field", "Toast", "PageHeader",
    "ActionBar", "Toggle", "ConsentSectionLabel", "StoryTag",
  ]) { globalThis[name] = Pass; }
  // Modal renders both children AND its footer prop (where the submit button
  // lives) so the withdrawal / capture flows are reachable in the test.
  globalThis.Modal = ({ children, footer }) =>
    globalThis.React.createElement(globalThis.React.Fragment, null, children, footer);
  // AuditDrawer renders its events (a prop, not children) when open.
  globalThis.AuditDrawer = ({ open, events }) => (open
    ? globalThis.React.createElement("div", null,
        (events || []).map((e, i) => globalThis.React.createElement(
          "div", { key: i }, `${e.who} ${e.action} ${e.detail}`)))
    : null);
  globalThis.window = globalThis;
  await import("./consent-shared.jsx");
  await import("./screens-consent-citizen.jsx");
});

const HISTORY = {
  member_id: "M-HEAD",
  events: [
    { purpose_code: "REGISTRATION", state: "GRANTED", captured_by: "op1", captured_via: "WEB_INTAKE", capture_method: "SIGNATURE", effective_from: "2026-05-30T10:00:00Z", audit_event_id: "AC-1" },
  ],
};

beforeEach(() => {
  globalThis.nsrApi = {
    get: vi.fn((url) => Promise.resolve(url.endsWith("/history") ? HISTORY : MATRIX)),
    post: vi.fn(() => Promise.resolve({ ticket_id: "WD-LIVE-1", sla_deadline: "2026-06-30T00:00:00Z" })),
  };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); delete globalThis.nsrApi; });

const MEMBERS = [{ id: "M-HEAD", name: "Achieng Alice", rel: "Head", age: 40 }];

describe("CitizenConsentScreen (live mode)", () => {
  it("fetches the member's matrix and shows real identity + state", async () => {
    render(globalThis.React.createElement(globalThis.CitizenConsentScreen,
      { members: MEMBERS, householdId: "HH-LIVE-1", live: true }));
    await waitFor(() => expect(globalThis.nsrApi.get).toHaveBeenCalledWith("/api/v1/consent/members/M-HEAD"));
    expect(screen.getByText("Achieng Alice")).toBeTruthy();
    expect(screen.getAllByText(/Granted/).length).toBeGreaterThan(0);
  });

  it("posts a real withdrawal to the live API", async () => {
    render(globalThis.React.createElement(globalThis.CitizenConsentScreen,
      { members: MEMBERS, householdId: "HH-LIVE-1", live: true }));
    await waitFor(() => expect(globalThis.nsrApi.get).toHaveBeenCalled());
    // REGISTRATION is Granted + withdrawable → a Withdraw action button exists.
    const withdrawBtn = screen.getAllByRole("button", { name: /^Withdraw$/ })[0];
    fireEvent.click(withdrawBtn);
    // Modal (pass-through stub) renders the submit button inline.
    const submit = await screen.findByRole("button", { name: /Submit withdrawal request/i });
    fireEvent.click(submit);
    await waitFor(() => expect(globalThis.nsrApi.post).toHaveBeenCalledWith(
      "/api/v1/consent/members/M-HEAD/withdraw",
      expect.objectContaining({ purpose_code: "REGISTRATION" })));
  });

  it("captures consent for an un-captured purpose via the live API", async () => {
    render(globalThis.React.createElement(globalThis.CitizenConsentScreen,
      { members: MEMBERS, householdId: "HH-LIVE-1", live: true }));
    await waitFor(() => expect(globalThis.nsrApi.get).toHaveBeenCalled());
    // RESEARCH is not captured → a Capture action button exists.
    const captureBtn = screen.getAllByRole("button", { name: /^Capture$/ })[0];
    fireEvent.click(captureBtn);
    const save = await screen.findByRole("button", { name: /Save consent/i });
    fireEvent.click(save);
    await waitFor(() => expect(globalThis.nsrApi.post).toHaveBeenCalledWith(
      "/api/v1/consent/members/M-HEAD/capture",
      expect.objectContaining({ state: "GRANTED", capture_method: "DIGITAL" })));
  });

  it("loads the consent history into the audit drawer", async () => {
    render(globalThis.React.createElement(globalThis.CitizenConsentScreen,
      { members: MEMBERS, householdId: "HH-LIVE-1", live: true }));
    await waitFor(() => expect(globalThis.nsrApi.get).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /View full consent history/i }));
    await waitFor(() => expect(globalThis.nsrApi.get).toHaveBeenCalledWith(
      "/api/v1/consent/members/M-HEAD/history"));
    // The formatted history event surfaces (AuditDrawer stub is pass-through).
    await waitFor(() => expect(screen.getByText(/granted Registration/i)).toBeTruthy());
  });
});
