/* Regression tests for the second capture run (20 Sep 2026).
 *
 * The wizard half. Backend in
 * apps/ingestion_hub/test_capture_defects_round2.py.
 *
 *   #2 the respondent phone reached nothing
 *   #3 every <select> in the wizard had an empty accessible name
 *
 * The selects are the interesting one. Round 1 fixed the accessible
 * name on raw <input> elements and its test asserted "no unnamed
 * control", counting a control inside a labelled role="group" as named.
 * That let fourteen selects through: <ChoiceSelect> and <GeoLevel> are
 * COMPONENTS, so the select is one level below the child <Field> can
 * clone, and a group's name is not the select's name. The tests here
 * assert the accessible name of each control, not the mechanism that
 * produced it.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let CaptureScreen, ReceiptOverlay, ReceiptSlipA6, householdContactPhone;

const CHOICES = {
  yes_no: [{ code: "1", label: "Yes" }, { code: "2", label: "No" }],
  rural_urban: [{ code: "1", label: "Urban" }, { code: "2", label: "Rural" }],
  sex: [{ code: "1", label: "Male" }, { code: "2", label: "Female" }],
  relationship: [{ code: "01", label: "Head" }, { code: "02", label: "Spouse" }],
  marital_status: [{ code: "1", label: "Married" }],
  birth_certificate: [{ code: "1", label: "Yes" }],
  nationality: [{ code: "1", label: "Ugandan" }],
  residency_status: [{ code: "1", label: "Usual resident" }],
  nin_status: [{ code: "1", label: "Yes, has card" }, { code: "8", label: "Don't know" }],
  literacy_status: [{ code: "1", label: "Can read and write" }],
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
  globalThis.useChoiceList = (name) => [CHOICES[name] || [], { loading: false, error: null }];
  // The real GeoTreePicker + Field come from components.jsx; useApi is
  // what GeoLevel fetches its rows through.
  globalThis.useApi = () => [{ results: [
    { code: "R-NORTHERN", name: "Northern" },
  ] }, { loading: false, error: null }];

  await import("../components/wide-view.jsx");
  await import("../../components.jsx");
  await import("./consent/consent-shared.jsx");
  await import("./consent/consent-capture-block.jsx");
  await import("./screens-capture-sections.jsx");
  await import("./screens-capture.jsx");

  ({ CaptureScreen, ReceiptOverlay, ReceiptSlipA6, householdContactPhone } = globalThis);
});

beforeEach(() => {
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve({ results: [] }),
    text: () => Promise.resolve('{"results":[]}'),
  }));
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

/* The accessible name of a control, by the rules an assistive
 * technology actually applies: aria-label, then aria-labelledby, then
 * an associated <label>. Deliberately does NOT count "is inside
 * something that has a name" — that was the hole in the round 1 check. */
const accessibleName = (el) => {
  const direct = el.getAttribute("aria-label");
  if (direct && direct.trim()) return direct.trim();
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy.split(/\s+/)
      .map(id => document.getElementById(id))
      .filter(Boolean)
      .map(n => n.textContent.trim())
      .join(" ")
      .trim();
    if (text) return text;
  }
  const id = el.getAttribute("id");
  if (id) {
    const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (label && label.textContent.trim()) return label.textContent.trim();
  }
  const wrapping = el.closest("label");
  if (wrapping && wrapping.textContent.trim()) return wrapping.textContent.trim();
  return "";
};

const controls = (selector) =>
  [...document.querySelectorAll(selector)].filter(el => el.type !== "hidden");

const openCapture = async () => {
  render(<CaptureScreen/>);
  await waitFor(() => expect(screen.getByText(/SECTION 1 OF 7/)).toBeTruthy());
};

const addHeadMember = async () => {
  fireEvent.click(screen.getAllByText("Roster")[0]);
  await waitFor(() => expect(screen.getByText(/SECTION 2 OF 7/)).toBeTruthy());
  fireEvent.click(screen.getAllByText("Add member")[0]);
  await waitFor(() => expect(screen.getByLabelText(/Surname/)).toBeTruthy());
};


/* ═══════════════════════════════════════════════════════════════════
   #3 — every dropdown was unlabelled
   ═══════════════════════════════════════════════════════════════════ */

describe("#3 accessible names", () => {
  it("names every select on the Identification tab", async () => {
    await openCapture();
    const selects = controls("select");
    expect(selects.length, "expected the geo chain to render").toBeGreaterThan(5);
    const unnamed = selects
      .filter(el => !accessibleName(el))
      .map(el => el.outerHTML.slice(0, 80));
    expect(unnamed, unnamed.join("\n")).toHaveLength(0);
  });

  it("names every select on the Roster tab too", async () => {
    await openCapture();
    await addHeadMember();
    const unnamed = controls("select")
      .filter(el => !accessibleName(el))
      .map(el => el.outerHTML.slice(0, 80));
    expect(unnamed, unnamed.join("\n")).toHaveLength(0);
  });

  it("gives each select the name of its own visible label", async () => {
    await openCapture();
    await addHeadMember();
    const sex = [...document.querySelectorAll("select")]
      .find(el => accessibleName(el).startsWith("Sex"));
    expect(sex, "no select is named 'Sex'").toBeTruthy();
    // Not the name of a neighbouring field, and not a group name.
    expect(accessibleName(sex)).toMatch(/^Sex/);
  });

  it("names every text and number input", async () => {
    await openCapture();
    await addHeadMember();
    const unnamed = controls("input, textarea")
      .filter(el => !accessibleName(el))
      .map(el => el.outerHTML.slice(0, 80));
    expect(unnamed, unnamed.join("\n")).toHaveLength(0);
  });

  it("says which Urban / Rural option is selected", async () => {
    await openCapture();
    const rural = screen.getByText("Rural").closest("button");
    const urban = screen.getByText("Urban").closest("button");
    // Rural is the default. Selection was communicated by CSS class
    // alone, so a screen reader could read both and tell you nothing.
    expect(rural.getAttribute("aria-pressed")).toBe("true");
    expect(urban.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(urban);
    expect(urban.getAttribute("aria-pressed")).toBe("true");
    expect(rural.getAttribute("aria-pressed")).toBe("false");
  });

  it("says which Yes / No option is selected", async () => {
    const { YesNoSeg } = globalThis;
    const Harness = () => {
      const [v, setV] = React.useState("");
      return <YesNoSeg value={v} onChange={setV}/>;
    };
    render(<Harness/>);
    const yes = screen.getByText("Yes").closest("button");
    const no = screen.getByText("No").closest("button");
    expect(yes.getAttribute("aria-pressed")).toBe("false");
    expect(no.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(yes);
    expect(yes.getAttribute("aria-pressed")).toBe("true");
    expect(no.getAttribute("aria-pressed")).toBe("false");
  });

  it("still names a segmented group that has no single control", () => {
    const { Field } = globalThis;
    render(<Field label="Urban / Rural">
      <div className="seg"><button>Urban</button><button>Rural</button></div>
    </Field>);
    expect(screen.getByRole("group", { name: "Urban / Rural" })).toBeTruthy();
  });
});


/* ═══════════════════════════════════════════════════════════════════
   #2 — the respondent phone reached nothing
   ═══════════════════════════════════════════════════════════════════ */

describe("#2 the household contact number", () => {
  it("is the head member's telephone", () => {
    expect(householdContactPhone([
      { line_number: 1, telephone_1: "+256782998877" },
      { line_number: 2, telephone_1: "+256700000000" },
    ])).toBe("+256782998877");
  });

  it("is empty, not undefined, when there is no head or no number", () => {
    expect(householdContactPhone([])).toBe("");
    expect(householdContactPhone(null)).toBe("");
    expect(householdContactPhone([{ line_number: 1 }])).toBe("");
    expect(householdContactPhone([{ line_number: 1, telephone_1: "  " }])).toBe("");
  });

  it("writes the Identification phone box through to the head member", async () => {
    await openCapture();
    await addHeadMember();
    // Back to Identification and type a number there.
    fireEvent.click(screen.getAllByText("Identification")[0]);
    await waitFor(() => expect(screen.getByLabelText(/Household phone/)).toBeTruthy());
    const box = screen.getByLabelText(/Household phone/);
    fireEvent.change(box, { target: { value: "+256782998877" } });

    // The roster's Telephone for Person 1 now shows the same value —
    // because it IS the same value, not a copy of it.
    fireEvent.click(screen.getAllByText("Roster")[0]);
    await waitFor(() => expect(screen.getByLabelText(/^Telephone/)).toBeTruthy());
    expect(screen.getByLabelText(/^Telephone/).value).toBe("+256782998877");
  });

  it("is disabled until there is a head to attach it to", async () => {
    await openCapture();
    expect(screen.getByLabelText(/Household phone/).disabled).toBe(true);
  });

  it("collects an address narrative", async () => {
    // Household.address_narrative existed and promotion read it;
    // nothing collected it, so every staged record showed Address —.
    await openCapture();
    expect(screen.getByLabelText(/Address narrative/)).toBeTruthy();
  });
});


describe("#2 the receipt names the number it used", () => {
  const ID = "01M2YC639696Y0CT44DJH2V351";

  it("prints the number when there is one", () => {
    render(<ReceiptOverlay provisionalId={ID} onClose={() => {}}
      captured={{ contactPhone: "+256782998877", smsConsent: "REFUSED" }}/>);
    expect(document.body.textContent).toMatch(/queued to\s*\+256782998877/);
  });

  it("says plainly that nothing was sent when there is none", () => {
    // "queued to the number recorded for this household" was asserted
    // on a household whose record held no number at all.
    render(<ReceiptOverlay provisionalId={ID} onClose={() => {}}
      captured={{ contactPhone: "", smsConsent: "REFUSED" }}/>);
    expect(document.body.textContent).toMatch(/No SMS has been sent/);
    expect(document.body.textContent).toMatch(/holds no\s*household contact number/);
    expect(document.body.textContent).not.toMatch(/has been queued/);
  });

  it("prints the number on the slip as well", () => {
    render(<ReceiptSlipA6 provisionalId={ID}
      captured={{ contactPhone: "+256782998877" }}/>);
    expect(screen.getByText("Contact number:")).toBeTruthy();
    expect(screen.getByText("+256782998877")).toBeTruthy();
  });

  it("says 'none recorded' on the slip rather than leaving it blank", () => {
    render(<ReceiptSlipA6 provisionalId={ID} captured={{}}/>);
    expect(screen.getByText("none recorded")).toBeTruthy();
  });
});
