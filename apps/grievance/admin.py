"""GRM admin workbench.

Operational supervisors at L2/L3/L4 need a hands-on surface even when
the React console isn't deployed (rural districts, intermittent
connectivity, training day fallback). This module turns
/admin/grievance/grievance/ into that surface:

- List shows opened_at, tier, category, status, household_id,
  assigned_to, sla_deadline and a coloured SLA-breach badge.
- Filters narrow to common operational slices (status, tier, category,
  breach state).
- Bulk admin actions trigger the same service-layer transitions that
  the REST API uses, so audit emission and signal wiring are identical.

All transitions remain in apps.grievance.services — the admin only
calls them, never re-implements the state machine. The actor recorded
in AuditEvent is request.user.username (with 'admin-bot' as the safe
fallback for service-account use).
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import Grievance, GrievanceStatus
from .services import (
    GrievanceError,
    assign,
    close,
    escalate,
    open_grievance,
    resolve,
)

OPEN_STATES = (GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS,
               GrievanceStatus.ESCALATED)


@admin.register(Grievance)
class GrievanceAdmin(admin.ModelAdmin):
    list_display = (
        "opened_at", "tier", "category", "status", "sla_badge",
        "household_id", "assigned_to", "sla_deadline",
    )
    list_filter = ("status", "tier", "category")
    search_fields = ("id", "household_id", "member_id",
                     "reporter_name", "reporter_phone", "assigned_to")
    readonly_fields = ("id", "opened_at", "sla_deadline",
                       "resolved_at", "closed_at", "linked_change_request_id",
                       "created_at", "updated_at")
    date_hierarchy = "opened_at"
    actions = ("admin_escalate", "admin_close")

    fieldsets = (
        (None, {"fields": ("id", "category", "sub_category", "description",
                            "status", "tier", "assigned_to")}),
        ("Subject",
         {"fields": ("household_id", "member_id")}),
        ("Reporter",
         {"fields": ("reporter_name", "reporter_phone", "reporter_relationship")}),
        ("Resolution",
         {"fields": ("resolution_narrative", "linked_change_request_id")}),
        ("Timestamps", {"fields": ("opened_at", "sla_deadline",
                                    "resolved_at", "closed_at",
                                    "created_at", "updated_at")}),
    )

    def save_model(self, request, obj, form, change):
        """For new grievances, route through apps.grievance.services.
        open_grievance so the SLA deadline is computed and the
        AuditEvent is emitted. Admin-direct CREATEs were silently
        skipping both, leaving rows with sla_deadline=NULL that the
        workbench couldn't badge."""
        actor = getattr(request.user, "username", "") or "admin-bot"
        if change:
            return super().save_model(request, obj, form, change)
        opened = open_grievance(
            category=obj.category, description=obj.description or "",
            household_id=obj.household_id or "",
            member_id=obj.member_id or "",
            reporter_name=obj.reporter_name or "",
            reporter_phone=obj.reporter_phone or "",
            reporter_relationship=obj.reporter_relationship or "",
            tier=obj.tier or "l1_parish_chief",
            assigned_to=obj.assigned_to or "",
            sub_category=obj.sub_category or "",
            actor=actor,
        )
        # Mirror the persisted state back onto the admin's in-memory
        # obj so redirects + change-history pick up the right id.
        obj.pk = opened.pk
        for f in opened._meta.fields:
            setattr(obj, f.name, getattr(opened, f.name))

    @admin.display(description="SLA")
    def sla_badge(self, obj: Grievance) -> str:
        # format_html with a placeholder keeps Django's auto-escape on
        # the dynamic label text, avoids the Django 6.0 deprecation
        # warning that fires on format_html() with no args, and avoids
        # bandit B308 (which flags any mark_safe call regardless of
        # whether the input is static).
        if obj.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
            return format_html('<span style="color:#666">{}</span>', "—")
        if obj.sla_deadline is None:
            return format_html('<span style="color:#999">{}</span>', "no SLA")
        if obj.sla_deadline < timezone.now():
            return format_html(
                '<span style="color:#b00;font-weight:600">{}</span>',
                "OVERDUE",
            )
        return format_html('<span style="color:#080">{}</span>', "ok")

    # --- bulk actions ----------------------------------------------------
    # The admin layer is a thin wrapper around the service layer; every
    # action goes through services.* so audit emission, GRM↔UPD
    # signalling, and state-transition guards all behave identically to
    # the REST surface.

    @admin.action(description="Escalate selected grievances one tier")
    def admin_escalate(self, request, queryset):
        actor = (getattr(request.user, "username", "") or "admin-bot")
        moved = 0
        skipped = 0
        for g in queryset:
            try:
                escalate(g, actor=actor, reason="admin bulk action")
                moved += 1
            except GrievanceError:
                skipped += 1
        self.message_user(
            request,
            f"Escalated {moved} grievance(s); {skipped} skipped (terminal "
            "status or already at L4).",
            level=messages.SUCCESS if moved else messages.WARNING,
        )

    @admin.action(description="Close selected RESOLVED grievances")
    def admin_close(self, request, queryset):
        actor = (getattr(request.user, "username", "") or "admin-bot")
        closed = 0
        skipped = 0
        for g in queryset:
            try:
                close(g, actor=actor)
                closed += 1
            except GrievanceError:
                skipped += 1
        self.message_user(
            request,
            f"Closed {closed} grievance(s); {skipped} skipped (not RESOLVED).",
            level=messages.SUCCESS if closed else messages.WARNING,
        )

    # Re-export for tests that want to invoke the services directly with
    # an admin-shaped actor identifier.
    _services = (assign, escalate, resolve, close)
