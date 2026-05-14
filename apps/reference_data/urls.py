from rest_framework.routers import DefaultRouter

from .api import GeographicUnitViewSet

router = DefaultRouter()
router.register(r"geographic-units", GeographicUnitViewSet, basename="geographic-unit")

urlpatterns = router.urls
