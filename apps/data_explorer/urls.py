"""DATA-EXP URL routing — mounted at /api/v1/data-explorer/.

ADR-0023 API surface:
  GET  /datasets                       → DatasetViewSet.list
  GET  /datasets/{id}                  → DatasetViewSet.retrieve
  GET  /datasets/{id}/variables        → DatasetViewSet.variables
  GET  /variables                      → VariableViewSet.list
  GET  /variables/{id}                 → VariableViewSet.retrieve
  GET  /privacy-classes                → PrivacyClassListView
  POST /aggregate                      → AggregateView
  GET  /coverage/{dataset_id}          → CoverageView
  GET  /synthetic-sample/{dataset_id}  → SyntheticSampleView
  POST /handoff                        → HandoffView
"""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    AggregateView,
    CoverageView,
    DatasetViewSet,
    HandoffView,
    PrivacyClassListView,
    SuppressionVocabularyView,
    SyntheticSampleView,
    VariableViewSet,
)

router = DefaultRouter()
router.register(r"datasets", DatasetViewSet, basename="data-explorer-dataset")
router.register(r"variables", VariableViewSet, basename="data-explorer-variable")


urlpatterns = [
    path("privacy-classes/", PrivacyClassListView.as_view(),
         name="data-explorer-privacy-classes"),
    path("suppression-vocabulary/", SuppressionVocabularyView.as_view(),
         name="data-explorer-suppression-vocab"),
    path("aggregate/", AggregateView.as_view(),
         name="data-explorer-aggregate"),
    path("coverage/<str:dataset_id>/", CoverageView.as_view(),
         name="data-explorer-coverage"),
    path("synthetic-sample/<str:dataset_id>/", SyntheticSampleView.as_view(),
         name="data-explorer-synthetic-sample"),
    path("handoff/", HandoffView.as_view(),
         name="data-explorer-handoff"),
] + router.urls
