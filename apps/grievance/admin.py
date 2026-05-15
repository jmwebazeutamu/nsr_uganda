from django.contrib import admin

from .models import Grievance


@admin.register(Grievance)
class GrievanceAdmin(admin.ModelAdmin):
    list_display = ("opened_at", "tier", "category", "status",
                    "household_id", "assigned_to", "sla_deadline")
    list_filter = ("status", "tier", "category")
    search_fields = ("id", "household_id", "member_id",
                     "reporter_name", "reporter_phone", "assigned_to")
    readonly_fields = ("id", "opened_at", "sla_deadline",
                       "resolved_at", "closed_at", "created_at", "updated_at")
    date_hierarchy = "opened_at"
