"""URL conf for /api/v1/admin/* endpoints — mounted by nsr_mis/urls.py."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.admin_console.api import (
    PMTModelVersionAdminViewSet,
    pmt_dashboard,
    pmt_events,
    pmt_recompute_run_now,
    pmt_transforms,
)

router = DefaultRouter()
router.register(
    r"pmt/versions",
    PMTModelVersionAdminViewSet,
    basename="admin-pmt-version",
)

urlpatterns = [
    path("pmt/dashboard/",            pmt_dashboard,        name="admin-pmt-dashboard"),
    path("pmt/recompute/run-now/",    pmt_recompute_run_now, name="admin-pmt-recompute-run-now"),
    path("pmt/events/",               pmt_events,           name="admin-pmt-events"),
    path("pmt/transforms/",           pmt_transforms,       name="admin-pmt-transforms"),
    *router.urls,
]
