/* Regression tests for the household-capture defects found running two
 * households end to end through the Operator Console (19 Sep 2026).
 *
 * The wizard half. The backend half is in
 * apps/ingestion_hub/test_capture_defects.py,
 * apps/dqa/test_per_member_required.py and
 * apps/reference_data/test_code_frame_cleanup.py.
 *
 * Covers #1 (slip ID), #3 (per-member validation), #4 (age from date of
 * birth), #6 (SMS vs consent), #7 (the phantom skip-logic rule),
 * #11 (the frozen clock), #12 (whose location the slip prints),
 * #13 (an escaped unicode sequence printed as text) and #14 (the footer
 * on the last section).
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESIGN = path.resolve(HERE, "..", "..");

let CaptureScreen, ReceiptSlipA6, ReceiptOverlay;
let ageFromDateOfBirth, memberDetailGaps;

// The seeded lists the wizard's selects read through useChoiceList.
const CHOICES = {
  yes_no: [{ code: "1", label: "Yes" }, { code: "2", label: "No" }],
  rural_urban: [{ code: "1", label: "Urban" }, { code: "2", label: "Rural" }],
  sex: [{ code: "1", label: "Male" }, { code: "2", label: "Female" }],
  relationship: [{ code: "01", label: "Head" }, { code: "02", label: "Spouse" }],
  literacy_status: [{ code: "1", label: "Can read and write" }],
  nin_status: [{ code: "1", label: "Yes, has card" }, { code: "8", label: "Don't know" }],
};

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;

  globalThis.Icon = ({ name }) => React.createElement("i", { "data-icon": name });
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.KPI = () => null;
  globalThis.PageHeader = ({ sub, right }) =>
    React.createElement("div", null, React.createElement("div", null, sub), right);
  globalThis.ActionBar = ({ left, children }) => React.createElement("div", null, left, children);
  globalThis.ReasonModal = () => null;
  globalThis.Modal = ({ open, title, children, footer }) => (open
    ? React.createElement("div", { role: "dialog", "aria-label": title }, children, footer)
    : null);
  globalThis.GeoTreePicker = () => null;
  globalThis.useChoiceList = (name) => [CHOICES[name] || [], { loading: false, error: null }];

  await import("../components/wide-view.jsx");
  await import("../../components.jsx");
  await import("./consent/consent-shared.jsx");
  await import("./consent/consent-capture-block.jsx");
  await import("./screens-capture-sections.jsx");
  await import("./screens-capture.jsx");

  ({ CaptureScreen, ReceiptSlipA6, ReceiptOverlay,
     ageFromDateOfBirth, memberDetailGaps } = globalThis);
});

beforeEach(() => {
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve({ results: [] }),
    text: () => Promise.resolve('{"results":[]}'),
  }));
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const source = (rel) => fs.readFileSync(path.join(DESIGN, rel), "utf8");

// What the browser would actually draw: source minus every comment. A
// comment that quotes the old string is how these fixes are documented,
// so the assertions have to look past them.
const stripComments = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");


/* ═══════════════════════════════════════════════════════════════════
   #4 — Age was not derived from date of birth.

   Date of birth 1979-03-12 with Age left blank made sections 3, 4 and 5
   report "No members meet the age threshold (2+)" with no member chips,
   for a head who is 47. The hint under Age read "Computed from DoB on
   save when both supplied", which computes the age only once an age is
   already there.
   ═══════════════════════════════════════════════════════════════════ */

describe("#4 age derived from date of birth", () => {
  it("derives the reported case: 1979-03-12 is 47 on 19 Sep 2026", () => {
    expect(ageFromDateOfBirth("1979-03-12", new Date("2026-09-19T12:00:00Z"))).toBe(47);
  });

  it("counts completed years, not calendar-year differences", () => {
    // Birthday not yet reached in the reference year.
    expect(ageFromDateOfBirth("1979-12-31", new Date("2026-09-19T00:00:00Z"))).toBe(46);
    // Birthday is today.
    expect(ageFromDateOfBirth("1979-09-19", new Date("2026-09-19T00:00:00Z"))).toBe(47);
    // Birthday was yesterday.
    expect(ageFromDateOfBirth("1979-09-18", new Date("2026-09-19T00:00:00Z"))).toBe(47);
  });

  it("returns null rather than a wrong number for unusable input", () => {
    const asOf = new Date("2026-09-19T00:00:00Z");
    for (const bad of ["", null, undefined, "12/03/1979", "1979-3-12",
                       "2026-02-31", "2030-01-01", "1800-01-01"]) {
      expect(ageFromDateOfBirth(bad, asOf), String(bad)).toBeNull();
    }
  });

  it("no longer tells the operator the age computes itself from itself", () => {
    expect(source("v0.1/screens/screens-capture-sections.jsx"))
      .not.toContain("Computed from DoB on save when both supplied");
  });

  it("the age-threshold filters read the derived age", () => {
    // memberDetailGaps applies the section's age threshold. A member
    // with a date of birth and a blank Age used to read as age 0 and
    // drop out of every threshold filter — which is the same defect
    // seen from the validator's side.
    const members = [{ line_number: 1, first_name: "Grace", surname: "Akello",
                       date_of_birth: "1979-03-12", age_years: null }];
    const gaps = memberDetailGaps("hd", members, {});
    expect(gaps).toHaveLength(1);
    expect(gaps[0].missing).toContain("Has chronic illness?");
  });

  it("a member below the threshold is not asked, so is not a gap", () => {
    const members = [{ line_number: 1, date_of_birth: "2025-06-01" }];  // age 1
    expect(memberDetailGaps("hd", members, {})).toHaveLength(0);
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #3 — Per-member required fields were validated for the selected
   member only.

   Household 2 had 3 members. "Has chronic illness?" was answered for
   member #1 only; Next was not blocked, Health & Disability never got a
   completion tick, and the wizard allowed the walk to section 7 and
   submission.
   ═══════════════════════════════════════════════════════════════════ */

describe("#3 every member is validated, not just the visible one", () => {
  const threeMembers = [
    { line_number: 1, first_name: "Robert", surname: "Tumusiime", age_years: 44 },
    { line_number: 2, first_name: "Joyce", surname: "Tumusiime", age_years: 38 },
    { line_number: 3, first_name: "Peter", surname: "Tumusiime", age_years: 12 },
  ];

  it("reports the members who are missing an answer, not just that some are", () => {
    const healthData = { 1: { health: { chronic_illness_flag: "1" } } };
    const gaps = memberDetailGaps("hd", threeMembers, healthData);
    expect(gaps.map(g => g.line_number)).toEqual([2, 3]);
    expect(gaps[0].label).toBe("Joyce Tumusiime");
  });

  it("is satisfied only when every member above the threshold is answered", () => {
    const healthData = Object.fromEntries(
      [1, 2, 3].map(n => [n, { health: { chronic_illness_flag: "2" } }]));
    expect(memberDetailGaps("hd", threeMembers, healthData)).toHaveLength(0);
  });

  it("treats an empty string as unanswered", () => {
    const healthData = {
      1: { health: { chronic_illness_flag: "" } },
      2: { health: { chronic_illness_flag: "2" } },
      3: { health: { chronic_illness_flag: "2" } },
    };
    expect(memberDetailGaps("hd", threeMembers, healthData).map(g => g.line_number))
      .toEqual([1]);
  });

  it("applies each section's own age threshold", () => {
    // Education is asked of age 3+; a 2-year-old is out of scope for it
    // but in scope for health (age 2+).
    const members = [{ line_number: 1, age_years: 2 }];
    expect(memberDetailGaps("ed", members, {})).toHaveLength(0);
    expect(memberDetailGaps("hd", members, {})).toHaveLength(1);
  });

  it("does not excuse a member whose age is unknown", () => {
    // An absent age is the roster validator's problem. Skipping the
    // member here would reopen the same hole from the other end.
    const members = [{ line_number: 1, age_years: null, date_of_birth: "" }];
    expect(memberDetailGaps("hd", members, {})).toHaveLength(1);
  });

  it("wires the gaps into the wizard's section validators", () => {
    const src = source("v0.1/screens/screens-capture.jsx");
    expect(src).toMatch(/hd:\s*_validatePerMember\("hd", "healthData"\)/);
    expect(src).toMatch(/ed:\s*_validatePerMember\("ed", "educationData"\)/);
    // The advisory no-op no longer covers the per-member sections.
    expect(src).not.toMatch(/hd:\s*_validateAdvisory/);
    expect(src).not.toMatch(/ed:\s*_validateAdvisory/);
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #1 — The receipt slip printed a Registry ID one increment off the
   staged record, and the SMS preview carried the same wrong ID.
   ═══════════════════════════════════════════════════════════════════ */

describe("#1 the slip renders the persisted Registry ID and nothing else", () => {
  const PERSISTED = "01M2Y6CPXVNNCKGJGSB240M1YT";

  it("prints the ID it was given", () => {
    render(<ReceiptSlipA6 provisionalId={PERSISTED} captured={{}}/>);
    expect(screen.getByText(PERSISTED)).toBeTruthy();
  });

  it("invents nothing when the server did not return one", () => {
    render(<ReceiptSlipA6 provisionalId={null} captured={{}}/>);
    // A slip carrying a plausible ID the registry has never heard of is
    // worse than one that says no ID was issued.
    expect(document.body.textContent).not.toMatch(/01[A-HJKMNP-TV-Z0-9]{24}/);
    expect(screen.getByText(/NOT ISSUED/)).toBeTruthy();
  });

  it("the slip and the SMS preview show the same ID", () => {
    render(<ReceiptOverlay provisionalId={PERSISTED} captured={{}} onClose={() => {}}/>);
    const shown = screen.getAllByText(
      (_, node) => (node.textContent || "").includes(PERSISTED));
    // At minimum: the slip's ID block and the SMS preview body.
    expect(shown.length).toBeGreaterThan(1);
    expect(document.body.textContent)
      .toMatch(new RegExp(`Your provisional Registry ID is ${PERSISTED}`));
  });

  it("offers nothing to print when no ID came back", () => {
    render(<ReceiptOverlay provisionalId={null} captured={{}} onClose={() => {}}/>);
    expect(screen.getByText(/No Registry ID was issued/)).toBeTruthy();
    expect(screen.queryByText(/SMS PREVIEW/)).toBeNull();
    expect(screen.getByText(/Do not hand out a slip/)).toBeTruthy();
  });

  it("the queue and the slip read the same field", () => {
    // _stageToRow feeds the queue; both sides must resolve to the
    // StageRecord's provisional_registry_id, which the backend now
    // issues as a single ULID shared with `id`.
    const dih = source("v0.1/screens/screens-dih.jsx");
    expect(dih).toContain("registryId: stage.provisional_registry_id || stage.id");
    expect(dih).not.toContain("current.id, \"mono\"");
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #6 — SMS was announced even when the respondent opted out of SMS.
   ADR-0031: the registry-ID message is transactional and exempt; every
   other SMS honours COMMUNICATIONS_SMS, and the dialog and the receipt
   say which is which.
   ═══════════════════════════════════════════════════════════════════ */

describe("#6 the SMS statement matches the consent that was recorded", () => {
  // A contact number is required for any of this to be about consent at
  // all — with none, the answer is "nothing was sent", whatever the
  // consent says (ADR-0033, covered in screens-capture.round2.test.jsx).
  const renderReceipt = (smsConsent) => render(
    <ReceiptOverlay provisionalId="01M2Y6CPXVNNCKGJGSB240M1YT"
      captured={{ smsConsent, contactPhone: "+256782998877" }} onClose={() => {}}/>);

  it("says no further SMS will follow when the purpose was refused", () => {
    renderReceipt("REFUSED");
    expect(document.body.textContent).toMatch(/no other SMS will follow/i);
    expect(document.body.textContent).toMatch(/service message sent as part of registration/i);
  });

  it("says the same when the purpose was never asked", () => {
    renderReceipt("");
    expect(document.body.textContent).toMatch(/no other SMS will follow/i);
  });

  it("acknowledges the agreement when the purpose was granted", () => {
    renderReceipt("GRANTED");
    expect(document.body.textContent).toMatch(/agreed to further SMS updates/);
  });

  it("never claims an unqualified 'an SMS has been queued'", () => {
    renderReceipt("REFUSED");
    expect(document.body.textContent)
      .not.toMatch(/An SMS has been queued to the number recorded for this household\./);
    // It names the number instead of referring to "the number recorded".
    expect(document.body.textContent).toMatch(/\+256782998877/);
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #13 — "’" printed as text in the submit dialog.
   ═══════════════════════════════════════════════════════════════════ */

describe("#13 no escaped unicode sequence is printed as text", () => {
  const FILES = [
    "v0.1/screens/screens-capture.jsx",
    "v0.1/screens/screens-capture-sections.jsx",
    "v0.1/screens/screens-dih.jsx",
    "v0.1/screens/consent/consent-shared.jsx",
    "v0.1/screens/consent/consent-capture-block.jsx",
    "components.jsx",
  ];

  it.each(FILES)("%s has no \\u escape in JSX text", (rel) => {
    // Inside a string literal a \u escape is correct and common
    // (screens-home.jsx uses "—"). In JSX TEXT it is not an escape
    // at all — it is six characters the browser draws verbatim, which is
    // what the submit dialog did with the respondent's apostrophe.
    // Comments are stripped first: several of them quote the old string
    // in order to document the fix.
    const offenders = stripComments(source(rel)).split("\n")
      .map((line, i) => [i + 1, line])
      // A \u sequence with no quote anywhere on the line is text, not a
      // string literal.
      .filter(([, line]) => /\\u[0-9a-fA-F]{4}/.test(line) && !/["'`]/.test(line));
    expect(offenders, JSON.stringify(offenders)).toHaveLength(0);
  });

  it("the submit dialog reads as prose", () => {
    const src = source("v0.1/screens/screens-capture.jsx");
    expect(src).not.toContain("respondent\\u2019s registered number");
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #7 — SKIP-FS-URBAN did nothing. The hint promised Food & Shocks would
   lose 4 questions for an Urban household; it never did, and it should
   not: FIES (8 items) and FCS (9 food groups) are standardised scales
   whose raw scores are only comparable when every item is asked.
   ═══════════════════════════════════════════════════════════════════ */

describe("#7 no rule is promised that does not exist", () => {
  it("the hint is gone from the wizard", () => {
    const src = source("v0.1/screens/screens-capture.jsx");
    // Only the comment explaining the removal may mention it.
    const rendered = stripComments(src);
    expect(rendered).not.toContain("SKIP-FS-URBAN");
    expect(rendered).not.toContain("will reduce by 4 questions");
  });

  it("Food & Shocks still asks all 8 FIES items and all 9 food groups", () => {
    const src = source("v0.1/screens/screens-capture-sections.jsx");
    const fies = src.match(/\["(worried_food|unhealthy_food|limited_variety|skipped_meal|ate_less|ran_out_food|hungry_no_eat|whole_day_no_eat)",/g);
    expect(new Set(fies)).toHaveProperty("size", 8);
    const groups = src.match(/const FOOD_GROUPS = \[([\s\S]*?)\];/)[1]
      .match(/\["\w+",/g);
    expect(groups).toHaveLength(9);
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #11 / #12 — the capture screen's date was stuck at 14 May 2026, and
   the slip printed the operator's office as the household's location.
   ═══════════════════════════════════════════════════════════════════ */

describe("#11 the clock is real", () => {
  it("no hardcoded timestamp survives in the capture screen", () => {
    const src = source("v0.1/screens/screens-capture.jsx");
    const rendered = stripComments(src);
    expect(rendered).not.toMatch(/14 May 2026/);
    expect(rendered).not.toMatch(/\b14:3[0-9] EAT/);
  });

  it("renders the instant it is given, in EAT", () => {
    // 2026-09-19T11:34:00Z is 14:34 in Kampala (UTC+3).
    const at = new Date("2026-09-19T11:34:00Z");
    render(<ReceiptSlipA6 provisionalId="01M2Y6CPXVNNCKGJGSB240M1YT"
      captured={{ issuedAt: at }}/>);
    expect(screen.getByText("19 September 2026 · 14:34 EAT")).toBeTruthy();
  });
});

describe("#12 the slip says where the household is", () => {
  const captured = {
    issuedAt: new Date("2026-09-19T11:35:00Z"),
    // Canonical level keys — the wizard posts `sub_county`, not
    // `subcounty`; the mismatch between the two spellings is what
    // stranded every walk-in capture (see round 2).
    geo: { _labels: { district: "Gulu", sub_county: "Awach", parish: "Burcoro" } },
  };

  it("prints the household's own place", () => {
    render(<ReceiptSlipA6 provisionalId="01M2Y6CPXVNNCKGJGSB240M1YT" captured={captured}/>);
    expect(screen.getByText("Burcoro · Awach · Gulu")).toBeTruthy();
  });

  it("labels the office line so it cannot be read as the household's location", () => {
    render(<ReceiptSlipA6 provisionalId="01M2Y6CPXVNNCKGJGSB240M1YT" captured={captured}/>);
    expect(screen.getByText("Captured by office:")).toBeTruthy();
    expect(screen.getByText("Household at:")).toBeTruthy();
    // The bare, unqualified "Captured at:" is what was misread.
    expect(screen.queryByText("Captured at:")).toBeNull();
  });

  it("says nothing rather than something wrong when no place was chosen", () => {
    render(<ReceiptSlipA6 provisionalId="01M2Y6CPXVNNCKGJGSB240M1YT" captured={{}}/>);
    const row = screen.getByText("Household at:").nextSibling;
    expect(row.textContent).toBe("—");
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #14 — the footer said "Next: Food & Shocks" while on Food & Shocks,
   section 7 of 7, and clicking it did nothing.
   ═══════════════════════════════════════════════════════════════════ */

describe("#14 the wizard footer", () => {
  it("offers Review, not a Next to nowhere, on the last section", async () => {
    render(<CaptureScreen/>);
    // Walk to the last section via the left rail (the stepper and the
    // rail both navigate; neither is gated).
    fireEvent.click(screen.getAllByText("Food & Shocks")[0]);
    await waitFor(() => expect(screen.getByText(/SECTION 7 OF 7/)).toBeTruthy());
    expect(screen.queryByText(/Next: Food & Shocks/)).toBeNull();
    const review = screen.getByText("Review").closest("button");
    expect(review.disabled).toBe(true);
    expect(review.title).toMatch(/last section/i);
  });

  it("still advances from an earlier section", async () => {
    render(<CaptureScreen/>);
    fireEvent.click(screen.getAllByText("Housing")[0]);
    await waitFor(() => expect(screen.getByText(/SECTION 6 OF 7/)).toBeTruthy());
    expect(screen.getByText(/Next: Food & Shocks/)).toBeTruthy();
  });

  it("gives the form column a floor and a wide-view control", () => {
    // The form collapsed to ~250px at a 1104px window while the left
    // half of the screen sat empty, and selects truncated to "— S".
    expect(source("styles.css")).toMatch(/\.capture-grid\s*\{[^}]*minmax\(520px, 1fr\)/);
    expect(source("v0.1/screens/screens-capture.jsx")).toContain("WideViewButtons");
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #15 — no form control in the wizard had a <label for> or an
   aria-label, so every input returned an empty accessible name.
   ═══════════════════════════════════════════════════════════════════ */

describe("#15 every control has an accessible name", () => {
  it("labels a plain input through its Field", () => {
    const { Field } = globalThis;
    render(<Field label="Latitude" hint="e.g. 0.31628">
      <input className="field-input"/>
    </Field>);
    const input = screen.getByLabelText("Latitude");
    expect(input).toBeTruthy();
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
  });

  it("labels a select the same way", () => {
    const { Field } = globalThis;
    render(<Field label="Sex" required>
      <select><option value="">— Select —</option></select>
    </Field>);
    const select = screen.getByLabelText(/Sex/);
    expect(select.getAttribute("aria-required")).toBe("true");
  });

  it("names a segmented button group rather than a single button", () => {
    const { Field } = globalThis;
    render(<Field label="Urban / Rural">
      <div className="seg"><button>Urban</button><button>Rural</button></div>
    </Field>);
    expect(screen.getByRole("group", { name: "Urban / Rural" })).toBeTruthy();
  });

  it("announces the validation message with the field", () => {
    const { Field } = globalThis;
    render(<Field label="Accuracy" error="14 m — above the 10 m limit">
      <input/>
    </Field>);
    const input = screen.getByLabelText("Accuracy");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const described = document.getElementById(input.getAttribute("aria-describedby"));
    expect(described.textContent).toMatch(/above the 10 m limit/);
  });

  it("leaves a control that already declares its own id alone", () => {
    const { Field } = globalThis;
    render(<Field label="Given id"><input id="mine"/></Field>);
    expect(screen.getByLabelText("Given id").id).toBe("mine");
  });

  it("gives every repeat-group delete button a name", () => {
    const { RepeatGroup } = globalThis;
    render(<RepeatGroup
      rows={[{ v: "a" }, { v: "b" }]}
      onChange={() => {}}
      emptyRow={() => ({ v: "" })}
      columns={[{ key: "v", label: "Value", render: (v) => <input readOnly value={v}/> }]}
    />);
    expect(screen.getByRole("button", { name: "Remove row 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove row 2" })).toBeTruthy();
  });

  it("every control the wizard actually renders has a non-empty name", async () => {
    render(<CaptureScreen/>);
    await waitFor(() => expect(screen.getByText(/SECTION 1 OF 7/)).toBeTruthy());
    const unnamed = [...document.querySelectorAll("input, select, textarea")]
      .filter(el => {
        if (el.type === "hidden") return false;
        if (el.getAttribute("aria-label")) return false;
        const id = el.getAttribute("id");
        if (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) return false;
        return !el.closest("[role='group'][aria-labelledby]");
      })
      .map(el => `${el.tagName.toLowerCase()}#${el.id || "(no id)"}`);
    expect(unnamed, unnamed.join(", ")).toHaveLength(0);
  });
});

void within;
