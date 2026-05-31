/* Render test for ConsentCaptureBlock — the per-purpose consent capture that
 * replaces the legacy Yes/No toggle in the household capture form. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  it("defaults REGISTRATION granted and lists the optional consent purposes", () => {
    const block = globalThis.defaultConsentBlock();
    expect(block.REGISTRATION).toBe("GRANTED");
    // Default-on optional purposes are GRANTED; default-off are blank.
    expect(block.REFERRAL).toBe("GRANTED");
    expect(block.COMMUNICATIONS_SMS).toBe("");
  });

  it("renders the registration gate + optional purposes", () => {
    render(globalThis.React.createElement(Harness));
    expect(screen.getByText(/Yes — consented/)).toBeTruthy();
    expect(screen.getByText(/No — refused/)).toBeTruthy();
    expect(screen.getByText("Programme referral")).toBeTruthy();
    expect(screen.getByText("Research")).toBeTruthy();
  });

  it("reveals a refusal-reason + warning when registration is refused", () => {
    render(globalThis.React.createElement(Harness));
    fireEvent.click(screen.getByText(/No — refused/));
    expect(screen.getByText(/Reason for refusal/)).toBeTruthy();
    expect(screen.getByText(/ends the intake/)).toBeTruthy();
  });
});
