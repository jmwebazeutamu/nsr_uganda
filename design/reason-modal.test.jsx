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

describe("the notice", () => {
  it("warns about the part of the selection that will be refused", () => {
    show({
      recordLabels: ["01A", "01B", "01C"],
      notice: "2 of the 3 selected will be refused — they are listed below.",
    });
    expect(screen.getByText(/2 of the 3 selected will be refused/)).toBeTruthy();
  });

  it("is absent when there is nothing to warn about", () => {
    show({ recordLabels: ["01A"] });
    expect(screen.queryByText(/will be refused/)).toBeNull();
  });
});

describe("the record list", () => {
  it("names every record the action will touch", () => {
    show({ recordLabels: ["01AAA", "01BBB", "01CCC"] });
    for (const id of ["01AAA", "01BBB", "01CCC"]) {
      expect(screen.getByText(id)).toBeTruthy();
    }
  });

  it("says how many, in words that match the count", () => {
    show({ recordLabels: ["01AAA", "01BBB"] });
    expect(screen.getByText("2 records")).toBeTruthy();
    cleanup();
    show({ recordLabels: ["01AAA"] });
    expect(screen.getByText("1 record")).toBeTruthy();
  });

  it("scrolls rather than truncating a long selection", () => {
    // "+ 188 more" would be the same defect again: the operator
    // cannot check what they are about to change.
    const ids = Array.from({ length: 40 }, (_, i) => `01ID${i}`);
    show({ recordLabels: ids });
    expect(screen.getAllByRole("listitem")).toHaveLength(40);
    expect(screen.getByText("01ID39")).toBeTruthy();
  });

  it("falls back to the single label when no list is given", () => {
    show({ recordLabel: "01SINGLE" });
    expect(screen.getByText("01SINGLE")).toBeTruthy();
  });

  it("shows neither when there is nothing to name", () => {
    show({ recordLabels: [] });
    expect(screen.queryByText(/Action will be applied to/)).toBeNull();
  });
});

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
