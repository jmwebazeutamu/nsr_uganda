"""CHB-004 — services.send_message orchestration + audit emission."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.chatbot.embeddings import HashEmbedder
from apps.chatbot.models import Conversation, ManualChunk, Message
from apps.chatbot.provider import CompletionResult
from apps.chatbot.services import send_message
from apps.security.models import AuditEvent


def _fake_completion(content: str = "Walk-in households go to the DIH fast-track lane.") -> CompletionResult:
    return CompletionResult(
        content=content,
        tokens_in=120,
        tokens_out=45,
        model="claude-sonnet-4-6",
    )


class SendMessageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="steward_01")
        cls.conv = Conversation.objects.create(user=cls.user)

        e = HashEmbedder()
        cls.chunk = ManualChunk.objects.create(
            source_path="steward/walk-in.md",
            heading_path="Walk-in submissions > Fast-track",
            content="Parish Chiefs auto-promote walk-in households via the DIH fast-track lane.",
            embedding=e.embed(
                "Parish Chiefs auto-promote walk-in households via the DIH fast-track lane."
            ),
            token_count=15,
        )

    @patch("apps.chatbot.services.complete")
    def test_persists_user_and_assistant_messages(self, mock_complete):
        mock_complete.return_value = _fake_completion()
        user_msg, assistant_msg = send_message(
            conversation=self.conv,
            user_content="How do walk-in submissions work?",
            actor_username="steward_01",
        )
        self.assertEqual(user_msg.role, Message.Role.USER)
        self.assertEqual(assistant_msg.role, Message.Role.ASSISTANT)
        self.assertEqual(assistant_msg.tokens_in, 120)
        self.assertEqual(assistant_msg.tokens_out, 45)
        self.assertEqual(assistant_msg.model, "claude-sonnet-4-6")
        self.assertEqual(self.conv.messages.count(), 2)

    @patch("apps.chatbot.services.complete")
    def test_assistant_message_carries_retrieval_sources(self, mock_complete):
        mock_complete.return_value = _fake_completion()
        _, assistant_msg = send_message(
            conversation=self.conv,
            user_content="walk-in households fast track",
            actor_username="steward_01",
        )
        self.assertGreater(len(assistant_msg.retrieval_sources), 0)
        top = assistant_msg.retrieval_sources[0]
        self.assertEqual(top["source_path"], "steward/walk-in.md")
        self.assertIn("score", top)
        self.assertIn("heading_path", top)

    @patch("apps.chatbot.services.complete")
    def test_emits_audit_on_send_and_reply(self, mock_complete):
        mock_complete.return_value = _fake_completion()
        send_message(
            conversation=self.conv,
            user_content="anything",
            actor_username="steward_01",
        )
        actions = list(
            AuditEvent.objects.filter(entity_type="message").values_list("action", flat=True)
        )
        self.assertIn("chatbot.message.send", actions)
        self.assertIn("chatbot.message.reply", actions)
        reply = AuditEvent.objects.get(action="chatbot.message.reply")
        self.assertEqual(reply.actor_kind, "model")
        self.assertEqual(reply.actor_id, "claude-sonnet-4-6")

    @patch("apps.chatbot.services.complete")
    def test_auto_titles_conversation_from_first_prompt(self, mock_complete):
        mock_complete.return_value = _fake_completion()
        self.assertEqual(self.conv.title, "")
        send_message(
            conversation=self.conv,
            user_content="How do walk-in submissions work in the DIH?",
            actor_username="steward_01",
        )
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.title, "How do walk-in submissions work in the DIH?")

    @patch("apps.chatbot.services.complete")
    def test_existing_title_is_preserved(self, mock_complete):
        mock_complete.return_value = _fake_completion()
        self.conv.title = "Existing"
        self.conv.save()
        send_message(
            conversation=self.conv,
            user_content="a new question",
            actor_username="steward_01",
        )
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.title, "Existing")

    @patch("apps.chatbot.services.complete")
    def test_provider_failure_leaves_user_message_persisted(self, mock_complete):
        mock_complete.side_effect = RuntimeError("API down")
        with self.assertRaises(RuntimeError):
            send_message(
                conversation=self.conv,
                user_content="anything",
                actor_username="steward_01",
            )
        # The user prompt survives so the user can retry without re-typing.
        self.assertEqual(self.conv.messages.count(), 1)
        self.assertEqual(self.conv.messages.first().role, Message.Role.USER)
