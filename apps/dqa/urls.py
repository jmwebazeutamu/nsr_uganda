from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    DqaResultViewSet,
    DqaRuleViewSet,
    EvaluateHouseholdView,
    HouseholdEvaluationsView,
    SeverityVocabularyView,
)

router = DefaultRouter()
router.register(r"rules", DqaRuleViewSet, basename="dqa-rule")
router.register(r"results", DqaResultViewSet, basename="dqa-result")

# US-S11-044 intra-household surface. Kept outside the router because
# /evaluate/household isn't a CRUD-style resource and /evaluations/
# is keyed on household_id, not a DqaEvaluation primary key.
urlpatterns = router.urls + [
    path(
        "evaluate/household",
        EvaluateHouseholdView.as_view(),
        name="dqa-evaluate-household",
    ),
    path(
        "evaluations/<str:household_id>",
        HouseholdEvaluationsView.as_view(),
        name="dqa-household-evaluations",
    ),
    path(
        "severity-vocabulary",
        SeverityVocabularyView.as_view(),
        name="dqa-severity-vocabulary",
    ),
]
