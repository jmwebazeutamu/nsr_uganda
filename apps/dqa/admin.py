import difflib
import json

from django.conf import settings
from django.contrib import admin, messages

from .forms import DqaRuleAdminForm, _active_form_schema
from .models import DqaResult, DqaRule
from .services import ApprovalError, approve, retire, submit_for_approval


@admin.register(DqaRule)
class DqaRuleAdmin(admin.ModelAdmin):
    list_display = ("rule_id", "version", "severity", "status", "author", "approved_by", "effective_from")
    list_filter = ("status", "severity")
    search_fields = ("rule_id", "description", "author", "approved_by")
    readonly_fields = ("id", "created_at", "updated_at", "approved_at",
                       "submitted_at", "approval_note", "rejection_reason")
    ordering = ("rule_id", "-version")
    actions = ["action_submit", "action_approve_as_admin", "action_retire"]

    _BASE_FIELDSETS = (
        (None, {"fields": ("id", "rule_id", "version", "status")}),
        ("Definition", {"fields": ("description", "severity", "applicability_filter",
                                    "expression", "error_message_template")}),
        ("Lifecycle", {"fields": ("effective_from", "effective_to",
                                   "author", "approved_by", "approved_at",
                                   "submitted_at", "approval_note", "rejection_reason",
                                   "created_at", "updated_at")}),
    )

    def get_fieldsets(self, request, obj=None):
        # US-076 — wizard fields only show when DQA_RULE_EDITOR_V2 is
        # on. When off, the base fieldsets render and the default
        # ModelForm has no wizard_* fields, avoiding a FieldError.
        base = self._BASE_FIELDSETS
        if getattr(settings, "DQA_RULE_EDITOR_V2", False):
            return base + (
                ("Wizard (optional — compiles to expression on save)",
                 {"fields": ("wizard_field", "wizard_field_type",
                             "wizard_op", "wizard_value"),
                  "classes": ("collapse",)}),
            )
        return base

    # US-076: switch between legacy textarea-only admin and the v2
    # builder via the DQA_RULE_EDITOR_V2 flag. When v2 is off, the
    # custom form is still loaded but the change_form template falls
    # back to the default; v2 on enables the preview pane + version
    # history + approve/reject modals in change_form.html.
    def get_form(self, request, obj=None, **kwargs):
        if getattr(settings, "DQA_RULE_EDITOR_V2", False):
            kwargs.setdefault("form", DqaRuleAdminForm)
        return super().get_form(request, obj, **kwargs)

    change_form_template = "admin/dqa/dqarule/change_form.html"

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        """Inject version-history + form-schema context for the
        custom change_form template."""
        extra_context = extra_context or {}
        extra_context["dqa_rule_editor_v2"] = getattr(
            settings, "DQA_RULE_EDITOR_V2", False,
        )
        extra_context["dqa_form_schema_json"] = json.dumps(
            _active_form_schema(), sort_keys=True, default=str,
        )
        if object_id:
            current = DqaRule.objects.filter(pk=object_id).first()
            if current:
                # All versions of this rule_id, newest first. Each row
                # carries a unified diff against the prior version's
                # expression JSON (US-076 version-history tab).
                versions = list(
                    DqaRule.objects.filter(rule_id=current.rule_id)
                                    .order_by("-version"),
                )
                history = []
                # diff against the immediately-prior version (sorted
                # ascending by version so v2 diffs v1, v3 diffs v2…).
                vs_asc = list(reversed(versions))
                for i, v in enumerate(vs_asc):
                    prior = vs_asc[i - 1] if i > 0 else None
                    if prior is None:
                        diff = ""
                    else:
                        a = json.dumps(prior.expression, indent=2, sort_keys=True).splitlines(keepends=True)
                        b = json.dumps(v.expression, indent=2, sort_keys=True).splitlines(keepends=True)
                        diff = "".join(difflib.unified_diff(
                            a, b,
                            fromfile=f"v{prior.version}",
                            tofile=f"v{v.version}",
                            n=2,
                        ))
                    history.append({"rule": v, "diff": diff})
                # Reverse to newest-first for display.
                history.reverse()
                extra_context["dqa_version_history"] = history
        return super().changeform_view(request, object_id, form_url, extra_context)

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
