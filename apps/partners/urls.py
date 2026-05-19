from rest_framework.routers import DefaultRouter

from .api import PartnerViewSet

router = DefaultRouter()
router.register(r"partners", PartnerViewSet, basename="partner")

urlpatterns = router.urls
