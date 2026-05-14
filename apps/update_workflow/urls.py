from rest_framework.routers import DefaultRouter

from .api import ChangeRequestViewSet

router = DefaultRouter()
router.register(r"change-requests", ChangeRequestViewSet, basename="change-request")

urlpatterns = router.urls
