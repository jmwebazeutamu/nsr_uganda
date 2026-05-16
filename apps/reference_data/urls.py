from rest_framework.routers import DefaultRouter

from .api import ChoiceListViewSet, GeographicUnitViewSet

router = DefaultRouter()
router.register(r"geographic-units", GeographicUnitViewSet, basename="geographic-unit")
router.register(r"choice-lists", ChoiceListViewSet, basename="choice-list")

urlpatterns = router.urls
