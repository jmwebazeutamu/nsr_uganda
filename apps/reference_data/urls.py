from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    ChoiceListBundleView,
    ChoiceListViewSet,
    GeographicUnitViewSet,
)

router = DefaultRouter()
router.register(r"geographic-units", GeographicUnitViewSet, basename="geographic-unit")
router.register(r"choice-lists", ChoiceListViewSet, basename="choice-list")

urlpatterns = [
    # ADR-0010 §6 — single round-trip bundle for questionnaire runtimes.
    # Mounted at /api/v1/reference-data/choice-list-bundle/ via nsr_mis/urls.py.
    path("choice-list-bundle/", ChoiceListBundleView.as_view(), name="choice-list-bundle"),
    *router.urls,
]
