from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only admin. AuditEvent is append-only — UI enforces what the
    Postgres trigger enforces structurally."""

    list_display = ("occurred_at", "action", "entity_type", "entity_id", "actor_id", "actor_kind")
    list_filter = ("action", "entity_type", "actor_kind")
    search_fields = ("entity_id", "actor_id", "reason")
    ordering = ("-occurred_at",)
    date_hierarchy = "occurred_at"

    readonly_fields = (
        "id", "occurred_at", "actor_id", "actor_kind", "action",
        "entity_type", "entity_id", "field_changes", "reason",
        "ip_address", "user_agent", "prev_hash_hex", "self_hash_hex",
    )
    exclude = ("prev_hash", "self_hash")

    @admin.display(description="prev_hash (hex)")
    def prev_hash_hex(self, obj):
        return obj.prev_hash.hex() if obj.prev_hash else "—"

    @admin.display(description="self_hash (hex)")
    def self_hash_hex(self, obj):
        return obj.self_hash.hex() if obj.self_hash else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
