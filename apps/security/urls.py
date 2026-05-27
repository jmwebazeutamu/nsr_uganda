from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    AuditEventViewSet,
    OperatorScopeViewSet,
    impersonate_start,
    impersonate_stop,
    me,
    user_search,
)

router = DefaultRouter()
router.register(r"audit-events", AuditEventViewSet, basename="audit-event")
# US-S11-028 — OperatorScope management surface for the System Admin
# > Operator scopes console tab. The bulk-grant @action is mounted
# at /operator-scopes/bulk-grant/ by the router.
router.register(r"operator-scopes", OperatorScopeViewSet, basename="operator-scope")

urlpatterns = [
    *router.urls,
    # Identity endpoint — the React shell uses this to show the actual
    # authenticated user in the topbar (not the hardcoded persona).
    path("users/me/", me, name="users-me"),
    # US-S11-028 — user search for the Grant Scope modal's user picker.
    path("users/", user_search, name="users-search"),
    # US-S11-042 — impersonation. The stop endpoint URL must match
    # ImpersonationGuardMiddleware.GUARD_EXEMPT_PATHS so a writes-
    # disabled session can still revert itself.
    path("impersonate/", impersonate_start, name="impersonate-start"),
    path("impersonate/stop/", impersonate_stop, name="impersonate-stop"),
]
