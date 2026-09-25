/* The confirm button says what it confirms.
 *
 * Its words came from `intent`, which picks its colour: intent
 * "success" printed "Confirm approve". So the GRM resolve dialog
 * offered to approve a grievance and UPD's "Release from hold" offered
 * to approve a release. Neither approves anything. Copy and colour are
 * separate decisions now.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

let ReasonModal;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.useState = React.useState;
  globalThis.useEffect = React.useEffect;
  globalThis.useRef = React.useRef;
  globalThis.useMemo = React.useMemo;
  await import("./components.jsx");
  ({ ReasonModal } = globalThis);
});

afterEach(cleanup);

const show = (props) => render(
  <ReasonModal open title="A dialog" reasonOptions={["Because"]}
               onClose={() => {}} onConfirm={() => {}} {...props}/>,
);

describe("ReasonModal's confirm button", () => {
  it("uses the label the caller gives it", () => {
    show({ intent: "success", confirmLabel: "Resolve" });
    expect(screen.getByRole("button", { name: "Resolve" })).toBeTruthy();
  });

  it("does not claim to approve when the caller named the action", () => {
    show({ intent: "success", confirmLabel: "Release" });
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
  });

  it("still says approve for a real approval", () => {
    show({ intent: "success" });
    expect(screen.getByRole("button", { name: "Confirm approve" })).toBeTruthy();
  });

  it("still says reject for a real rejection", () => {
    show({ intent: "danger" });
    expect(screen.getByRole("button", { name: "Confirm reject" })).toBeTruthy();
  });

  it("falls back to a plain Confirm for anything else", () => {
    show({ intent: "primary" });
    expect(screen.getByRole("button", { name: "Confirm" })).toBeTruthy();
  });

  it("keeps the colour decision separate from the words", () => {
    // A green button that says "Resolve" is the point: intent still
    // drives the class, confirmLabel drives the copy.
    show({ intent: "success", confirmLabel: "Resolve" });
    expect(screen.getByRole("button", { name: "Resolve" }).className)
      .toContain("btn-success");
  });
});
