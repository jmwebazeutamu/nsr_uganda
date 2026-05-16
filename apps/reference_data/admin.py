from django.contrib import admin

from .models import ChoiceList, ChoiceOption, GeographicUnit


@admin.register(GeographicUnit)
class GeographicUnitAdmin(admin.ModelAdmin):
    list_display = ("level", "code", "name", "parent", "status", "effective_from", "effective_to")
    list_filter = ("level", "status")
    search_fields = ("code", "name")
    raw_id_fields = ("parent",)
    ordering = ("level", "code")


# US-116 — ChoiceList admin. Inline ChoiceOption editing for the
# common case of small lists; the standalone ChoiceOption admin is
# for ops who need to find a specific code across all lists. The
# write-side service-layer + approval workflow lands in US-116b
# (mirror DqaRule admin pattern with action buttons).
class ChoiceOptionInline(admin.TabularInline):
    model = ChoiceOption
    extra = 0
    fields = ("code", "label", "language", "parent_code", "sort_order", "status")
    ordering = ("sort_order", "code")


@admin.register(ChoiceList)
class ChoiceListAdmin(admin.ModelAdmin):
    list_display = ("list_name", "version", "status", "option_count",
                    "author", "approved_by", "effective_from")
    list_filter = ("status",)
    search_fields = ("list_name", "description", "author", "approved_by")
    readonly_fields = ("id", "created_at", "updated_at",
                       "approved_at", "submitted_at",
                       "approval_note", "rejection_reason")
    ordering = ("list_name", "-version")
    inlines = [ChoiceOptionInline]

    def get_queryset(self, request):
        from django.db.models import Count
        return (super().get_queryset(request)
                .annotate(_option_count=Count("options")))

    @admin.display(description="Options", ordering="_option_count")
    def option_count(self, obj):
        return getattr(obj, "_option_count", obj.options.count())


@admin.register(ChoiceOption)
class ChoiceOptionAdmin(admin.ModelAdmin):
    list_display = ("choice_list", "code", "label", "language",
                    "parent_code", "status")
    list_filter = ("status", "language", "choice_list__list_name")
    search_fields = ("code", "label", "choice_list__list_name")
    raw_id_fields = ("choice_list",)
    ordering = ("choice_list", "sort_order", "code")
