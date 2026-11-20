/* The advisory AI rank column in the reviewer's dedup queue (ADR-0045).
 *
 * The server decides whether a pair carries a rank (only while the feature is
 * advisory). The screen renders what arrived, asks for rank ordering, and does
 * not invent a number for a pair that has none.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";

let DedupScreen;

const MODEL = { results: [{ config: { tiers: {
  tier1: { candidate_score: 1 },
  tier3: { review_threshold: 0.6, auto_merge_threshold: 0.95 },
} } }] };

const pair = (id, extra = {}) => ({
  id, record_a_id: "A", record_b_id: "B", tier: 3, match_reason: "fuzzy",
  composite_score: 0.7, status: "pending", created_at: "2026-10-02T00:00:00Z",
  per_field_scores: {}, ai_rank: null, ...extra,
});

const MEMBER = { household: "H", surname: "S", first_name: "F", sex: "1" };
let pairs;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.PageHeader = ({ children }) => React.createElement("div", null, children);
  globalThis.Modal = () => null;
  globalThis.ReasonModal = () => null;
  globalThis.ActionBar = () => null;
  globalThis.Toast = () => null;
  globalThis.useWideView = () => ({ isWide: false });
  globalThis.WideViewButtons = () => null;
  globalThis.WideShell = ({ children }) => React.createElement("div", null, children);
  globalThis.WideDetailHost = () => null;
  await import("./screens-dedup.jsx");
  ({ DedupScreen } = globalThis);
});

beforeEach(() => {
  pairs = { results: [pair("P1")] };
  globalThis.fetch = vi.fn((url) => {
    const u = String(url);
    const body = u.includes("/ddup/model-versions/") ? MODEL
      : u.includes("/ddup/match-pairs/") ? pairs
      : u.includes("/data-management/members/") ? MEMBER : {};
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  });
});
afterEach(cleanup);

const queueRows = () => within(screen.getAllByRole("table")[0]).getAllByRole("row").slice(1);

describe("AI rank column", () => {
  it("shows the score the server attached", async () => {
    pairs = { results: [pair("P1", { ai_rank: { score: 0.913, model: "pair-ranker v2" } })] };
    render(<DedupScreen/>);
    await waitFor(() => expect(screen.getByText("0.91")).toBeInTheDocument());
  });

  it("says which model and that it is advisory, not a probability", async () => {
    pairs = { results: [pair("P1", { ai_rank: { score: 0.5, model: "pair-ranker v2" } })] };
    render(<DedupScreen/>);
    await waitFor(() => expect(screen.getByText("0.50")).toBeInTheDocument());
    const title = screen.getByText("0.50").getAttribute("title");
    expect(title).toMatch(/pair-ranker v2/);
    expect(title).toMatch(/not a probability/);
    expect(title).toMatch(/you decide/);
  });

  it("shows a dash, not a number, for a pair with no rank", async () => {
    render(<DedupScreen/>);
    await waitFor(() => expect(queueRows().length).toBe(1));
    const cells = within(queueRows()[0]).getAllByRole("cell");
    expect(cells.some((c) => c.textContent === "—")).toBe(true);
  });

  it("keeps the server's order and never re-sorts it", async () => {
    pairs = { results: [
      pair("LOW", { ai_rank: { score: 0.2, model: "m v1" } }),
      pair("HIGH", { ai_rank: { score: 0.9, model: "m v1" } }),
    ] };
    render(<DedupScreen/>);
    await waitFor(() => expect(queueRows().length).toBe(2));
    expect(within(queueRows()[0]).getByText("0.20")).toBeInTheDocument();
    expect(within(queueRows()[1]).getByText("0.90")).toBeInTheDocument();
  });

  it("asks the server to order by rank", async () => {
    render(<DedupScreen/>);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const urls = globalThis.fetch.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes("/ddup/match-pairs/") && u.includes("order=ai"))).toBe(true);
  });

  it("labels the column as advisory", async () => {
    render(<DedupScreen/>);
    await waitFor(() => expect(screen.getByText("AI rank")).toBeInTheDocument());
    expect(screen.getByText("AI rank").getAttribute("title")).toMatch(/Advisory/);
  });

  it("does not change what is composite and exact", async () => {
    pairs = { results: [pair("P1", { tier: 1, composite_score: null })] };
    render(<DedupScreen/>);
    await waitFor(() => expect(screen.getByText("exact")).toBeInTheDocument());
  });
});
