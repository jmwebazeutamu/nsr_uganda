"""Top-k cosine retrieval over ManualChunk.

v1 is Python-side — load all chunks, dot-product the query vector
against each, return the top k. The manuals corpus is hundreds of
chunks; loading them is cheap. Graduates to pgvector + ANN index
once the corpus grows (ADR-0021).
"""

from __future__ import annotations

from dataclasses import dataclass

from .embeddings import get_embedder
from .models import ManualChunk


@dataclass(frozen=True)
class RetrievalHit:
    chunk: ManualChunk
    score: float


def _cosine(a: list[float], b: list[float]) -> float:
    # Both embeddings are produced by L2-normalised embedders, so cosine
    # reduces to a dot product. Guarded for length mismatches anyway.
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def retrieve(query: str, k: int = 5) -> list[RetrievalHit]:
    """Return the top-k ManualChunks closest to `query` by cosine."""
    embedder = get_embedder()
    q_vec = embedder.embed(query)
    scored: list[RetrievalHit] = []
    for chunk in ManualChunk.objects.all():
        scored.append(RetrievalHit(chunk=chunk, score=_cosine(q_vec, chunk.embedding)))
    scored.sort(key=lambda h: -h.score)
    return scored[:k]
