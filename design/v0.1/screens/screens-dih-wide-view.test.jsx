/* The DIH review queue in the wide view (ADR-0030).
 *
 * The queue's table sits in a 280px scroll box above a detail rail, so
 * roughly five rows of an eighty-two row queue are visible. These cases
 * cover the three things the wide view changes on this screen: the
 * table gets the window's height, the detail rail becomes a drawer
 * opened by selecting a row, and the pop-out carries the filters the
 * operator had set.
 *
 * The rest of the screen is deliberately untouched, and the first case
 * here is the one that proves it.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let DIHScreen;

const STAGE = {
  id: "01M2PJKTF66932S855ZZZZZZZZ",
  state: "quality_failed",
  source_system: "Kobo",
  intake_channel: "Kobo",
  canonical_payload: {
    members: [{ is_head: true, surname: "Nakalema", first_name: "Daniel" }],
    geographic: { region: "Karamoja", parish: "412.02.05.01" },
  },
  dqa_summary: { blocking_failures: [{ rule_id: "AC-MANDATORY" }], warnings: [], info: [] },
  ddup_candidates: [],
  idv_outcome: "pending",
  created_at: new Date().toISOString(),
};

const jsonOk = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;

  const passthrough = ({ children }) => React.createElement("div", null, children);
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

  await import("../components/wide-view.jsx");
  await import("./screens-dih.jsx");
  ({ DIHScreen } = globalThis);
  void passthrough;
});

beforeEach(() => {
  globalThis.fetch = vi.fn((url) => {
    if (String(url).includes("stage-records")) return jsonOk({ results: [STAGE] });
    return jsonOk({ results: [] });
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); delete globalThis.window.open; });

// The head's name appears in the row and again in the detail rail, so
// every lookup here takes the first — the table cell.
const rowCell = async () => {
  await waitFor(() => expect(screen.getAllByText("Nakalema Daniel").length).toBeGreaterThan(0));
  return screen.getAllByText("Nakalema Daniel")[0];
};

describe("normal layout", () => {
  it("still stacks the detail under the table", async () => {
    render(<DIHScreen/>);
    fireEvent.click(await rowCell());
    // The compare rail renders inline, as it always has.
    expect(screen.getAllByText(/staged record/i).length).toBeGreaterThan(1);
    expect(document.querySelector(".drawer.drawer-wide")).toBeNull();
    expect(document.querySelector(".wide-shell")).toBeNull();
  });

  it("offers the two wide-view buttons", async () => {
    render(<DIHScreen/>);
    await rowCell();
    expect(screen.getByText("Wider view")).toBeTruthy();
    expect(screen.getByText("Open in new window")).toBeTruthy();
  });
});

describe("maximised", () => {
  it("takes the window and holds the row list open", async () => {
    render(<DIHScreen/>);
    await rowCell();
    fireEvent.click(screen.getByText("Wider view"));
    expect(document.querySelector(".wide-shell")).toBeTruthy();
    // The table is still there — maximising must not cost the operator
    // their list.
    expect(screen.getAllByText("Nakalema Daniel").length).toBeGreaterThan(0);
  });

  it("gives the table the window's height instead of 280px", async () => {
    render(<DIHScreen/>);
    await rowCell();
    const before = [...document.querySelectorAll("div")]
      .find(d => (d.style.maxHeight || "").endsWith("px") && d.querySelector("table"));
    expect(before.style.maxHeight).toBe("280px");

    fireEvent.click(screen.getByText("Wider view"));
    const after = [...document.querySelectorAll("div")]
      .find(d => (d.style.maxHeight || "").includes("100vh") && d.querySelector("table"));
    expect(after).toBeTruthy();
  });

  it("starts from the list, not from a record", async () => {
    // The queue auto-selects the first row so the stacked detail rail is
    // never empty. Going wide is a request for the list; opening the
    // drawer over it immediately would undo the point of the button.
    render(<DIHScreen/>);
    await rowCell();
    fireEvent.click(screen.getByText("Wider view"));
    expect(document.querySelector(".drawer.drawer-wide")).toBeNull();
  });

  it("opens the detail as a drawer when a row is selected, and closes it again", async () => {
    render(<DIHScreen/>);
    await rowCell();
    fireEvent.click(screen.getByText("Wider view"));

    fireEvent.click(screen.getAllByText("Nakalema Daniel")[0]);
    const drawer = document.querySelector(".drawer.drawer-wide");
    expect(drawer).toBeTruthy();
    // The record's own name titles the drawer, not a generic label.
    expect(drawer.textContent).toContain("Nakalema Daniel");

    fireEvent.click(drawer.querySelector('button[aria-label="Close record detail"]'));
    expect(document.querySelector(".drawer.drawer-wide")).toBeNull();
    expect(screen.getAllByText("Nakalema Daniel").length).toBeGreaterThan(0);  // list survives
  });
});

describe("pop-out", () => {
  it("carries the quick filter the operator had set", async () => {
    const open = vi.fn(() => ({ focus: vi.fn() }));
    globalThis.window.open = open;
    render(<DIHScreen/>);
    await rowCell();

    const quickFilter = [...document.querySelectorAll("button")]
      .find(b => /quality failed/i.test(b.textContent));
    fireEvent.click(quickFilter);
    fireEvent.click(screen.getByText("Open in new window"));

    const url = open.mock.calls[0][0];
    expect(url).toContain("wide=dih");
    const filters = JSON.parse(decodeURIComponent(url.split("filters=")[1]));
    expect(filters.quick).toBe("state_quality_failed");  // the id QUICK_FILTERS uses
  });

  it("carries nothing when nothing is filtered", async () => {
    const open = vi.fn(() => ({ focus: vi.fn() }));
    globalThis.window.open = open;
    render(<DIHScreen/>);
    await rowCell();
    fireEvent.click(screen.getByText("Open in new window"));
    expect(open.mock.calls[0][0]).not.toContain("filters=");
  });
});
