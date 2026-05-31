"""System checks for Consent Management.

Registered in apps.consent.apps.ConsentConfig.ready(). The DB-touching check
wraps ``list(qs)`` in try/except so it is a no-op before migrations run (the
lazy-queryset-in-checks trap: a bare ``qs.exists()`` would let an
OperationalError escape when `manage.py check` runs pre-migrate in CI).
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Warning as DjangoWarning
from django.core.checks import register

CONSENT_W001 = "consent.W001"

# The nine purpose codes the module expects once seeded (CONSENT-O-01:
# scope-doc list including ELIGIBILITY).
EXPECTED_PURPOSE_CODES = {
    "REGISTRATION", "ELIGIBILITY", "REFERRAL", "PAYMENTS",
    "COMMUNICATIONS_SMS", "COMMUNICATIONS_USSD", "RESEARCH",
    "STATISTICS", "GRIEVANCE_CONTACT",
}


@register()
def check_consent_catalogue_seeded(app_configs, **kwargs):
    """When the module flag is on, warn if the purpose catalogue is missing
    expected codes (e.g. migrations not applied, or a partial seed)."""
    if not getattr(settings, "CONSENT_MODULE_ENABLED", False):
        return []
    from .models import ConsentPurpose
    try:
        present = set(
            ConsentPurpose.objects.values_list("code", flat=True))
    except Exception:  # noqa: BLE001 — pre-migrate / no table yet
        return []
    missing = EXPECTED_PURPOSE_CODES - present
    if missing:
        return [DjangoWarning(
            "Consent module is enabled but the purpose catalogue is missing "
            f"expected codes: {sorted(missing)}.",
            hint="Run migrations; migration 0002 seeds the catalogue.",
            id=CONSENT_W001,
        )]
    return []
