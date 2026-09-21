/* Questionnaire wave review (ADR-0034).
 *
 * The screen's job is to make ONE thing impossible to miss: an answer
 * code whose meaning changed while its value stayed the same. Most of
 * these cases are about that — that it is shown, that it is counted at
 * the top, that it sorts first, and that the screen says plainly what
 * may not be done about it.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

let AdminInstrumentReviewScreen;

const CHANGESET = {
  old: { name: "NSRHH", version: "2026.1", label: "NSR Household", items: 2 },
  new: { name: "NSRHH", version: "2026.2", label: "NSR Household", items: 3 },
  counts: { breaking: 2, review: 2, info: 0 },
  is_clean: false,
  changes: [
    {
      kind: "code.relabelled", severity: "breaking", item: "WALL_MATERIAL",
      summary: "'WALL_MATERIAL': code 3 now means 'Concrete' (was 'Wood').",
      detail: "Same code, different label. If the code was REUSED for a different answer, every household already coded 3 is now misclassified.",
      old: "3=Wood", new: "3=Concrete",
    },
    {
      kind: "code.removed", severity: "breaking", item: "ROOF_MATERIAL",
      summary: "'ROOF_MATERIAL': answer code 15 = 'Tins' withdrawn.",
      detail: "Deprecate the option, never delete it.",
      old: "15=Tins", new: "",
    },
    {
      kind: "code.added", severity: "review", item: "ROOF_MATERIAL",
      summary: "'ROOF_MATERIAL': new answer code 17 = 'Tarpaulin'.",
      detail: "", old: "", new: "17=Tarpaulin",
    },
    {
      kind: "item.added", severity: "review", item: "COOKING_FUEL",
      summary: "New question 'COOKING_FUEL' (Cooking fuel) with a coded answer list.",
      detail: "", old: "", new: "COOKING_FUEL",
    },
  ],
};

const CLEAN = {
  old: { name: "NSRHH", version: "2026.1", label: "", items: 2 },
  new: { name: "NSRHH", version: "2026.2", label: "", items: 2 },
  counts: { breaking: 0, review: 1, info: 0 },
  is_clean: true,
  changes: [CHANGESET.changes[2]],
};

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = ({ name }) => React.createElement("i", { "data-icon": name });
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.PageHeader = ({ title, sub, right }) =>
    React.createElement("div", null, React.createElement("h1", null, title),
      React.createElement("p", null, sub), right);

  await import("../../components.jsx");          // the real Field
  await import("./screens-admin-refdata-instrument.jsx");
  ({ AdminInstrumentReviewScreen } = globalThis);
});

beforeEach(() => { globalThis.fetch = vi.fn(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ok = (body) => Promise.resolve({
  ok: true, status: 200, json: () => Promise.resolve(body),
});

const paste = (title, text) => {
  fireEvent.change(screen.getByLabelText(new RegExp(`${title} — or paste`)),
    { target: { value: text } });
};

// The filter row and the row chips use the same words, so every query
// has to say which it means.
const filterGroup = () => screen.getByRole("group", { name: "Filter by severity" });
const filterButton = (name) => within(filterGroup()).getByRole("button", { name });
const breakingChips = () => screen.queryAllByText("Needs a decision")
  .filter(el => !filterGroup().contains(el));

const compareWith = async (body) => {
  globalThis.fetch.mockReturnValue(ok(body));
  render(<AdminInstrumentReviewScreen/>);
  paste("Previous instrument", "[Dictionary]\nName=X\n");
  paste("Incoming wave", "[Dictionary]\nName=X\n");
  fireEvent.click(screen.getByText("Compare"));
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
};


describe("before a comparison", () => {
  it("cannot compare until both dictionaries are supplied", () => {
    render(<AdminInstrumentReviewScreen/>);
    const button = screen.getByText("Compare").closest("button");
    expect(button.disabled).toBe(true);
    paste("Previous instrument", "[Dictionary]\nName=X\n");
    expect(screen.getByText("Compare").closest("button").disabled).toBe(true);
    paste("Incoming wave", "[Dictionary]\nName=X\n");
    expect(screen.getByText("Compare").closest("button").disabled).toBe(false);
  });

  it("says why the dictionary is needed at all", () => {
    render(<AdminInstrumentReviewScreen/>);
    expect(document.body.textContent).toMatch(/cannot be parsed without it/);
  });

  it("does not claim the left side is what the registry is interpreting", () => {
    // It is whatever file the reviewer picked, and a diff against the
    // wrong .dcf is wrong and looks authoritative. US-121 removes the
    // caveat by storing the accepted instrument.
    render(<AdminInstrumentReviewScreen/>);
    expect(document.body.textContent).not.toMatch(/registry is already interpreting/);
    expect(document.body.textContent).toMatch(/Both sides are supplied by you/);
    expect(document.body.textContent).toMatch(/cannot confirm/);
  });
});


describe("the changeset", () => {
  it("leads with the count that needs a decision", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(screen.getByText("2 need a decision")).toBeTruthy());
  });

  it("shows the reused code and what it means", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(
      screen.getByText(/code 3 now means 'Concrete' \(was 'Wood'\)/)).toBeTruthy());
    expect(document.body.textContent).toMatch(/3=Wood/);
    expect(document.body.textContent).toMatch(/3=Concrete/);
    expect(document.body.textContent).toMatch(/misclassified/);
  });

  it("sorts what needs a decision first", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(breakingChips().length).toBe(2));
    // The server returns them already ordered worst-first; the screen
    // must not reorder them into arrival order.
    const text = document.body.textContent;
    expect(text.indexOf("code 3 now means")).toBeLessThan(text.indexOf("new answer code 17"));
  });

  it("says plainly what may not be done about a breaking change", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(
      document.body.textContent).toMatch(/nearest matching\s*code/));
    expect(document.body.textContent).toMatch(/does not receive a transfer/);
  });

  it("names both instrument versions", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(screen.getByText(/2026\.1\s*→\s*2026\.2/)).toBeTruthy());
  });

  it("filters by severity without losing the totals", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(breakingChips().length).toBe(2));
    fireEvent.click(filterButton(/Needs a decision/));
    await waitFor(() => expect(breakingChips().length).toBe(2));
    fireEvent.click(filterButton(/^Show only: Review/));
    await waitFor(() => expect(breakingChips()).toHaveLength(0));
    // The header count is the wave's, not the filter's.
    expect(screen.getByText("2 need a decision")).toBeTruthy();
  });

  it("distinguishes 'nothing to decide' from 'nothing changed'", async () => {
    await compareWith(CLEAN);
    await waitFor(() => expect(screen.getByText("Nothing needs a decision")).toBeTruthy());
    // A clean wave can still have changes, and they are still shown.
    expect(screen.getByText(/new answer code 17/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/nearest matching/);
  });
});


describe("when the dictionary cannot be read", () => {
  it("shows the parse error verbatim rather than 'failed'", async () => {
    // "old: duplicate item name 'ROOF'" is actionable. "Something went
    // wrong" sends a reviewer to an engineer.
    globalThis.fetch.mockReturnValue(Promise.resolve({
      ok: false, status: 400,
      json: () => Promise.resolve({ old: ["duplicate item name 'ROOF'"] }),
    }));
    render(<AdminInstrumentReviewScreen/>);
    paste("Previous instrument", "junk");
    paste("Incoming wave", "junk");
    fireEvent.click(screen.getByText("Compare"));
    await waitFor(() => expect(
      screen.getByText(/old: duplicate item name 'ROOF'/)).toBeTruthy());
    expect(screen.getByText(/Could not compare/)).toBeTruthy();
  });

  it("survives a non-JSON response", async () => {
    globalThis.fetch.mockReturnValue(Promise.resolve({
      ok: false, status: 502, json: () => Promise.reject(new Error("not json")),
    }));
    render(<AdminInstrumentReviewScreen/>);
    paste("Previous instrument", "x");
    paste("Incoming wave", "x");
    fireEvent.click(screen.getByText("Compare"));
    await waitFor(() => expect(screen.getByText(/HTTP 502/)).toBeTruthy());
  });
});


describe("the request", () => {
  it("carries a CSRF token on the write", async () => {
    // Seven console writes once shipped without one and returned 403
    // against the real server while passing their own tests.
    document.cookie = "csrftoken=abc123";
    await compareWith(CHANGESET);
    const [, init] = globalThis.fetch.mock.calls[0];
    expect(init.headers["X-CSRFToken"]).toBe("abc123");
    expect(init.credentials).toBe("same-origin");
  });

  it("posts to the wave-review endpoint", async () => {
    await compareWith(CHANGESET);
    expect(globalThis.fetch.mock.calls[0][0]).toBe("/api/v1/intake/cspro/diff/");
  });
});


describe("accessibility", () => {
  it("names every control", async () => {
    render(<AdminInstrumentReviewScreen/>);
    const unnamed = [...document.querySelectorAll("input, textarea, select")]
      .filter(el => {
        if (el.getAttribute("aria-label")) return false;
        const id = el.getAttribute("id");
        if (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) return false;
        const by = el.getAttribute("aria-labelledby");
        return !(by && document.getElementById(by.split(/\s+/)[0]));
      })
      .map(el => el.outerHTML.slice(0, 70));
    expect(unnamed, unnamed.join("\n")).toHaveLength(0);
  });

  it("says which severity filter is active", async () => {
    await compareWith(CHANGESET);
    await waitFor(() => expect(filterButton(/^Show all changes/)).toBeTruthy());
    expect(filterButton(/^Show all changes/).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(filterButton(/^Show only: Review/));
    expect(filterButton(/^Show only: Review/).getAttribute("aria-pressed")).toBe("true");
    expect(filterButton(/^Show all changes/).getAttribute("aria-pressed")).toBe("false");
  });

  it("distinguishes the filter controls from the row severity chips", async () => {
    // Both carry the same words. Only one of them is a control.
    await compareWith(CHANGESET);
    await waitFor(() => expect(filterGroup()).toBeTruthy());
    expect(within(filterGroup()).getAllByRole("button")).toHaveLength(4);
  });
});

