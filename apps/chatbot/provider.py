"""Anthropic Claude Messages client wrapper.

Tests monkeypatch `complete` directly — the real Anthropic SDK is
imported lazily inside the function body so test environments without
the package installed still load the module.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class CompletionResult:
    content: str
    tokens_in: int
    tokens_out: int
    model: str


def complete(
    messages: list[dict],
    system: str = "",
    model: str | None = None,
    max_tokens: int = 1024,
) -> CompletionResult:
    """Call the Anthropic Messages API. `messages` follows Anthropic's
    {role, content} shape and must NOT contain a system role —
    system goes through the `system` kwarg."""
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured — set it in .env "
            "before enabling the chatbot."
        )
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model or settings.CHATBOT_MODEL,
        max_tokens=max_tokens,
        system=system or None,
        messages=messages,
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return CompletionResult(
        content=text,
        tokens_in=resp.usage.input_tokens,
        tokens_out=resp.usage.output_tokens,
        model=resp.model,
    )
