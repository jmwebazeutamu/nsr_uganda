"""DRF permissions for the DIH module.

US-S11-021: the "Run connector" button on the System Admin > Connector
runs tab lets two role families trigger a Kobo pull:
- System Admin (Django group `nsr_admin`, seeded by
  apps.admin_console.migrations.0001_seed_admin_groups)
- NSR Unit Coordinator (Django group `nsr_unit_coordinator`, seeded by
  apps.ingestion_hub.migrations.0006_seed_nsr_unit_coordinator_group)

Both groups exist on every DB. Superusers always pass — they're the
incident-response escape hatch.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

DIH_TRIGGER_GROUPS = ("nsr_admin", "nsr_unit_coordinator")


class IsDihTrigger(BasePermission):
    """Gate the trigger-run endpoint.

    403 (not 404) is intentional: an authenticated operator who is
    routed here from elsewhere in the console should see a loud
    failure so they know they don't belong on this action.
    """

    message = (
        "Triggering a DIH connector pull requires membership in one "
        f"of: {', '.join(DIH_TRIGGER_GROUPS)}."
    )

    def has_permission(self, request, view) -> bool:
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        return user.groups.filter(name__in=DIH_TRIGGER_GROUPS).exists()
