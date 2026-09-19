/* Roles & scopes screen — the account list is real, or it is empty.
 *
 * The screen this replaces rendered ten invented operator accounts from a
 * `SEC_USERS` fixture and never fetched users at all. These cases pin the
 * two properties that matter: what it shows comes from the API, and when
 * the API does not answer it says so instead of showing something.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

let AdminSecurityRolesScreen;
let _secScopesByUser;
let _secRoleTone;

const USERS = [
  {
    id: 1, username: "amuge.k", display_name: "Amuge K.", email: "amuge.k@example.test",
    groups: ["cdo"], is_active: true, is_superuser: false,
    last_login: "2026-09-18T06:30:00Z", date_joined: "2026-02-01T08:00:00Z",
  },
  {
    id: 2, username: "opio.t", display_name: "Opio T.", email: "opio.t@example.test",
    groups: [], is_active: false, is_superuser: false,
    last_login: null, date_joined: "2026-03-04T08:00:00Z",
  },
  {
    id: 3, username: "root", display_name: "root", email: "",
    groups: ["nsr_admin"], is_active: true, is_superuser: true,
    last_login: "2026-09-19T05:00:00Z", date_joined: "2026-01-01T08:00:00Z",
  },
];

const SCOPES = [
  { id: 11, user: 1, scope_level: "district", scope_code: "D-MOROTO", scope_label: "Moroto", active: true, granted_at: "2026-05-02T09:00:00Z", granted_by: "root", note: "" },
  { id: 12, user: 1, scope_level: "district", scope_code: "D-NAPAK", scope_label: "Napak", active: false, granted_at: "2026-05-02T09:00:00Z", granted_by: "root", note: "rotated off" },
];

const ROLES = [
  { code: "cdo", label: "CDO", permissions: ["data_approve", "data_entry", "data_modify", "data_view"], default_scope: "district", external: false, in_tor: true, adr0006: "CDO", notes: "", member_count: 1 },
  { code: "nsr_admin", label: "Super Admin", permissions: ["data_view"], default_scope: "national", external: false, in_tor: true, adr0006: "SA", notes: "", member_count: 1 },
];

const jsonOnce = (body) => ({ ok: true, json: () => Promise.resolve(body) });

const routeFetch = (overrides = {}) => vi.fn((url) => {
  if (url.startsWith("/api/v1/security/users/")) return Promise.resolve(overrides.users || jsonOnce(USERS));
  if (url.startsWith("/api/v1/security/operator-scopes/")) return Promise.resolve(overrides.scopes || jsonOnce(SCOPES));
  if (url.startsWith("/api/v1/security/roles/")) return Promise.resolve(overrides.roles || jsonOnce(ROLES));
  return Promise.reject(new Error(`unexpected url ${url}`));
});

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => globalThis.React.createElement("span", null, children);
  globalThis.PageHeader = ({ title }) => globalThis.React.createElement("h1", null, title);
  globalThis.KPI = ({ title, value, foot }) => globalThis.React.createElement(
    "div", { "data-kpi": title }, `${title}:${value}:${foot || ""}`,
  );
  globalThis.window = globalThis;

  await import("./screens-admin-security-roles.jsx");
  ({ AdminSecurityRolesScreen, _secScopesByUser, _secRoleTone } = globalThis);
});

beforeEach(() => { globalThis.fetch = routeFetch(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const kpi = (title) => screen.getByText(new RegExp(`^${title}:`)).textContent.split(":")[1];

describe("account list", () => {
  it("renders the accounts the API returned", async () => {
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(screen.getByText("Amuge K.")).toBeTruthy());
    expect(screen.getByText("Opio T.")).toBeTruthy();
    // "root" is both the display name and the username on that row.
    expect(screen.getAllByText("root").length).toBeGreaterThan(0);
  });

  it("carries no trace of the fixture it replaced", async () => {
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(screen.getByText("Amuge K.")).toBeTruthy());
    for (const ghost of ["Akello P.", "Bahati Esther", "Adong F.", "Dr. Nakanwagi", "Test User X"]) {
      expect(screen.queryByText(ghost)).toBeNull();
    }
  });

  it("labels a role by its catalogue label, not its group name", async () => {
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(screen.getAllByText("CDO").length).toBeGreaterThan(0));
  });

  it("shows only the account's active scope as its primary scope", async () => {
    render(<AdminSecurityRolesScreen/>);
    // D-NAPAK is granted but inactive, so the row must not offer it.
    await waitFor(() => expect(screen.getByText("district:D-MOROTO")).toBeTruthy());
    expect(screen.queryByText("district:D-NAPAK")).toBeNull();
  });
});

describe("KPIs count what loaded", () => {
  it("counts accounts, active accounts and national scope", async () => {
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(kpi("Accounts")).toBe("3"));
    expect(kpi("Active")).toBe("2");
    expect(kpi("National wildcard scope")).toBe("0");
  });

  it("excludes superusers from the no-scope count", async () => {
    // root holds no OperatorScope row but bypasses scope checks, so
    // counting it would report a finding that is not one. Only the
    // disabled non-superuser (Opio T.) qualifies.
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(kpi("No scope granted")).toBe("1"));
  });

  it("shows a dash rather than a zero while still loading", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {}));  // never resolves
    render(<AdminSecurityRolesScreen/>);
    expect(kpi("Accounts")).toBe("—");
    expect(screen.getByText(/Loading accounts, scopes and the role catalogue/)).toBeTruthy();
  });
});

describe("when a source does not answer", () => {
  it("names the failure and lists nothing", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("network")));
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(screen.getByText(/Could not load 3 sources/)).toBeTruthy());
    expect(screen.getByText(/users: network/)).toBeTruthy();
    // The banner says the load failed; it must NOT also say the registry
    // is empty, which is a claim nothing here can support. Only the table
    // row carries the empty text.
    expect(screen.getAllByText("No operator accounts exist yet.").length).toBe(1);
    expect(kpi("Accounts")).toBe("0");
  });

  it("reports a partial failure as partial", async () => {
    globalThis.fetch = routeFetch({ roles: Promise.reject(new Error("HTTP 503")) });
    render(<AdminSecurityRolesScreen/>);
    await waitFor(() => expect(screen.getByText("Amuge K.")).toBeTruthy());
    expect(screen.getByText(/Could not load one source/)).toBeTruthy();
    // Without the catalogue the group name is shown raw rather than
    // guessed at — the account list is still true.
    expect(screen.getByText("cdo")).toBeTruthy();
  });

  it("distinguishes an empty registry from a failed one", async () => {
    globalThis.fetch = routeFetch({ users: jsonOnce([]) });
    render(<AdminSecurityRolesScreen/>);
    // Said twice on purpose: once as the page banner, once in the table.
    await waitFor(() => expect(screen.getAllByText("No operator accounts exist yet.").length).toBe(2));
    expect(screen.queryByText(/Could not load/)).toBeNull();
  });
});

describe("helpers", () => {
  it("groups scope rows by the account that holds them", () => {
    const byUser = _secScopesByUser(SCOPES);
    expect(byUser[1]).toHaveLength(2);
    expect(byUser[2]).toBeUndefined();
  });

  it("survives a missing scope list", () => {
    expect(_secScopesByUser(null)).toEqual({});
  });

  it("tones a role by its reach", () => {
    expect(_secRoleTone({ external: false, default_scope: "national" })).toBe("danger");
    expect(_secRoleTone({ external: true, default_scope: "partner" })).toBe("programme");
    expect(_secRoleTone({ external: false, default_scope: "parish" })).toBe("data");
  });
});
