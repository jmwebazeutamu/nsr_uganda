/* IDV outcome rendering.
 *
 * Every value the backend can write must render, and render
 * DISTINCTLY. The defect was three different facts — a NIRA mismatch,
 * an operator's manual acceptance, and a household that never offered a
 * NIN — all rendering as one amber "Pending", because the branch chain
 * compared against display words the server never produced.
 *
 * So these cases walk the whole vocabulary rather than sampling it. A
 * test that happens to pick a handled value is how the bug survived.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

let IDV_OUTCOMES, idvOutcome, IdvChip;

// Every value written to StageRecord.idv_outcome. Mirrored in
// apps/ingestion_hub/test_idv_vocabulary.py, which asserts this list
// against the Python source.
const BACKEND_WRITES = [
  "", "match", "mismatch", "no_match", "bad_format",
  "service_unavailable", "unknown", "manual_accept", "nin_partial",
];

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = ({ name }) => React.createElement("i", { "data-icon": name });
  globalThis.Chip = ({ children, tone, title }) =>
    React.createElement("span", { "data-tone": tone, title }, children);
  await import("./idv-outcomes.jsx");
  ({ IDV_OUTCOMES, idvOutcome, IdvChip } = globalThis);
});

afterEach(() => cleanup());


describe("the vocabulary", () => {
  it.each(BACKEND_WRITES)("renders %o", (code) => {
    const o = idvOutcome(code);
    expect(o.known).toBe(true);
    expect(o.label).toBeTruthy();
    expect(o.detail).toBeTruthy();
  });

  it("gives every outcome a different label", () => {
    // The defect in one assertion.
    const labels = BACKEND_WRITES.map(c => idvOutcome(c).label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("gives every outcome a different explanation", () => {
    const details = BACKEND_WRITES.map(c => idvOutcome(c).detail);
    expect(new Set(details).size).toBe(details.length);
  });

  it("never renders anything as 'Pending'", () => {
    // Nothing the backend writes means "waiting". Every value is a
    // settled fact: it matched, it didn't, nobody asked, or NIRA was
    // unreachable. "Pending" was never true of any of them.
    for (const code of BACKEND_WRITES) {
      expect(idvOutcome(code).label.toLowerCase()).not.toContain("pending");
    }
  });
});


describe("the outcomes a reviewer must not miss", () => {
  it.each(["mismatch", "no_match", "bad_format"])(
    "tones %s as danger", (code) => {
      expect(idvOutcome(code).tone).toBe("danger");
    });

  it("does not tone a failed check the same as an unreachable NIRA", () => {
    // "NIRA said no" and "we couldn't ask NIRA" are different problems
    // with different next steps.
    expect(idvOutcome("mismatch").tone)
      .not.toBe(idvOutcome("service_unavailable").tone);
  });

  it("does not let a manual acceptance read as a NIRA match", () => {
    expect(idvOutcome("manual_accept").label).not.toBe(idvOutcome("match").label);
    expect(idvOutcome("manual_accept").detail).toMatch(/without a NIRA match/);
  });

  it("distinguishes 'never asked' from 'verified'", () => {
    expect(idvOutcome("").label).toBe("Not run");
    expect(idvOutcome("").tone).not.toBe(idvOutcome("match").tone);
  });
});


describe("a code the console does not know", () => {
  it("is shown as itself, not folded into a friendly default", () => {
    // Silently defaulting is what turned a NIRA mismatch into
    // "Pending". An unknown value should look like something is wrong.
    const o = idvOutcome("some_new_nira_status");
    expect(o.known).toBe(false);
    expect(o.label).toBe("some_new_nira_status");
    expect(o.tone).toBe("danger");
    expect(o.detail).toMatch(/Do not read it as verified/);
  });

  it("handles null and undefined as 'not run', not as unknown", () => {
    for (const empty of [null, undefined, "   "]) {
      expect(idvOutcome(empty).known).toBe(true);
      expect(idvOutcome(empty).label).toBe("Not run");
    }
  });
});


describe("the chip", () => {
  it.each(BACKEND_WRITES)("renders a label for %o", (code) => {
    render(<IdvChip outcome={code}/>);
    expect(screen.getByText(idvOutcome(code).label)).toBeTruthy();
  });

  it("carries the explanation as its title, so the column is not cryptic", () => {
    render(<IdvChip outcome="mismatch"/>);
    expect(screen.getByText("Mismatch").getAttribute("title"))
      .toMatch(/details do not agree/);
  });

  it("flags an unrecognised code with an alert icon", () => {
    render(<IdvChip outcome="brand_new"/>);
    expect(document.querySelector('[data-icon="alert"]')).toBeTruthy();
  });

  it("marks a real match with a check", () => {
    render(<IdvChip outcome="match"/>);
    expect(document.querySelector('[data-icon="check"]')).toBeTruthy();
  });

  it("does not put a check on anything that is not a match", () => {
    for (const code of BACKEND_WRITES.filter(c => c !== "match")) {
      cleanup();
      render(<IdvChip outcome={code}/>);
      expect(document.querySelector('[data-icon="check"]'), code).toBeNull();
    }
  });
});


describe("the table itself", () => {
  it("covers exactly what the backend writes", () => {
    expect(Object.keys(IDV_OUTCOMES).sort()).toEqual([...BACKEND_WRITES].sort());
  });
});
