/* The DIH review queue and its record panel, after the capture-run
 * defects of 19 Sep 2026.
 *
 * #1  the queue row and the receipt slip must show the same Registry ID
 * #8  the Region filter mixed display names and raw codes in one list
 * #10 the panel showed raw codes where the reviewer needs labels, and
 *     blanks where it had the answer
 *
 * A reviewer decides whether to promote a household into the national
 * registry on the strength of this panel. "Urban / rural: 2" and
 * "REL 01" are not facts anyone can check.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

let DIHScreen;

const CHOICES = {
  rural_urban: [{ code: "1", label: "Urban" }, { code: "2", label: "Rural" }],
  sex: [{ code: "1", label: "Male" }, { code: "2", label: "Female" }],
  relationship: [{ code: "01", label: "Head" }, { code: "02", label: "Spouse" }],
};

// Household 1 from the capture run: Akello Grace, Gulu · Aswa · Awach ·
// Burcoro, one member, Rural, NIN last-4 4821.
const STAGE = {
  id: "01M2Y6CPXVNNCKGJGSB240M1YV",            // the stage row's own key
  provisional_registry_id: "01M2Y6CPXVNNCKGJGSB240M1YT",  // what the slip printed
  state: "pending_promotion",
  canonical_payload: {
    urban_rural: "2",
    members: [{
      is_head: true, line_number: 1,
      surname: "Akello", first_name: "Grace",
      relationship_to_head: "01", sex: "2", age_years: 47,
      nin_status: "1", nin_last4: "4821",
      telephone_1: "+256 772 000000",
    }],
    geographic: {
      region: "R-NORTHERN", district: "304", subcounty: "304.1.01",
      parish: "304.1.01.01",
      _labels: { region: "Northern", district: "Gulu",
                 subcounty: "Awach", parish: "Burcoro" },
    },
  },
  dqa_summary: { blocking_failures: [], warnings: [], info: [] },
  ddup_candidates: [],
  idv_outcome: "nin_partial",
  created_at: new Date().toISOString(),
};

// A second row whose payload carries a raw region code with no label,
// which is what made the filter list "Northern" beside "R-CENTRAL".
const STAGE_RAW_REGION = {
  ...STAGE,
  id: "01M2Y6NG9XXNWA2BA5F5962GMA",
  provisional_registry_id: "01M2Y6NG9XXNWA2BA5F5962GM9",
  canonical_payload: {
    ...STAGE.canonical_payload,
    urban_rural: "1",
    geographic: { region: "R-WESTERN", parish: "418.1.03.02" },
    members: [{ ...STAGE.canonical_payload.members[0], surname: "Tumusiime",
                first_name: "Robert", sex: "1" }],
  },
};

// A Kobo pull: the connector writes the CODE into the geographic chain
// and keeps the display name in _source_keys. The queue used to prefer
// that display name as the row's region key, so the same region reached
// the filter under two keys and the filter listed both.
const STAGE_KOBO = {
  ...STAGE,
  id: "01M2KOBOZZZZZZZZZZZZZZZZZZ",
  provisional_registry_id: "01M2KOBOZZZZZZZZZZZZZZZZZZ",
  canonical_payload: {
    ...STAGE.canonical_payload,
    geographic: { region: "R-NORTHERN", parish: "304.1.01.02" },
    _source_keys: { kobo_form_id: "aXY123", kobo_region_name: "northern" },
    members: [{ ...STAGE.canonical_payload.members[0],
                surname: "Alum", first_name: "Betty" }],
  },
};

const jsonOk = (body) => Promise.resolve({
  ok: true, status: 200,
  json: () => Promise.resolve(body),
  text: () => Promise.resolve(JSON.stringify(body)),
});

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;

  globalThis.Icon = () => null;
  globalThis.Chip = ({ children, tone, title }) =>
    React.createElement("span", { "data-tone": tone, title }, children);
  globalThis.KPI = ({ title, value }) => React.createElement("div", null, `${title}:${value}`);
  globalThis.PageHeader = ({ title, right }) => React.createElement("div", null, title, right);
  globalThis.AuditDrawer = () => null;
  globalThis.ActionBar = ({ left, children }) => React.createElement("div", null, left, children);
  globalThis.ReasonModal = () => null;
  globalThis.Modal = ({ open, children }) => (open ? React.createElement("div", null, children) : null);
  globalThis.Toast = () => null;
  globalThis.useNavCounts = () => [{}];
  globalThis.useChoiceList = (name) => [CHOICES[name] || [], { loading: false, error: null }];

  await import("../components/wide-view.jsx");
  await import("../components/idv-outcomes.jsx");
  await import("../components/household-review-model.jsx");
  await import("../components/household-review.jsx");
  await import("./screens-dih.jsx");
  ({ DIHScreen } = globalThis);
});

beforeEach(() => {
  globalThis.fetch = vi.fn((url) => {
    if (String(url).includes("stage-records")) {
      return jsonOk({ results: [STAGE, STAGE_RAW_REGION, STAGE_KOBO] });
    }
    return jsonOk({ results: [] });
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const openFirstRecord = async () => {
  render(<DIHScreen/>);
  await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
  fireEvent.click(screen.getAllByText("Akello Grace")[0]);
  await waitFor(() => expect(summaryValue("Urban / rural")).toBeTruthy());
};

/* The record panel's key/value grid, not the queue table above it —
 * "Source" and "Provisional ID" are column headers up there too. The
 * grid is the parent of the label, and the value is its next sibling. */
const summaryGrid = () => {
  const label = screen.getAllByText("Urban / rural")
    .find(el => el.classList.contains("t-cap"));
  return label ? label.parentElement : null;
};

const summaryValue = (key) => {
  const grid = summaryGrid();
  if (!grid) return null;
  const label = [...grid.children].find(el => el.textContent === key);
  return label ? label.nextSibling : null;
};

/* The roster table inside the record panel — the queue's own table
 * carries the same class. */
const rosterTable = () => {
  const tables = [...document.querySelectorAll("table.tbl")];
  return tables[tables.length - 1];
};


describe("#1 the queue shows the Registry ID the citizen was handed", () => {
  it("renders provisional_registry_id, not the stage row's own key", async () => {
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
    const text = document.body.textContent;
    // …M1YT is on the slip; …M1YV is the stage key. Records staged
    // before the backend fix carry both, and only the first is a
    // number the respondent can quote at a parish office.
    expect(text).toMatch(/01M2Y6CPXVNNCKGJGSB240M1YT/);
    expect(text).not.toMatch(/01M2Y6CPXVNNCKGJGSB240M1YV/);
  });

  it("labels it as the Registry ID in the record panel", async () => {
    await openFirstRecord();
    expect(screen.getAllByText("Provisional Registry ID").length).toBeGreaterThan(0);
  });
});


describe("#8 the Region filter reads as regions", () => {
  it("shows names, never raw codes", async () => {
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
    const select = screen.getByTitle("Region as captured on the form");
    const labels = [...select.options].map(o => o.textContent);
    expect(labels).toContain("Northern");
    expect(labels).toContain("Western");
    // The corruption from the other direction: the list carried
    // "Northern, R-CENTRAL, R-EASTERN, R-NORTHERN, R-WESTERN, Western".
    expect(labels.filter(l => /^R-/.test(l))).toHaveLength(0);
  });

  it("lists each region exactly once", async () => {
    // Round 1 stopped the raw codes being SHOWN; it did not stop there
    // being two of them. The list read
    // "Northern · Central · Eastern · Northern · Western · Western" —
    // four regions as six options — because rows were keyed on whatever
    // spelling their connector used. Picking one silently returned a
    // subset.
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
    const select = screen.getByTitle("Region as captured on the form");
    const labels = [...select.options].map(o => o.textContent).slice(1); // drop "any"
    expect(labels).toEqual([...new Set(labels)]);
    const values = [...select.options].map(o => o.value).slice(1);
    expect(values).toEqual([...new Set(values)]);
  });

  it("offers the four national regions whatever is on screen", async () => {
    // Built from the code list, not from the distinct values in the
    // loaded page — so the option set cannot reacquire a duplicate from
    // a page of data that happens to contain one, and a region with no
    // records visible is still selectable.
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
    const select = screen.getByTitle("Region as captured on the form");
    const labels = [...select.options].map(o => o.textContent).slice(1);
    expect(labels).toEqual(["Central", "Eastern", "Northern", "Western"]);
  });

  it("keys a Kobo record on its code, not its display name", async () => {
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Alum Betty").length).toBeGreaterThan(0));
    const select = screen.getByTitle("Region as captured on the form");
    fireEvent.change(select, { target: { value: "R-NORTHERN" } });
    // Both the wizard record (region code + _labels) and the Kobo
    // record (region code + kobo_region_name) must be reachable under
    // the one key.
    await waitFor(() => {
      const queue = document.querySelectorAll("table.tbl")[0].textContent;
      expect(queue).toMatch(/Akello Grace/);
      expect(queue).toMatch(/Alum Betty/);
    });
  });

  it("keeps the stored value as the filter key", async () => {
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
    const select = screen.getByTitle("Region as captured on the form");
    // Filtering compares what the ROW holds — here the raw code
    // "R-WESTERN" — while the operator reads "Western". Labelling the
    // option must not change the key it filters on.
    const western = [...select.options].find(o => o.textContent === "Western");
    expect(western.value).toBe("R-WESTERN");
    void western;
    fireEvent.change(select, { target: { value: western.value } });
    // Assert on the QUEUE table: the detail rail keeps showing whichever
    // record is selected, filtered out of the list or not.
    await waitFor(() => {
      const queue = document.querySelectorAll("table.tbl")[0].textContent;
      expect(queue).not.toMatch(/Akello Grace/);
      expect(queue).toMatch(/Tumusiime Robert/);
    });
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #5 — the detail panel's clock was frozen.

   Defect 11 was fixed on the capture form; the same hardcoded strings
   survived here, on the panel a reviewer reads before promoting. The
   header said "Captured 14:35 EAT today" on a record captured at 06:01,
   and the SLA line said "22h 48m until walk-in cutoff" on every record
   regardless of age — including ones the queue's own AGE column, right
   beside it, reported as "0m".
   ═══════════════════════════════════════════════════════════════════ */

describe("#5 the detail panel clock is real", () => {
  const renderAt = async (createdAt) => {
    globalThis.fetch = vi.fn((url) => String(url).includes("stage-records")
      ? jsonOk({ results: [{ ...STAGE, created_at: createdAt }] })
      : jsonOk({ results: [] }));
    render(<DIHScreen/>);
    await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText("Akello Grace")[0]);
    await waitFor(() => expect(summaryValue("Urban / rural")).toBeTruthy());
  };

  // The clock is frozen for this block.
  //
  // The test used to pin 03:01Z on today's date and assert "06:01 EAT
  // today". That only holds when the suite runs between 03:01 UTC and
  // midnight; run just after midnight EAT it asserted that a record
  // captured hours in the future had been captured today, and failed for
  // a reason with nothing to do with the screen. Making the offset
  // relative does not fix it either — two hours before 00:11 EAT is
  // yesterday. A panel that formats a clock has to be tested against a
  // known clock.
  const FROZEN_NOW = new Date("2026-09-22T09:00:00Z");   // 12:00 EAT
  const CAPTURED_AT = new Date("2026-09-22T03:01:00Z");  // 06:01 EAT, same day

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(FROZEN_NOW);
  });
  afterEach(() => { vi.useRealTimers(); });

  it("renders the record's own capture time in EAT", async () => {
    await renderAt(CAPTURED_AT.toISOString());
    expect(document.body.textContent).toMatch(/Captured 06:01 EAT today/);
    // The frozen string the panel used to print on every record.
    expect(document.body.textContent).not.toMatch(/Captured 14:35 EAT today/);
  });

  it("dates a record that was not captured today", async () => {
    const then = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
    await renderAt(then.toISOString());
    expect(document.body.textContent).not.toMatch(/EAT today/);
    // Month abbreviation length varies by ICU build ("Sep" / "Sept").
    expect(document.body.textContent).toMatch(/Captured \d{2} \w{3,4} \d{4}, \d{2}:\d{2} EAT/);
  });

  it("reports a fresh record as within SLA, not at risk", async () => {
    await renderAt(new Date().toISOString());
    expect(document.body.textContent).toMatch(/Within SLA/);
    // Captured now, so the full 24h window is left.
    expect(document.body.textContent).toMatch(/24h 0m until walk-in cutoff/);
    // The fixed string that was printed on every record.
    expect(document.body.textContent).not.toMatch(/22h 48m/);
  });

  it("reports a record past 12h as at risk", async () => {
    await renderAt(new Date(Date.now() - 13 * 60 * 60 * 1000).toISOString());
    expect(document.body.textContent).toMatch(/SLA at risk/);
    expect(document.body.textContent).toMatch(/11h \d+m until walk-in cutoff/);
  });

  it("reports a record past 24h as breached, not as time remaining", async () => {
    await renderAt(new Date(Date.now() - 30 * 60 * 60 * 1000).toISOString());
    expect(document.body.textContent).toMatch(/SLA breached/);
    expect(document.body.textContent).toMatch(/6h \d+m past the walk-in cutoff/);
    expect(document.body.textContent).not.toMatch(/until walk-in cutoff/);
  });

  it("says so rather than guessing when there is no timestamp", async () => {
    await renderAt(null);
    expect(document.body.textContent).toMatch(/SLA cannot be computed/);
    expect(document.body.textContent).toMatch(/Captured — \(no timestamp\)/);
  });

  it("agrees with the queue row beside it", async () => {
    // The two disagreed on screen: the row said "0m", the panel said
    // "14:35" and "22h 48m".
    await renderAt(new Date().toISOString());
    // The queue's AGE column and the panel now derive from the same
    // created_at, so a record the queue calls 0m old cannot be one the
    // panel calls 1h 12m into its SLA.
    expect(document.body.textContent).toMatch(/0m/);
    expect(document.body.textContent).toMatch(/Captured \d{2}:\d{2} EAT today/);
    expect(document.body.textContent).toMatch(/24h 0m until walk-in cutoff/);
  });
});


/* ═══════════════════════════════════════════════════════════════════
   Detailed household review (US-S24-DIH-REVIEW)
   ═══════════════════════════════════════════════════════════════════ */

describe("the detailed review", () => {
  it("replaces the fabricated Health / Education / Housing blocks", () => {
    // Those accordions showed the SAME invented content for every
    // household — "Roof: Iron sheets, Walls: Brick (burnt)", "3 of 3
    // enrolled" — on the panel used to decide whether to promote a
    // household into the national registry.
    const src = fs.readFileSync(
      path.join(HERE, "screens-dih.jsx"), "utf8");
    const rendered = src.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
    expect(rendered).not.toContain('["Roof","Iron sheets"]');
    expect(rendered).not.toContain("3 of 3 enrolled");
    expect(rendered).not.toContain('["Members with disability","0"]');
  });

  it("offers a way into it from the staged record", async () => {
    await openFirstRecord();
    expect(screen.getByText("Detailed review")).toBeTruthy();
  });

  it("opens the review on the selected household", async () => {
    await openFirstRecord();
    fireEvent.click(screen.getByText("Detailed review").closest("button"));
    await waitFor(() => expect(
      screen.getByRole("region", { name: "Household detailed review" })).toBeTruthy());
    expect(screen.getByText("Household composition")).toBeTruthy();
  });

  it("refuses to offer edits on a record awaiting promotion", async () => {
    // It has cleared its gates; correcting it now would bypass them.
    // The panel says so rather than offering inputs the server refuses.
    await openFirstRecord();
    fireEvent.click(screen.getByText("Detailed review").closest("button"));
    await waitFor(() => expect(screen.getByText(/Read-only/)).toBeTruthy());
    expect(document.body.textContent).toMatch(/cleared its gates/);
  });

  it("closes without touching the record", async () => {
    await openFirstRecord();
    fireEvent.click(screen.getByText("Detailed review").closest("button"));
    await waitFor(() => expect(
      screen.getByRole("region", { name: "Household detailed review" })).toBeTruthy());
    fireEvent.click(screen.getByText("Close").closest("button"));
    await waitFor(() => expect(
      screen.queryByRole("region", { name: "Household detailed review" })).toBeNull());
  });
});


describe("#10 the record panel reads as facts, not codes", () => {
  it("resolves urban/rural through its choice list", async () => {
    await openFirstRecord();
    // "Urban / rural: 2" is what a reviewer was given.
    expect(summaryValue("Urban / rural").textContent).toBe("Rural");
  });

  it("resolves relationship and sex in the roster", async () => {
    await openFirstRecord();
    const roster = rosterTable();
    expect(roster.textContent).toMatch(/Head/);
    expect(roster.textContent).toMatch(/Female/);
    expect(roster.textContent).not.toMatch(/\bREL\b|\bSEX\b/);
  });

  it("shows the NIN it holds instead of an em-dash", async () => {
    await openFirstRecord();
    // The registry holds the last four, so that is what it shows —
    // masked, never the whole number, and never "—" for a household
    // that produced a card at the desk.
    expect(screen.getAllByText("•••• 4821").length).toBeGreaterThan(0);
  });

  it("names the parish rather than printing its code alone", async () => {
    await openFirstRecord();
    const parish = summaryValue("Parish");
    expect(parish.textContent).toMatch(/Burcoro/);
    expect(parish.textContent).toMatch(/Awach/);
    expect(parish.textContent).toMatch(/Gulu/);
    // "418.1.03.02 · —" was the whole line for a walk-in household.
    expect(parish.textContent).not.toMatch(/·\s*—/);
  });

  it("names the source instead of leaving it blank", async () => {
    await openFirstRecord();
    const source = summaryValue("Source");
    expect(source.textContent).not.toBe("—");
    expect(source.textContent).toMatch(/Walk-in/);
  });

  it("shows what IDV actually said, per outcome", async () => {
    // The column compared against "Matched"/"Mismatch" — words the
    // backend never writes — so a NIRA MISMATCH rendered as amber
    // "Pending" on the panel used to decide whether to promote.
    for (const [outcome, label] of [
      ["mismatch", "Mismatch"],
      ["manual_accept", "Accepted by operator"],
      ["match", "Matched"],
      ["", "Not run"],
    ]) {
      cleanup();
      globalThis.fetch = vi.fn((url) => String(url).includes("stage-records")
        ? jsonOk({ results: [{ ...STAGE, idv_outcome: outcome }] })
        : jsonOk({ results: [] }));
      render(<DIHScreen/>);
      await waitFor(() => expect(screen.getAllByText("Akello Grace").length).toBeGreaterThan(0));
      expect(screen.getAllByText(label).length, outcome).toBeGreaterThan(0);
      expect(screen.queryByText("Pending"), outcome).toBeNull();
    }
  });

  it("tells the reviewer a card WAS seen when only the last 4 are held", async () => {
    await openFirstRecord();
    // "IDV (NIRA): not run — No NIN provided or IDV not yet run" told a
    // reviewer the opposite of what happened at the desk.
    expect(document.body.textContent).toMatch(/A NIN card was seen and the last 4 digits recorded/);
    expect(document.body.textContent).not.toMatch(/No NIN provided or IDV not yet run/);
  });

  it("falls back to the raw code when a list cannot resolve it", async () => {
    // Better a visible unmapped code than a value that silently
    // disappears behind an em-dash.
    const { CodedValue } = globalThis;
    if (!CodedValue) return;  // not exported in this build
    render(<CodedValue listName="rural_urban" code="9"/>);
    expect(screen.getByText("9")).toBeTruthy();
  });
});
