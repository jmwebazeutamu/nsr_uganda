"""IsExplorerRoleAndFlagEnabled — single permission class that gates
every DATA-EXP endpoint.

Per ADR-0023 D9:
- DATA_EXPLORER_ENABLED off → 503 from every endpoint.
- EXPLORER role missing → 403.

The EXPLORER role is a Keycloak realm role (OPEN-5 default). Until
the Keycloak adapter lands we accept either:
- a Django group named EXPLORER (operator console), OR
- the user's `is_superuser` flag (dev/test convenience).
"""

from __future__ import annotations

from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from .feature_flag import data_explorer_enabled


class FeatureFlagOff(APIException):
    status_code = 503
    default_detail = "data_explorer_disabled"
    default_code = "data_explorer_disabled"


class FlagEnabledPublic(BasePermission):
    """Flag gate WITHOUT a role requirement — for the public
    questionnaire-transparency catalogue (ADR-0023 public-discovery
    extension). Anyone may read the metadata-only data dictionary, but
    the DATA_EXPLORER_ENABLED kill-switch still applies (off → 503) so
    the surface can be pulled in an incident exactly like the gated
    endpoints. No record data or cell counts are served through it."""

    def has_permission(self, request, view) -> bool:
        if not data_explorer_enabled(request):
            raise FeatureFlagOff()
        return True


class IsExplorerRoleAndFlagEnabled(BasePermission):
    """Combined flag + role gate. Order matters — the flag check runs
    first so a flag-off response cannot be used to enumerate role
    membership."""

    message = "EXPLORER role required."

    def has_permission(self, request, view) -> bool:
        if not data_explorer_enabled(request):
            # Raise rather than return False so the response is 503,
            # not 403. Returning False would have DRF answer 403/401.
            raise FeatureFlagOff()
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        # Group-based fallback until Keycloak realm-role adapter lands.
        try:
            return user.groups.filter(name="EXPLORER").exists()
        except Exception:  # noqa: BLE001 — defensive in case of mocks
            return False
