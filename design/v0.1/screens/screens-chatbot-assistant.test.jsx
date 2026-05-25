/* CHB-005 — Assistant screen smoke + interaction tests.
 *
 * The screen is fixture-driven; the live backend lands behind
 * /api/v1/chatbot/. These tests pin the local interactions: empty
 * draft can't send, Enter submits, the optimistic user bubble
 * appears immediately, and the citation chip points at the
 * /manual/ page.
 */

import React from "react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

let ChatbotAssistantScreen;

beforeAll(async () => {
  // PageHeader isn't stubbed in vitest.setup.js — bind a minimal
  // replacement before the screen module loads.
  globalThis.PageHeader = ({ title, children }) =>
    React.createElement(
      "div",
      { "data-page-header": true },
      React.createElement("h1", null, title),
      children,
    );
  await import("./screens-chatbot-assistant.jsx");
  ({ ChatbotAssistantScreen } = globalThis);
});

afterEach(() => {
  cleanup();
});

describe("ChatbotAssistantScreen", () => {
  it("renders the demo conversation list", () => {
    render(<ChatbotAssistantScreen />);
    expect(screen.getByText("How do walk-in submissions work?")).toBeInTheDocument();
    expect(
      screen.getByText("What's the difference between DAT-DQA and DAT-DDUP?"),
    ).toBeInTheDocument();
  });

  it("renders the demo assistant message + citation chip", () => {
    render(<ChatbotAssistantScreen />);
    // Citation links to the MkDocs source path.
    const link = screen.getByText("field/walk-in-capture.md").closest("a");
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/manual/field/walk-in-capture/");
  });

  it("disables Send when the draft is empty", () => {
    render(<ChatbotAssistantScreen />);
    const sendBtn = screen.getByRole("button", { name: "Send" });
    expect(sendBtn).toBeDisabled();
  });

  it("appends a user bubble optimistically when sending", () => {
    render(<ChatbotAssistantScreen />);
    const textarea = screen.getByPlaceholderText(/Ask about walk-in capture/);
    act(() => {
      fireEvent.change(textarea, { target: { value: "What's a fast-track promotion?" } });
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    expect(
      screen.getByText("What's a fast-track promotion?"),
    ).toBeInTheDocument();
  });

  it("Enter submits, Shift+Enter does not", () => {
    render(<ChatbotAssistantScreen />);
    const textarea = screen.getByPlaceholderText(/Ask about walk-in capture/);
    act(() => {
      fireEvent.change(textarea, { target: { value: "q1" } });
    });
    act(() => {
      fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    });
    // Shift+Enter must not have sent (the bubble would be there if it did).
    // Textarea retains its value.
    expect(textarea.value).toBe("q1");
    act(() => {
      fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    });
    expect(screen.getByText("q1")).toBeInTheDocument();
  });

  it("New conversation button creates a fresh empty thread", () => {
    render(<ChatbotAssistantScreen />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /New conversation/i }));
    });
    // Empty-state copy renders when the active conversation has no messages.
    expect(
      screen.getByText("Ask anything about the NSR MIS user manual."),
    ).toBeInTheDocument();
  });
});
