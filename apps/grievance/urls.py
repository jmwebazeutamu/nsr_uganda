from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import GrievanceTaskViewSet, GrievanceViewSet
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
    *router.urls,
]
