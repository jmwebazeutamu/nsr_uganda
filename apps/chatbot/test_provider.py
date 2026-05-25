"""CHB-004 — provider.complete sanity."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.chatbot.provider import complete


def test_complete_raises_without_api_key():
    with override_settings(ANTHROPIC_API_KEY=""):
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            complete(messages=[{"role": "user", "content": "hi"}])
