from django.contrib import admin

from .models import (
    ConsentEvidence,
    ConsentLanguage,
    ConsentPurpose,
    ConsentRecord,
    ConsentRecordVersion,
    ConsentStatementVersion,
    ConsentWithdrawalTicket,
    WithdrawalDecision,
)


@admin.register(ConsentPurpose)
class ConsentPurposeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "lawful_basis", "withdrawable", "status")
    list_filter = ("status", "lawful_basis", "withdrawable")
    search_fields = ("code", "name")


@admin.register(ConsentStatementVersion)
class ConsentStatementVersionAdmin(admin.ModelAdmin):
    list_display = ("purpose", "version", "status", "is_material", "effective_from")
    list_filter = ("status", "is_material")


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ("member", "purpose", "state", "captured_via", "captured_at")
    list_filter = ("state", "captured_via", "purpose")
    search_fields = ("member__id",)


@admin.register(ConsentRecordVersion)
class ConsentRecordVersionAdmin(admin.ModelAdmin):
    list_display = ("member_id", "purpose_code", "state", "state_from", "effective_from")
    list_filter = ("state",)
    search_fields = ("member_id",)


@admin.register(ConsentWithdrawalTicket)
class ConsentWithdrawalTicketAdmin(admin.ModelAdmin):
    list_display = ("member", "purpose", "state", "requested_at", "sla_deadline")
    list_filter = ("state", "purpose")


@admin.register(WithdrawalDecision)
class WithdrawalDecisionAdmin(admin.ModelAdmin):
    list_display = ("ticket", "decision", "decided_by", "decided_at")
    list_filter = ("decision",)


@admin.register(ConsentEvidence)
class ConsentEvidenceAdmin(admin.ModelAdmin):
    list_display = ("consent_record", "evidence_type", "captured_at")
    list_filter = ("evidence_type",)


@admin.register(ConsentLanguage)
class ConsentLanguageAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "is_ready", "display_order")
