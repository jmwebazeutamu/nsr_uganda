/* CHB-006 — Assistant screen tests against a stubbed nsrApi.
 *
 * The live screen calls nsrApi.get/post against /api/v1/chatbot/…
 * Tests bind a fake nsrApi on globalThis before the screen module
 * evaluates so the same code path runs under jsdom.
 */

import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let ChatbotAssistantScreen;

const SAMPLE_LIST = [
  {
    id: "01HCHBONE000000000000000001",
    title: "How do walk-in submissions work?",
    started_at: "2026-05-25T10:00:00Z",
    updated_at: "2026-05-25T10:42:00Z",
    message_count: 2,
  },
  {
    id: "01HCHBONE000000000000000002",
    title: "Routing a grievance to GRM Officer",
    started_at: "2026-05-23T09:00:00Z",
    updated_at: "2026-05-23T09:22:00Z",
    message_count: 0,
  },
];

const SAMPLE_DETAIL_WITH_MESSAGES = {
  id: "01HCHBONE000000000000000001",
  title: "How do walk-in submissions work?",
  started_at: "2026-05-25T10:00:00Z",
  updated_at: "2026-05-25T10:42:00Z",
  message_count: 2,
  messages: [
    {
      id: "m1",
      role: "user",
      content: "How do walk-in submissions work for Parish Chiefs?",
      created_at: "2026-05-25T10:41:00Z",
    },
    {
      id: "m2",
      role: "assistant",
      model: "claude-sonnet-4-6",
      content: "Parish Chiefs auto-promote walk-in households via the DIH fast-track lane.",
      tokens_in: 1450,
      tokens_out: 112,
      retrieval_sources: [
        {
          chunk_id: "01HCHB001",
          source_path: "field/walk-in-capture.md",
          heading_path: "Walk-in capture > Fast-track lane",
          score: 0.92,
        },
      ],
      created_at: "2026-05-25T10:41:18Z",
    },
  ],
};

const SAMPLE_DETAIL_EMPTY = {
  id: "01HCHBONE000000000000000002",
  title: "Routing a grievance to GRM Officer",
  started_at: "2026-05-23T09:00:00Z",
  updated_at: "2026-05-23T09:22:00Z",
  message_count: 0,
  messages: [],
};

const detailFor = (id) =>
  id === SAMPLE_DETAIL_WITH_MESSAGES.id ? SAMPLE_DETAIL_WITH_MESSAGES : SAMPLE_DETAIL_EMPTY;

beforeAll(async () => {
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

beforeEach(() => {
  globalThis.nsrApi = {
    get: vi.fn((url) => {
      if (url === "/api/v1/chatbot/conversations/") {
        return Promise.resolve({ results: SAMPLE_LIST });
      }
      const match = url.match(/\/conversations\/([^/]+)\/$/);
      if (match) return Promise.resolve(detailFor(match[1]));
      return Promise.reject(new Error(`unexpected GET ${url}`));
    }),
    post: vi.fn((url, body) => {
      if (url === "/api/v1/chatbot/conversations/") {
        return Promise.resolve({
          id: "01HCHBNEW00000000000000001",
          title: "",
          started_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
          messages: [],
        });
      }
      if (url.endsWith("/messages/")) {
        return Promise.resolve({
          user_message: {
            id: "u-new",
            role: "user",
            content: body.content,
            created_at: new Date().toISOString(),
          },
          assistant_message: {
            id: "a-new",
            role: "assistant",
            content: "Mock assistant reply.",
            model: "claude-sonnet-4-6",
            tokens_in: 100,
            tokens_out: 40,
            retrieval_sources: [],
            created_at: new Date().toISOString(),
          },
        });
      }
      return Promise.reject(new Error(`unexpected POST ${url}`));
    }),
  };
});

afterEach(() => {
  cleanup();
});

describe("ChatbotAssistantScreen — list + detail", () => {
  it("loads the conversation list and shows the first as active", async () => {
    render(<ChatbotAssistantScreen />);
    await waitFor(() =>
      expect(screen.getByText("How do walk-in submissions work?")).toBeInTheDocument(),
    );
    // Detail loads automatically — the assistant reply renders.
    await waitFor(() =>
      expect(
        screen.getByText(/Parish Chiefs auto-promote walk-in households/),
      ).toBeInTheDocument(),
    );
  });

  it("renders citation chips with /manual/ links", async () => {
    render(<ChatbotAssistantScreen />);
    const link = await screen.findByText("field/walk-in-capture.md");
    expect(link.closest("a").getAttribute("href")).toBe(
      "/manual/field/walk-in-capture/",
    );
  });

  it("switches to another conversation when clicked", async () => {
    render(<ChatbotAssistantScreen />);
    const other = await screen.findByText("Routing a grievance to GRM Officer");
    act(() => fireEvent.click(other));
    // Empty-state copy renders for the zero-message conversation.
    await waitFor(() =>
      expect(
        screen.getByText("Ask anything about the NSR MIS user manual."),
      ).toBeInTheDocument(),
    );
  });
});

describe("ChatbotAssistantScreen — sending", () => {
  it("send button disabled while draft is empty", async () => {
    render(<ChatbotAssistantScreen />);
    await screen.findByText("How do walk-in submissions work?");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("Enter posts to /messages/ and shows the assistant reply", async () => {
    render(<ChatbotAssistantScreen />);
    await screen.findByText("How do walk-in submissions work?");
    const textarea = screen.getByPlaceholderText(/Ask about walk-in capture/);
    act(() => fireEvent.change(textarea, { target: { value: "test prompt" } }));
    act(() => fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false }));
    await waitFor(() =>
      expect(globalThis.nsrApi.post).toHaveBeenCalledWith(
        expect.stringContaining("/messages/"),
        { content: "test prompt" },
      ),
    );
    await waitFor(() =>
      expect(screen.getByText("Mock assistant reply.")).toBeInTheDocument(),
    );
  });

  it("Shift+Enter inserts a newline and does not send", async () => {
    render(<ChatbotAssistantScreen />);
    await screen.findByText("How do walk-in submissions work?");
    const textarea = screen.getByPlaceholderText(/Ask about walk-in capture/);
    act(() => fireEvent.change(textarea, { target: { value: "q1" } }));
    act(() => fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true }));
    // No POST to /messages/ — only the GETs that ran on mount.
    expect(
      globalThis.nsrApi.post.mock.calls.find((c) => c[0].endsWith("/messages/")),
    ).toBeUndefined();
    expect(textarea.value).toBe("q1");
  });

  it("New conversation POSTs and switches focus to the fresh thread", async () => {
    render(<ChatbotAssistantScreen />);
    await screen.findByText("How do walk-in submissions work?");
    act(() => fireEvent.click(screen.getByRole("button", { name: /New conversation/i })));
    await waitFor(() =>
      expect(globalThis.nsrApi.post).toHaveBeenCalledWith(
        "/api/v1/chatbot/conversations/",
        {},
      ),
    );
  });

  it("send error surfaces inline and the user bubble is preserved", async () => {
    globalThis.nsrApi.post = vi.fn((url) => {
      if (url.endsWith("/messages/")) return Promise.reject(new Error("upstream 500"));
      return Promise.resolve({});
    });
    render(<ChatbotAssistantScreen />);
    await screen.findByText("How do walk-in submissions work?");
    const textarea = screen.getByPlaceholderText(/Ask about walk-in capture/);
    act(() => fireEvent.change(textarea, { target: { value: "will fail" } }));
    act(() => fireEvent.click(screen.getByRole("button", { name: "Send" })));
    await waitFor(() => expect(screen.getByText(/Could not send/)).toBeInTheDocument());
    // Optimistic bubble survived the failure.
    expect(screen.getByText("will fail")).toBeInTheDocument();
  });
});

describe("ChatbotAssistantScreen — flag off", () => {
  it("404 on the list endpoint shows the disabled banner", async () => {
    globalThis.nsrApi.get = vi.fn(() => {
      const err = new Error("HTTP 404");
      err.status = 404;
      return Promise.reject(err);
    });
    render(<ChatbotAssistantScreen />);
    await waitFor(() =>
      expect(screen.getByText(/chatbot is disabled in this environment/i))
        .toBeInTheDocument(),
    );
  });
});
