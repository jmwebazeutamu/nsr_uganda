/* The audit drawer's filters.
 *
 * The two selects shipped with hardcoded option lists — "NSR Unit /
 * CDO / System" and "Created / Approved / Rejected / Update" — wired to
 * nothing. Choosing an actor changed no row. The options did not even
 * describe the events beside them, because those events were
 * fabricated from the record's current state.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

let AuditDrawer;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.useState = React.useState;
  globalThis.useEffect = React.useEffect;
  globalThis.useRef = React.useRef;
  globalThis.useMemo = React.useMemo;
  await import("./components.jsx");
  ({ AuditDrawer } = globalThis);
});

afterEach(cleanup);

const EVENTS = [
  { who: "parish.chief", action: "opened the grievance",
    detail: "category=data_correction", time: "12 May 09:14", audit: "a1b2c3" },
  { who: "cdo.aine", action: "assigned it",
    detail: "assigned", time: "12 May 10:02", audit: "d4e5f6" },
  { who: "system", action: "escalated it", tone: "system",
    detail: "SLA breached", time: "14 May 09:14", audit: "778899" },
];

const open = (events = EVENTS) =>
  render(<AuditDrawer open events={events} onClose={() => {}}/>);

describe("the audit drawer", () => {
  it("offers the actors that are actually in the chain", () => {
    open();
    const options = [...screen.getByLabelText("Filter by actor").options]
      .map(o => o.value);
    expect(options).toEqual(["", "cdo.aine", "parish.chief", "system"]);
  });

  it("offers the actions that are actually in the chain", () => {
    open();
    const options = [...screen.getByLabelText("Filter by action").options]
      .map(o => o.value);
    expect(options).toEqual([
      "", "assigned it", "escalated it", "opened the grievance",
    ]);
  });

  it("narrows the rows when an actor is chosen", () => {
    open();
    expect(screen.getAllByText(/Audit ID/)).toHaveLength(3);

    fireEvent.change(screen.getByLabelText("Filter by actor"),
                     { target: { value: "cdo.aine" } });

    expect(screen.getAllByText(/Audit ID/)).toHaveLength(1);
    expect(screen.getByText("d4e5f6")).toBeTruthy();
  });

  it("combines the two filters", () => {
    open();
    fireEvent.change(screen.getByLabelText("Filter by actor"),
                     { target: { value: "cdo.aine" } });
    fireEvent.change(screen.getByLabelText("Filter by action"),
                     { target: { value: "escalated it" } });
    expect(screen.queryByText(/Audit ID/)).toBeNull();
    expect(screen.getByText("No events match these filters.")).toBeTruthy();
  });

  it("says how many of how many it is showing", () => {
    open();
    fireEvent.change(screen.getByLabelText("Filter by actor"),
                     { target: { value: "system" } });
    expect(screen.getByText(/1\s*of 3 events/)).toBeTruthy();
  });

  it("distinguishes an empty chain from an over-narrow filter", () => {
    open([]);
    expect(screen.getByText("No audit events for this record.")).toBeTruthy();
  });

  it("survives an event with no actor", () => {
    // The chain's actor_id is a free-text column; a row written before
    // the actor was resolvable has an empty one.
    expect(() => open([{ ...EVENTS[0], who: "" }])).not.toThrow();
  });
});
