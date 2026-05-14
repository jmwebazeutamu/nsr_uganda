from django.contrib import admin

from .models import ChangeRequest


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "entity_type", "entity_id", "change_type",
                    "pmt_relevant", "status", "required_role", "sla_deadline",
                    "requester", "approver")
    list_filter = ("status", "change_type", "pmt_relevant", "source_channel", "entity_type")
    search_fields = ("id", "entity_id", "requester", "approver", "decision_reason")
    readonly_fields = ("id", "created_at", "updated_at", "decided_at", "approver",
                       "sla_deadline", "required_role")
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {"fields": ("id", "entity_type", "entity_id", "status")}),
        ("Change", {"fields": ("change_type", "pmt_relevant", "changes",
                               "evidence", "requester_note")}),
        ("Routing + SLA", {"fields": ("source_channel", "requester", "required_role",
                                       "sla_deadline", "pmt_preview")}),
        ("Decision", {"fields": ("approver", "decided_at", "decision_reason")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
