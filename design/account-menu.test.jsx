/* The account menu, and the thing it nearly lost.
 *
 * Collapsing five header icons into one menu removed the only caller of
 * the DSA quick-find. The panel stayed mounted in the operator shell —
 * state declared, component rendered — with nothing able to set it open.
 * Nothing failed; the feature was simply unreachable.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_SOURCE = fs.readFileSync(path.join(HERE, "app.jsx"), "utf8");

let AccountMenu;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.useState = React.useState;
  globalThis.useEffect = React.useEffect;
  globalThis.useRef = React.useRef;
  globalThis.useMemo = React.useMemo;
  await import("./components.jsx");
  ({ AccountMenu } = globalThis);
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const openMenu = (props = {}) => {
  render(<AccountMenu name="Akello Grace" initials="AG" {...props}/>);
  fireEvent.click(screen.getByRole("button", { name: /Akello Grace/ }));
};

describe("the account menu", () => {
  it("keeps the account actions together", () => {
    openMenu();
    expect(screen.getByRole("menuitem", { name: "View/Edit Profile" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Change Password" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Logout" })).toBeTruthy();
  });

  it("offers Find a DSA when the shell supplies a handler", () => {
    openMenu({ onFindDsa: () => {} });
    expect(screen.getByRole("menuitem", { name: "Find a DSA" })).toBeTruthy();
  });

  it("omits it when the shell does not", () => {
    // The admin shell has no DSA finder, so the item must not appear
    // there pointing at nothing.
    openMenu();
    expect(screen.queryByRole("menuitem", { name: "Find a DSA" })).toBeNull();
  });

  it("opens the finder and closes itself", () => {
    const onFindDsa = vi.fn();
    openMenu({ onFindDsa });
    fireEvent.click(screen.getByRole("menuitem", { name: "Find a DSA" }));
    expect(onFindDsa).toHaveBeenCalledTimes(1);
    // A menu left hanging over the panel it just opened is its own bug.
    expect(screen.queryByRole("menuitem", { name: "Find a DSA" })).toBeNull();
  });

  it("closes on Escape", () => {
    openMenu();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menuitem", { name: "Logout" })).toBeNull();
  });
});

describe("the operator shell still opens the DSA finder", () => {
  it("passes a handler that sets the panel open", () => {
    // The guard for the regression itself: DsaQuickFind is rendered on
    // `dsaFindOpen`, so something has to be able to set it true.
    expect(APP_SOURCE).toMatch(/onFindDsa=\{[^}]*setDsaFindOpen\(true\)/s);
  });

  it("still withholds it from a partner-analyst", () => {
    // The old header button was hidden for that role; moving it into the
    // menu must not quietly widen who can search every agreement.
    expect(APP_SOURCE).toMatch(/role === "partner-analyst" \? null :/);
  });
});
