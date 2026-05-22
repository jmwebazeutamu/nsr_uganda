"""Admin Console gating — the five admin groups + the DRF permission
class that mirrors the view-level UserPassesTestMixin gate."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

# The five groups defined in HANDOFF §2.1. Group names are seeded by
# the data migration `apps/admin_console/migrations/0001_seed_groups.py`
# so any deployment without a manual group setup still passes the
# acceptance gate.
ADMIN_CONSOLE_GROUPS = (
    "nsr_admin",
    "mglsd_statistics",
    "dpo",
    "nsr_dba",
    "nsr_security",
)


def user_can_admin_console(user) -> bool:
    """Return True if `user` is allowed to load the Admin Console.

    Superusers always pass — they're an escape hatch for setup +
    incident response. Otherwise the user must be in at least one
    of the five admin groups.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=ADMIN_CONSOLE_GROUPS).exists()


class IsAdminConsoleUser(BasePermission):
    """DRF permission gating /api/v1/admin/* endpoints.

    The view-level UserPassesTestMixin gates the HTML shell at
    /admin-console/; this permission gates the API endpoints the
    shell calls. Both must agree or you'd ship a console that loads
    but produces 403s on every fetch.

    403 is intentional (not 404) — per HANDOFF §2.1 the spec
    insists on a *loud* failure: a misrouted operator should
    notice they don't belong here.
    """

    message = (
        "Admin Console access requires membership in one of: "
        + ", ".join(ADMIN_CONSOLE_GROUPS) + "."
    )

    def has_permission(self, request, view) -> bool:
        return user_can_admin_console(request.user)
