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

// As served by /user-accounts/roles/, which reads them off ScopeLevel.
const SCOPE_LEVELS = [
  { value: "national", label: "National", takes_codes: false, geographic: false },
  { value: "region", label: "Region", takes_codes: true, geographic: true },
  { value: "sub_region", label: "Sub Region", takes_codes: true, geographic: true },
  { value: "district", label: "District", takes_codes: true, geographic: true },
  { value: "sub_county", label: "Sub County", takes_codes: true, geographic: true },
  { value: "parish", label: "Parish", takes_codes: true, geographic: true },
  { value: "village", label: "Village", takes_codes: true, geographic: true },
  { value: "partner", label: "Partner", takes_codes: true, geographic: false },
];

const GEO = {
  region: [{ code: "R-NORTHERN", name: "Northern" }, { code: "R-CENTRAL", name: "Central" }],
  district: [{ code: "102", name: "Kampala" }, { code: "UG-MOR", name: "Moroto" }],
  // Two parishes really are both called Acanga — 839 parish names are
  // shared by at least two parishes.
  parish: [
    { code: "207.1.05.01", name: "Acanga", parent_code: "207.1.05" },
    { code: "311.2.07.04", name: "Acanga", parent_code: "311.2.07" },
    { code: "207.1.05.02", name: "Acan Oryema", parent_code: "207.1.05" },
  ],
};

const ROLES = [
  { code: "enumerator", label: "Enumerator", privileged: false, assignable: true,
    default_scope: "parish" },
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
    if (u.includes("user-accounts/roles/")) {
      return jsonOk({ roles: ROLES, scope_levels: SCOPE_LEVELS });
    }
    if (u.includes("geographic-units")) {
      const level = new URL(u, "http://x").searchParams.get("level");
      return jsonOk({ results: (GEO[level] || []) });
    }
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


describe("scope at creation", () => {
  const openCreate = async () => {
    await show();
    fireEvent.click(screen.getByRole("button", { name: /New account/ }));
  };

  it("warns that an account with no scope will see nothing", async () => {
    await openCreate();
    expect(document.body.textContent).toMatch(/see no records at all/);
  });

  it("offers the scope level the chosen role defaults to", async () => {
    await openCreate();
    fireEvent.click(screen.getByRole("button", { name: /Enumerator/ }));
    expect(screen.getByRole("button", { name: /Use parish/ })).toBeTruthy();
  });

  it("offers every level the server serves, including region and village", async () => {
    await openCreate();
    const select = screen.getByRole("combobox", { name: "Initial scope level" });
    const values = [...select.querySelectorAll("option")].map(o => o.value);
    // The first cut dropped these three.
    expect(values).toContain("region");
    expect(values).toContain("sub_region");
    expect(values).toContain("village");
  });

  it("lists real places to pick, rather than asking for codes", async () => {
    // District codes are "102" (Kampala) and "UG-MOR" (Moroto); nobody
    // recalls those, and the wrong one grants the wrong district.
    await openCreate();
    fireEvent.change(screen.getByRole("combobox", { name: "Initial scope level" }),
                     { target: { value: "district" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Kampala" })).toBeTruthy());
    expect(screen.getByRole("button", { name: "Moroto" })).toBeTruthy();
  });

  it("grants the code behind the place, through the Operator scopes endpoint", async () => {
    await openCreate();
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "new.person" } });
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "new starter" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Initial scope level" }),
                     { target: { value: "district" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Kampala" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Kampala" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(posted.length).toBe(2));
    expect(posted[0].url).toMatch(/user-accounts\/create\/$/);
    expect(posted[1].url).toMatch(/operator-scopes\/bulk-grant\/$/);
    expect(posted[1].body.scope_level).toBe("district");
    expect(posted[1].body.scope_codes).toEqual(["102"]);
  });

  it("holds the confirm until a level that needs codes has one", async () => {
    await openCreate();
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "new starter" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Initial scope level" }),
                     { target: { value: "district" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Kampala" })).toBeTruthy());
    expect(screen.getByRole("button", { name: "Confirm" }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Kampala" }));
    expect(screen.getByRole("button", { name: "Confirm" }).disabled).toBe(false);
  });

  it("national takes no codes and shows no place list", async () => {
    await openCreate();
    fireEvent.change(screen.getByRole("combobox", { name: "Initial scope level" }),
                     { target: { value: "national" } });
    expect(screen.queryByLabelText("Search places")).toBeNull();
  });

  it("creates without a scope when none is chosen", async () => {
    await openCreate();
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "no.scope" } });
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "scope to follow" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0].url).toMatch(/create\/$/);
  });
});

describe("edit", () => {
  const openEdit = async () => {
    await show();
    const row = screen.getByText("akello.g").closest("tr");
    fireEvent.click([...row.querySelectorAll("button")].find(b => b.textContent === "Edit"));
  };

  it("pre-fills the current details", async () => {
    await openEdit();
    expect(screen.getByDisplayValue("Grace")).toBeTruthy();
    expect(screen.getByDisplayValue("g@example.test")).toBeTruthy();
  });

  it("will not let the username be changed", async () => {
    await openEdit();
    const username = screen.getByDisplayValue("akello.g");
    expect(username.disabled).toBe(true);
    expect(document.body.textContent).toMatch(/audit chain records who did what by username/);
  });

  it("posts only the editable fields, with the reason", async () => {
    await openEdit();
    fireEvent.change(screen.getByDisplayValue("g@example.test"), {
      target: { value: "grace.akello@example.test" },
    });
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "corrected address" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0].url).toMatch(/\/profile\/$/);
    expect(posted[0].body).toEqual({
      first_name: "Grace", last_name: "Akello",
      email: "grace.akello@example.test", reason: "corrected address",
    });
    expect(posted[0].body.username).toBeUndefined();
  });
});


describe("places read as names", () => {
  const openCreate = async () => {
    await show();
    fireEvent.click(screen.getByRole("button", { name: /New account/ }));
  };

  const pickParish = async () => {
    await openCreate();
    fireEvent.change(screen.getByRole("combobox", { name: "Initial scope level" }),
                     { target: { value: "parish" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /Acan Oryema/ })).toBeTruthy());
  };

  it("names the selection instead of reciting its code", async () => {
    // The screen showed "1 selected: 207.1.05.01", which tells an
    // administrator nothing about where they just granted access.
    await pickParish();
    fireEvent.click(screen.getByRole("button", { name: /Acan Oryema/ }));
    const summary = screen.getByText(/1 selected/).parentElement;
    expect(summary.textContent).toMatch(/Acan Oryema/);
  });

  it("keeps the code beside the name, because names are not unique", async () => {
    await pickParish();
    fireEvent.click(screen.getByRole("button", { name: /Acan Oryema/ }));
    const summary = screen.getByText(/1 selected/).parentElement;
    expect(summary.textContent).toMatch(/207\.1\.05\.02/);
  });

  it("distinguishes two places that share a name", async () => {
    // Both are called Acanga. Side by side with nothing else, choosing
    // between them is a coin toss.
    await pickParish();
    const acangas = screen.getAllByRole("button", { name: /Acanga/ });
    expect(acangas).toHaveLength(2);
    expect(acangas[0].textContent).toMatch(/207\.1\.05/);
    expect(acangas[1].textContent).toMatch(/311\.2\.07/);
  });

  it("does not clutter a name that is already unique", async () => {
    await pickParish();
    const unique = screen.getByRole("button", { name: /Acan Oryema/ });
    expect(unique.textContent.trim()).toBe("Acan Oryema");
  });

  it("still posts the code, not the name", async () => {
    await pickParish();
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "parish.chief" } });
    fireEvent.change(screen.getByPlaceholderText(/Why this change/), {
      target: { value: "new parish chief" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Acan Oryema/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted.length).toBe(2));
    expect(posted[1].body.scope_codes).toEqual(["207.1.05.02"]);
  });
});
