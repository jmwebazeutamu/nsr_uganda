/* global React, PageHeader, Chip, Icon */
// NSR MIS — Chatbot Assistant (US-CHB-005)
// RAG-grounded helper over the user manuals. Mock data only; the live
// backend lands behind /api/v1/chatbot/ — see ADR-0021 + apps/chatbot/.

const { useState: useStateChb, useRef: useRefChb, useEffect: useEffectChb } = React;

const DEMO_CONVERSATIONS = [
  {
    id: "01HCHBDEMO001",
    title: "How do walk-in submissions work?",
    updated_at: "2026-05-25T10:42:00Z",
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
        content:
          "A Parish Chief captures a walk-in household through the DIH fast-track lane. The submission lands in the DIH staging area as usual, but is auto-promoted past the standard review queue so the household reaches the registry the same working day. DQA + DDUP checks still run; if either fails the record drops back into the steward queue for manual review.",
        retrieval_sources: [
          {
            chunk_id: "01HCHB001",
            source_path: "field/walk-in-capture.md",
            heading_path: "Walk-in capture > Fast-track lane",
            score: 0.92,
          },
          {
            chunk_id: "01HCHB002",
            source_path: "steward/dih-review-queue.md",
            heading_path: "DIH review queue > Auto-promotion",
            score: 0.78,
          },
        ],
        tokens_in: 1450,
        tokens_out: 112,
        created_at: "2026-05-25T10:41:18Z",
      },
    ],
  },
  {
    id: "01HCHBDEMO002",
    title: "What's the difference between DAT-DQA and DAT-DDUP?",
    updated_at: "2026-05-24T16:08:00Z",
    messages: [],
  },
  {
    id: "01HCHBDEMO003",
    title: "Routing a grievance to GRM Officer",
    updated_at: "2026-05-23T09:22:00Z",
    messages: [],
  },
];

const relTime = (iso) => {
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
};

const MessageBubble = ({ message }) => {
  const isUser = message.role === "user";
  return (
    <div style={{
      display: "flex",
      justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: 16,
    }}>
      <div style={{
        maxWidth: "78%",
        background: isUser ? "var(--primary-900)" : "var(--neutral-0)",
        color: isUser ? "var(--neutral-0)" : "var(--neutral-900)",
        border: isUser ? "0" : "1px solid var(--neutral-300)",
        borderRadius: 12,
        padding: "10px 14px",
        fontSize: 14,
        lineHeight: 1.5,
        whiteSpace: "pre-wrap",
        boxShadow: isUser ? "none" : "var(--shadow-card)",
      }}>
        {message.content}
        {message.role === "assistant" && message.retrieval_sources?.length > 0 && (
          <div style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: "1px dashed var(--neutral-300)",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}>
            <div style={{
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--neutral-500)",
            }}>
              Sources
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {message.retrieval_sources.map((src) => (
                <a key={src.chunk_id}
                   href={`/manual/${src.source_path.replace(/\.md$/, "/")}`}
                   target="_blank" rel="noreferrer"
                   style={{
                     display: "inline-flex",
                     alignItems: "center",
                     gap: 4,
                     padding: "3px 8px",
                     borderRadius: 6,
                     background: "var(--neutral-100)",
                     color: "var(--neutral-700)",
                     fontSize: 11.5,
                     fontWeight: 500,
                     textDecoration: "none",
                     border: "1px solid var(--neutral-300)",
                   }}
                   title={`${src.heading_path} · score ${src.score.toFixed(2)}`}>
                  <Icon name="file" size={11}/>
                  {src.source_path}
                </a>
              ))}
            </div>
          </div>
        )}
        {message.role === "assistant" && message.tokens_in != null && (
          <div style={{
            marginTop: 8,
            fontSize: 10,
            color: "var(--neutral-500)",
          }}>
            {message.model} · {message.tokens_in} in / {message.tokens_out} out
          </div>
        )}
      </div>
    </div>
  );
};

const ChatbotAssistantScreen = () => {
  const [conversations, setConversations] = useStateChb(DEMO_CONVERSATIONS);
  const [activeId, setActiveId] = useStateChb(DEMO_CONVERSATIONS[0].id);
  const [draft, setDraft] = useStateChb("");
  const [pending, setPending] = useStateChb(false);
  const scrollRef = useRefChb(null);

  const active = conversations.find((c) => c.id === activeId);

  useEffectChb(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [active?.messages?.length, pending]);

  const newConversation = () => {
    const id = `01HCHB${Date.now().toString(36).toUpperCase().padStart(20, "0").slice(-20)}`;
    const fresh = { id, title: "", updated_at: new Date().toISOString(), messages: [] };
    setConversations([fresh, ...conversations]);
    setActiveId(id);
    setDraft("");
  };

  const send = () => {
    if (!draft.trim() || pending) return;
    const userMsg = {
      id: `u-${Date.now()}`,
      role: "user",
      content: draft.trim(),
      created_at: new Date().toISOString(),
    };
    // Optimistically append.
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeId
          ? {
              ...c,
              title: c.title || draft.trim().slice(0, 80),
              messages: [...c.messages, userMsg],
              updated_at: userMsg.created_at,
            }
          : c,
      ),
    );
    setDraft("");
    setPending(true);
    // Mock — the real wiring calls POST /api/v1/chatbot/conversations/{id}/messages/.
    setTimeout(() => {
      const assistantMsg = {
        id: `a-${Date.now()}`,
        role: "assistant",
        model: "claude-sonnet-4-6",
        content:
          "Mock reply: the real chatbot will call /api/v1/chatbot/conversations/{id}/messages/ and return the assistant turn with retrieval_sources populated from the ManualChunk index.",
        retrieval_sources: [
          {
            chunk_id: "01HCHBSAMPLE",
            source_path: "steward/dqa-rules.md",
            heading_path: "DQA rules > Authoring",
            score: 0.81,
          },
        ],
        tokens_in: 980,
        tokens_out: 64,
        created_at: new Date().toISOString(),
      };
      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeId
            ? { ...c, messages: [...c.messages, assistantMsg], updated_at: assistantMsg.created_at }
            : c,
        ),
      );
      setPending(false);
    }, 700);
  };

  const onKeyDown = (e) => {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Assistant"
        breadcrumb={["Admin console", "Assistant"]}
        tone="system"
      >
        <Chip tone="sec" size="sm">US-CHB-005</Chip>
        <Chip tone="draft" size="sm">Preview</Chip>
      </PageHeader>

      <div style={{
        display: "grid",
        gridTemplateColumns: "260px 1fr",
        gap: 16,
        height: "calc(100vh - 180px)",
        marginTop: 12,
      }}>
        {/* Conversation list */}
        <aside style={{
          background: "var(--neutral-0)",
          border: "1px solid var(--neutral-300)",
          borderRadius: 8,
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          overflow: "hidden",
        }}>
          <button onClick={newConversation}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 6,
                    padding: "8px 12px",
                    border: "1px solid var(--primary-900)",
                    background: "var(--primary-900)",
                    color: "var(--neutral-0)",
                    borderRadius: 6,
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}>
            <Icon name="plus" size={12}/> New conversation
          </button>
          <div style={{
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: "var(--neutral-500)",
            padding: "8px 4px 4px",
          }}>
            Recent
          </div>
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
            {conversations.map((c) => {
              const isActive = c.id === activeId;
              return (
                <button key={c.id}
                        onClick={() => setActiveId(c.id)}
                        style={{
                          textAlign: "left",
                          padding: "8px 10px",
                          borderRadius: 6,
                          border: "1px solid transparent",
                          background: isActive ? "var(--primary-100)" : "transparent",
                          borderColor: isActive ? "var(--primary-700)" : "transparent",
                          cursor: "pointer",
                          display: "flex",
                          flexDirection: "column",
                          gap: 2,
                        }}>
                  <div style={{
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 500,
                    color: "var(--neutral-900)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}>
                    {c.title || "Untitled conversation"}
                  </div>
                  <div style={{ fontSize: 10.5, color: "var(--neutral-500)" }}>
                    {relTime(c.updated_at)}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Chat pane */}
        <section style={{
          background: "var(--neutral-100)",
          border: "1px solid var(--neutral-300)",
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}>
          <div ref={scrollRef} style={{
            flex: 1,
            overflowY: "auto",
            padding: 20,
          }}>
            {active && active.messages.length === 0 && (
              <div style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
                color: "var(--neutral-500)",
                gap: 8,
              }}>
                <Icon name="message-square" size={32}/>
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  Ask anything about the NSR MIS user manual.
                </div>
                <div style={{ fontSize: 12 }}>
                  Replies cite the source page so you can verify.
                </div>
              </div>
            )}
            {active && active.messages.map((m) => <MessageBubble key={m.id} message={m}/>)}
            {pending && (
              <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
                <div style={{
                  background: "var(--neutral-0)",
                  border: "1px solid var(--neutral-300)",
                  borderRadius: 12,
                  padding: "10px 14px",
                  fontSize: 13,
                  color: "var(--neutral-500)",
                }}>
                  thinking…
                </div>
              </div>
            )}
          </div>

          {/* Input bar */}
          <div style={{
            padding: 12,
            borderTop: "1px solid var(--neutral-300)",
            background: "var(--neutral-0)",
            display: "flex",
            gap: 8,
            alignItems: "flex-end",
          }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask about walk-in capture, DQA rules, routing…"
              rows={2}
              style={{
                flex: 1,
                resize: "none",
                padding: "8px 10px",
                border: "1px solid var(--neutral-300)",
                borderRadius: 6,
                fontSize: 13,
                fontFamily: "inherit",
                lineHeight: 1.5,
                outline: "none",
              }}
            />
            <button onClick={send}
                    disabled={!draft.trim() || pending}
                    style={{
                      padding: "10px 16px",
                      border: 0,
                      background:
                        !draft.trim() || pending
                          ? "var(--neutral-300)"
                          : "var(--primary-900)",
                      color: "var(--neutral-0)",
                      borderRadius: 6,
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: !draft.trim() || pending ? "not-allowed" : "pointer",
                    }}>
              Send
            </button>
          </div>
        </section>
      </div>
    </div>
  );
};

if (typeof window !== "undefined") {
  window.ChatbotAssistantScreen = ChatbotAssistantScreen;
}
