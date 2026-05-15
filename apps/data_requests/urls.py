from rest_framework.routers import DefaultRouter

from .api import DataRequestViewSet, DsaViewSet, PartnerViewSet

router = DefaultRouter()
router.register(r"partners", PartnerViewSet, basename="partner")
router.register(r"agreements", DsaViewSet, basename="dsa")
router.register(r"requests", DataRequestViewSet, basename="data-request")

urlpatterns = router.urls
