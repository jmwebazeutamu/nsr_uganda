/* US-S11-028 — Operator scopes tab unit tests.
 *
 * Coverage:
 *   - _scopeLevelLabel translates the wire enum to operator-facing copy
 *   - UserPicker fires onChange when an option is clicked
 *   - GeoCascadePicker walks parents → leaves; multi-select works
 *   - GrantScopeModal submit shape matches the bulk-grant API
 *   - RevokeScopeConfirm fires onConfirm
 *
 * Backend fetches are stubbed via vi.fn().mockResolvedValue.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let GrantScopeModal;
let GeoCascadePicker;
let UserPicker;
let RevokeScopeConfirm;
let _scopeLevelLabel;
let _SCOPE_LEVEL_OPTIONS;
let _GEO_LEVELS_ORDER;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon       = () => null;
  globalThis.Chip       = ({ children }) => globalThis.React.createElement("span", null, children);
  globalThis.PageHeader = () => null;
  globalThis.Toast      = () => null;
  globalThis.window = globalThis;

  await import("./screens-admin.jsx");
  ({
    GrantScopeModal, GeoCascadePicker, UserPicker, RevokeScopeConfirm,
    _scopeLevelLabel, _SCOPE_LEVEL_OPTIONS, _GEO_LEVELS_ORDER,
  } = globalThis);
});

beforeEach(() => {
  globalThis.fetch = vi.fn().mockRejectedValue(new Error("network"));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


describe("_scopeLevelLabel", () => {
  it("translates each wire enum to a human label", () => {
    for (const opt of _SCOPE_LEVEL_OPTIONS) {
      expect(_scopeLevelLabel(opt.value)).toBe(opt.label);
    }
  });
  it("falls back to the raw value when unknown", () => {
    expect(_scopeLevelLabel("mystery")).toBe("mystery");
  });
});


describe("UserPicker", () => {
  it("fires onChange with the picked user", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { id: 1, username: "ops-grace", display_name: "Grace Akello", groups: [] },
        { id: 2, username: "ops-pete",  display_name: "Pete Onyango", groups: [] },
      ],
    });
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<UserPicker value={null} onChange={onChange}/>);
    await waitFor(() => screen.getByText("ops-grace"));
    await user.click(screen.getByText("ops-grace"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].username).toBe("ops-grace");
  });
});


describe("GeoCascadePicker", () => {
  it("walks region → district and supports multi-select at the leaf", async () => {
    // First fetch loads regions; once an operator picks a region, a
    // second fetch loads sub_regions; a third loads districts. We
    // stub the chain in order.
    const fetchMock = vi.fn()
      // Initial /forms/-style region fetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { code: "R-CENTRAL", name: "Central", parent_code: "" },
          { code: "R-EAST",    name: "East",    parent_code: "" },
        ],
      })
      // Sub-regions under R-CENTRAL
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { code: "SR-BUGANDA-SOUTH", name: "Buganda South", parent_code: "R-CENTRAL" },
        ],
      })
      // Districts under SR-BUGANDA-SOUTH
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { code: "D-WAKISO",  name: "Wakiso",  parent_code: "SR-BUGANDA-SOUTH" },
          { code: "D-KAMPALA", name: "Kampala", parent_code: "SR-BUGANDA-SOUTH" },
        ],
      });
    globalThis.fetch = fetchMock;

    const user = userEvent.setup();
    // Wrap in a stateful host so value flows back as a controlled
    // prop — without this, toggleLeaf reads stale value and the
    // multi-select stays at 1 element.
    let latest = [];
    const Host = () => {
      const [v, setV] = globalThis.React.useState([]);
      latest = v;
      return (
        <GeoCascadePicker
          targetLevel="district"
          value={v}
          onChange={setV}
        />
      );
    };
    render(<Host/>);
    // Pick Region.
    await waitFor(() => screen.getByText(/Central \(R-CENTRAL\)/));
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0], "R-CENTRAL");
    // Sub-region dropdown populated; pick the only option.
    await waitFor(() => screen.getByText(/Buganda South \(SR-BUGANDA-SOUTH\)/));
    const selects2 = screen.getAllByRole("combobox");
    await user.selectOptions(selects2[1], "SR-BUGANDA-SOUTH");
    // Leaves render as checkboxes.
    await waitFor(() => screen.getByText(/Wakiso/));
    const wakiso = screen.getByLabelText(/Wakiso/);
    const kampala = screen.getByLabelText(/Kampala/);
    await user.click(wakiso);
    expect(latest).toEqual(["D-WAKISO"]);
    await user.click(kampala);
    expect(latest).toEqual(["D-WAKISO", "D-KAMPALA"]);
    // Select-all + Clear buttons.
    await user.click(screen.getByRole("button", { name: /Clear/ }));
    expect(latest).toEqual([]);
    await user.click(screen.getByRole("button", { name: /Select all 2/ }));
    expect(latest).toEqual(["D-WAKISO", "D-KAMPALA"]);
  });
});


describe("GrantScopeModal", () => {
  it("submit posts user_id + scope_level + scope_codes for national", async () => {
    // The modal fires a /users/ fetch on mount. Stub a one-user
    // response with a unique username so getByText resolves
    // unambiguously.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { id: 7, username: "officer-priscilla",
          display_name: "Priscilla Nakato", groups: [] },
      ],
    });
    globalThis.fetch = fetchMock;
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<GrantScopeModal onSubmit={onSubmit} onClose={() => {}}/>);
    await waitFor(() => screen.getByText("officer-priscilla"));
    await user.click(screen.getByText("officer-priscilla"));
    // Pick national — the level select is the only <select> in the
    // modal until partner/geographic levels add their own.
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0], "national");
    // Submit button text reflects "Grant scope" (no count).
    await user.click(screen.getByRole("button", { name: /^Grant scope$/ }));
    expect(onSubmit).toHaveBeenCalledWith({
      user_id: 7, scope_level: "national", scope_codes: [], note: "",
    });
  });

  it("submit is disabled until user + level + (codes|partner) are set", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => [],
    });
    render(<GrantScopeModal onSubmit={() => {}} onClose={() => {}}/>);
    await new Promise(r => setTimeout(r, 0));
    const submit = screen.getByRole("button", { name: /Grant/ });
    expect(submit.disabled).toBe(true);
  });
});


describe("RevokeScopeConfirm", () => {
  const row = {
    id: "01OP-1", username: "ops-grace",
    scope_level: "district", scope_code: "D-WAKISO",
    scope_label: "Wakiso (D-WAKISO)",
  };

  it("fires onConfirm when Revoke is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <RevokeScopeConfirm
        row={row} submitting={false}
        onClose={() => {}} onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Revoke/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("Cancel calls onClose without firing onConfirm", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    render(
      <RevokeScopeConfirm
        row={row} submitting={false}
        onClose={onClose} onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Cancel/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons while submitting", () => {
    render(
      <RevokeScopeConfirm
        row={row} submitting={true}
        onClose={() => {}} onConfirm={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /Revoking/ }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: /Cancel/ }).disabled).toBe(true);
  });
});
