from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import GrievanceTaskViewSet, GrievanceViewSet
from .external.api import (
    PartnerApiConfigView,
    PartnerApiDryRunView,
    PartnerApiRunView,
    PartnerApiTestView,
)
from .external.receiver import StaacPushReceiver

router = DefaultRouter()
router.register(r"grievances", GrievanceViewSet, basename="grievance")
router.register(r"tasks", GrievanceTaskViewSet, basename="grievance-task")

urlpatterns = [
    # Machine-to-machine, outside the router: STAAC is not a console
    # user and this is not a console resource. Spec §6; the receiver
    # refuses everything until its authentication profile is agreed
    # and GRM_STAAC_PUSH_SECRET is set.
    path("partners/staac/handovers/", StaacPushReceiver.as_view(),
         name="staac-push-receiver"),
    # The configuration surface. Reading it needs a session; changing
    # it, or calling the partner, needs an administrator.
    path("partner-api/staac/", PartnerApiConfigView.as_view(),
         name="staac-partner-config"),
    path("partner-api/staac/test-connection/", PartnerApiTestView.as_view(),
         name="staac-partner-test"),
    path("partner-api/staac/dry-run/", PartnerApiDryRunView.as_view(),
         name="staac-partner-dry-run"),
    path("partner-api/staac/run/", PartnerApiRunView.as_view(),
         name="staac-partner-run"),
    *router.urls,
]
