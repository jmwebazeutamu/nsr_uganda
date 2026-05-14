from django.contrib import admin

from .models import DdupModelVersion, MatchPair, MergeDecision


@admin.register(DdupModelVersion)
class DdupModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "status", "author", "approved_by", "effective_from", "updated_at")
    list_filter = ("status",)
    readonly_fields = ("id", "created_at", "updated_at", "approved_at")
    search_fields = ("description", "author", "approved_by")


@admin.register(MatchPair)
class MatchPairAdmin(admin.ModelAdmin):
    list_display = ("created_at", "record_type", "record_a_id", "record_b_id", "tier",
                    "match_reason", "status")
    list_filter = ("status", "tier", "record_type", "match_reason")
    search_fields = ("record_a_id", "record_b_id")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("model_version",)
    ordering = ("-created_at",)


@admin.register(MergeDecision)
class MergeDecisionAdmin(admin.ModelAdmin):
    list_display = ("decided_at", "action", "surviving_record_id", "losing_record_id",
                    "decided_by", "reverse_window_until", "reversed_at")
    list_filter = ("action",)
    search_fields = ("surviving_record_id", "losing_record_id", "decided_by", "reason")
    readonly_fields = (
        "id", "match_pair", "action", "surviving_record_id", "losing_record_id",
        "chosen_field_values", "reason", "decided_by", "decided_at",
        "reverse_window_until", "reversed_at", "reversed_by",
    )
    raw_id_fields = ("match_pair",)
    ordering = ("-decided_at",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
