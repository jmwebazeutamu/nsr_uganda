from django.contrib import admin

from .models import FormVersion, Submission


@admin.register(FormVersion)
class FormVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "name", "is_active", "effective_from", "effective_to")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "enumerator", "result", "state",
                    "stage_record_id", "provisional_registry_id")
    list_filter = ("channel", "state", "result")
    search_fields = ("id", "enumerator", "supervisor",
                     "stage_record_id", "provisional_registry_id")
    raw_id_fields = ("form_version",)
    readonly_fields = ("id", "stage_record_id", "provisional_registry_id",
                       "created_at", "updated_at")
    date_hierarchy = "created_at"
