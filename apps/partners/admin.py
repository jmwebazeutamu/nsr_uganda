"""Admin registration for the partners module (ADR-0009 §"Admin parity is a release blocker")."""

from __future__ import annotations

from django.contrib import admin

from .models import (
    DataSharingAgreement,
    DsaSignature,
    Partner,
    PartnerContact,
    Programme,
)


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


@admin.register(PartnerContact)
class PartnerContactAdmin(admin.ModelAdmin):
    list_display = ("partner", "role", "full_name", "title", "email", "nin_verified_at")
    list_filter = ("role",)
    search_fields = ("partner__code", "full_name", "email", "nin_last4")
    readonly_fields = ("id", "nin_hash", "nin_last4", "nin_verified_at",
                       "created_at", "updated_at")
    raw_id_fields = ("partner",)


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("partner", "name", "kind", "status",
                    "start_date", "end_date", "beneficiary_estimate")
    list_filter = ("kind", "status")
    search_fields = ("partner__code", "name")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("partner",)
    filter_horizontal = ("geographic_units",)


class DsaSignatureInline(admin.TabularInline):
    model = DsaSignature
    extra = 0
    readonly_fields = ("id", "docusign_envelope_id", "signed_at",
                       "created_at", "updated_at")


@admin.register(DataSharingAgreement)
class DataSharingAgreementAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "partner", "version", "status",
        "effective_from", "effective_to", "monthly_row_budget",
    )
    list_filter = ("status", "sensitive_data_handling")
    search_fields = ("reference", "partner__code", "partner__name")
    readonly_fields = ("id", "created_at", "updated_at", "signed_at")
    raw_id_fields = ("partner",)
    filter_horizontal = ("programmes", "geographic_scope")
    inlines = [DsaSignatureInline]


@admin.register(DsaSignature)
class DsaSignatureAdmin(admin.ModelAdmin):
    list_display = ("dsa", "sequence_order", "signer_role",
                    "signer_email", "method", "status", "signed_at")
    list_filter = ("status", "method", "signer_role")
    search_fields = ("dsa__reference", "signer_name", "signer_email",
                     "docusign_envelope_id")
    readonly_fields = ("id", "created_at", "updated_at", "signed_at",
                       "docusign_envelope_id")
    raw_id_fields = ("dsa",)
