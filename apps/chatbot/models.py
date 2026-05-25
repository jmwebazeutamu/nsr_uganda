"""Chatbot Assistant models (ADR-0021).

- Conversation — one per chat thread, scoped to a user.
- Message — append-only turn within a Conversation.
- ManualChunk — chunked + embedded manual content for RAG retrieval.

The embedding is stored as a plain JSON list (384 floats from
sentence-transformers/all-MiniLM-L6-v2). v1 retrieval is Python-side
cosine; pgvector graduation path is documented in ADR-0021.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from nsr_mis.common.fields import ULIDField


class Conversation(models.Model):
    """One chat thread per user. Title is optional — left blank when the
    first user prompt is the implicit title."""

    id = ULIDField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chatbot_conversations",
    )
    title = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self) -> str:
        return self.title or f"Conversation {self.id}"


class Message(models.Model):
    """One turn — user prompt, assistant reply, or system instruction.

    `retrieval_sources` records which ManualChunks the assistant cited.
    Shape: ``[{"chunk_id": "...", "source_path": "...",
    "heading_path": "...", "score": 0.87}]``.
    """

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    id = ULIDField(primary_key=True)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    # Token + model metadata recorded for cost / debugging.
    # Nullable since user-role turns don't have them.
    tokens_in = models.IntegerField(null=True, blank=True)
    tokens_out = models.IntegerField(null=True, blank=True)
    model = models.CharField(max_length=64, blank=True)
    retrieval_sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:60]}"


class ManualChunk(models.Model):
    """Chunked + embedded manual content for RAG retrieval."""

    id = ULIDField(primary_key=True)
    # Path relative to docs/user-manual/docs/, e.g. "steward/walk-in.md".
    source_path = models.CharField(max_length=255, db_index=True)
    # "Field Steward Manual > Walk-in submission > Quality-Failed archive"
    heading_path = models.CharField(max_length=512, blank=True)
    content = models.TextField()
    # 384-d list of floats from all-MiniLM-L6-v2.
    embedding = models.JSONField()
    token_count = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["source_path"])]

    def __str__(self) -> str:
        return f"{self.source_path}#{self.heading_path}"
