from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import FormVersionViewSet, SubmissionViewSet, cspro_diff

router = DefaultRouter()
router.register(r"form-versions", FormVersionViewSet, basename="form-version")
router.register(r"submissions", SubmissionViewSet, basename="submission")

urlpatterns = [
    # Wave review (ADR-0034). Not a viewset — there is no resource, only
    # a comparison between two documents the caller supplies.
    path("cspro/diff/", cspro_diff, name="cspro-diff"),
    *router.urls,
]
