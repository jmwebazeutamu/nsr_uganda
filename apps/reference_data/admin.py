from django.contrib import admin

from .models import GeographicUnit


@admin.register(GeographicUnit)
class GeographicUnitAdmin(admin.ModelAdmin):
    list_display = ("level", "code", "name", "parent", "status", "effective_from", "effective_to")
    list_filter = ("level", "status")
    search_fields = ("code", "name")
    raw_id_fields = ("parent",)
    ordering = ("level", "code")
