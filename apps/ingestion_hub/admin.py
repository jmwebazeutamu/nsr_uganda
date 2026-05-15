from datetime import timedelta

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Connector,
    ConnectorRun,
    ConnectorRunStatus,
    DataProvisionAgreement,
    FastTrackAuditSample,
    MappingRule,
    MappingRuleVersion,
    PromotionBatch,
    PromotionDecision,
    Quarantine,
    RawLanding,
    SourceSystem,
    StageRecord,
)

# Runs sitting in RUNNING state beyond this are considered stuck —
# Celery worker likely died mid-import. Operations runbook fires the
# bulk "mark failed" admin action to clear them.
STUCK_RUN_THRESHOLD = timedelta(hours=6)


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
    list_display = (
        "started_at", "connector", "status_badge",
        "records_received", "records_landed", "records_staged",
        "records_promoted", "records_quarantined", "records_rejected",
        "duration_display",
    )
    list_filter = ("status", "connector")
    raw_id_fields = ("connector",)
    date_hierarchy = "started_at"
    actions = ("mark_stuck_runs_failed",)
    readonly_fields = (
        "id", "connector", "started_at", "finished_at", "status",
        "records_received", "records_landed", "records_staged",
        "records_promoted", "records_quarantined", "records_rejected",
        "duration_display",
    )

    @admin.display(description="Status")
    def status_badge(self, obj: ConnectorRun) -> str:
        """Colour-coded status with a red 'STUCK' overlay for RUNNING
        rows older than STUCK_RUN_THRESHOLD. Same XSS-clean pattern
        as the GRM admin badge from S4-005."""
        tone = {
            ConnectorRunStatus.PENDING:     ("#999",    obj.status),
            ConnectorRunStatus.RUNNING:     ("#1565c0", obj.status),
            ConnectorRunStatus.SUCCEEDED:   ("#198754", obj.status),
            ConnectorRunStatus.FAILED:      ("#b00",    obj.status),
            ConnectorRunStatus.QUARANTINED: ("#b87410", obj.status),
        }.get(obj.status, ("#666", obj.status))
        color, label = tone
        # Stuck overlay — visible only on RUNNING rows past threshold.
        if (obj.status == ConnectorRunStatus.RUNNING
                and (timezone.now() - obj.started_at) > STUCK_RUN_THRESHOLD):
            return format_html(
                '<span style="color:#b00;font-weight:600">{}</span>',
                "STUCK > 6h",
            )
        return format_html('<span style="color:{}">{}</span>', color, label)

    @admin.display(description="Duration")
    def duration_display(self, obj: ConnectorRun) -> str:
        """Compact h:mm:ss for finished runs, "running for Xh Ym" for
        live ones. None for pending."""
        if obj.status == ConnectorRunStatus.PENDING:
            return "—"
        end = obj.finished_at or timezone.now()
        delta = end - obj.started_at
        hours = delta.total_seconds() / 3600
        if obj.finished_at is None:
            if hours >= 1:
                return f"running {hours:.1f}h"
            return f"running {delta.total_seconds()/60:.0f}m"
        if hours >= 1:
            return f"{int(hours)}h {int(delta.total_seconds()/60) % 60}m"
        return f"{int(delta.total_seconds()/60)}m {int(delta.total_seconds()) % 60}s"

    @admin.action(description="Mark stuck RUNNING runs as FAILED (≥ 6h since start)")
    def mark_stuck_runs_failed(self, request, queryset):
        """Bulk-fail runs that have been RUNNING beyond the stuck
        threshold. Doesn't touch records_* counters — those reflect
        whatever the worker managed before it died, and an operator
        reading the audit chain can see exactly how far the run got.
        finished_at gets set to now() so the duration display flips
        from the rolling 'running' indicator to a fixed h:m number."""
        cutoff = timezone.now() - STUCK_RUN_THRESHOLD
        target = queryset.filter(
            status=ConnectorRunStatus.RUNNING, started_at__lt=cutoff,
        )
        marked = 0
        for run in target:
            run.status = ConnectorRunStatus.FAILED
            run.finished_at = timezone.now()
            run.note = (
                (run.note + "\n" if run.note else "")
                + f"Admin marked as FAILED via bulk action — was stuck "
                f"since {run.started_at.isoformat()}."
            )
            run.save(update_fields=["status", "finished_at", "note"])
            marked += 1
        skipped = queryset.count() - marked
        self.message_user(
            request,
            f"Marked {marked} stuck run(s) as FAILED; {skipped} skipped "
            f"(either not RUNNING or under the {STUCK_RUN_THRESHOLD} threshold).",
            level=messages.SUCCESS if marked else messages.WARNING,
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


@admin.register(FastTrackAuditSample)
class FastTrackAuditSampleAdmin(admin.ModelAdmin):
    """NSR Unit audit queue for fast-tracked auto-promotions (AC-DIH-FT-AUTO)."""

    list_display = ("sampled_at", "stage_record", "household_id", "status",
                    "reviewed_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("stage_record__id", "household_id", "reviewed_by", "notes")
    raw_id_fields = ("stage_record",)
    readonly_fields = ("id", "stage_record", "household_id", "sampled_at")
    date_hierarchy = "sampled_at"


@admin.register(Quarantine)
class QuarantineAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "connector_run", "escalated")
    list_filter = ("reason", "escalated")
    raw_id_fields = ("connector_run", "raw_landing")
