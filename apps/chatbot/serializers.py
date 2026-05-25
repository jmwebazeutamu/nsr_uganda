from __future__ import annotations

from rest_framework import serializers

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "tokens_in",
            "tokens_out",
            "model",
            "retrieval_sources",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "role",
            "tokens_in",
            "tokens_out",
            "model",
            "retrieval_sources",
            "created_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "title", "started_at", "updated_at", "message_count"]
        read_only_fields = ["id", "started_at", "updated_at", "message_count"]

    def get_message_count(self, obj: Conversation) -> int:
        return obj.messages.count()


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = [*ConversationSerializer.Meta.fields, "messages"]


class SendMessageSerializer(serializers.Serializer):
    """Input shape for POST /conversations/{id}/messages/."""

    content = serializers.CharField(min_length=1, max_length=8000)
