/* BUG-S27-018 — regression: FieldStepV2 must not crash when fed a
 * builder-schema row that lacks the optional `completeness` key.
 *
 * The browser harness's local FS_FIELDS fallback always carries
 * `completeness` (a percentage), but the live builder-schema
 * (apps/data_requests/builder_schema.py) only emits the contract
 * keys group/key/label/sensitivity/type. Earlier code called
 * `field.completeness.toFixed(1)` unconditionally → TypeError on
 * every render under Django dev server, so Step 3 of the DRS wizard
 * rendered nothing. This test mounts FieldStepV2 with backend-shape
 * rows and asserts a clean render.
 */

import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

let FieldStepV2;

beforeAll(async () => {
  await import("./screens-drs-fieldselector.jsx");
  ({ FieldStepV2 } = globalThis);
});

afterEach(() => {
  cleanup();
});

// Mirrors the shape that /api/v1/drs/requests/builder-schema/
// actually returns — no completeness, no example, no desc.
const BACKEND_FIELDS = [
  { group: "Identifiers", key: "household.id",
    label: "Registry ID", sensitivity: "Public", type: "text" },
  { group: "Geography", key: "household.sub_region_code",
    label: "Sub-region", sensitivity: "Public", type: "enum" },
  { group: "Geography", key: "household.gps_lat",
    label: "GPS latitude", sensitivity: "Sensitive", type: "number",
    disabled: true, disabled_reason: "DSA clause 4.2.b" },
];

describe("FieldStepV2 — backend catalogue parity", () => {
  it("renders without throwing when rows omit `completeness`", () => {
    expect(() =>
      render(
        <FieldStepV2
          selectedKeys={[]}
          onChange={() => {}}
          fields={BACKEND_FIELDS}
          dsaReference="DSA-TEST"
        />,
      ),
    ).not.toThrow();
    // Confirm the rows actually mounted (and not a silent empty render).
    expect(screen.getByText("Registry ID")).toBeInTheDocument();
    expect(screen.getByText("Sub-region")).toBeInTheDocument();
  });

  it("still renders the breakdown card with no selection", () => {
    render(
      <FieldStepV2
        selectedKeys={[]}
        onChange={() => {}}
        fields={BACKEND_FIELDS}
        dsaReference="DSA-TEST"
      />,
    );
    expect(screen.getByText(/SELECTION SUMMARY/)).toBeInTheDocument();
  });
});
