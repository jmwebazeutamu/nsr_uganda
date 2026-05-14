"""Django system checks that fail-closed against dev-default secrets.

Registered in apps/security/apps.py. Run on every `manage.py check`,
which CI executes before tests and which is the gate every deploy
pipeline relies on.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, register

DEV_PEPPER = "dev-only-nin-pepper-replace-before-deploy"
DEV_DATA_KEY = "6kZf3vUYNDxBcLg3Vh-uYqOjQp4mEX0sIqAJ8u3OZk0="
DEV_SECRET_KEY_PREFIX = "dev-only-"


@register()
def check_production_secrets(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    errors = []
    if str(settings.NSR_NIN_PEPPER) == DEV_PEPPER:
        errors.append(Error(
            "NSR_NIN_PEPPER is still the dev default — set the env var before booting.",
            id="security.E001",
        ))
    if str(settings.NSR_DATA_KEY) == DEV_DATA_KEY:
        errors.append(Error(
            "NSR_DATA_KEY is still the dev default — set the env var before booting.",
            id="security.E002",
        ))
    if str(settings.SECRET_KEY).startswith(DEV_SECRET_KEY_PREFIX):
        errors.append(Error(
            "DJANGO_SECRET_KEY is still the dev default — set the env var before booting.",
            id="security.E003",
        ))
    return errors
