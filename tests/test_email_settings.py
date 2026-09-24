from __future__ import annotations

from nsr_mis.email_settings import default_from_email, default_email_backend, server_email_from_default


def test_default_email_backend_prefers_smtp_when_credentials_exist():
    assert default_email_backend(host_user="admin@quasar.ug") == (
        "django.core.mail.backends.smtp.EmailBackend"
    )
    assert default_email_backend(host_password="secret") == (
        "django.core.mail.backends.smtp.EmailBackend"
    )


def test_default_email_backend_falls_back_to_console_without_credentials():
    assert default_email_backend() == "django.core.mail.backends.console.EmailBackend"


def test_server_email_uses_bare_address():
    assert server_email_from_default("NSR MIS <admin@quasar.ug>") == "admin@quasar.ug"
    assert server_email_from_default("admin@quasar.ug") == "admin@quasar.ug"


# ---------------------------------------------------------------------------
# The From address is the mailbox we authenticate as
# ---------------------------------------------------------------------------

def test_from_address_derives_from_the_authenticated_mailbox():
    """comms.quasar.ug enforces sender-login match, so a From the login
    does not own is refused at send time:

        553 5.7.1 <johnson@quasar.ug>: Sender address rejected:
        not owned by user

    Deriving the default removes the mismatch by construction — change
    the mailbox and the From follows it.
    """
    assert default_from_email("johnson@quasar.ug") == "NSR MIS <johnson@quasar.ug>"
    assert default_from_email("admin@quasar.ug") == "NSR MIS <admin@quasar.ug>"


def test_from_address_falls_back_when_no_mailbox_is_configured():
    """Nothing is being delivered in that state, so the value only has
    to be well-formed."""
    assert default_from_email("") == "NSR MIS <admin@quasar.ug>"
    assert server_email_from_default(default_from_email("")) == "admin@quasar.ug"


def test_the_derived_from_always_matches_the_mailbox():
    """The property that makes 553 impossible to configure by accident."""
    for mailbox in ("a@b.ug", "johnson@quasar.ug", "noreply@mglsd.go.ug"):
        assert server_email_from_default(default_from_email(mailbox)) == mailbox


class TestSenderMismatchCheck:

    def _run(self):
        from apps.security.checks import (
            check_from_address_matches_the_authenticated_mailbox as check,
        )
        return check(None)

    def test_warns_when_the_from_is_a_mailbox_we_cannot_send_as(self, settings):
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        settings.EMAIL_HOST_USER = "admin@quasar.ug"
        settings.DEFAULT_FROM_EMAIL = "NSR MIS <johnson@quasar.ug>"

        messages = self._run()

        assert [m.id for m in messages] == ["security.W008"]
        assert "not owned by user" in messages[0].hint

    def test_silent_when_they_match(self, settings):
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        settings.EMAIL_HOST_USER = "admin@quasar.ug"
        settings.DEFAULT_FROM_EMAIL = "NSR MIS <admin@quasar.ug>"

        assert self._run() == []

    def test_silent_when_no_mailbox_is_configured(self, settings):
        """Nothing is being delivered, so there is nothing to mismatch."""
        settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
        settings.EMAIL_HOST_USER = ""
        settings.DEFAULT_FROM_EMAIL = "NSR MIS <johnson@quasar.ug>"

        assert self._run() == []
