/* global React, PageHeader, Chip, Icon, nsrApi */
// NSR MIS — Chatbot Assistant (US-CHB-005 + US-CHB-006)
// RAG-grounded helper over the user manuals. Live API path:
//   GET    /api/v1/chatbot/conversations/
//   POST   /api/v1/chatbot/conversations/
//   GET    /api/v1/chatbot/conversations/{id}/
//   POST   /api/v1/chatbot/conversations/{id}/messages/
// Backend gates on CHATBOT_ENABLED — 404 surfaces as the off-state UI.

const { useState: useStateChb, useRef: useRefChb, useEffect: useEffectChb } = React;

const relTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
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
        opacity: message.__pending ? 0.7 : 1,
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
                   title={`${src.heading_path} · score ${Number(src.score || 0).toFixed(2)}`}>
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
  const [conversations, setConversations] = useStateChb([]);
  const [activeId, setActiveId] = useStateChb(null);
  // {id, title, messages: [...]} for the currently-open thread.
  const [activeDetail, setActiveDetail] = useStateChb(null);
  const [loadingList, setLoadingList] = useStateChb(true);
  const [loadingDetail, setLoadingDetail] = useStateChb(false);
  const [error, setError] = useStateChb(null);
  const [draft, setDraft] = useStateChb("");
  const [pending, setPending] = useStateChb(false);
  const [sendError, setSendError] = useStateChb(null);
  const scrollRef = useRefChb(null);

  // Load conversation list on mount.
  useEffectChb(() => {
    let cancelled = false;
    nsrApi.get("/api/v1/chatbot/conversations/")
      .then((data) => {
        if (cancelled) return;
        const list = (data && (data.results || data)) || [];
        setConversations(list);
        if (list.length > 0) setActiveId(list[0].id);
        setLoadingList(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err);
        setLoadingList(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Load messages whenever the active conversation changes.
  useEffectChb(() => {
    if (!activeId) { setActiveDetail(null); return undefined; }
    let cancelled = false;
    setLoadingDetail(true);
    nsrApi.get(`/api/v1/chatbot/conversations/${activeId}/`)
      .then((data) => {
        if (cancelled) return;
        setActiveDetail(data);
        setLoadingDetail(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err);
        setLoadingDetail(false);
      });
    return () => { cancelled = true; };
  }, [activeId]);

  // Auto-scroll to bottom on new content.
  useEffectChb(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [activeDetail?.messages?.length, pending]);

  const newConversation = async () => {
    setSendError(null);
    try {
      const fresh = await nsrApi.post("/api/v1/chatbot/conversations/", {});
      setConversations((prev) => [fresh, ...prev]);
      setActiveId(fresh.id);
      setActiveDetail({ ...fresh, messages: [] });
      setDraft("");
    } catch (err) {
      setError(err);
    }
  };

  const send = async () => {
    if (!draft.trim() || pending || !activeId) return;
    const content = draft.trim();
    const optimisticId = `pending-${Date.now()}`;
    setSendError(null);
    setDraft("");
    setPending(true);
    setActiveDetail((d) => d && ({
      ...d,
      messages: [
        ...(d.messages || []),
        { id: optimisticId, role: "user", content, created_at: new Date().toISOString(), __pending: true },
      ],
    }));
    try {
      const resp = await nsrApi.post(
        `/api/v1/chatbot/conversations/${activeId}/messages/`,
        { content },
      );
      setActiveDetail((d) => {
        if (!d) return d;
        const without = (d.messages || []).filter((m) => m.id !== optimisticId);
        return {
          ...d,
          title: d.title || (resp.user_message?.content || "").slice(0, 80),
          messages: [...without, resp.user_message, resp.assistant_message],
        };
      });
      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeId
            ? {
                ...c,
                title: c.title || (resp.user_message?.content || "").slice(0, 80),
                updated_at: resp.assistant_message?.created_at || c.updated_at,
              }
            : c,
        ),
      );
    } catch (err) {
      // Leave the optimistic bubble — user sees what they typed and
      // an inline error so they can retry without re-typing.
      setSendError(String(err.message || err));
    } finally {
      setPending(false);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // 404 on the list endpoint means CHATBOT_ENABLED=False on the
  // server. Surface that as an inline notice rather than a raw error.
  const flagOff = error && error.status === 404;

  return (
    <div className="page">
      <PageHeader
        title="Assistant"
        breadcrumb={["Admin console", "Assistant"]}
        tone="system"
      >
        <Chip tone="sec" size="sm">US-CHB</Chip>
        {flagOff && <Chip tone="draft" size="sm">Disabled</Chip>}
      </PageHeader>

      {flagOff && (
        <div style={{
          marginTop: 16,
          padding: 16,
          background: "var(--neutral-100)",
          border: "1px solid var(--neutral-300)",
          borderRadius: 8,
          color: "var(--neutral-700)",
          fontSize: 13,
        }}>
          The chatbot is disabled in this environment. An administrator must
          set <code>CHATBOT_ENABLED=True</code> and provide an
          <code>ANTHROPIC_API_KEY</code> in the server <code>.env</code>.
        </div>
      )}

      {!flagOff && (
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
            {loadingList && (
              <div style={{ padding: 12, color: "var(--neutral-500)", fontSize: 12 }}>
                Loading…
              </div>
            )}
            {!loadingList && conversations.length === 0 && (
              <div style={{ padding: 12, color: "var(--neutral-500)", fontSize: 12 }}>
                No conversations yet.
              </div>
            )}
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
            {!activeId && !loadingList && (
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
                <div style={{ fontSize: 14, fontWeight: 500 }}>Start a new conversation.</div>
              </div>
            )}
            {activeId && loadingDetail && (
              <div style={{ color: "var(--neutral-500)", fontSize: 13 }}>Loading messages…</div>
            )}
            {activeId && !loadingDetail && activeDetail && (activeDetail.messages || []).length === 0 && (
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
            {activeDetail && (activeDetail.messages || []).map((m) => (
              <MessageBubble key={m.id} message={m}/>
            ))}
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
            {sendError && (
              <div style={{
                marginTop: 12,
                padding: "8px 12px",
                borderRadius: 6,
                background: "#FDECEA",
                color: "#7F1D1D",
                fontSize: 12.5,
              }}>
                Could not send: {sendError}
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
              placeholder={
                activeId
                  ? "Ask about walk-in capture, DQA rules, routing…"
                  : "Click ‘New conversation’ to begin"
              }
              disabled={!activeId}
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
                background: activeId ? "var(--neutral-0)" : "var(--neutral-100)",
              }}
            />
            <button onClick={send}
                    disabled={!draft.trim() || pending || !activeId}
                    style={{
                      padding: "10px 16px",
                      border: 0,
                      background:
                        !draft.trim() || pending || !activeId
                          ? "var(--neutral-300)"
                          : "var(--primary-900)",
                      color: "var(--neutral-0)",
                      borderRadius: 6,
                      fontSize: 13,
                      fontWeight: 600,
                      cursor:
                        !draft.trim() || pending || !activeId
                          ? "not-allowed"
                          : "pointer",
                    }}>
              Send
            </button>
          </div>
        </section>
      </div>
      )}
    </div>
  );
};

if (typeof window !== "undefined") {
  window.ChatbotAssistantScreen = ChatbotAssistantScreen;
}
