from rest_framework.routers import DefaultRouter

from .api import DdupModelVersionViewSet, MatchPairViewSet, MergeDecisionViewSet


router = DefaultRouter()
router.register(r"model-versions", DdupModelVersionViewSet, basename="ddup-model-version")
router.register(r"match-pairs", MatchPairViewSet, basename="ddup-match-pair")
router.register(r"merge-decisions", MergeDecisionViewSet, basename="ddup-merge-decision")

urlpatterns = router.urls
