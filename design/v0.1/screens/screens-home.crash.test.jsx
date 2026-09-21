/* The home screen must not take the whole view down over a payload it
 * did not expect.
 *
 * Reported as the error boundary's card:
 *
 *   SCREEN CRASHED
 *   Cannot read properties of undefined (reading 'length')
 *
 * `q.items.length` was read three times while `items` came straight
 * from a fetch result. The setter always supplied an array, so nothing
 * caught it — but the home screen is the first thing an operator sees,
 * and a queue entry arriving without `items` blanks it entirely.
 *
 * These cases feed the shapes a real endpoint can return when something
 * upstream is wrong, rather than the shape it returns when everything
 * is right.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

let HomeScreen;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.KPI = ({ title, value }) => React.createElement("div", null, `${title}:${value}`);
  globalThis.PageHeader = ({ title, sub, right }) =>
    React.createElement("div", null, title, sub, right);
  globalThis.Sparkline = () => null;
  globalThis.HomeChartBand = () => null;
  globalThis.DsaWorkspaceTile = () => null;
  await import("./screens-home.jsx");
  ({ HomeScreen } = globalThis);
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

/** Answer every request with `body`, whatever it is. */
const respondWith = (body) => {
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }));
};

const renderHome = async () => {
  render(<HomeScreen role="nsr-unit" onNavigate={() => {}} operatorName="Test"/>);
  // The greeting is the first thing rendered and does not depend on a
  // fetch, so its presence means the screen mounted rather than threw.
  await waitFor(() => expect(screen.getByText(/Signed in as/)).toBeTruthy());
};

describe("payload shapes the home screen must survive", () => {
  it.each([
    ["an empty object", {}],
    ["results missing entirely", { count: 4 }],
    ["results null", { results: null, count: 0 }],
    ["results not an array", { results: { nope: true } }],
    ["a bare array", []],
    ["null", null],
    ["a string", "not json really"],
    ["a number", 7],
  ])("renders with %s", async (_label, body) => {
    respondWith(body);
    await renderHome();
    expect(document.body.textContent).not.toMatch(/SCREEN CRASHED/);
  });

  it("survives a queue entry whose items are missing", async () => {
    // The exact shape behind the reported crash: an entry present in
    // the queue map, but with no `items` array on it.
    respondWith({ results: undefined, count: 12 });
    await renderHome();
    expect(document.body.textContent).not.toMatch(/reading 'length'/);
  });

  it("survives every request failing", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline")));
    await renderHome();
    expect(document.body.textContent).not.toMatch(/SCREEN CRASHED/);
  });

  it("survives a non-JSON body", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token '<'")),
      text: () => Promise.resolve("<html>"),
    }));
    await renderHome();
    expect(document.body.textContent).not.toMatch(/SCREEN CRASHED/);
  });

  it("shows a KPI the API did not supply as an em dash, not a zero", async () => {
    // A number nobody counted must not look like a number somebody did.
    respondWith({});
    await renderHome();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
