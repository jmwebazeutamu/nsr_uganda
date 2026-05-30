from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    ConsentPurposeViewSet,
    ConsentStatementVersionViewSet,
    MemberCaptureView,
    MemberConsentView,
    MemberWithdrawView,
    WithdrawalTicketViewSet,
)

router = DefaultRouter()
router.register(r"purposes", ConsentPurposeViewSet, basename="consent-purpose")
router.register(r"statements", ConsentStatementVersionViewSet, basename="consent-statement")
router.register(r"withdrawal-tickets", WithdrawalTicketViewSet, basename="consent-withdrawal-ticket")

# Member-keyed endpoints sit outside the router (keyed on member_id, not a
# ConsentRecord pk).
urlpatterns = router.urls + [
    path("members/<str:member_id>", MemberConsentView.as_view(),
         name="consent-member-matrix"),
    path("members/<str:member_id>/capture", MemberCaptureView.as_view(),
         name="consent-member-capture"),
    path("members/<str:member_id>/withdraw", MemberWithdrawView.as_view(),
         name="consent-member-withdraw"),
]
