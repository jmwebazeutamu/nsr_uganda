/* Render test for ConsentCaptureBlock — the per-purpose consent capture that
 * replaces the legacy Yes/No toggle in the household capture form. */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.BasisChip = () => null;
  globalThis.Toggle = ({ on, onChange, ariaLabel }) => globalThis.React.createElement(
    "button", { role: "switch", "aria-checked": !!on, "aria-label": ariaLabel,
      onClick: () => onChange && onChange(!on) }, on ? "on" : "off");
  globalThis.window = globalThis;
  await import("./consent-shared.jsx");
  await import("./consent-capture-block.jsx");
});
afterEach(() => cleanup());

// Controlled wrapper holding the block state.
const Harness = () => {
  const [block, setBlock] = globalThis.React.useState(globalThis.defaultConsentBlock());
  return globalThis.React.createElement(globalThis.ConsentCaptureBlock, { value: block, onChange: setBlock });
};

describe("ConsentCaptureBlock", () => {
  // Regression — defect #5. A fresh capture opened with
  // "✓ Yes — consented" already selected and four optional purposes
  // already ON, so a submitted record asserted consent the respondent
  // was never asked for. DPPA 2019 requires a freely given, specific,
  // informed indication BY THE DATA SUBJECT; a default is an indication
  // by the form designer. See ADR-0031.
  it("leaves every consent-basis purpose unset — nothing is pre-answered", () => {
    const block = globalThis.defaultConsentBlock();
    expect(block.REGISTRATION).toBe("");
    for (const p of globalThis.PURPOSES.filter(x => x.basis === "Consent")) {
      expect(block[p.code], `${p.code} must start unset`).toBe("");
    }
  });

  it("keeps non-consent-basis purposes granted — they are not consent", () => {
    const block = globalThis.defaultConsentBlock();
    // STATISTICS rides the DPPA 2019 §7(2)(e) statistical exemption. It
    // has no unset state to be in: it is not asked, it applies.
    expect(block.STATISTICS).toBe("GRANTED");
  });

  it("names the transactional registry-ID SMS in the consent statement", () => {
    // Defect #6 / ADR-0031: the registry-ID SMS is sent whatever the SMS
    // notifications purpose says, so the respondent has to be told at
    // the point of consent rather than discovering it from the receipt.
    const statement = globalThis.REGISTRATION_STATEMENT_EN.join(" ");
    expect(statement).toMatch(/one text message/i);
    expect(statement).toMatch(/tracking number/i);
    expect(statement).toMatch(/even if you say no to text messages/i);
  });

  it("renders the registration gate, with optional purposes hidden until it is granted", () => {
    render(globalThis.React.createElement(Harness));
    expect(screen.getByText(/Yes — consented/)).toBeTruthy();
    expect(screen.getByText(/No — refused/)).toBeTruthy();
    // Neither button is pre-selected.
    expect(screen.getByText(/Yes — consented/).closest("button").className).toBe("");
    // Optional purposes only appear once registration is actually granted.
    expect(screen.queryByText("Programme referral")).toBeNull();
    fireEvent.click(screen.getByText(/Yes — consented/));
    expect(screen.getByText("Programme referral")).toBeTruthy();
    expect(screen.getByText("Research")).toBeTruthy();
  });

  it("shows optional purposes as 'not asked' until the operator answers them", () => {
    render(globalThis.React.createElement(Harness));
    fireEvent.click(screen.getByText(/Yes — consented/));
    // Every optional purpose starts unanswered, and says so.
    const optional = globalThis.PURPOSES.filter(
      p => p.basis === "Consent" && p.code !== "REGISTRATION");
    expect(screen.getAllByText("not asked").length).toBe(optional.length);
    // Answering one clears its badge and leaves the rest alone.
    const group = screen.getByRole("group", { name: "Programme referral" });
    fireEvent.click(within(group).getByText("Yes"));
    expect(screen.getAllByText("not asked").length).toBe(optional.length - 1);
  });

  it("reveals a refusal-reason + warning when registration is refused", () => {
    render(globalThis.React.createElement(Harness));
    fireEvent.click(screen.getByText(/No — refused/));
    expect(screen.getByText(/Reason for refusal/)).toBeTruthy();
    expect(screen.getByText(/ends the intake/)).toBeTruthy();
  });
});
