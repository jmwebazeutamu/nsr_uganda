from rest_framework.routers import DefaultRouter

from .api import (
    ConnectorRunViewSet,
    ConnectorViewSet,
    SourceSystemViewSet,
    StageRecordViewSet,
)


router = DefaultRouter()
router.register(r"source-systems", SourceSystemViewSet, basename="source-system")
router.register(r"connectors", ConnectorViewSet, basename="connector")
router.register(r"connector-runs", ConnectorRunViewSet, basename="connector-run")
router.register(r"stage-records", StageRecordViewSet, basename="stage-record")

urlpatterns = router.urls
