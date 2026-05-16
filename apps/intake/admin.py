from django.contrib import admin

from .models import (
    FormConstraint,
    FormQuestion,
    FormSection,
    FormSkipLogic,
    FormVersion,
    Submission,
)

# --- US-117a admin -------------------------------------------------------
#
# Three-level nesting (FormVersion → FormSection → FormQuestion) is
# clunky in stock Django admin inlines (no two-level nesting). For
# US-117a we give each model its own changelist + per-question
# inline editors for skip-logic and constraints. The richer
# tree-view UI lands in US-117b (custom template, drag-to-reorder,
# inline expression preview).


class FormSkipLogicInline(admin.TabularInline):
    model = FormSkipLogic
    extra = 0
    fields = ("dsl", "description")


class FormConstraintInline(admin.TabularInline):
    model = FormConstraint
    extra = 0
    fields = ("dsl", "message", "description")


class FormQuestionInline(admin.TabularInline):
    """Read-only inline of questions on the section admin — gives
    the operator a quick at-a-glance view without leaving the
    section page. Full editing happens on the FormQuestion admin."""

    model = FormQuestion
    extra = 0
    fields = ("order_in_section", "name", "type", "required",
              "choice_list_ref", "label")
    readonly_fields = fields
    show_change_link = True
    can_delete = False
    ordering = ("order_in_section", "name")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FormVersion)
class FormVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "name", "status", "is_active",
                    "section_count", "question_count",
                    "author", "approved_by", "effective_from")
    list_filter = ("status", "is_active")
    search_fields = ("name", "description", "author", "approved_by")
    readonly_fields = ("id", "created_at", "updated_at", "approved_at",
                       "submitted_at", "approval_note", "rejection_reason",
                       "section_count", "question_count")
    fieldsets = (
        (None, {"fields": ("id", "version", "name", "description", "status",
                           "is_active")}),
        ("Lifecycle", {"fields": ("effective_from", "effective_to",
                                   "author", "approved_by", "approved_at",
                                   "submitted_at", "approval_note",
                                   "rejection_reason",
                                   "created_at", "updated_at")}),
        ("Counts", {"fields": ("section_count", "question_count")}),
    )

    def get_queryset(self, request):
        from django.db.models import Count
        return (super().get_queryset(request)
                .annotate(
                    _section_count=Count("sections", distinct=True),
                    _question_count=Count("sections__questions", distinct=True),
                ))

    @admin.display(description="Sections", ordering="_section_count")
    def section_count(self, obj):
        return getattr(obj, "_section_count", obj.sections.count())

    @admin.display(description="Questions", ordering="_question_count")
    def question_count(self, obj):
        return getattr(obj, "_question_count", 0)


@admin.register(FormSection)
class FormSectionAdmin(admin.ModelAdmin):
    list_display = ("form_version", "order", "code", "name", "label",
                    "question_count")
    list_filter = ("form_version",)
    search_fields = ("code", "name", "label")
    raw_id_fields = ("form_version",)
    ordering = ("form_version", "order", "code")
    inlines = [FormQuestionInline]

    def get_queryset(self, request):
        from django.db.models import Count
        return (super().get_queryset(request)
                .annotate(_question_count=Count("questions")))

    @admin.display(description="Questions", ordering="_question_count")
    def question_count(self, obj):
        return getattr(obj, "_question_count", obj.questions.count())


@admin.register(FormQuestion)
class FormQuestionAdmin(admin.ModelAdmin):
    list_display = ("section", "order_in_section", "name", "type",
                    "required", "choice_list_ref", "label_short")
    list_filter = ("type", "required", "section__form_version",
                   "section__code")
    search_fields = ("name", "label", "hint")
    raw_id_fields = ("section", "choice_list_ref")
    ordering = ("section", "order_in_section", "name")
    inlines = [FormSkipLogicInline, FormConstraintInline]

    @admin.display(description="Label")
    def label_short(self, obj):
        label = obj.label or ""
        return label if len(label) <= 60 else label[:57] + "…"


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "enumerator", "result", "state",
                    "stage_record_id", "provisional_registry_id")
    list_filter = ("channel", "state", "result")
    search_fields = ("id", "enumerator", "supervisor",
                     "stage_record_id", "provisional_registry_id")
    raw_id_fields = ("form_version",)
    readonly_fields = ("id", "stage_record_id", "provisional_registry_id",
                       "created_at", "updated_at")
    date_hierarchy = "created_at"
