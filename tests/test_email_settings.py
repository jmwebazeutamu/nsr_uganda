from __future__ import annotations

from nsr_mis.email_settings import default_email_backend, server_email_from_default


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
