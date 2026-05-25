"""Embedder protocol + two implementations.

`SentenceTransformerEmbedder` is the production path — loads
`all-MiniLM-L6-v2` (384-d) lazily so the import doesn't pay the
sentence-transformers cost unless an embedder is actually used.

`HashEmbedder` is a deterministic, dependency-free fallback used by
tests + dev when the model weights aren't available. Cosine
similarity between identical texts is 1.0; between disjoint texts is
close to 0 — good enough for retrieval unit tests.

`get_embedder()` honours `settings.CHATBOT_EMBEDDER` ("sentence" or
"hash"). Tests override via `override_settings(CHATBOT_EMBEDDER="hash")`.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

from django.conf import settings

EMBEDDING_DIM = 384


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic bag-of-tokens hash embedder.

    Each whitespace-separated token is hashed into one of EMBEDDING_DIM
    slots (SHA-256 mod EMBEDDING_DIM) and the vector is L2-normalised.
    Identical inputs produce identical vectors; cosine over shared
    tokens correlates monotonically with token overlap.
    """

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        tokens = text.lower().split()
        if not tokens:
            return vec
        for token in tokens:
            h = hashlib.sha256(token.encode()).digest()
            idx = int.from_bytes(h[:4], "big") % EMBEDDING_DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class SentenceTransformerEmbedder:
    """all-MiniLM-L6-v2 wrapper. Model is loaded once on first embed()."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            # Lazy — keeps the ~1 GB torch transitive out of import-time.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)

    def embed(self, text: str) -> list[float]:
        self._ensure_model()
        return self._model.encode(text, normalize_embeddings=True).tolist()


_DEFAULT: Embedder | None = None


def get_embedder() -> Embedder:
    """Cached singleton — settings.CHATBOT_EMBEDDER picks the impl."""
    global _DEFAULT
    if _DEFAULT is not None:
        return _DEFAULT
    name = getattr(settings, "CHATBOT_EMBEDDER", "sentence")
    if name == "hash":
        _DEFAULT = HashEmbedder()
    else:
        _DEFAULT = SentenceTransformerEmbedder()
    return _DEFAULT


def reset_embedder_cache() -> None:
    """Test hook — clear the cached embedder so override_settings sticks."""
    global _DEFAULT
    _DEFAULT = None
