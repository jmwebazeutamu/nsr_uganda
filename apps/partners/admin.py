"""Admin registration for the partners module (ADR-0009 §"Admin parity is a release blocker")."""

from __future__ import annotations

from django.contrib import admin

from .models import Partner


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "type", "sector", "status",
        "lead_user", "last_activity_at",
    )
    list_filter = ("type", "sector", "status")
    search_fields = ("code", "name", "registration_no", "primary_email")
    readonly_fields = ("id", "created_at", "updated_at", "last_activity_at")
    fieldsets = (
        (None, {
            "fields": (
                "id", "code", "name", "registration_no", "country",
                "website", "primary_email",
            ),
        }),
        ("Coded fields (ChoiceList-backed)", {
            "fields": ("type", "sector", "status", "tone"),
            "description": (
                "Raw ChoiceOption.code values resolved via "
                "apps.reference_data.services. Options come from the "
                "partner_type / partner_sector / partner_status / ui_tone "
                "ChoiceLists (ADR-0010)."
            ),
        }),
        ("Operations", {
            "fields": ("lead_user", "logo_short", "note", "last_activity_at"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
