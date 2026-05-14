from rest_framework.routers import DefaultRouter

from .api import PMTModelVersionViewSet, PMTResultViewSet

router = DefaultRouter()
router.register(r"model-versions", PMTModelVersionViewSet, basename="pmt-model-version")
router.register(r"results", PMTResultViewSet, basename="pmt-result")

urlpatterns = router.urls
