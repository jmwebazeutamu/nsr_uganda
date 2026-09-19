/* Wide view — the URL contract and the two containers.
 *
 * The pop-out is a real second window loading `?wide=<screen>`, so the
 * URL *is* the interface between the two windows. These cases pin what
 * it carries, what it refuses to carry, and that a screen wrapped in
 * these containers is unchanged when the wide view is off.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

let useWideView, WideViewButtons, WideShell, WideDetailHost, wideTableScrollStyle;
let _wideRequestedScreen, _wideInheritedFilters, _wideCleanFilters, _wideUrl, WIDE_FILTERS_MAX;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.window = globalThis;
  await import("./wide-view.jsx");
  ({
    useWideView, WideViewButtons, WideShell, WideDetailHost, wideTableScrollStyle,
    _wideRequestedScreen, _wideInheritedFilters, _wideCleanFilters, _wideUrl,
    WIDE_FILTERS_MAX,
  } = globalThis);
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the pop-out URL", () => {
  it("names the screen it is opening", () => {
    expect(_wideUrl("dih", null, "/console/")).toBe("/console/?wide=dih");
  });

  it("carries the filters that are set", () => {
    const url = _wideUrl("dih", { quick: "quality_failed", source: "Kobo" }, "/console/");
    const filters = JSON.parse(new URLSearchParams(url.split("?")[1]).get("filters"));
    expect(filters).toEqual({ quick: "quality_failed", source: "Kobo" });
  });

  it("does not carry 'any' as though it were a filter", () => {
    // Empty selects are how the screen says "no filter". Sending them
    // would make the popped window's toolbar look configured when it
    // is not.
    const url = _wideUrl("dih", { quick: null, source: "", dqa: undefined, tab: false }, "/console/");
    expect(url).toBe("/console/?wide=dih");
  });

  it("opens at the path it was given, so the design harness works too", () => {
    const url = _wideUrl("dih", null, "/design/nsr-mis-console.html");
    expect(url.startsWith("/design/nsr-mis-console.html?")).toBe(true);
  });

  it("drops filters rather than emitting a truncated URL", () => {
    const huge = { quick: "x".repeat(WIDE_FILTERS_MAX + 100) };
    const url = _wideUrl("dih", huge, "/console/");
    expect(url).toBe("/console/?wide=dih");
  });
});

describe("reading a wide window's URL", () => {
  it("recognises the screen", () => {
    expect(_wideRequestedScreen("?wide=dih")).toBe("dih");
    expect(_wideRequestedScreen("?foo=1")).toBeNull();
    expect(_wideRequestedScreen("")).toBeNull();
  });

  it("round-trips the filters it wrote", () => {
    const url = _wideUrl("dih", { quick: "sla_at_risk" }, "/console/");
    expect(_wideInheritedFilters(url.split("?")[1])).toEqual({ quick: "sla_at_risk" });
  });

  it("ignores a filters param that is not an object", () => {
    // Anything but a plain object came from somewhere this code did not
    // write, so it does not get applied to a queue of personal data.
    expect(_wideInheritedFilters("wide=dih&filters=%5B1%2C2%5D")).toBeNull();
    expect(_wideInheritedFilters('wide=dih&filters="nope"')).toBeNull();
    expect(_wideInheritedFilters("wide=dih&filters=%7Bbroken")).toBeNull();
  });

  it("treats no filters as no filters, not as an error", () => {
    expect(_wideInheritedFilters("wide=dih")).toBeNull();
    expect(_wideCleanFilters({})).toBeNull();
  });
});

const Harness = ({ screenId = "dih", onReady, selected = true }) => {
  const wide = useWideView(screenId);
  // Mirrors a screen's own selected-row state: the drawer is open
  // because a row is selected, and closing it clears the selection.
  const [open, setOpen] = globalThis.React.useState(selected);
  onReady?.(wide);
  return (
    <WideShell wide={wide}>
      <div data-testid="body">
        <WideViewButtons wide={wide} filters={{ quick: "quality_failed" }}/>
        <WideDetailHost wide={wide} open={open} onClose={() => setOpen(false)} title="Nakalema Daniel">
          <div data-testid="detail">detail rail</div>
        </WideDetailHost>
      </div>
    </WideShell>
  );
};

describe("in the normal window", () => {
  it("offers both ways to get more room", () => {
    render(<Harness/>);
    expect(screen.getByText("Wider view")).toBeTruthy();
    expect(screen.getByText("Open in new window")).toBeTruthy();
  });

  it("leaves the layout exactly as it was", () => {
    // The detail renders inline — no drawer, no overlay. A screen that
    // never uses the wide view must be untouched by this module.
    render(<Harness/>);
    expect(screen.getByTestId("detail")).toBeTruthy();
    expect(document.querySelector(".drawer")).toBeNull();
    expect(document.querySelector(".wide-shell")).toBeNull();
  });

  it("does not constrain the table's height", () => {
    let wide;
    render(<Harness onReady={w => { wide = w; }}/>);
    expect(wideTableScrollStyle(wide)).toBeUndefined();
  });
});

describe("maximised", () => {
  it("puts the screen in a full-viewport overlay and moves the detail into a drawer", () => {
    render(<Harness/>);
    fireEvent.click(screen.getByText("Wider view"));
    expect(document.querySelector(".wide-shell")).toBeTruthy();
    expect(document.querySelector(".drawer.drawer-wide")).toBeTruthy();
    expect(screen.getByTestId("detail")).toBeTruthy();  // same markup, new home
  });

  it("offers the way back", () => {
    render(<Harness/>);
    fireEvent.click(screen.getByText("Wider view"));
    expect(screen.getByText("Exit wide view")).toBeTruthy();
    fireEvent.click(screen.getByText("Exit wide view"));
    expect(document.querySelector(".wide-shell")).toBeNull();
  });

  it("Escape closes the drawer first, and only then leaves the overlay", () => {
    // One key, least destructive thing first: an operator pressing Esc
    // to dismiss a record should not also lose the wide list they were
    // working through.
    render(<Harness/>);
    fireEvent.click(screen.getByText("Wider view"));
    expect(document.querySelector(".drawer.drawer-wide")).toBeTruthy();

    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(document.querySelector(".drawer.drawer-wide")).toBeNull();
    expect(document.querySelector(".wide-shell")).toBeTruthy();

    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(document.querySelector(".wide-shell")).toBeNull();
  });

  it("gives the table the window's height", () => {
    let wide;
    render(<Harness onReady={w => { wide = w; }}/>);
    fireEvent.click(screen.getByText("Wider view"));
    expect(wideTableScrollStyle(wide).maxHeight).toMatch(/100vh/);
  });

  it("stops the page behind the overlay from scrolling", () => {
    render(<Harness/>);
    fireEvent.click(screen.getByText("Wider view"));
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByText("Exit wide view"));
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});

describe("popping out", () => {
  it("opens the wide URL in a named window", () => {
    const open = vi.fn(() => ({ focus: vi.fn() }));
    globalThis.window.open = open;
    render(<Harness/>);
    fireEvent.click(screen.getByText("Open in new window"));
    const [url, name] = open.mock.calls[0];
    expect(url).toContain("wide=dih");
    expect(JSON.parse(decodeURIComponent(url.split("filters=")[1]))).toEqual({ quick: "quality_failed" });
    // Named, so a second click focuses the window rather than opening
    // a third copy of the same queue.
    expect(name).toBe("nsr-wide-dih");
  });

  it("falls back to maximising when the popup is blocked", () => {
    // A blocked popup returns null. Doing nothing would leave a button
    // that appears broken; the operator asked for a wider view, so they
    // get one.
    globalThis.window.open = vi.fn(() => null);
    render(<Harness/>);
    fireEvent.click(screen.getByText("Open in new window"));
    expect(document.querySelector(".wide-shell")).toBeTruthy();
  });

  it("survives window.open throwing", () => {
    globalThis.window.open = vi.fn(() => { throw new Error("blocked"); });
    render(<Harness/>);
    expect(() => fireEvent.click(screen.getByText("Open in new window"))).not.toThrow();
    expect(document.querySelector(".wide-shell")).toBeTruthy();
  });
});

describe("inside a popped-out window", () => {
  const withSearch = (search, fn) => {
    const original = globalThis.window.location;
    delete globalThis.window.location;
    globalThis.window.location = { search, pathname: "/console/" };
    try { fn(); } finally { globalThis.window.location = original; }
  };

  it("is wide without being maximised, and offers no further pop-out", () => {
    withSearch("?wide=dih&filters=%7B%22quick%22%3A%22sla_at_risk%22%7D", () => {
      let wide;
      render(<Harness onReady={w => { wide = w; }}/>);
      expect(wide.isPopout).toBe(true);
      expect(wide.isWide).toBe(true);
      expect(wide.maximised).toBe(false);
      expect(wide.inheritedFilters).toEqual({ quick: "sla_at_risk" });
      // No "Open in new window" inside the window that is already it.
      expect(screen.queryByText("Open in new window")).toBeNull();
      expect(screen.queryByText("Wider view")).toBeNull();
      // No overlay either — the shell supplies the chrome here.
      expect(document.querySelector(".wide-shell")).toBeNull();
      expect(document.querySelector(".drawer.drawer-wide")).toBeTruthy();
    });
  });

  it("ignores a wide param for a different screen", () => {
    withSearch("?wide=registry", () => {
      let wide;
      render(<Harness onReady={w => { wide = w; }}/>);
      expect(wide.isPopout).toBe(false);
      expect(wide.isWide).toBe(false);
    });
  });
});
