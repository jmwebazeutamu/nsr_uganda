"""CHB-003 — HashEmbedder properties + factory selection."""

from __future__ import annotations

import math

from django.test import override_settings

from apps.chatbot.embeddings import (
    EMBEDDING_DIM,
    HashEmbedder,
    SentenceTransformerEmbedder,
    get_embedder,
    reset_embedder_cache,
)
from apps.chatbot.retrieval import _cosine


def test_hash_embedder_returns_384_dim():
    vec = HashEmbedder().embed("walk-in submission")
    assert len(vec) == EMBEDDING_DIM


def test_hash_embedder_is_l2_normalised():
    vec = HashEmbedder().embed("walk-in submission")
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-9


def test_hash_embedder_identical_text_cosine_is_one():
    e = HashEmbedder()
    a = e.embed("walk-in submission")
    b = e.embed("walk-in submission")
    assert abs(_cosine(a, b) - 1.0) < 1e-9


def test_hash_embedder_disjoint_texts_cosine_near_zero():
    e = HashEmbedder()
    a = e.embed("walk-in submission fast track")
    b = e.embed("grievance routing officer")
    # Disjoint token sets hash to different slots — cosine should
    # be effectively zero (allowing for accidental hash collisions).
    assert _cosine(a, b) < 0.1


def test_hash_embedder_empty_text_returns_zero_vector():
    vec = HashEmbedder().embed("")
    assert vec == [0.0] * EMBEDDING_DIM


def test_factory_returns_hash_when_settings_says_hash():
    reset_embedder_cache()
    with override_settings(CHATBOT_EMBEDDER="hash"):
        assert isinstance(get_embedder(), HashEmbedder)
    reset_embedder_cache()


def test_factory_returns_sentence_when_settings_says_sentence():
    # We do NOT instantiate it (would download the model); the
    # factory builds a SentenceTransformerEmbedder whose model is
    # lazy-loaded only when embed() is first called.
    reset_embedder_cache()
    with override_settings(CHATBOT_EMBEDDER="sentence"):
        assert isinstance(get_embedder(), SentenceTransformerEmbedder)
    reset_embedder_cache()
