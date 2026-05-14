from rest_framework.routers import DefaultRouter

from .api import DqaResultViewSet, DqaRuleViewSet


router = DefaultRouter()
router.register(r"rules", DqaRuleViewSet, basename="dqa-rule")
router.register(r"results", DqaResultViewSet, basename="dqa-result")

urlpatterns = router.urls
