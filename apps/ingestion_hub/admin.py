from django.contrib import admin

from .models import (
    Connector,
    ConnectorRun,
    DataProvisionAgreement,
    MappingRule,
    MappingRuleVersion,
    PromotionBatch,
    PromotionDecision,
    Quarantine,
    RawLanding,
    SourceSystem,
    StageRecord,
)


@admin.register(SourceSystem)
class SourceSystemAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "is_active", "updated_at")
    list_filter = ("kind", "is_active")
    search_fields = ("code", "name")


@admin.register(DataProvisionAgreement)
class DPAAdmin(admin.ModelAdmin):
    list_display = ("reference", "source_system", "valid_from", "valid_to", "residence_policy_days")
    list_filter = ("source_system",)
    search_fields = ("reference", "purpose")
    raw_id_fields = ("source_system",)


@admin.register(Connector)
class ConnectorAdmin(admin.ModelAdmin):
    list_display = ("name", "source_system", "is_active", "updated_at")
    list_filter = ("source_system", "is_active")
    raw_id_fields = ("source_system",)
    search_fields = ("name",)


@admin.register(ConnectorRun)
class ConnectorRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "connector", "status", "records_landed",
                    "records_promoted", "records_quarantined", "records_rejected")
    list_filter = ("status", "connector")
    raw_id_fields = ("connector",)
    date_hierarchy = "started_at"
    readonly_fields = (
        "id", "connector", "started_at", "finished_at", "status",
        "records_received", "records_landed", "records_staged",
        "records_promoted", "records_quarantined", "records_rejected",
    )


@admin.register(RawLanding)
class RawLandingAdmin(admin.ModelAdmin):
    """Append-only per AC-DIH-LANDING-IMMUTABLE."""
    list_display = ("received_at", "connector_run", "source_reference")
    list_filter = ("connector_run__connector__source_system",)
    raw_id_fields = ("connector_run",)
    readonly_fields = ("id", "connector_run", "payload", "received_at", "source_reference")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MappingRule)
class MappingRuleAdmin(admin.ModelAdmin):
    list_display = ("source_system", "code", "description")
    raw_id_fields = ("source_system",)
    search_fields = ("code", "description")


@admin.register(MappingRuleVersion)
class MappingRuleVersionAdmin(admin.ModelAdmin):
    list_display = ("rule", "version", "is_active", "created_at")
    list_filter = ("is_active",)
    raw_id_fields = ("rule",)


@admin.register(StageRecord)
class StageRecordAdmin(admin.ModelAdmin):
    list_display = ("created_at", "state", "provisional_registry_id",
                    "connector_run", "promoted_at")
    list_filter = ("state",)
    search_fields = ("provisional_registry_id", "rejected_reason")
    raw_id_fields = ("raw_landing", "connector_run", "mapping_rule_version")
    readonly_fields = (
        "id", "provisional_registry_id", "promoted_household_id",
        "promoted_at", "rejected_at", "rejected_by", "created_at", "updated_at",
    )
    date_hierarchy = "created_at"


@admin.register(PromotionDecision)
class PromotionDecisionAdmin(admin.ModelAdmin):
    list_display = ("decided_at", "action", "actor", "stage_record", "batch")
    list_filter = ("action",)
    raw_id_fields = ("stage_record", "batch")
    readonly_fields = (
        "id", "stage_record", "batch", "action", "actor", "reason", "decided_at",
    )

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PromotionBatch)
class PromotionBatchAdmin(admin.ModelAdmin):
    list_display = ("submitted_at", "label", "record_count",
                    "approver_a", "approver_b", "finalised_at")


@admin.register(Quarantine)
class QuarantineAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "connector_run", "escalated")
    list_filter = ("reason", "escalated")
    raw_id_fields = ("connector_run", "raw_landing")
