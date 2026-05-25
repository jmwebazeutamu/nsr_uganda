"""CHB-004 — DRF API tests for chatbot conversations + messages."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.chatbot.embeddings import HashEmbedder
from apps.chatbot.models import Conversation, ManualChunk
from apps.chatbot.provider import CompletionResult


def _fake_completion() -> CompletionResult:
    return CompletionResult(
        content="See the steward manual on walk-in submissions.",
        tokens_in=80,
        tokens_out=30,
        model="claude-sonnet-4-6",
    )


@override_settings(CHATBOT_ENABLED=True)
class ConversationViewSetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user(username="alice", password="x")
        cls.bob = get_user_model().objects.create_user(username="bob", password="x")
        e = HashEmbedder()
        ManualChunk.objects.create(
            source_path="steward/walk-in.md",
            heading_path="Walk-in submissions > Fast-track",
            content="Parish Chiefs auto-promote walk-in households via the DIH fast-track lane.",
            embedding=e.embed(
                "Parish Chiefs auto-promote walk-in households via the DIH fast-track lane."
            ),
            token_count=15,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.alice)

    def test_anonymous_request_is_unauthorised(self):
        self.client.force_authenticate(user=None)
        r = self.client.get("/api/v1/chatbot/conversations/")
        self.assertIn(r.status_code, (401, 403))

    def test_create_conversation_owned_by_caller(self):
        r = self.client.post("/api/v1/chatbot/conversations/", {"title": "Question"}, format="json")
        self.assertEqual(r.status_code, 201)
        conv = Conversation.objects.get(id=r.json()["id"])
        self.assertEqual(conv.user, self.alice)

    def test_list_only_shows_own_conversations(self):
        Conversation.objects.create(user=self.alice, title="alice-one")
        Conversation.objects.create(user=self.bob, title="bob-one")
        r = self.client.get("/api/v1/chatbot/conversations/")
        self.assertEqual(r.status_code, 200)
        titles = {c["title"] for c in r.json().get("results", r.json())}
        self.assertIn("alice-one", titles)
        self.assertNotIn("bob-one", titles)

    def test_cannot_retrieve_other_users_conversation(self):
        bob_conv = Conversation.objects.create(user=self.bob)
        r = self.client.get(f"/api/v1/chatbot/conversations/{bob_conv.id}/")
        self.assertEqual(r.status_code, 404)

    @patch("apps.chatbot.services.complete")
    def test_send_message_returns_user_and_assistant(self, mock_complete):
        mock_complete.return_value = _fake_completion()
        conv = Conversation.objects.create(user=self.alice)
        r = self.client.post(
            f"/api/v1/chatbot/conversations/{conv.id}/messages/",
            {"content": "how do walk-ins work"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["user_message"]["role"], "user")
        self.assertEqual(body["assistant_message"]["role"], "assistant")
        self.assertEqual(
            body["assistant_message"]["content"],
            "See the steward manual on walk-in submissions.",
        )

    @patch("apps.chatbot.services.complete")
    def test_send_message_rejects_empty_content(self, mock_complete):
        conv = Conversation.objects.create(user=self.alice)
        r = self.client.post(
            f"/api/v1/chatbot/conversations/{conv.id}/messages/",
            {"content": ""},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        mock_complete.assert_not_called()

    @patch("apps.chatbot.services.complete")
    def test_send_message_rejected_for_other_users_conversation(self, mock_complete):
        bob_conv = Conversation.objects.create(user=self.bob)
        r = self.client.post(
            f"/api/v1/chatbot/conversations/{bob_conv.id}/messages/",
            {"content": "hi"},
            format="json",
        )
        self.assertEqual(r.status_code, 404)
        mock_complete.assert_not_called()

    def test_get_messages_returns_history(self):
        conv = Conversation.objects.create(user=self.alice)
        from apps.chatbot.models import Message

        Message.objects.create(conversation=conv, role=Message.Role.USER, content="q")
        Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, content="a")
        r = self.client.get(f"/api/v1/chatbot/conversations/{conv.id}/messages/")
        self.assertEqual(r.status_code, 200)
        roles = [m["role"] for m in r.json()]
        self.assertEqual(roles, ["user", "assistant"])


class ChatbotFlagGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user(username="alice", password="x")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.alice)

    @override_settings(CHATBOT_ENABLED=False)
    def test_flag_off_returns_404(self):
        r = self.client.get("/api/v1/chatbot/conversations/")
        self.assertEqual(r.status_code, 404)
