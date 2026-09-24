"""Tests for apps.security.notifications.send_notification."""

from __future__ import annotations

from unittest import mock

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


# ---------------------------------------------------------------------------
# "sent" has to mean sent
# ---------------------------------------------------------------------------

class TestDeliveryIsDistinguishableFromDiscarding:
    """Production ran for months on the console backend. `send_mail`
    returns success for it, so eighteen notifications — DSA signing,
    password resets, a grievance assignment — were audited as sent while
    every one was written to stdout. Nothing failed, so nothing
    surfaced.
    """

    def test_a_discarding_backend_is_recorded_as_not_delivered(
        self, db, settings,
    ):
        from apps.security.models import AuditEvent
        from apps.security.notifications import send_notification

        settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

        result = send_notification(
            to="someone@example.test", subject="s", body="b",
            entity_type="test", entity_id="t1", audit_actor="ops",
        )

        assert result["sent"] is True          # the call succeeded…
        assert result["delivered"] is False    # …and nothing was sent
        event = AuditEvent.objects.filter(entity_id="t1").first()
        assert event.field_changes["delivered"] is False
        assert "console" in event.field_changes["backend"]

    def test_a_real_backend_is_recorded_as_delivered(self, db, settings):
        from apps.security.models import AuditEvent
        from apps.security.notifications import send_notification

        # locmem is what the test runner swaps in; name an SMTP backend
        # so the recorded fact is the one production would carry.
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

        with mock.patch("apps.security.notifications.send_mail") as sender:
            sender.return_value = 1
            result = send_notification(
                to="someone@example.test", subject="s", body="b",
                entity_type="test", entity_id="t2", audit_actor="ops",
            )

        assert result["delivered"] is True
        event = AuditEvent.objects.filter(entity_id="t2").first()
        assert event.field_changes["delivered"] is True

    def test_delivers_mail_knows_the_discarding_backends(self):
        from apps.security.notifications import (
            NON_DELIVERING_BACKENDS,
            delivers_mail,
        )

        for backend in NON_DELIVERING_BACKENDS:
            assert delivers_mail(backend) is False, backend
        assert delivers_mail("django.core.mail.backends.smtp.EmailBackend")


class TestTheCheckSaysSo:
    """A warning on every management command and in every deploy's
    output, so this cannot sit unnoticed for another four months."""

    def _run(self, settings):
        from apps.security.checks import (
            check_email_backend_delivers_in_production,
        )
        return check_email_backend_delivers_in_production(None)

    def test_warns_when_production_cannot_send(self, settings):
        settings.DEBUG = False
        settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

        messages = self._run(settings)

        assert [m.id for m in messages] == ["security.W007"]
        assert "will not be delivered" in messages[0].msg

    def test_silent_when_the_backend_delivers(self, settings):
        settings.DEBUG = False
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

        assert self._run(settings) == []

    def test_silent_in_debug(self, settings):
        settings.DEBUG = True
        settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

        assert self._run(settings) == []
