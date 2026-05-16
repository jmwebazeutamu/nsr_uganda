from django.contrib import admin, messages

from .models import DqaResult, DqaRule
from .services import ApprovalError, approve, retire, submit_for_approval


@admin.register(DqaRule)
class DqaRuleAdmin(admin.ModelAdmin):
    list_display = ("rule_id", "version", "severity", "status", "author", "approved_by", "effective_from")
    list_filter = ("status", "severity")
    search_fields = ("rule_id", "description", "author", "approved_by")
    readonly_fields = ("id", "created_at", "updated_at", "approved_at")
    ordering = ("rule_id", "-version")
    actions = ["action_submit", "action_approve_as_admin", "action_retire"]

    fieldsets = (
        (None, {"fields": ("id", "rule_id", "version", "status")}),
        ("Definition", {"fields": ("description", "severity", "applicability_filter",
                                    "expression", "error_message_template")}),
        ("Lifecycle", {"fields": ("effective_from", "effective_to",
                                   "author", "approved_by", "approved_at",
                                   "created_at", "updated_at")}),
    )

    def _act(self, request, queryset, fn, label: str):
        ok, fail = 0, 0
        for rule in queryset:
            try:
                fn(rule)
                ok += 1
            except ApprovalError as e:
                fail += 1
                self.message_user(request, f"{rule.rule_id} v{rule.version}: {e}", level=messages.WARNING)
        if ok:
            self.message_user(request, f"{label}: {ok} ok, {fail} skipped", level=messages.SUCCESS)
        elif fail:
            self.message_user(request, f"{label}: {fail} skipped", level=messages.WARNING)

    @admin.action(description="Submit selected DRAFT rules for approval")
    def action_submit(self, request, queryset):
        actor = request.user.username or "admin"
        self._act(
            request, queryset,
            lambda r: submit_for_approval(r, actor=actor),
            "submit_for_approval",
        )

    @admin.action(description="Approve selected PENDING rules (as me)")
    def action_approve_as_admin(self, request, queryset):
        approver = request.user.username or "admin"
        # The service requires a non-blank note; bulk admin action
        # uses a generic default so the audit row still carries
        # SOMETHING — operators wanting a per-rule justification go
        # through the per-row Rule Editor UI (US-076).
        self._act(
            request, queryset,
            lambda r: approve(
                r, approver=approver, note="Approved via admin action",
                actor=approver,
            ),
            "approve",
        )

    @admin.action(description="Retire selected ACTIVE rules")
    def action_retire(self, request, queryset):
        actor = request.user.username or "admin"
        self._act(
            request, queryset,
            lambda r: retire(r, actor=actor),
            "retire",
        )


@admin.register(DqaResult)
class DqaResultAdmin(admin.ModelAdmin):
    list_display = ("executed_at", "rule", "record_type", "record_id", "passed", "severity")
    list_filter = ("passed", "severity", "record_type")
    search_fields = ("rule__rule_id", "record_id", "reason")
    readonly_fields = ("rule", "record_type", "record_id", "passed", "severity", "reason", "executed_at")
    ordering = ("-executed_at",)
    date_hierarchy = "executed_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
