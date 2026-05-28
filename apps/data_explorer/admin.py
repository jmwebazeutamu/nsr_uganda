"""Django admin for DATA-EXP — catalogue browse + VariableApproval
dual-approval workflow.

Per ADR-0023 D5: two distinct (Variable, role) approvals in {DQA, DPO}
flip the Variable to ACTIVE. Mirrors the DAT-DQA + PMTModelVersion
patterns.
"""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import (
    AggregateQueryLog,
    ApprovalRole,
    CoverageSnapshot,
    Dataset,
    ExplorerSession,
    PrivacyClass,
    QueryThrottleCounter,
    RefreshCadence,
    Variable,
    VariableApproval,
    VariableStatus,
)


@admin.register(PrivacyClass)
class PrivacyClassAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "k_floor", "daily_user_cap",
                    "daily_org_cap", "blocks_aggregate")
    search_fields = ("code", "label")


@admin.register(RefreshCadence)
class RefreshCadenceAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "interval_seconds")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "privacy_class", "refresh_cadence",
                    "geographic_floor", "source_matview")
    list_filter = ("privacy_class", "refresh_cadence", "geographic_floor")
    search_fields = ("code", "label", "description", "source_matview")


@admin.register(Variable)
class VariableAdmin(admin.ModelAdmin):
    list_display = ("code", "dataset", "privacy_class", "status",
                    "data_type", "version", "updated_at")
    list_filter = ("status", "privacy_class", "dataset", "data_type")
    search_fields = ("code", "label", "source_field", "description")
    readonly_fields = ("shape_hash", "version", "created_at", "updated_at")
    actions = ["mark_active_via_dual_approval"]

    @admin.action(description="Mark ACTIVE (records a DQA + DPO approval row)")
    def mark_active_via_dual_approval(self, request, queryset):
        """Convenience admin action — staff can land both approval rows
        in one click for ops use. Production flow uses the
        VariableApprovalAdmin row-add path so each role is a distinct
        actor."""
        actor = getattr(request.user, "username", "admin")
        for v in queryset:
            VariableApproval.objects.update_or_create(
                variable=v, approval_role=ApprovalRole.DQA,
                defaults={"approver": actor, "note": "admin convenience"},
            )
            VariableApproval.objects.update_or_create(
                variable=v, approval_role=ApprovalRole.DPO,
                defaults={"approver": actor, "note": "admin convenience"},
            )
            v.status = VariableStatus.ACTIVE
            v.save(update_fields=["status", "updated_at"])
            emit_audit(
                "data_explorer.variable.activated", "variable",
                str(v.id), actor=actor,
                reason="admin dual-approval convenience action",
            )


@admin.register(VariableApproval)
class VariableApprovalAdmin(admin.ModelAdmin):
    list_display = ("variable", "approver", "approval_role",
                    "approved_at", "overridden_privacy_class")
    list_filter = ("approval_role",)
    search_fields = ("variable__code", "approver", "note")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # When both DQA and DPO rows exist for the variable, flip the
        # variable to ACTIVE. Mirrors the DqaRuleVersion + PMTModelVersion
        # dual-approval pattern.
        roles = set(
            VariableApproval.objects
            .filter(variable=obj.variable)
            .values_list("approval_role", flat=True)
        )
        if ApprovalRole.DQA in roles and ApprovalRole.DPO in roles:
            v = obj.variable
            if v.status != VariableStatus.ACTIVE:
                v.status = VariableStatus.ACTIVE
                # DPO override of the PrivacyClass (if any) lands here.
                if obj.overridden_privacy_class_id and obj.approval_role == ApprovalRole.DPO:
                    old_class = v.privacy_class.code
                    v.privacy_class = obj.overridden_privacy_class
                    emit_audit(
                        "data_explorer.variable.privacy_class.overridden",
                        "variable", str(v.id),
                        actor=obj.approver,
                        reason=(
                            f"DPO override {old_class} → "
                            f"{obj.overridden_privacy_class.code}"
                        ),
                        field_changes={
                            "old_class": old_class,
                            "new_class": obj.overridden_privacy_class.code,
                        },
                    )
                v.save(update_fields=["status", "privacy_class", "updated_at"])
                emit_audit(
                    "data_explorer.variable.activated", "variable",
                    str(v.id),
                    actor=obj.approver,
                    reason=(
                        f"dual approval complete (DQA+DPO) at "
                        f"{timezone.now().isoformat()}"
                    ),
                )


@admin.register(AggregateQueryLog)
class AggregateQueryLogAdmin(admin.ModelAdmin):
    list_display = ("executed_at", "actor", "dataset",
                    "result_row_count", "suppressed_cell_count",
                    "strictest_privacy_class")
    list_filter = ("strictest_privacy_class", "dataset")
    search_fields = ("actor", "query_hash", "filter_hash")
    readonly_fields = ("executed_at",)


@admin.register(QueryThrottleCounter)
class QueryThrottleCounterAdmin(admin.ModelAdmin):
    list_display = ("date_utc", "actor", "privacy_class", "org_code",
                    "count", "updated_at")
    list_filter = ("privacy_class", "date_utc")
    search_fields = ("actor", "org_code")


@admin.register(ExplorerSession)
class ExplorerSessionAdmin(admin.ModelAdmin):
    list_display = ("started_at", "actor", "handoff_status",
                    "data_request_id", "last_query_at")
    list_filter = ("handoff_status",)
    search_fields = ("actor", "data_request_id", "last_query_hash")


@admin.register(CoverageSnapshot)
class CoverageSnapshotAdmin(admin.ModelAdmin):
    list_display = ("dataset", "geo_level", "geo_code",
                    "completeness_pct", "row_count", "captured_at")
    list_filter = ("dataset", "geo_level")
    search_fields = ("geo_code", "geo_label")
