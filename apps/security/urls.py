from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    AuditEventViewSet,
    OperatorScopeViewSet,
    impersonate_start,
    impersonate_stop,
    me,
    role_catalogue,
    user_search,
)
from .user_api import UserAdminViewSet

router = DefaultRouter()
router.register(r"audit-events", AuditEventViewSet, basename="audit-event")
# US-S11-028 — OperatorScope management surface for the System Admin
# > Operator scopes console tab. The bulk-grant @action is mounted
# at /operator-scopes/bulk-grant/ by the router.
router.register(r"operator-scopes", OperatorScopeViewSet, basename="operator-scope")
# Account administration for the console's User management screen. Gated
# on nsr_admin alone, narrower than the admin console's own five-group
# gate — see user_api.IsUserAdmin.
#
# Mounted at user-accounts/, NOT users/. `users/` is already the scope
# picker's search endpoint (path("users/", user_search) below), with a
# different permission class and a different response shape. Registering
# a router on `users` shadows it — router urls come first — which would
# have left the Roles & scopes screen and the Grant Scope modal reading
# an endpoint that returns something else and refuses most of their
# callers.
router.register(r"user-accounts", UserAdminViewSet, basename="managed-user")

urlpatterns = [
    *router.urls,
    # Identity endpoint — the React shell uses this to show the actual
    # authenticated user in the topbar (not the hardcoded persona).
    path("users/me/", me, name="users-me"),
    # US-S11-028 — user search for the Grant Scope modal's user picker.
    path("users/", user_search, name="users-search"),
    # The role catalogue (ADR-0028), read-only. The Roles & scopes
    # screen renders this instead of its own nine invented roles.
    path("roles/", role_catalogue, name="role-catalogue"),
    # US-S11-042 — impersonation. The stop endpoint URL must match
    # ImpersonationGuardMiddleware.GUARD_EXEMPT_PATHS so a writes-
    # disabled session can still revert itself.
    path("impersonate/", impersonate_start, name="impersonate-start"),
    path("impersonate/stop/", impersonate_stop, name="impersonate-stop"),
]
