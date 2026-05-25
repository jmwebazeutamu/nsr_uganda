"""Pin CHATBOT_EMBEDDER=hash for all chatbot tests.

The sentence-transformers backend would download ~80 MB of model
weights on first use and pull ~1 GB of torch transitive imports.
Tests use the deterministic HashEmbedder so retrieval assertions
stay stable and no network access is needed.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from apps.chatbot.embeddings import reset_embedder_cache


@pytest.fixture(autouse=True)
def _force_hash_embedder():
    prev = getattr(settings, "CHATBOT_EMBEDDER", None)
    settings.CHATBOT_EMBEDDER = "hash"
    reset_embedder_cache()
    yield
    reset_embedder_cache()
    if prev is None:
        if hasattr(settings, "CHATBOT_EMBEDDER"):
            del settings.CHATBOT_EMBEDDER
    else:
        settings.CHATBOT_EMBEDDER = prev
