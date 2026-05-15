from django.contrib import admin, messages
from django.utils.html import format_html, format_html_join

from .models import DdupModelVersion, MatchPair, MergeAction, MergeDecision
from .services import MergeError, reverse_merge_decision


def _score_colour(v: float) -> str:
    """Match the corridor signal — green ≥0.9, amber 0.5-0.9, red <0.5
    — so reviewers see at a glance which fields drove a tier-3 match."""
    return "#198754" if v >= 0.9 else "#b87410" if v >= 0.5 else "#a93226"


@admin.register(DdupModelVersion)
class DdupModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "status", "author", "approved_by", "effective_from", "updated_at")
    list_filter = ("status",)
    readonly_fields = ("id", "created_at", "updated_at", "approved_at")
    search_fields = ("description", "author", "approved_by")


@admin.register(MatchPair)
class MatchPairAdmin(admin.ModelAdmin):
    list_display = ("created_at", "record_type", "record_a_id", "record_b_id", "tier",
                    "match_reason", "composite_score", "status")
    list_filter = ("status", "tier", "record_type", "match_reason")
    search_fields = ("record_a_id", "record_b_id")
    readonly_fields = ("id", "created_at", "updated_at", "scores_table")
    raw_id_fields = ("model_version",)
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("id", "record_type", "record_a_id", "record_b_id",
                            "tier", "match_reason", "status")}),
        ("Scoring", {"fields": ("model_version", "composite_score",
                                  "per_field_scores", "scores_table")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Per-field breakdown")
    def scores_table(self, obj: MatchPair) -> str:
        """Render per_field_scores as a small readable table. Saves
        reviewers from squinting at raw JSON in the workbench — the
        tier-3 model's per-field decimals (Jaro-Winkler etc.) are
        the WHY behind every probabilistic match."""
        scores = obj.per_field_scores or {}
        if not scores:
            return format_html('<em>{}</em>', "no per-field scores recorded")
        rows = format_html_join(
            "",
            '<tr><td style="padding:4px 12px 4px 0">{}</td>'
            '<td style="font-family:monospace;text-align:right;color:{}">{}</td></tr>',
            (
                (field, _score_colour(v), f"{v:.3f}")
                for field, v in sorted(scores.items())
            ),
        )
        return format_html("<table>{}</table>", rows)


@admin.register(MergeDecision)
class MergeDecisionAdmin(admin.ModelAdmin):
    list_display = ("decided_at", "action", "surviving_record_id", "losing_record_id",
                    "decided_by", "reverse_window_until", "reversed_at")
    list_filter = ("action",)
    search_fields = ("surviving_record_id", "losing_record_id", "decided_by", "reason")
    readonly_fields = (
        "id", "match_pair", "action", "surviving_record_id", "losing_record_id",
        "chosen_field_values", "reason", "decided_by", "decided_at",
        "reverse_window_until", "reversed_at", "reversed_by", "reversed_reason",
        "pre_merge_snapshot",
    )
    raw_id_fields = ("match_pair",)
    ordering = ("-decided_at",)
    actions = ("admin_reverse_merge",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Reverse selected MERGE decisions (within 30d window)")
    def admin_reverse_merge(self, request, queryset):
        """Bulk reverse — delegates to services.reverse_merge_decision
        so audit + guard semantics are identical to the REST surface.
        Skipped rows (already reversed, window closed, non-MERGE) are
        counted and surfaced as a warning rather than aborting the
        batch — same pattern as GRM S4-005 and UPD S5-001 admin
        actions."""
        actor = (getattr(request.user, "username", "") or "admin-bot")
        reason = "admin bulk reverse (no detail captured)"
        reversed_count = 0
        skipped = 0
        for decision in queryset:
            if decision.action != MergeAction.MERGE:
                skipped += 1
                continue
            try:
                reverse_merge_decision(decision, actor=actor, reason=reason)
                reversed_count += 1
            except MergeError:
                skipped += 1
        self.message_user(
            request,
            f"Reversed {reversed_count} decision(s); {skipped} skipped "
            "(non-MERGE, already reversed, or window closed).",
            level=messages.SUCCESS if reversed_count else messages.WARNING,
        )
