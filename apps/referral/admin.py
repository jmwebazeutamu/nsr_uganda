from django.contrib import admin

from .models import Programme, ProgrammeEnrolment, Referral


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "dsa_reference", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "dsa_reference")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "programme", "household", "status",
                    "programme_side_id", "last_delivery_at")
    list_filter = ("status", "programme")
    search_fields = ("id", "household__id", "programme__code", "programme_side_id")
    readonly_fields = ("id", "sent_at", "accepted_at", "enrolled_at",
                       "rejected_at", "exited_at",
                       "last_delivery_id", "last_delivery_at")
    raw_id_fields = ("programme", "household")
    date_hierarchy = "sent_at"


@admin.register(ProgrammeEnrolment)
class ProgrammeEnrolmentAdmin(admin.ModelAdmin):
    list_display = ("effective_date", "programme", "household", "status", "exit_reason")
    list_filter = ("status", "programme")
    search_fields = ("id", "household__id", "programme__code")
    raw_id_fields = ("programme", "household", "referral")
    readonly_fields = ("id", "created_at", "updated_at")
