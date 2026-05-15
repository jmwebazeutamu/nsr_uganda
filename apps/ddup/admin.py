from django.contrib import admin, messages
from django.utils.html import format_html, format_html_join

from .models import DdupModelVersion, MatchPair, MergeAction, MergeDecision
from .services import (
    AUTO_REVERSE_RATE_CEILING,
    SAFE_DEFAULT_THRESHOLD,
    THRESHOLD_NUDGE_STEP,
    DdupApprovalError,
    MergeError,
    clone_with_threshold_delta,
    reverse_merge_decision,
)


def _score_colour(v: float) -> str:
    """Match the corridor signal — green ≥0.9, amber 0.5-0.9, red <0.5
    — so reviewers see at a glance which fields drove a tier-3 match."""
    return "#198754" if v >= 0.9 else "#b87410" if v >= 0.5 else "#a93226"


@admin.register(DdupModelVersion)
class DdupModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "status", "author", "approved_by",
                    "effective_from", "merge_summary", "updated_at")
    list_filter = ("status",)
    actions = (
        "nudge_threshold_up", "nudge_threshold_down", "set_safe_default",
    )
    readonly_fields = (
        "id", "created_at", "updated_at", "approved_at",
        "auto_merge_count", "manual_merge_count",
        "auto_reverse_count", "manual_reverse_count",
        "auto_reverse_rate_display",
    )
    search_fields = ("description", "author", "approved_by")
    fieldsets = (
        (None, {"fields": ("id", "version", "description", "status",
                            "author", "approved_by", "approved_at",
                            "effective_from")}),
        ("Configuration", {"fields": ("config",)}),
        ("Feedback (US-S10-002)", {
            "description": (
                "Computed live from MergeDecision joins. A rising "
                "auto-reverse rate means the auto-merge threshold is "
                "too low for this model version — operators tune "
                "config['tier3']['auto_merge_threshold'] upward."
            ),
            "fields": ("auto_merge_count", "manual_merge_count",
                        "auto_reverse_count", "manual_reverse_count",
                        "auto_reverse_rate_display"),
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Merges (auto / manual)")
    def merge_summary(self, obj: DdupModelVersion) -> str:
        """Compact list_display column — auto/manual counts + reverse
        rate if any auto-merges have happened. A red 'TUNE UP' badge
        appears when the rate exceeds the policy ceiling (US-S11-005),
        cueing operators to run the threshold-tuning action."""
        a = obj.auto_merge_count
        m = obj.manual_merge_count
        rate = obj.auto_reverse_rate
        if rate is None:
            return f"{a} auto / {m} manual"
        base = f"{a} auto ({rate:.1%} reversed) / {m} manual"
        if rate > AUTO_REVERSE_RATE_CEILING:
            return format_html(
                "{} <span style='background:#b00;color:white;padding:1px 6px;"
                "border-radius:3px;font-size:11px;font-weight:600;margin-left:6px;"
                "letter-spacing:0.04em'>TUNE UP</span>",
                base,
            )
        return base

    @admin.display(description="Auto-reverse rate")
    def auto_reverse_rate_display(self, obj: DdupModelVersion) -> str:
        """Human-readable variant for the form view — leans on the
        DPO calibration story rather than the raw decimal. Over-
        ceiling rows get a recommended-action hint (US-S11-005)."""
        rate = obj.auto_reverse_rate
        if rate is None:
            return "(no auto-merges yet for this version)"
        base = f"{rate:.1%} ({obj.auto_reverse_count} of {obj.auto_merge_count})"
        if rate > AUTO_REVERSE_RATE_CEILING:
            return format_html(
                "{} — <strong style='color:#b00'>over {:.0%} ceiling.</strong> "
                "Recommended: run 'Nudge auto_merge_threshold +{:.2f}' "
                "from the action menu to mint a calibrated draft.",
                base, AUTO_REVERSE_RATE_CEILING, THRESHOLD_NUDGE_STEP,
            )
        return base

    # --- Calibration actions (US-S11-005) -------------------------------

    def _clone_and_report(
        self, request, queryset, *, delta: float, reason: str,
    ) -> None:
        """Shared body for the three calibration actions. Creates one
        DRAFT clone per selected row. Skipped rows (already at
        boundary) are reported as warnings — same pattern as the
        admin_reverse_merge action below."""
        actor = (getattr(request.user, "username", "") or "admin-bot")
        drafted = []
        skipped = []
        for source in queryset:
            try:
                draft = clone_with_threshold_delta(
                    source, delta=delta, actor=actor, reason=reason,
                )
                drafted.append(f"v{source.version} -> v{draft.version}")
            except DdupApprovalError as exc:
                skipped.append(f"v{source.version} ({exc})")
        if drafted:
            self.message_user(
                request,
                f"Calibration draft(s) created: {', '.join(drafted)}. "
                f"Activate via the standard dual-approval workflow.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped: {'; '.join(skipped)}",
                level=messages.WARNING,
            )

    @admin.action(description=f"Nudge auto_merge_threshold +{THRESHOLD_NUDGE_STEP:.2f}")
    def nudge_threshold_up(self, request, queryset):
        """Tighter threshold — fewer auto-merges. Use when
        auto_reverse_rate is over ceiling."""
        self._clone_and_report(
            request, queryset, delta=THRESHOLD_NUDGE_STEP,
            reason="Admin nudge: auto_reverse_rate over ceiling",
        )

    @admin.action(description=f"Nudge auto_merge_threshold -{THRESHOLD_NUDGE_STEP:.2f}")
    def nudge_threshold_down(self, request, queryset):
        """Looser threshold — more auto-merges. Use when too many
        true-positive pairs are landing in the manual queue."""
        self._clone_and_report(
            request, queryset, delta=-THRESHOLD_NUDGE_STEP,
            reason="Admin nudge: manual-queue backlog over policy",
        )

    @admin.action(description=f"Set auto_merge_threshold to safe default ({SAFE_DEFAULT_THRESHOLD:.2f})")
    def set_safe_default(self, request, queryset):
        """Reset to the policy-default threshold. Useful when an
        experimental setting needs walking back."""
        actor = (getattr(request.user, "username", "") or "admin-bot")
        drafted = []
        skipped = []
        for source in queryset:
            current = float(
                (source.config or {}).get("tier3", {})
                                     .get("auto_merge_threshold", SAFE_DEFAULT_THRESHOLD),
            )
            delta = SAFE_DEFAULT_THRESHOLD - current
            if delta == 0:
                skipped.append(f"v{source.version} (already at safe default)")
                continue
            try:
                draft = clone_with_threshold_delta(
                    source, delta=delta, actor=actor,
                    reason="Admin: reset to safe default threshold",
                )
                drafted.append(f"v{source.version} -> v{draft.version}")
            except DdupApprovalError as exc:
                skipped.append(f"v{source.version} ({exc})")
        if drafted:
            self.message_user(
                request,
                f"Safe-default draft(s) created: {', '.join(drafted)}.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped: {'; '.join(skipped)}",
                level=messages.WARNING,
            )


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
