/* global React, Icon */
// Wide view — one pattern, two entry points.
// =========================================================
// The console's list screens stack a table over a detail rail, which
// leaves about five rows of an 82-row queue on screen. At national load
// that is the wrong shape for triage: an operator scanning for SLA
// breaches needs the list, not the record.
//
// This module gives any list screen two ways to get the whole window:
//
//   MAXIMISE   an in-page overlay. The screen renders inside a fixed
//              full-viewport container, over the sidebar and masthead.
//              Escape or the button restores it. Nothing is navigated,
//              so no state is lost and no popup blocker is involved.
//
//   POP OUT    a real second window at `?wide=<screen>`, which the app
//              shell recognises at boot and renders without the nav or
//              masthead. It is the same application on the same session
//              cookie — fully interactive, not a copy of the table — so
//              it can be dragged to a second monitor while the decision
//              panel stays in the first window.
//
// State passes one way, at open time: the current filters are encoded
// into the URL and the popped window starts from them. After that the
// two windows are independent and each refetches from the API. There is
// deliberately no live channel between them — cross-window state sync is
// a substantial thing to get right, and the case for it here is thin.
//
// See docs/adr/0030-console-wide-view.md.

const WIDE_PARAM = "wide";
const WIDE_FILTERS_PARAM = "filters";
// A guard, not a limit anyone should hit: filters are a handful of short
// strings. A URL longer than this means something unintended is being
// serialised, and a popped window with a truncated query is worse than
// one that starts from defaults.
const WIDE_FILTERS_MAX = 1500;

/** Which screen, if any, this document was opened as a wide window for. */
const _wideRequestedScreen = (search) => {
  try {
    return new URLSearchParams(search || "").get(WIDE_PARAM) || null;
  } catch {
    return null;
  }
};

/** Drop empty values so "any" does not travel as a real filter. */
const _wideCleanFilters = (filters) => {
  if (!filters || typeof filters !== "object" || Array.isArray(filters)) return null;
  const out = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value === null || value === undefined || value === "" || value === false) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    out[key] = value;
  }
  return Object.keys(out).length ? out : null;
};

/** The filters a wide window was opened with, or null. */
const _wideInheritedFilters = (search) => {
  let raw;
  try {
    raw = new URLSearchParams(search || "").get(WIDE_FILTERS_PARAM);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    // Anything but a plain object came from somewhere this code did not
    // write, so it is not applied.
    return _wideCleanFilters(parsed);
  } catch {
    return null;
  }
};

/** The URL a pop-out opens. Pure, so the contract can be tested. */
const _wideUrl = (screen, filters, path = "/console/") => {
  const params = new URLSearchParams();
  params.set(WIDE_PARAM, screen);
  const clean = _wideCleanFilters(filters);
  if (clean) {
    const encoded = JSON.stringify(clean);
    if (encodeURIComponent(encoded).length <= WIDE_FILTERS_MAX) {
      params.set(WIDE_FILTERS_PARAM, encoded);
    }
  }
  return `${path}?${params.toString()}`;
};

/**
 * Wide-view state for one screen.
 *
 * `isWide` is true in both modes, so a screen has one branch to write.
 * What differs is who supplies the chrome: the overlay below when
 * maximised, the app shell when popped out.
 */
const useWideView = (screenId) => {
  const search = typeof window !== "undefined" ? (window.location.search || "") : "";
  const isPopout = _wideRequestedScreen(search) === screenId;
  const [maximised, setMaximised] = React.useState(false);
  const [popoutBlocked, setPopoutBlocked] = React.useState(false);
  const isWide = isPopout || maximised;

  // Escape leaves the overlay. Not wired in a popped-out window: there,
  // Escape closing the whole window would be a surprise.
  React.useEffect(() => {
    if (!maximised) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setMaximised(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [maximised]);

  // The overlay scrolls; the page behind it must not.
  React.useEffect(() => {
    if (!maximised || typeof document === "undefined") return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [maximised]);

  const popOut = (filters) => {
    const path = (typeof window !== "undefined" && window.location.pathname) || "/console/";
    const url = _wideUrl(screenId, filters, path);
    let opened = null;
    try {
      opened = window.open(url, `nsr-wide-${screenId}`, "noopener=false,width=1680,height=1000");
    } catch {
      opened = null;
    }
    if (!opened) {
      // Blocked, or opened into nothing. Falling back to the overlay
      // gives the operator what they asked for — a wider view — instead
      // of a button that appears to do nothing.
      setPopoutBlocked(true);
      setMaximised(true);
      return false;
    }
    setPopoutBlocked(false);
    try { opened.focus(); } catch { /* focus is a courtesy, not a requirement */ }
    return true;
  };

  return {
    isWide,
    isPopout,
    maximised,
    popoutBlocked,
    maximise: () => setMaximised(true),
    restore: () => setMaximised(false),
    popOut,
    inheritedFilters: isPopout ? _wideInheritedFilters(search) : null,
  };
};

/**
 * The header buttons. Renders nothing in a popped-out window — that
 * window IS the wide view, and an "open in new window" button inside it
 * only invites a second copy.
 */
const WideViewButtons = ({ wide, filters, label = "records" }) => {
  if (!wide || wide.isPopout) return null;
  if (wide.maximised) {
    return (
      <button className="btn" onClick={wide.restore} title="Back to the normal layout (Esc)">
        <Icon name="x" size={14}/> Exit wide view
      </button>
    );
  }
  return (
    <>
      <button className="btn" onClick={wide.maximise}
              title={`Fill the window with the ${label} table`}>
        <Icon name="maximize" size={14}/> Wider view
      </button>
      <button className="btn" onClick={() => wide.popOut(filters)}
              title="Open this list in a second window, carrying the current filters">
        <Icon name="externalLink" size={14}/> Open in new window
      </button>
    </>
  );
};

/**
 * The full-viewport container for MAXIMISE. Transparent in every other
 * mode: a screen wraps its whole body in this and is otherwise unchanged.
 */
const WideShell = ({ wide, children }) => {
  if (!wide || !wide.maximised) return <>{children}</>;
  return (
    <div className="wide-shell" role="region" aria-label="Wide view">
      {children}
    </div>
  );
};

/**
 * Where a row's detail goes.
 *
 * Normal layout: exactly where it was — this renders its children inline,
 * so the stacked table-over-detail arrangement is untouched.
 *
 * Wide layout: a right-hand drawer over the table, opened by selecting a
 * row. The table keeps the width it was given; the operator keeps their
 * place in the list; every action in the detail still works because it is
 * the same markup with the same handlers.
 */
const WideDetailHost = ({ wide, open, onClose, title, subtitle, children }) => {
  const isWide = !!(wide && wide.isWide);

  // Escape closes the drawer before it leaves the overlay, so a single
  // key does the least destructive thing first.
  React.useEffect(() => {
    if (!isWide || !open) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose?.();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [isWide, open, onClose]);

  if (!isWide) return <>{children}</>;
  if (!open) return null;

  return (
    <>
      <div className="drawer-backdrop drawer-fixed open" onClick={onClose}/>
      <aside className="drawer drawer-wide open" aria-label={title || "Record detail"}>
        <div className="drawer-header">
          <div style={{ minWidth: 0 }}>
            <div className="t-cap">RECORD DETAIL</div>
            <h3 className="t-h3" style={{ margin: "2px 0 0" }}>{title}</h3>
            {subtitle && <div className="t-cap mt-1">{subtitle}</div>}
          </div>
          <button className="icon-btn" onClick={onClose} title="Close (Esc)" aria-label="Close record detail">
            <Icon name="x"/>
          </button>
        </div>
        <div className="drawer-body" style={{ padding: 16 }}>
          {children}
        </div>
      </aside>
    </>
  );
};

/** A scroll box for the table itself, so its sticky header earns its keep. */
const wideTableScrollStyle = (wide, reserved = 260) =>
  (wide && wide.isWide)
    ? { maxHeight: `calc(100vh - ${reserved}px)`, overflow: "auto" }
    : undefined;

Object.assign(window, {
  useWideView,
  WideViewButtons,
  WideShell,
  WideDetailHost,
  wideTableScrollStyle,
  // Exported for the unit tests and for the app shell's boot check.
  _wideRequestedScreen,
  _wideInheritedFilters,
  _wideCleanFilters,
  _wideUrl,
  WIDE_FILTERS_MAX,
});
