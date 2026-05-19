import "@testing-library/jest-dom";
import React from "react";

// The browser harness wires Icon, Chip, Modal as globals via
// components.jsx. Component-under-test files reference them by bare
// identifier — to keep the modal source identical between browser
// and test, we bind matching globals here BEFORE component imports
// resolve (Vitest evaluates setupFiles ahead of test-file imports).

globalThis.React = React;

globalThis.Icon = ({ name, size, color, style, ...rest }) =>
  React.createElement("i", { "data-icon": name, style, ...rest });

globalThis.Chip = ({ children, tone, size, dot, icon, style, ...rest }) =>
  React.createElement(
    "span",
    {
      "data-chip": true,
      "data-tone": tone || "neutral",
      "data-size": size || "md",
      style,
      ...rest,
    },
    children,
  );

globalThis.Modal = ({ open, onClose, title, children, footer, width }) =>
  open
    ? React.createElement(
        "div",
        {
          role: "dialog",
          "aria-label": title,
          "data-modal-width": width,
        },
        React.createElement("h2", { "data-modal-title": true }, title),
        React.createElement("div", { "data-modal-body": true }, children),
        footer
          ? React.createElement(
              "div",
              { className: "modal-footer", "data-modal-footer": true },
              footer,
            )
          : null,
      )
    : null;

// The Modal stub above doesn't wire ESC by itself — the real Modal
// component does. We bind a window-level listener that mirrors that
// behaviour, so tests can fire keydown Escape and expect onClose to
// fire. The cleanup hooks per test reset listeners via RTL.
globalThis.__nsrModalEscHandler = null;
const Modal = globalThis.Modal;
globalThis.Modal = ({ open, onClose, title, children, footer, width }) => {
  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose && onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return Modal({ open, onClose, title, children, footer, width });
};
