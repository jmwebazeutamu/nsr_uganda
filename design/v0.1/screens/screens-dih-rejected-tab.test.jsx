/* Rejected records have a screen.
 *
 * They never did. `reject_stage_record` writes the state, the reason, the
 * actor and the timestamp, keeps the full canonical_payload, and emits an
 * audit event — and no surface fetched any of it. The DIH screen's Archive
 * tab queries `state=quarantined`; it only looked as though it covered
 * rejections because quarantine writes the same rejected_* columns.
 *
 * On production that meant fourteen refused households, each holding a
 * complete payload, reachable only through the API or the database.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let DIHScreen;

const jsonOk = (body) => Promise.resolve({
  ok: true, status: 200, json: () => Promise.resolve(body),
});

const REJECTED = {
  id: "01KRPPW6WMJD2FBX4TYXAC22VF",
  provisional_registry_id: "01KRPPW6WMJD2FBX4TYXAC22VF",
  state: "rejected",
  rejected_reason: "ddup-duplicate-of: 01KSNF35HWEK78FZA4AW9NFRVH",
  rejected_at: "2026-09-19T11:02:00Z",
  rejected_by: "ops-backfill",
  source_system: "kobo",
  canonical_payload: {
    members: [{ is_head: true, surname: "Okello", first_name: "Robert" }],
    geographic: {},
  },
};

const QUARANTINED = {
  ...REJECTED,
  id: "01KQUARANTINEDQUARANTINED1",
  provisional_registry_id: "01KQUARANTINEDQUARANTINED1",
  state: "quarantined",
  rejected_reason: "unfixable quality failure",
  rejected_by: "nsr-admin",
  canonical_payload: {
    members: [{ is_head: true, surname: "Nakato", first_name: "Sarah" }],
    geographic: {},
  },
};

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.KPI = ({ title, value }) => React.createElement("div", null, `${title}:${value}`);
  globalThis.PageHeader = ({ title, right }) => React.createElement("div", null, title, right);
  globalThis.AuditDrawer = () => null;
  globalThis.ActionBar = ({ left, children }) => React.createElement("div", null, left, children);
  globalThis.ReasonModal = () => null;
  globalThis.Modal = ({ open, children }) => (open ? React.createElement("div", null, children) : null);
  globalThis.Toast = () => null;
  globalThis.useNavCounts = () => [{}];
  globalThis.useChoiceList = () => [[], { loading: false, error: null }];

  await import("../components/wide-view.jsx");
  await import("../components/idv-outcomes.jsx");
  await import("../components/household-review-model.jsx");
  await import("../components/household-review.jsx");
  await import("./screens-dih.jsx");
  ({ DIHScreen } = globalThis);
});

let requested;

beforeEach(() => {
  requested = [];
  globalThis.fetch = vi.fn((url) => {
    const u = String(url);
    requested.push(u);
    if (u.includes("state=rejected")) return jsonOk({ results: [REJECTED] });
    if (u.includes("state=quarantined")) return jsonOk({ results: [QUARANTINED] });
    if (u.includes("stage-records")) return jsonOk({ results: [] });
    return jsonOk({ results: [] });
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const openRejectedTab = async () => {
  render(<DIHScreen/>);
  await waitFor(() => expect(screen.getByText("Rejected")).toBeTruthy());
  fireEvent.click(screen.getByText("Rejected"));
};

describe("the rejected tab", () => {
  it("asks the API for rejected records", async () => {
    render(<DIHScreen/>);
    await waitFor(() => expect(
      requested.some(u => u.includes("state=rejected")),
    ).toBe(true));
  });

  it("is a separate query from the archive tab", async () => {
    // Archive shows quarantined. Two terminal states, two meanings, two
    // queries — not one list filtered client-side.
    render(<DIHScreen/>);
    await waitFor(() => expect(requested.length).toBeGreaterThan(1));
    expect(requested.some(u => u.includes("state=quarantined"))).toBe(true);
    expect(requested.some(u => u.includes("state=rejected"))).toBe(true);
  });

  it("shows a rejected record with its reason, actor and date", async () => {
    await openRejectedTab();
    await waitFor(() => expect(screen.getByText(/ddup-duplicate-of/)).toBeTruthy());
    expect(screen.getByText("ops-backfill")).toBeTruthy();
    expect(screen.getByText("2026-09-19")).toBeTruthy();
  });

  it("does not show quarantined records under Rejected", async () => {
    await openRejectedTab();
    await waitFor(() => expect(screen.getByText(/ddup-duplicate-of/)).toBeTruthy());
    expect(screen.queryByText("unfixable quality failure")).toBeNull();
  });

  it("names the ID column 'Voided', because none of these reached the registry", async () => {
    // reject_stage_record burns the provisional ID: prod has 14 rejected
    // records, all still carrying one, and zero Household rows for any of
    // them. Calling the column "Provisional ID" would imply it is still
    // pending.
    await openRejectedTab();
    expect(screen.getByRole("columnheader", { name: "Voided ID" })).toBeTruthy();
  });

  it("hides the queue's filter bar and actions", async () => {
    await openRejectedTab();
    expect(screen.queryByText("QUICK FILTERS")).toBeNull();
  });

  it("renders an empty state rather than a blank panel", async () => {
    globalThis.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("state=rejected")) return jsonOk({ results: [] });
      return jsonOk({ results: [] });
    });
    await openRejectedTab();
    await waitFor(() => expect(screen.getByText("No rejected records.")).toBeTruthy());
  });

  it("counts them on the tab, so the queue is not the only number seen", async () => {
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getByText("Rejected")).toBeTruthy());
    const tab = screen.getByText("Rejected").closest("button");
    await waitFor(() => expect(tab.textContent).toMatch(/1/));
  });
});
