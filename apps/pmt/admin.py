from django.contrib import admin

from .models import PMTBandThreshold, PMTModelVersion, PMTResult


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


@admin.register(PMTBandThreshold)
class PMTBandThresholdAdmin(admin.ModelAdmin):
    """Read-only history. Analysts use this to trace what the
    threshold was on a given day (eligibility audit + recalibration
    drift). The daily recompute job is the only writer."""

    list_display = ("computed_at", "model_version", "band_name",
                    "score_threshold", "percentile_rank",
                    "sample_size", "computed_by")
    list_filter = ("band_name", "model_version", "computed_by")
    search_fields = ("band_name", "computed_by")
    readonly_fields = ("id", "model_version", "band_name",
                       "score_threshold", "percentile_rank",
                       "sample_size", "computed_at", "computed_by")
    raw_id_fields = ("model_version",)
    date_hierarchy = "computed_at"
    ordering = ("-computed_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
