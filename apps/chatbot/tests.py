from django.apps import apps
from django.test import TestCase


class ChatbotAppLoadingTests(TestCase):
    """Smoke tests for the CHB-001 scaffold — no models or endpoints yet."""

    def test_app_is_installed(self):
        self.assertIn("apps.chatbot", {a.name for a in apps.get_app_configs()})

    def test_app_label(self):
        self.assertEqual(apps.get_app_config("chatbot").verbose_name, "Chatbot Assistant (CHB)")
