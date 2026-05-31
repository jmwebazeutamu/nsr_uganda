"""Django system checks that fail-closed against dev-default secrets.

Registered in apps/security/apps.py. Run on every `manage.py check`,
which CI executes before tests and which is the gate every deploy
pipeline relies on.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, register

# These constants are intentionally the dev-default values. The check below
# refuses to boot when production env matches them — they are markers, not
# credentials. # nosec B105 silences bandit's hardcoded-password warning.
DEV_PEPPER = "dev-only-nin-pepper-replace-before-deploy"  # nosec B105
DEV_DATA_KEY = "6kZf3vUYNDxBcLg3Vh-uYqOjQp4mEX0sIqAJ8u3OZk0="  # nosec B105
DEV_SECRET_KEY_PREFIX = "dev-only-"  # nosec B105


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


@register()
def check_postgres_required_outside_dev(app_configs, **kwargs):
    """Outside DEBUG the database must be PostgreSQL — the audit-chain
    integrity trigger (security/0002_auditevent_chain_trigger.py) is
    Postgres-only and silently no-ops on every other vendor, which
    would render the SAD §8.4 hash-chain guarantee meaningless."""
    if settings.DEBUG:
        return []
    # Validate only the DEFAULT database — that is where the audit-chain trigger
    # lives. The `analytics_replica` alias is an intentional no-op that points at
    # SQLite in dev/CI (DATABASE_URL_ANALYTICS unset) and only resolves to a real
    # Postgres read-replica in staging/prod; including it here would fail CI's
    # Postgres job purely because the replica defaults to SQLite.
    default_engine = (
        settings.DATABASES.get("default", {}).get("ENGINE", "").split(".")[-1]
    )
    if default_engine and default_engine not in ("postgresql", "postgis"):
        return [Error(
            f"non-Postgres default DATABASE ENGINE '{default_engine}' is forbidden "
            f"when DEBUG=False — the audit-chain trigger requires PostgreSQL.",
            id="security.E004",
        )]
    return []
