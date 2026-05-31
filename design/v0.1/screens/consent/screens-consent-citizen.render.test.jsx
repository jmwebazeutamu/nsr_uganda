/* Render regression test for CitizenConsentScreen.
 *
 * The screen iterates the real PURPOSES vocabulary and reads each member's
 * consent record. When CONSENT-O-01 added ELIGIBILITY (and dropped
 * IDENTITY_VERIFICATION), the mock seedRecords no longer had a record for
 * every purpose, and `memberRecords[p.code].state` crashed the whole
 * Household detail screen (reported 2026-05-31). This test mounts the screen
 * with the REAL consent-shared vocabulary so the missing-record path executes
 * — it must render, not throw.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);

  // Pass-through stubs so nested content actually mounts (so the
  // PURPOSES.map render loop runs and would throw on an unguarded record).
  const Pass = ({ children }) => globalThis.React.createElement(
    globalThis.React.Fragment, null, children);
  for (const name of [
    "Icon", "Chip", "KPI", "Field", "Modal", "Toast", "PageHeader",
    "AuditDrawer", "ActionBar", "Toggle", "ConsentSectionLabel", "StoryTag",
  ]) {
    globalThis[name] = Pass;
  }
  globalThis.window = globalThis;

  // Real vocabulary (PURPOSES incl. ELIGIBILITY, chips, PURPOSE_BY_CODE).
  await import("./consent-shared.jsx");
  // The screen under test.
  await import("./screens-consent-citizen.jsx");
});

afterEach(() => cleanup());

describe("CitizenConsentScreen renders against the reconciled vocabulary", () => {
  it("mounts without throwing on purposes that have no seeded record", () => {
    const CitizenConsentScreen = globalThis.CitizenConsentScreen;
    expect(typeof CitizenConsentScreen).toBe("function");
    // Would throw "Cannot read properties of undefined (reading 'state')"
    // before the null-guard fix.
    expect(() => render(globalThis.React.createElement(CitizenConsentScreen)))
      .not.toThrow();
  });

  it("shows the ELIGIBILITY purpose row (the one that used to crash)", () => {
    render(globalThis.React.createElement(globalThis.CitizenConsentScreen));
    expect(screen.getAllByText(/Eligibility assessment/i).length).toBeGreaterThan(0);
  });
});
