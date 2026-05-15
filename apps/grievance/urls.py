from rest_framework.routers import DefaultRouter

from .api import GrievanceViewSet

router = DefaultRouter()
router.register(r"grievances", GrievanceViewSet, basename="grievance")

urlpatterns = router.urls
