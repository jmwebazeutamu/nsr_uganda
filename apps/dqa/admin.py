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
    actions = ["action_submit", "action_approve_as_admin",
               "action_retire", "action_backfill"]

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
        self._act(request, queryset, submit_for_approval, "submit_for_approval")

    @admin.action(description="Approve selected PENDING rules (as me)")
    def action_approve_as_admin(self, request, queryset):
        approver = request.user.username or "admin"
        self._act(request, queryset, lambda r: approve(r, approver=approver), "approve")

    @admin.action(description="Retire selected ACTIVE rules")
    def action_retire(self, request, queryset):
        self._act(request, queryset, retire, "retire")

    # US-080b — sweep the selected ACTIVE rule(s) against every
    # stored Household/Member matching applicability_filter.entity.
    # Synchronous; the management command in
    # apps/dqa/management/commands/backfill_dqa_rules.py handles
    # production-scale runs (and is the only path that should be
    # used against 12M-row datasets).
    @admin.action(description="Backfill against stored records (US-080b)")
    def action_backfill(self, request, queryset):
        from .backfill import backfill_rule
        ok, fail, skipped = 0, 0, 0
        actor = request.user.username or "admin"
        for rule in queryset:
            try:
                report = backfill_rule(rule, actor=actor)
                ok += 1
                self.message_user(
                    request,
                    f"{rule.rule_id} v{rule.version}: "
                    f"{report['records_scanned']} "
                    f"{report['entity']}(s) scanned, "
                    f"{report['failures']} failure(s)",
                    level=messages.SUCCESS,
                )
            except ValueError as e:
                skipped += 1
                self.message_user(
                    request, f"{rule.rule_id} v{rule.version}: skipped — {e}",
                    level=messages.WARNING,
                )
            except Exception as e:
                fail += 1
                self.message_user(
                    request, f"{rule.rule_id} v{rule.version}: error — {e}",
                    level=messages.ERROR,
                )
        if ok or skipped or fail:
            self.message_user(
                request,
                f"backfill: {ok} swept, {skipped} skipped, {fail} errored",
                level=messages.SUCCESS if ok and not fail else messages.WARNING,
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
