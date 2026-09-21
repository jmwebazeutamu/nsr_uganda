/* The Decision panel must say what failed, not which rule failed.
 *
 * It read `Raised: ${findings.map(f => f.rule_id).join(", ")}`, which
 * put "Raised: AC-HOH-EXISTS." in front of a QA admin — a rule code,
 * where the evaluator had already rendered "Exactly 1 member must be
 * flagged as Head; found 0." into the same payload.
 *
 * The same line also dropped every intra-household finding. Two
 * evaluators write into one summary in two shapes: the record-scope one
 * writes {rule_id, reason}, the household one writes {rule_code,
 * message}. Reading rule_id alone meant a record could report "1
 * blocking" and then list nothing at all.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let DIHScreen;

// One of each shape, as ingestion_hub.services folds them together.
const SUMMARY = {
  blocking_failures: [
    {
      rule_id: "AC-NIN-FORMAT", rule_version: 2, severity: "block",
      reason: "NIN 'CM123' does not match the NIRA format ^(CM|CF)[A-Z0-9]{12}$.",
    },
    {
      rule_code: "AC-HOH-EXISTS", rule_version: 1, severity: "block",
      message: "Exactly 1 member must be flagged as Head; found 0.",
      offending_member_ids: ["M-02", "M-03"],
    },
  ],
  warnings: [
    {
      rule_code: "AC-HOH-AGE", rule_version: 1, severity: "flag",
      message: "Head of household must be at least 18 years old.",
    },
  ],
  info: [],
};

const stage = (summary) => ({
  id: "01M2PJKTF66932S855ZZZZZZZZ",
  state: "quality_failed",
  source_system: "Kobo",
  intake_channel: "Kobo",
  canonical_payload: {
    members: [{ is_head: true, surname: "Nakalema", first_name: "Daniel" }],
    geographic: { region: "Karamoja", parish: "412.02.05.01" },
  },
  dqa_summary: summary,
  ddup_candidates: [],
  idv_outcome: "pending",
  created_at: new Date().toISOString(),
});

const jsonOk = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

const mountWith = async (summary) => {
  globalThis.fetch = vi.fn((url) =>
    String(url).includes("stage-records")
      ? jsonOk({ results: [stage(summary)] })
      : jsonOk({ results: [] }));
  render(<DIHScreen/>);
  await waitFor(() => expect(screen.getAllByText("Nakalema Daniel").length).toBeGreaterThan(0));
  fireEvent.click(screen.getAllByText("Nakalema Daniel")[0]);
};

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.KPI = () => null;
  globalThis.PageHeader = ({ title, right }) => React.createElement("div", null, title, right);
  globalThis.AuditDrawer = () => null;
  globalThis.ActionBar = ({ left, children }) => React.createElement("div", null, left, children);
  globalThis.ReasonModal = () => null;
  globalThis.Modal = ({ open, children }) => (open ? React.createElement("div", null, children) : null);
  globalThis.Toast = () => null;
  globalThis.useNavCounts = () => [{}];
  await import("../components/wide-view.jsx");
  await import("../components/idv-outcomes.jsx");
  await import("./screens-dih.jsx");
  ({ DIHScreen } = globalThis);
});

beforeEach(() => { globalThis.fetch = vi.fn(() => jsonOk({ results: [] })); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("what the Decision panel says", () => {
  it("shows the rendered message, not the rule code", async () => {
    await mountWith(SUMMARY);
    expect(screen.getByText("Exactly 1 member must be flagged as Head; found 0.")).toBeTruthy();
    expect(screen.getByText(/does not match the NIRA format/)).toBeTruthy();
    // The old output, verbatim.
    expect(screen.queryByText(/^Raised: /)).toBeNull();
  });

  it("lists the intra-household findings it used to drop", async () => {
    // AC-HOH-EXISTS arrives as `rule_code`. Under the old line it was
    // counted in "2 blocking" and then named nowhere.
    await mountWith(SUMMARY);
    const panel = screen.getByText("DQA OUTCOMES").closest("div").parentElement;
    expect(panel.textContent).toContain("Exactly 1 member must be flagged as Head");
  });

  it("keeps the code as provenance, because everything else keys on it", async () => {
    // The Rule Editor, the violations report and the audit chain all
    // refer to the rule by code; an admin who wants to change the rule
    // needs it. It just is not the headline any more.
    await mountWith(SUMMARY);
    expect(screen.getByText("AC-HOH-EXISTS v1")).toBeTruthy();
    expect(screen.getByText("AC-NIN-FORMAT v2")).toBeTruthy();
  });

  it("names the members a household rule is complaining about", async () => {
    await mountWith(SUMMARY);
    expect(screen.getByText(/member M-02, M-03/)).toBeTruthy();
  });

  it("separates blocking from warning", async () => {
    await mountWith(SUMMARY);
    expect(screen.getAllByText("blocking").length).toBe(2);
    expect(screen.getAllByText("warning").length).toBe(1);
  });

  it("falls back to the code rather than inventing a sentence", async () => {
    // A rule with no message template is an authoring gap. Guessing at
    // what the code means would be the console making up a rule.
    await mountWith({
      blocking_failures: [{ rule_id: "AC-SOMETHING-NEW", rule_version: 1 }],
      warnings: [], info: [],
    });
    expect(screen.getByText("AC-SOMETHING-NEW")).toBeTruthy();
  });

  it("still says so when everything passed", async () => {
    await mountWith({ blocking_failures: [], warnings: [], info: [] });
    expect(screen.getByText("Clean — all rules passed.")).toBeTruthy();
  });

  it("caps the list and says how many are left", async () => {
    const many = {
      blocking_failures: [1, 2, 3, 4, 5].map(i => ({
        rule_code: `AC-RULE-${i}`, rule_version: 1, message: `Finding number ${i}.`,
      })),
      warnings: [], info: [],
    };
    await mountWith(many);
    expect(screen.getByText("Finding number 1.")).toBeTruthy();
    expect(screen.queryByText("Finding number 4.")).toBeNull();
    expect(screen.getByText(/\+2 more/)).toBeTruthy();
  });
});

describe("the queue row", () => {
  it("explains its B / W chips on hover", async () => {
    // Triage should not require opening a record to find out what "B 1"
    // stands for.
    await mountWith(SUMMARY);
    const cell = [...document.querySelectorAll("[title]")]
      .find(el => (el.getAttribute("title") || "").includes("BLOCKING"));
    expect(cell).toBeTruthy();
    expect(cell.getAttribute("title")).toContain("Exactly 1 member must be flagged as Head");
    expect(cell.getAttribute("title")).toContain("WARNING · Head of household must be at least 18");
  });
});
