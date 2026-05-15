from rest_framework.routers import DefaultRouter

from .api import ProgrammeEnrolmentViewSet, ProgrammeViewSet, ReferralViewSet

router = DefaultRouter()
router.register(r"programmes", ProgrammeViewSet, basename="programme")
router.register(r"referrals", ReferralViewSet, basename="referral")
router.register(r"enrolments", ProgrammeEnrolmentViewSet, basename="enrolment")

urlpatterns = router.urls
