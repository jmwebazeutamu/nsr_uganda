"""Service layer for chatbot turn-taking.

`send_message` is the one entry point — viewsets call this. Keeps the
LLM + retrieval + audit orchestration out of the request layer so it's
testable without spinning up DRF.
"""

from __future__ import annotations

from apps.security.audit import emit as emit_audit

from .models import Conversation, Message
from .provider import complete
from .retrieval import retrieve

SYSTEM_PROMPT_HEADER = (
    "You are the NSR MIS Assistant — an internal-staff helper for the Uganda "
    "National Social Registry MIS. Answer using ONLY the manual passages "
    "provided in <context>. If the answer is not in the context, say so "
    "plainly. Cite the source path of each passage you used."
)


def _build_system_prompt(hits) -> str:
    if not hits:
        return SYSTEM_PROMPT_HEADER + "\n\n<context>(no relevant passages found)</context>"
    parts = [SYSTEM_PROMPT_HEADER, "\n<context>"]
    for hit in hits:
        parts.append(f"\n[source: {hit.chunk.source_path} — {hit.chunk.heading_path}]")
        parts.append(hit.chunk.content)
    parts.append("\n</context>")
    return "\n".join(parts)


def send_message(
    *,
    conversation: Conversation,
    user_content: str,
    actor_username: str,
    k: int = 5,
) -> tuple[Message, Message]:
    """Persist the user prompt, retrieve context, call the LLM, persist
    the assistant reply, emit audit on both turns.

    Returns the (user_message, assistant_message) pair. Raises whatever
    the provider raises if the LLM call fails — the user message is
    already persisted at that point so the user can retry.
    """
    user_msg = Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content=user_content,
    )
    emit_audit(
        action="chatbot.message.send",
        entity_type="message",
        entity_id=user_msg.id,
        actor=actor_username,
    )

    hits = retrieve(user_content, k=k)
    history = [
        {"role": m.role, "content": m.content}
        for m in conversation.messages.exclude(role=Message.Role.SYSTEM).order_by("created_at")
    ]
    system_prompt = _build_system_prompt(hits)

    result = complete(messages=history, system=system_prompt)

    sources = [
        {
            "chunk_id": hit.chunk.id,
            "source_path": hit.chunk.source_path,
            "heading_path": hit.chunk.heading_path,
            "score": round(float(hit.score), 4),
        }
        for hit in hits
    ]
    assistant_msg = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=result.content,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        model=result.model,
        retrieval_sources=sources,
    )
    emit_audit(
        action="chatbot.message.reply",
        entity_type="message",
        entity_id=assistant_msg.id,
        actor=result.model,
        actor_kind="model",
    )

    # Auto-title from the first user prompt — keeps the conversation
    # list readable without forcing the UI to ask for a title up front.
    if not conversation.title:
        conversation.title = user_content[:200]
        conversation.save(update_fields=["title", "updated_at"])
    else:
        conversation.save(update_fields=["updated_at"])

    return user_msg, assistant_msg
