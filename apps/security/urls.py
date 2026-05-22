from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import AuditEventViewSet, me

router = DefaultRouter()
router.register(r"audit-events", AuditEventViewSet, basename="audit-event")

urlpatterns = [
    *router.urls,
    # Identity endpoint — the React shell uses this to show the actual
    # authenticated user in the topbar (not the hardcoded persona).
    path("users/me/", me, name="users-me"),
]
