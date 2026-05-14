from rest_framework.routers import DefaultRouter

from .api import HouseholdViewSet, MemberViewSet

router = DefaultRouter()
router.register(r"households", HouseholdViewSet, basename="household")
router.register(r"members", MemberViewSet, basename="member")

urlpatterns = router.urls
