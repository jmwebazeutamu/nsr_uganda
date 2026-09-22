/* User management: the refusals are the feature.
 *
 * The screen exists so adding a user or resetting a password does not
 * need the Django admin. What matters is not that it can do those
 * things, but that it cannot do the ones that would make one admin
 * account enough to own the registry.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let AdminUsersScreen;

const jsonOk = (body) => Promise.resolve({
  ok: true, status: 200, json: () => Promise.resolve(body),
});

const USERS = [
  { id: 1, username: "akello.g", first_name: "Grace", last_name: "Akello",
    email: "g@example.test", is_active: true, is_superuser: false,
    last_login: "2026-09-20T08:00:00Z", roles: ["enumerator"], manageable: true },
  { id: 2, username: "root", first_name: "", last_name: "", email: "",
    is_active: true, is_superuser: true, last_login: null,
    roles: [], manageable: false },
  { id: 3, username: "the-admin", first_name: "", last_name: "", email: "",
    is_active: true, is_superuser: false, last_login: null,
    roles: ["nsr_admin"], manageable: true },
];

const ROLES = [
  { code: "enumerator", label: "Enumerator", privileged: false, assignable: true },
  { code: "dpo", label: "Data Protection Officer", privileged: true, assignable: true },
  { code: "ghost", label: "Unsynced Role", privileged: false, assignable: false },
];

let posted;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.PageHeader = ({ title, right }) => React.createElement("div", null, title, right);
  await import("./screens-admin-users.jsx");
  ({ AdminUsersScreen } = globalThis);
});

beforeEach(() => {
  posted = [];
  globalThis.fetch = vi.fn((url, opts) => {
    const u = String(url);
    if (opts && opts.method === "POST") {
      posted.push({ url: u, body: JSON.parse(opts.body) });
      if (u.includes("/create/")) {
        return jsonOk({ user: { ...USERS[0], username: "new.person" },
                        temporary_password: "Xk7rTmQw2ncPfa" });
      }
      if (u.includes("/reset-password/")) {
        return jsonOk({ method: "temporary", temporary_password: "Zq4mBn8vRtLkcd" });
      }
      return jsonOk({});
    }
    if (u.includes("user-accounts/roles/")) return jsonOk({ roles: ROLES });
    if (u.includes("users/me/")) return jsonOk({ username: "the-admin" });
    if (u.includes("user-accounts")) return jsonOk({ results: USERS });
    return jsonOk({});
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const show = async () => {
  render(<AdminUsersScreen/>);
  await waitFor(() => expect(screen.getByText("akello.g")).toBeTruthy());
};

describe("what it refuses", () => {
  it("offers no actions on a superuser", async () => {
    await show();
    const row = screen.getByText("root").closest("tr");
    expect(row.textContent).toMatch(/not managed here/);
    expect(row.querySelector("button")).toBeNull();
  });

  it("will not let an admin change their own roles", async () => {
    await show();
    // "the-admin" is the signed-in user per /users/me/.
    const row = screen.getByText("the-admin").closest("tr");
    const rolesBtn = [...row.querySelectorAll("button")]
      .find(b => b.textContent === "Roles");
    expect(rolesBtn.disabled).toBe(true);
  });

  it("will not let an admin deactivate themselves", async () => {
    await show();
    const row = screen.getByText("the-admin").closest("tr");
    const btn = [...row.querySelectorAll("button")]
      .find(b => b.textContent === "Deactivate");
    expect(btn.disabled).toBe(true);
  });

  it("holds the confirm until a reason is given", async () => {
    await show();
    const row = screen.getByText("akello.g").closest("tr");
    fireEvent.click([...row.querySelectorAll("button")].find(b => b.textContent === "Deactivate"));
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "left the unit" },
    });
    expect(screen.getByRole("button", { name: "Confirm" }).disabled).toBe(false);
  });

  it("greys a role that has no group yet", async () => {
    await show();
    const row = screen.getByText("akello.g").closest("tr");
    fireEvent.click([...row.querySelectorAll("button")].find(b => b.textContent === "Roles"));
    const ghost = screen.getByRole("button", { name: /Unsynced Role/ });
    expect(ghost.disabled).toBe(true);
  });
});

describe("what it does", () => {
  it("sends the reason with the change", async () => {
    await show();
    const row = screen.getByText("akello.g").closest("tr");
    fireEvent.click([...row.querySelectorAll("button")].find(b => b.textContent === "Deactivate"));
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "left the unit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0].url).toMatch(/set-active\/$/);
    expect(posted[0].body).toEqual({ active: false, reason: "left the unit" });
  });

  it("shows a temporary password once, with a warning that it is not stored", async () => {
    await show();
    const row = screen.getByText("akello.g").closest("tr");
    fireEvent.click([...row.querySelectorAll("button")].find(b => b.textContent === "Reset password"));
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "locked out" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText("Zq4mBn8vRtLkcd")).toBeTruthy());
    expect(document.body.textContent).toMatch(/shown once/i);
  });

  it("disables the email option when there is no address", async () => {
    await show();
    const row = screen.getByText("the-admin").closest("tr");
    fireEvent.click([...row.querySelectorAll("button")].find(b => b.textContent === "Reset password"));
    const radios = screen.getAllByRole("radio");
    expect(radios[1].disabled).toBe(true);
    expect(document.body.textContent).toMatch(/no address on file/);
  });

  it("reads accounts from user-accounts, not the scope picker's users endpoint", async () => {
    await show();
    const calls = globalThis.fetch.mock.calls.map(c => String(c[0]));
    expect(calls.some(u => u.includes("/security/user-accounts/"))).toBe(true);
    // /security/users/ belongs to the Grant Scope picker and has a
    // different shape; reading it here would silently half-work.
    expect(calls.some(u => /\/security\/users\/(\?|$)/.test(u))).toBe(false);
  });
});
