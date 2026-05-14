from django.contrib import admin

from .models import PMTModelVersion, PMTResult


@admin.register(PMTModelVersion)
class PMTModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "status", "author", "approved_by", "effective_from",
                    "validation_r_squared", "updated_at")
    list_filter = ("status",)
    search_fields = ("description", "author", "approved_by")
    readonly_fields = ("id", "created_at", "updated_at", "approved_at")
    ordering = ("-version",)


@admin.register(PMTResult)
class PMTResultAdmin(admin.ModelAdmin):
    list_display = ("computed_at", "household", "model_version", "score", "band",
                    "triggered_by")
    list_filter = ("band", "triggered_by", "model_version")
    search_fields = ("household__id",)
    readonly_fields = ("id", "household", "model_version", "score", "band",
                       "inputs_snapshot", "triggered_by", "computed_at")
    raw_id_fields = ("household", "model_version")
    date_hierarchy = "computed_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
