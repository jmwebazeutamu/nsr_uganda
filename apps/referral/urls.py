from rest_framework.routers import DefaultRouter

from .api import ProgrammeEnrolmentViewSet, ReferralViewSet

# US-S26-005 / ADR-0015: the legacy /api/v1/ref/programmes/ route is
# gone; programme reads go through the canonical /api/v1/programmes/
# on the partners app.
router = DefaultRouter()
router.register(r"referrals", ReferralViewSet, basename="referral")
router.register(r"enrolments", ProgrammeEnrolmentViewSet, basename="enrolment")

urlpatterns = router.urls
