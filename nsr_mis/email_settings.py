"""Helpers for resolving Django email settings.

Kept separate from `settings.py` so the resolution logic is testable
without reloading the settings module.
"""

from __future__ import annotations

from email.utils import parseaddr


def default_email_backend(*, host_user: str = "", host_password: str = "") -> str:
    """Return the backend Django should use when EMAIL_BACKEND is not
    explicitly set.

    If SMTP credentials are present, prefer the SMTP backend. Otherwise
    fall back to the console backend so dev/CI stays side-effect free.
    """
    if host_user or host_password:
        return "django.core.mail.backends.smtp.EmailBackend"
    return "django.core.mail.backends.console.EmailBackend"


def server_email_from_default(default_from_email: str) -> str:
    """Derive a plain envelope address from DEFAULT_FROM_EMAIL.

    Django's `SERVER_EMAIL` is used for system/admin mail. A formatted
    display-name header (e.g. `NSR MIS <admin@quasar.ug>`) is accepted
    by some mail servers but the envelope should be the bare address.
    """
    _name, addr = parseaddr(default_from_email or "")
    return addr or default_from_email
