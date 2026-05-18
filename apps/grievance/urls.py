from rest_framework.routers import DefaultRouter

from .api import GrievanceTaskViewSet, GrievanceViewSet

router = DefaultRouter()
router.register(r"grievances", GrievanceViewSet, basename="grievance")
router.register(r"tasks", GrievanceTaskViewSet, basename="grievance-task")

urlpatterns = router.urls
