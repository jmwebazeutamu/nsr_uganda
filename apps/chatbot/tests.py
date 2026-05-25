from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from .models import Conversation, ManualChunk, Message


class ChatbotAppLoadingTests(TestCase):
    """Smoke tests for the CHB-001 scaffold."""

    def test_app_is_installed(self):
        self.assertIn("apps.chatbot", {a.name for a in apps.get_app_configs()})

    def test_app_label(self):
        self.assertEqual(apps.get_app_config("chatbot").verbose_name, "Chatbot Assistant (CHB)")


class ConversationModelTests(TestCase):
    """CHB-002 — Conversation persistence + ULID PKs."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="parish_chief_01")

    def test_ulid_pk_is_26_chars(self):
        c = Conversation.objects.create(user=self.user, title="How do I correct an NIN?")
        self.assertEqual(len(c.id), 26)
        # Crockford base32 — uppercase, no I/L/O/U
        self.assertEqual(c.id, c.id.upper())

    def test_user_cascade_deletes_conversations(self):
        Conversation.objects.create(user=self.user)
        Conversation.objects.create(user=self.user)
        self.user.delete()
        self.assertEqual(Conversation.objects.count(), 0)

    def test_updated_at_advances_on_save(self):
        c = Conversation.objects.create(user=self.user, title="t1")
        first = c.updated_at
        c.title = "t2"
        c.save()
        c.refresh_from_db()
        self.assertGreater(c.updated_at, first)


class MessageModelTests(TestCase):
    """CHB-002 — Message append-only ordering + retrieval_sources shape."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="steward_01")
        cls.conv = Conversation.objects.create(user=cls.user)

    def test_messages_order_by_created_at(self):
        m1 = Message.objects.create(conversation=self.conv, role=Message.Role.USER, content="q1")
        m2 = Message.objects.create(
            conversation=self.conv, role=Message.Role.ASSISTANT, content="a1"
        )
        ordered = list(self.conv.messages.all())
        self.assertEqual(ordered, [m1, m2])

    def test_retrieval_sources_defaults_to_empty_list(self):
        m = Message.objects.create(
            conversation=self.conv, role=Message.Role.USER, content="hi"
        )
        self.assertEqual(m.retrieval_sources, [])

    def test_retrieval_sources_round_trips_citations(self):
        citations = [
            {"chunk_id": "01H...", "source_path": "steward/walk-in.md", "score": 0.87},
            {"chunk_id": "01H...", "source_path": "admin/refdata.md", "score": 0.71},
        ]
        m = Message.objects.create(
            conversation=self.conv,
            role=Message.Role.ASSISTANT,
            content="See the steward manual...",
            retrieval_sources=citations,
            model="claude-sonnet-4-6",
            tokens_in=120,
            tokens_out=45,
        )
        m.refresh_from_db()
        self.assertEqual(m.retrieval_sources, citations)
        self.assertEqual(m.tokens_in, 120)


class ManualChunkModelTests(TestCase):
    """CHB-002 — Embedding column round-trips a 384-d float list."""

    def test_embedding_round_trips_as_list(self):
        embedding = [0.1] * 384
        chunk = ManualChunk.objects.create(
            source_path="steward/walk-in.md",
            heading_path="Walk-in submission > Fast-track",
            content="Parish Chiefs may submit walk-in households via the DIH fast-track lane.",
            embedding=embedding,
            token_count=18,
        )
        chunk.refresh_from_db()
        self.assertEqual(len(chunk.embedding), 384)
        self.assertEqual(chunk.embedding[0], 0.1)

    def test_embedding_is_required(self):
        with self.assertRaises(IntegrityError):
            ManualChunk.objects.create(
                source_path="x.md",
                content="x",
                token_count=1,
                # no embedding — JSONField with no default + no null=True
            )
