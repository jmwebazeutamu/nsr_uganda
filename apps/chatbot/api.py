from __future__ import annotations

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Conversation
from .serializers import (
    ConversationDetailSerializer,
    ConversationSerializer,
    MessageSerializer,
    SendMessageSerializer,
)
from .services import send_message


class ChatbotFlagMixin:
    """Return 404 on every endpoint when CHATBOT_ENABLED is False so
    unauthenticated callers can't fingerprint the feature."""

    def initial(self, request, *args, **kwargs):
        if not getattr(settings, "CHATBOT_ENABLED", False):
            raise NotFound()
        super().initial(request, *args, **kwargs)


class ConversationViewSet(ChatbotFlagMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ConversationDetailSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["get", "post"], url_path="messages")
    def messages(self, request, pk=None):
        conversation = self.get_object()
        if request.method == "GET":
            data = MessageSerializer(conversation.messages.all(), many=True).data
            return Response(data)

        payload = SendMessageSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user_msg, assistant_msg = send_message(
            conversation=conversation,
            user_content=payload.validated_data["content"],
            actor_username=request.user.username,
        )
        return Response(
            {
                "user_message": MessageSerializer(user_msg).data,
                "assistant_message": MessageSerializer(assistant_msg).data,
            },
            status=status.HTTP_201_CREATED,
        )
