/* Home-screen chart band (US-S24-HOME-CHARTS).
 *
 * Two readers: the coordinator during the week, and whoever they print
 * it for. Most of these cases are about the second one — a chart that
 * covers one sub-region while reading as national is wrong in a way its
 * reader cannot detect, and a chart that invents a number to fill a
 * failed fetch is worse than a blank space.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";

let HomeChartBand, HomeBarChart, HomeChartCard;

const PAYLOAD = {
  region: "",
  households_by_pmt_band: [
    { key: "extreme_poverty", label: "Extreme poverty", count: 42 },
    { key: "poverty", label: "Poverty", count: 26 },
    { key: "vulnerable", label: "Vulnerable", count: 220 },
    { key: "not_poor", label: "Not poor", count: 0 },
  ],
  members_by_pmt_band: [
    { key: "extreme_poverty", label: "Extreme poverty", count: 241 },
    { key: "poverty", label: "Poverty", count: 128 },
    { key: "vulnerable", label: "Vulnerable", count: 918 },
    { key: "not_poor", label: "Not poor", count: 0 },
  ],
  dih_backlog_by_reason: [
    { key: "quality_failed", label: "DQA failure", count: 0 },
    { key: "pending_promotion", label: "Awaiting promotion", count: 66 },
  ],
  dqa_failures_by_rule: [
    { key: "AC-GPS-ACCURACY", label: "AC-GPS-ACCURACY", severity: "flag", count: 5 },
  ],
  enrolments_by_programme: [
    { key: "NUSAF", label: "Northern Uganda Social Action Fund (NUSAF) IV", count: 10 },
  ],
};

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = ({ name }) => React.createElement("i", { "data-icon": name });
  await import("./home-charts.jsx");
  ({ HomeChartBand, HomeBarChart, HomeChartCard } = globalThis);
});

beforeEach(() => {
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve(PAYLOAD),
  }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const bars = () => [...document.querySelectorAll(".chart-bar-fill")];
const widthOf = (el) => parseFloat(el.style.width);

const renderBand = async (props = {}) => {
  render(<HomeChartBand {...props}/>);
  await waitFor(() => expect(screen.getByText("Households by PMT band")).toBeTruthy());
};


describe("the bar list", () => {
  it("scales bars to the largest value, not to a round number", () => {
    // A registry of 288 padded to an axis of 1,000 looks empty.
    render(<HomeBarChart rows={PAYLOAD.households_by_pmt_band}/>);
    const widths = bars().map(widthOf);
    expect(Math.max(...widths)).toBe(100);
    expect(widths[0]).toBeCloseTo((42 / 220) * 100, 1);
  });

  it("gives a non-zero bar a visible stub", () => {
    // One household out of a million must not render as the same
    // nothing as no households.
    render(<HomeBarChart rows={[
      { key: "a", label: "Many", count: 1000000 },
      { key: "b", label: "One", count: 1 },
    ]}/>);
    expect(widthOf(bars()[1])).toBeGreaterThanOrEqual(2);
  });

  it("draws no bar at all for zero", () => {
    render(<HomeBarChart rows={[{ key: "z", label: "None", count: 0 }]}/>);
    expect(widthOf(bars()[0])).toBe(0);
  });

  it("prints every value as text beside its bar", () => {
    // This is the table view: the bar is decorative, the row reads
    // "<label> <count>" to a screen reader and on a photocopy.
    render(<HomeBarChart rows={PAYLOAD.households_by_pmt_band}/>);
    expect(screen.getByText("Extreme poverty")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("220")).toBeTruthy();
  });

  it("hides the bar from assistive technology", () => {
    render(<HomeBarChart rows={PAYLOAD.households_by_pmt_band}/>);
    for (const track of document.querySelectorAll(".chart-bar-track")) {
      expect(track.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("renders a missing count as an em dash, never as zero", () => {
    // The home screen's rule since the fabricated-KPI cleanup: a number
    // the API did not supply is not a number.
    render(<HomeBarChart rows={[{ key: "a", label: "Unknown", count: null }]}/>);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("says so when there is nothing to show", () => {
    render(<HomeBarChart rows={[]} emptyText="Nothing is held."/>);
    expect(screen.getByText("Nothing is held.")).toBeTruthy();
  });
});


describe("colour", () => {
  it("uses one hue for an unordered chart, so colour never means identity", () => {
    // Validated, not assumed: --accent-data against --accent-quality is
    // ΔE 3.8 under protanopia, so two bars in the module accents are the
    // same bar to a protanopic reader. Identity lives in the label.
    render(<HomeBarChart rows={PAYLOAD.households_by_pmt_band}/>);
    const fills = new Set(bars().map(b => b.style.background));
    expect(fills.size).toBe(1);
    expect([...fills][0]).toContain("--chart-bar");
  });

  it("uses the sequential ramp only for an ordered scale", () => {
    render(<HomeBarChart rows={PAYLOAD.households_by_pmt_band} ramp/>);
    const fills = bars().map(b => b.style.background);
    expect(new Set(fills).size).toBe(4);
    // Darkest first — more deprived is darker, which is what makes the
    // ramp encode the band order rather than decorate it.
    expect(fills[0]).toContain("--chart-seq-1");
    expect(fills[3]).toContain("--chart-seq-4");
  });

  it("does not run off the end of the ramp", () => {
    const rows = Array.from({ length: 7 }, (_, i) => ({ key: `k${i}`, label: `L${i}`, count: i + 1 }));
    render(<HomeBarChart rows={rows} ramp/>);
    expect(bars().every(b => b.style.background.includes("--chart-seq-"))).toBe(true);
  });
});


describe("the band", () => {
  it("fetches all five series in one round-trip", async () => {
    await renderBand();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch.mock.calls[0][0]).toBe("/api/v1/rpt/dashboards/home-charts/");
  });

  it("renders every chart the operator asked for", async () => {
    await renderBand();
    for (const title of [
      "Households by PMT band", "Members by PMT band",
      "Records held before promotion", "DQA findings by rule",
      "Households enrolled, by programme",
    ]) {
      expect(screen.getByText(title), title).toBeTruthy();
    }
  });

  it("follows the drill-down", async () => {
    await renderBand({ region: "SR-ACHOLI-NORTHERN", regionLabel: "Acholi" });
    expect(globalThis.fetch.mock.calls[0][0])
      .toBe("/api/v1/rpt/dashboards/home-charts/?region=SR-ACHOLI-NORTHERN");
  });

  it("states the scope on every card", async () => {
    // The screen gets printed. A chart covering Acholi that reads as
    // national is wrong in a way its reader cannot detect.
    await renderBand({ region: "SR-ACHOLI-NORTHERN", regionLabel: "Acholi" });
    await waitFor(() => expect(screen.getAllByText("Acholi").length).toBe(5));
  });

  it("says 'all regions in scope' when not drilled in", async () => {
    await renderBand();
    await waitFor(() => expect(screen.getAllByText("All regions in scope").length).toBe(5));
  });

  it("refetches when the drill-down changes", async () => {
    const { rerender } = render(<HomeChartBand region=""/>);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    rerender(<HomeChartBand region="SR-ACHOLI-NORTHERN"/>);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
  });

  it("labels the DQA chart a count, not a rate", async () => {
    // Only failures are persisted, so a long bar means "this rule
    // produced this many findings", not "this rule fails often".
    await renderBand();
    expect(screen.getByText(/a count, not a failure rate/)).toBeTruthy();
  });

  it("says enrolment is per household, not per person", async () => {
    await renderBand();
    expect(screen.getByText(/per household, not per person/)).toBeTruthy();
  });
});


describe("when the data does not arrive", () => {
  it("shows nothing rather than something wrong", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 500 }));
    render(<HomeChartBand/>);
    await waitFor(() => expect(screen.getAllByText(/Could not load/).length).toBe(5));
    // No invented series. A fabricated chart on an operator surface is
    // a decision made about households nobody counted. (Static copy may
    // contain digits — "last 30 days" — so this asserts that no COUNT
    // was rendered, not that no digit appears anywhere.)
    expect(bars()).toHaveLength(0);
    for (const n of ["42", "26", "220", "241", "918", "66", "10"]) {
      expect(screen.queryByText(n), `invented a count: ${n}`).toBeNull();
    }
  });

  it("survives the network rejecting outright", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline")));
    render(<HomeChartBand/>);
    await waitFor(() => expect(screen.getAllByText(/Could not load/).length).toBe(5));
  });

  it("distinguishes loading from failed", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {}));   // never settles
    render(<HomeChartBand/>);
    expect(screen.getAllByText("Loading…").length).toBe(5);
    expect(screen.queryByText(/Could not load/)).toBeNull();
  });

  it("an empty series is not an error", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({ ...PAYLOAD, enrolments_by_programme: [] }),
    }));
    render(<HomeChartBand/>);
    await waitFor(() => expect(
      screen.getByText("No active enrolments in this scope.")).toBeTruthy());
    expect(screen.queryByText(/Could not load/)).toBeNull();
  });
});


describe("the card", () => {
  it("shows its children only once ready", () => {
    render(<HomeChartCard title="T" state="loading"><div>body</div></HomeChartCard>);
    expect(screen.queryByText("body")).toBeNull();
    cleanup();
    render(<HomeChartCard title="T" state="ready"><div>body</div></HomeChartCard>);
    expect(screen.getByText("body")).toBeTruthy();
  });

  it("carries a heading so the band is navigable", async () => {
    await renderBand();
    const headings = within(document.body).getAllByRole("heading");
    expect(headings.map(h => h.textContent)).toContain("Registry at a glance");
  });
});
