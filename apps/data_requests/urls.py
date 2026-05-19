from rest_framework.routers import DefaultRouter

from .api import DataRequestViewSet

router = DefaultRouter()
# Partner + DSA routes moved to apps/partners/urls.py per ADR-0013.
# Only data-request routes remain on /api/v1/drs/.
router.register(r"requests", DataRequestViewSet, basename="data-request")

urlpatterns = router.urls
