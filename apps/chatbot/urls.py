from rest_framework.routers import DefaultRouter

from .api import ConversationViewSet

router = DefaultRouter()
router.register(r"conversations", ConversationViewSet, basename="chatbot-conversation")

urlpatterns = router.urls
