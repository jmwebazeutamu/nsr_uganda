from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    ConnectorRunViewSet,
    ConnectorViewSet,
    SourceSystemViewSet,
    StageRecordViewSet,
    walk_in_submit,
)

router = DefaultRouter()
router.register(r"source-systems", SourceSystemViewSet, basename="source-system")
router.register(r"connectors", ConnectorViewSet, basename="connector")
router.register(r"connector-runs", ConnectorRunViewSet, basename="connector-run")
router.register(r"stage-records", StageRecordViewSet, basename="stage-record")

urlpatterns = [
    path("walk-in-submissions/", walk_in_submit, name="dih-walk-in-submit"),
    *router.urls,
]
