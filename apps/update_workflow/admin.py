from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import ChangeRequest, ChangeStatus, UpdRoutingRule
from .services import UpdError, reject_change_request


@admin.register(UpdRoutingRule)
class UpdRoutingRuleAdmin(admin.ModelAdmin):
    list_display = ("change_type", "pmt_relevant", "required_role",
                    "sla_hours", "is_active", "updated_at")
    list_filter = ("change_type", "pmt_relevant", "is_active")
    search_fields = ("required_role", "note")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("change_type", "pmt_relevant", "is_active")}),
        ("Routing", {"fields": ("required_role", "sla_hours", "note")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "entity_type", "entity_id", "change_type",
                    "pmt_relevant", "status", "sla_badge", "required_role",
                    "sla_deadline", "requester", "approver")
    list_filter = ("status", "change_type", "pmt_relevant", "source_channel",
                   "entity_type", "sampled_for_audit")
    search_fields = ("id", "entity_id", "requester", "approver", "decision_reason")
    readonly_fields = ("id", "created_at", "updated_at", "decided_at", "approver",
                       "sla_deadline", "required_role", "sampled_for_audit")
    date_hierarchy = "created_at"
    actions = ("admin_reject",)

    fieldsets = (
        (None, {"fields": ("id", "entity_type", "entity_id", "status")}),
        ("Change", {"fields": ("change_type", "pmt_relevant", "changes",
                               "evidence", "requester_note")}),
        ("Routing + SLA", {"fields": ("source_channel", "requester", "required_role",
                                       "sla_deadline", "pmt_preview")}),
        ("Decision", {"fields": ("approver", "decided_at", "decision_reason",
                                  "sampled_for_audit")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="SLA")
    def sla_badge(self, obj: ChangeRequest) -> str:
        # format_html with a placeholder keeps Django's auto-escape on the
        # label text and avoids the Django 6.0 deprecation on format_html()
        # without args; same pattern as apps.grievance.admin.sla_badge.
        if obj.status in (ChangeStatus.COMMITTED, ChangeStatus.REJECTED,
                          ChangeStatus.REVERSED):
            return format_html('<span style="color:#666">{}</span>', "—")
        if obj.sla_deadline is None:
            return format_html('<span style="color:#999">{}</span>', "no SLA")
        if obj.sla_deadline < timezone.now():
            return format_html(
                '<span style="color:#b00;font-weight:600">{}</span>', "OVERDUE",
            )
        return format_html('<span style="color:#080">{}</span>', "ok")

    @admin.action(description="Reject selected PENDING_APPROVAL requests")
    def admin_reject(self, request, queryset):
        actor = (getattr(request.user, "username", "") or "admin-bot")
        rejected = 0
        skipped = 0
        for cr in queryset:
            try:
                reject_change_request(
                    cr, approver=actor,
                    reason="admin bulk reject (no detail captured)",
                )
                rejected += 1
            except UpdError:
                # Self-approve guard, non-PENDING state, or missing reason
                # all surface as UpdError — skip without aborting the batch.
                skipped += 1
        self.message_user(
            request,
            f"Rejected {rejected} request(s); {skipped} skipped (wrong state "
            "or admin user is also the requester — change request requires a "
            "different approver).",
            level=messages.SUCCESS if rejected else messages.WARNING,
        )
