"""Django system checks that fail-closed against dev-default secrets.

Registered in apps/security/apps.py. Run on every `manage.py check`,
which CI executes before tests and which is the gate every deploy
pipeline relies on.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register

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


# --- role catalogue (US-063 / ADR-0006 / ADR-0028) --------------------------
#
# The Keycloak realm export and apps.security.roles must agree: Phase 1 maps a
# `realm_access.roles` entry straight onto a Django Group of the same name, so
# a role in one and not the other either grants nothing or silently fails to
# grant something an operator was told they hold. Hand-maintained parallel
# lists are what left Epic 17 five stories out of date; this makes the same
# drift a failing build.

#: Service-account roles have no human counterpart and so no Django Group.
REALM_ONLY_ROLES = frozenset({"connector:write"})

#: Keycloak adds these to every realm.
KEYCLOAK_BUILTIN_PREFIXES = ("default-roles-", "offline_access", "uma_authorization")


@register("security")
def check_role_catalogue_matches_realm(app_configs, **kwargs):
    import json
    from pathlib import Path

    from apps.security.roles import ROLE_CODES

    path = Path(settings.BASE_DIR) / "infrastructure" / "keycloak" / "realm-nsr-mis.json"
    if not path.exists():
        # A deployment consuming an externally-provisioned realm (NITA-U) will
        # not ship the export. Not an error.
        return []

    try:
        realm = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [Error(
            f"could not read the Keycloak realm export at {path}: {exc}",
            hint="Fix the JSON, or remove it if this deployment uses an "
                 "externally-provisioned realm.",
            id="security.E005",
        )]

    declared = {
        r.get("name", "")
        for r in realm.get("roles", {}).get("realm", [])
        if r.get("name")
        and r["name"] not in REALM_ONLY_ROLES
        and not r["name"].startswith(KEYCLOAK_BUILTIN_PREFIXES)
    }

    missing_in_realm = sorted(ROLE_CODES - declared)
    missing_in_catalogue = sorted(declared - ROLE_CODES)
    if not missing_in_realm and not missing_in_catalogue:
        return []

    parts = []
    if missing_in_realm:
        parts.append(f"in the catalogue but not the realm: {missing_in_realm}")
    if missing_in_catalogue:
        parts.append(f"in the realm but not the catalogue: {missing_in_catalogue}")

    return [Error(
        "The Keycloak realm export and apps.security.roles disagree — "
        + "; ".join(parts) + ".",
        hint="Both are version-controlled. Update apps/security/roles.py and "
             "regenerate the realm role list from it.",
        id="security.E005",
    )]


@register("security")
def check_every_role_has_a_group(app_configs, **kwargs):
    """Warn when a catalogue role has no Django Group yet.

    A Warning, not an Error: on a fresh database `manage.py check` runs before
    the migration that creates them.
    """
    from django.contrib.auth.models import Group

    from apps.security.roles import ROLE_CODES

    try:
        existing = set(Group.objects.values_list("name", flat=True))
    except Exception:
        # Table not there yet (pre-migrate). Fail open.
        return []

    missing = sorted(ROLE_CODES - existing)
    if not missing:
        return []
    return [Warning(
        f"{len(missing)} role(s) in the catalogue have no Django Group: {missing}.",
        hint="Run `manage.py migrate security` (or `manage.py sync_roles`).",
        id="security.W001",
    )]


@register("security")
def check_access_purposes_are_known(app_configs, **kwargs):
    """A viewset's `access_purpose` must be a real, ACTIVE ConsentPurpose.

    Purpose limitation is only meaningful if the vocabulary is the agreed one.
    A typo would write an audit trail attributing access to a purpose nobody
    approved — which reads as evidence and is not.
    """
    from apps.security.purpose import known_purpose_codes

    known = known_purpose_codes()
    if not known:
        # Pre-migrate, or the consent catalogue is not seeded. Fail open.
        return []

    declared: dict[str, set[str]] = {}
    try:
        from django.apps import apps as django_apps
        for cfg in django_apps.get_app_configs():
            if not cfg.name.startswith("apps."):
                continue
            try:
                module = __import__(f"{cfg.name}.api", fromlist=["api"])
            except ModuleNotFoundError:
                # Not every app exposes an api module. Narrow on purpose: a
                # broken api module should surface here, not be swallowed.
                continue
            for attr in dir(module):
                obj = getattr(module, attr, None)
                if not isinstance(obj, type):
                    continue
                codes = set()
                one = getattr(obj, "access_purpose", None)
                if isinstance(one, str) and one:
                    codes.add(one)
                many = getattr(obj, "access_purpose_map", None)
                if isinstance(many, dict):
                    codes |= {v for v in many.values() if v}
                for c in codes:
                    declared.setdefault(c, set()).add(f"{cfg.label}.{attr}")
    except Exception:
        return []

    unknown = {c: v for c, v in declared.items() if c not in known}
    if not unknown:
        return []
    return [Error(
        "access_purpose values that are not ACTIVE ConsentPurpose codes: "
        + "; ".join(f"{c} ({', '.join(sorted(v))})" for c, v in sorted(unknown.items()))
        + ".",
        hint="Purposes come from the ConsentPurpose catalogue (DEP-22). Add the "
             "purpose there, or correct the declaration — do not start a second "
             "vocabulary beside the consent one.",
        id="security.E006",
    )]
