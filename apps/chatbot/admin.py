from django.contrib import admin

from .models import Conversation, ManualChunk, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "started_at", "updated_at")
    list_filter = ("started_at",)
    search_fields = ("title", "user__username")
    readonly_fields = ("id", "started_at", "updated_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "model", "tokens_in", "tokens_out", "created_at")
    list_filter = ("role", "model")
    search_fields = ("content",)
    readonly_fields = ("id", "created_at")


@admin.register(ManualChunk)
class ManualChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "source_path", "heading_path", "token_count", "created_at")
    list_filter = ("source_path",)
    search_fields = ("source_path", "heading_path", "content")
    readonly_fields = ("id", "created_at", "embedding")
