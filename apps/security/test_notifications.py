"""Tests for apps.security.notifications.send_notification."""

from __future__ import annotations

import pytest
from django.core import mail
from django.test import override_settings

from apps.security.models import AuditEvent
from apps.security.notifications import send_notification


@pytest.mark.django_db
class TestSendNotification:
    """Single entry-point for transactional workflow emails. Wraps
    send_mail with audit emission + fail-silently semantics."""

    def test_happy_path_sends_and_audits(self):
        result = send_notification(
            to="signer@example.com",
            subject="[NSR MIS] Awaiting your signature",
            body="Hello",
            entity_type="pmt_model_version",
            entity_id="01PMT",
            audit_actor="workflow",
            audit_action="pmt.signoff.notified",
            audit_reason="step 2 awaiting steward",
        )
        assert result["sent"] is True
        assert result["recipients"] == ["signer@example.com"]
        assert result["error"] == ""

        # One mail in the outbox with the right shape.
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.subject == "[NSR MIS] Awaiting your signature"
        assert msg.to == ["signer@example.com"]
        assert msg.body == "Hello"

        # AuditEvent emitted with the per-workflow action code.
        events = AuditEvent.objects.filter(
            action="pmt.signoff.notified",
            entity_type="pmt_model_version",
            entity_id="01PMT",
        )
        assert events.count() == 1
        assert events.first().actor_id == "workflow"

    def test_list_of_recipients_deduped_and_stripped(self):
        send_notification(
            to=[" a@x ", "b@x", "a@x", "", None],
            subject="s", body="b",
            entity_type="dsa", entity_id="01DSA",
            audit_actor="workflow",
        )
        assert mail.outbox[-1].to == ["a@x", "b@x"]

    def test_empty_recipient_audits_skip_does_not_send(self):
        result = send_notification(
            to=None,
            subject="s", body="b",
            entity_type="dsa", entity_id="01DSA",
            audit_actor="workflow",
            audit_reason="partner has no primary_email",
        )
        assert result == {"sent": False, "recipients": [], "error": "no recipients"}
        assert mail.outbox == []
        # Skip is itself audited — gaps in recipient data should be
        # findable later via the audit chain.
        skipped = AuditEvent.objects.filter(
            action="notification.skipped",
            entity_type="dsa", entity_id="01DSA",
        )
        assert skipped.count() == 1
        assert "partner has no primary_email" in skipped.first().reason

    @override_settings(EMAIL_BACKEND="apps.security.test_notifications.FailingBackend")
    def test_smtp_failure_audits_and_does_not_raise(self):
        # The custom backend below raises on every send. The helper
        # must catch it, audit "notification.failed", and return
        # sent=False — calling workflows must never inherit the
        # exception.
        result = send_notification(
            to="signer@example.com",
            subject="s", body="b",
            entity_type="pmt_model_version",
            entity_id="01PMT",
            audit_actor="workflow",
        )
        assert result["sent"] is False
        assert "boom" in result["error"]
        failed = AuditEvent.objects.filter(
            action="notification.failed",
            entity_type="pmt_model_version",
            entity_id="01PMT",
        )
        assert failed.count() == 1


# Helper backend for the SMTP-failure test.
from django.core.mail.backends.base import BaseEmailBackend  # noqa: E402


class FailingBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise RuntimeError("boom")
