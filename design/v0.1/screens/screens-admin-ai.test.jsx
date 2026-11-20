/* AI oversight screen (ADR-0045).
 *
 * What it pins: the screen renders what the server says and decides nothing.
 * State labels, tones, and "can reviewers see this" arrive in the payload; the
 * screen carries no tone table of its own, issues no write, and says plainly
 * when nothing has been scored or the API did not answer.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

let AdminAiScreen;

const state = (code, label, tone) => ({ code, label, tone });
const OFF = state("off", "Off", "neutral");
const SHADOW = state("shadow", "Shadow", "reference");
const ADVISORY = state("advisory", "Advisory", "system");

const feature = (over = {}) => ({
  code: "ddup.rank", label: "DDUP candidate ranking",
  stored_state: SHADOW, effective_state: SHADOW, shown_to_reviewers: false,
  model: { id: "M1", name: "pair-ranker", version: 2, status: "active", owner: "NSR Unit",
           validated_on: "2026-11-01", approved_by: "bob", approved_at: "2026-11-02T08:00:00Z", runtime: "local" },
  gate_config: {},
  evaluation: { labelled: 3, above_cutoff: 0, precision: null, meets_gate: false,
                reasons: ["gate_config not set (min_labelled_decisions)"] },
  last_run: { id: "R1", started_at: "2026-11-20T01:00:00Z", state: "shadow", scored: 12, skipped: 2, note: "" },
  changed_by: "ops", changed_at: "2026-11-19T10:00:00Z",
  ...over,
});

const DQA = feature({
  code: "dqa.anomaly", label: "DQA anomaly flags", stored_state: OFF, effective_state: OFF,
  model: null, last_run: null,
  evaluation: { labelled: 0, above_cutoff: 0, precision: null, meets_gate: false,
                reasons: ["no reviewer disposition is recorded for this feature; nothing to evaluate"] },
});

const OVERVIEW = { master_enabled: true, features: [feature(), DQA] };

const SUGGESTIONS = {
  feature: "ddup.rank", effective_state: SHADOW, shown_to_reviewers: false,
  run: { id: "R1", started_at: "2026-11-20T01:00:00Z", state: "shadow", scored: 12, skipped: 2 },
  total: 12,
  results: [
    { id: "S1", subject_type: "match_pair", subject_id: "PAIR-ONE", score: 0.91,
      details: { contributions: { "member.surname": 1.8 } },
      reviewer_outcome: { code: "merge", label: "Merge" }, subject_status: "merged" },
    { id: "S2", subject_type: "match_pair", subject_id: "PAIR-TWO", score: 0.42,
      details: {}, reviewer_outcome: null, subject_status: "pending" },
  ],
};

const ok = (body) => ({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) });

const routeFetch = (over = {}) => vi.fn((url) => {
  if (url.startsWith("/api/v1/admin/ai/overview/")) return Promise.resolve(over.overview || ok(OVERVIEW));
  if (url.startsWith("/api/v1/admin/ai/suggestions/")) return Promise.resolve(over.suggestions || ok(SUGGESTIONS));
  return Promise.reject(new Error(`unexpected url ${url}`));
});

beforeAll(async () => {
  globalThis.React = await import("react").then((m) => m.default || m);
  globalThis.window = globalThis;
  globalThis.PageHeader = ({ title }) => globalThis.React.createElement("h1", null, title);
  globalThis.KPI = ({ title, value }) => globalThis.React.createElement("div", { "data-kpi": title }, `${title}:${value}`);
  await import("../data/api-client.jsx");
  await import("./screens-admin-ai.jsx");
  ({ AdminAiScreen } = globalThis);
});

beforeEach(() => { globalThis.fetch = routeFetch(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("what it shows", () => {
  it("renders every feature with the label and tone the server sent", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("DQA anomaly flags")).toBeTruthy());
    const shadowChip = screen.getByText("Shadow");
    expect(shadowChip.getAttribute("data-tone")).toBe("reference");
    expect(screen.getByText("Off").getAttribute("data-tone")).toBe("neutral");
  });

  it("says plainly that reviewers cannot see a shadow feature", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getAllByText(/cannot see its suggestions/).length).toBe(2));
  });

  it("says when reviewers can see an advisory feature", async () => {
    globalThis.fetch = routeFetch({ overview: ok({ master_enabled: true, features: [
      feature({ stored_state: ADVISORY, effective_state: ADVISORY, shown_to_reviewers: true }),
    ] }) });
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText(/can see its suggestions/)).toBeTruthy());
  });

  it("shows the model, its owner and its validation date", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText(/pair-ranker v2/)).toBeTruthy());
    expect(screen.getByText(/owner NSR Unit/)).toBeTruthy();
    expect(screen.getByText(/validated 2026-11-01/)).toBeTruthy();
    expect(screen.getByText("No model attached.")).toBeTruthy();
  });

  it("shows why a gate is not met, in the server's words", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("gate_config not set (min_labelled_decisions)")).toBeTruthy());
  });

  it("renders the last run in East Africa Time", async () => {
    render(<AdminAiScreen/>);
    // 01:00 UTC is 04:00 EAT.
    await waitFor(() => expect(screen.getByText(/20 Nov 2026, 04:00 EAT/)).toBeTruthy());
  });

  it("flags a feature whose stored state is overridden", async () => {
    globalThis.fetch = routeFetch({ overview: ok({ master_enabled: true, features: [
      feature({ stored_state: ADVISORY, effective_state: OFF }),
    ] }) });
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("Set to Advisory, running as Off.")).toBeTruthy());
  });

  it("warns when the master switch is off", async () => {
    globalThis.fetch = routeFetch({ overview: ok({ ...OVERVIEW, master_enabled: false }) });
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("AI services are switched off.")).toBeTruthy());
  });

  it("does not warn when it is on", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("DQA anomaly flags")).toBeTruthy());
    expect(screen.queryByText("AI services are switched off.")).toBeNull();
  });
});

describe("suggestions", () => {
  it("lists the selected feature's suggestions with the reviewer's decision", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("match_pair:PAIR-ONE")).toBeTruthy());
    expect(screen.getByText("0.910")).toBeTruthy();
    expect(screen.getByText("Merge")).toBeTruthy();
    expect(screen.getByText(/Reviewers cannot see these/)).toBeTruthy();
    expect(screen.getByText(/2 of 12/)).toBeTruthy();
  });

  it("asks the server for the feature that was picked", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("match_pair:PAIR-ONE")).toBeTruthy());
    fireEvent.click(screen.getByText("DQA anomaly flags"));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("feature=dqa.anomaly"), expect.anything(),
    ));
  });

  it("says nothing has been scored rather than showing an empty table", async () => {
    globalThis.fetch = routeFetch({ suggestions: ok({ ...SUGGESTIONS, run: null, total: 0, results: [] }) });
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText(/Nothing has been scored for DDUP candidate ranking/)).toBeTruthy());
  });
});

describe("when the API does not answer", () => {
  it("says so instead of rendering anything", async () => {
    globalThis.fetch = routeFetch({ overview: { ok: false, status: 500, text: () => Promise.resolve("") } });
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/could not be loaded/));
    expect(screen.queryByText("DDUP candidate ranking")).toBeNull();
  });

  it("reports a failed suggestions call without losing the feature list", async () => {
    globalThis.fetch = routeFetch({ suggestions: { ok: false, status: 403, text: () => Promise.resolve("") } });
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Suggestions could not be loaded/));
    expect(screen.getAllByText("DDUP candidate ranking").length).toBeGreaterThan(0);
  });
});

describe("it decides nothing and writes nothing", () => {
  it("issues only GET requests", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("match_pair:PAIR-ONE")).toBeTruthy());
    fireEvent.click(screen.getByText("DQA anomaly flags"));
    await waitFor(() => expect(globalThis.fetch.mock.calls.length).toBeGreaterThan(2));
    for (const [, init] of globalThis.fetch.mock.calls) expect(init.method).toBe("GET");
  });

  it("offers no button that changes a feature", async () => {
    render(<AdminAiScreen/>);
    await waitFor(() => expect(screen.getByText("DQA anomaly flags")).toBeTruthy());
    for (const word of [/enable/i, /activate/i, /turn on/i, /promote/i, /approve/i]) {
      expect(screen.queryByRole("button", { name: word })).toBeNull();
    }
  });

  it("carries no tone table or colour of its own", () => {
    const src = fs.readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), "screens-admin-ai.jsx"), "utf8",
    ).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    expect(src).not.toMatch(/_TONE\s*=|TONE\s*=\s*\{/);
    expect(src).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(src).not.toMatch(/(?:on|off|shadow|advisory)\s*:\s*"(?:neutral|danger|quality|data|system|reference)"/);
  });
});
