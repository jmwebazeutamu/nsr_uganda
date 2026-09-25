/* QA P3.19 — the sidebar badge.
 *
 * It refreshed on a 60-second timer and nothing else. An operator who
 * closed the last open grievance watched "1" sit next to Grievances
 * for up to a minute, and the obvious reading of that is that the
 * close did not take.
 *
 * It was also counting wrongly: it fetched 200 rows and filtered them
 * in the browser, so a queue with more than 200 cases was capped, and
 * "not closed and not resolved" was written out here as well as in the
 * dashboard tile and the workbench.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";

let useNavCounts, navCountsChanged;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  await import("./use-nav-counts.jsx");
  ({ useNavCounts, navCountsChanged } = globalThis);
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

const calls = () => globalThis.fetch.mock.calls.map(c => String(c[0]));

const stub = () => {
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, json: () => Promise.resolve({ count: 3 }),
  }));
};

const Probe = () => {
  const [counts] = useNavCounts();
  return <span data-testid="grm">{String(counts.grm)}</span>;
};

describe("the grievance badge asks the server for the count", () => {
  it("uses the server's definition of an active case", async () => {
    stub();
    render(<Probe/>);
    await waitFor(() => {
      expect(calls().some(u => u.includes("/grm/grievances/?active=true"))).toBe(true);
    });
  });

  it("does not page through rows to count them", async () => {
    // page_size=200 both capped the badge and made this a third
    // definition of "open".
    stub();
    render(<Probe/>);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(calls().some(u => u.includes("page_size=200"))).toBe(false);
  });

  it("reads the paginated count", async () => {
    stub();
    const { getByTestId } = render(<Probe/>);
    await waitFor(() => expect(getByTestId("grm").textContent).toBe("3"));
  });
});

describe("a screen can say the counts are stale", () => {
  it("re-fetches when a screen announces a change", async () => {
    stub();
    render(<Probe/>);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const before = globalThis.fetch.mock.calls.length;

    navCountsChanged();

    await waitFor(() => {
      expect(globalThis.fetch.mock.calls.length).toBeGreaterThan(before);
    });
  });

  it("stops listening once the sidebar unmounts", async () => {
    stub();
    const { unmount } = render(<Probe/>);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    unmount();
    const after = globalThis.fetch.mock.calls.length;

    navCountsChanged();
    await new Promise(r => setTimeout(r, 10));

    expect(globalThis.fetch.mock.calls.length).toBe(after);
  });

  it("one bad listener does not stop the others", () => {
    // The set is shared; a screen that throws on its own refresh must
    // not take the sidebar's with it.
    stub();
    expect(() => navCountsChanged()).not.toThrow();
  });
});

describe("the GRM workbench announces its changes", () => {
  const grm = fs.readFileSync(
    path.join(process.cwd(), "design/v0.1/screens/screens-grm.jsx"), "utf8",
  );

  it("marks the badge stale on refresh, which every action calls", () => {
    expect(grm).toContain("const badgeStale = () => {");
    expect(grm).toMatch(/const refresh = \(\) => \{\s*\n\s*badgeStale\(\);/);
  });

  it("marks it stale after the actions that skip refresh()", () => {
    // Task transitions and task creation change what the badge counts
    // without going through the roster refresh.
    expect((grm.match(/badgeStale\(\);/g) || []).length).toBeGreaterThanOrEqual(3);
  });

  it("does not assume the shell is mounted", () => {
    // The screens also run in the file:// design preview, where
    // nothing owns the sidebar.
    expect(grm).toContain('typeof navCountsChanged === "function"');
  });
});
