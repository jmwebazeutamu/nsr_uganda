from rest_framework.routers import DefaultRouter

from .api import FormVersionViewSet, SubmissionViewSet

router = DefaultRouter()
router.register(r"form-versions", FormVersionViewSet, basename="form-version")
router.register(r"submissions", SubmissionViewSet, basename="submission")

urlpatterns = router.urls
