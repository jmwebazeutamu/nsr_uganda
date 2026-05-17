import json

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.http import require_POST

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

    # US-117b — custom change form with the section/question tree
    # on the left and the standard admin edit form on the right.
    # Gated by settings.QUESTIONNAIRE_EDITOR_V2 — when off, the
    # template's {% if %} falls back to the default admin form so
    # ops can disable the new UI without a deploy.
    change_form_template = "admin/intake/formversion/change_form.html"

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["questionnaire_editor_v2"] = getattr(
            settings, "QUESTIONNAIRE_EDITOR_V2", False,
        )
        if object_id:
            fv = FormVersion.objects.filter(pk=object_id).first()
            if fv:
                # Pre-fetch the section/question tree the template
                # renders on the left. Single-query traversal — even
                # a 10-section / 200-question form is one round-trip.
                sections = list(
                    fv.sections.prefetch_related("questions").order_by("order", "code"),
                )
                tree = []
                for sec in sections:
                    tree.append({
                        "id": sec.id,
                        "code": sec.code,
                        "label": sec.label,
                        "order": sec.order,
                        "questions": [
                            {
                                "id": q.id, "name": q.name, "type": q.type,
                                "label": q.label, "required": q.required,
                                "order": q.order_in_section,
                            }
                            for q in sec.questions.all().order_by("order_in_section", "name")
                        ],
                    })
                extra_context["dqa_form_tree"] = tree
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        urls = super().get_urls()
        # US-117b reorder + validate endpoints. Live under
        # /admin/intake/formversion/_us117b/ so they're admin-gated
        # automatically by AdminSite.has_permission().
        extra = [
            path(
                "_us117b/reorder-section/<str:section_id>/",
                self.admin_site.admin_view(_reorder_section_view),
                name="intake_us117b_reorder_section",
            ),
            path(
                "_us117b/reorder-question/<str:question_id>/",
                self.admin_site.admin_view(_reorder_question_view),
                name="intake_us117b_reorder_question",
            ),
            path(
                "_us117b/validate-expression/",
                self.admin_site.admin_view(_validate_expression_view),
                name="intake_us117b_validate_expression",
            ),
            # US-118 — XLSForm download. GET because it's a pure
            # read; admin gating comes from admin_site.admin_view.
            path(
                "_us118/export-xlsform/<str:form_version_id>/",
                self.admin_site.admin_view(_export_xlsform_view),
                name="intake_us118_export_xlsform",
            ),
            # US-117d — in-admin HTML preview (the "what does this
            # look like to a respondent" view, NOT the editor).
            path(
                "_us117b/preview/<str:form_version_id>/",
                self.admin_site.admin_view(_preview_form_view),
                name="intake_us117b_preview_form",
            ),
            # US-117e — interactive in-admin preview. Skip-logic
            # fires, constraints validate, repeats (rosters) support
            # add/remove. Backed by a single-page React harness
            # (Babel-standalone) that reads the FormVersion schema
            # embedded in the page.
            path(
                "_us117e/preview/<str:form_version_id>/",
                self.admin_site.admin_view(_interactive_preview_view),
                name="intake_us117e_interactive_preview",
            ),
            path(
                "_us117e/schema/<str:form_version_id>/",
                self.admin_site.admin_view(_interactive_schema_view),
                name="intake_us117e_schema",
            ),
        ]
        return extra + urls

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


# --- US-117b reorder + validate views ---------------------------------------

@require_POST
def _reorder_section_view(request, section_id):
    """Move a section up or down within its FormVersion. Body:
    {"direction": "up" | "down"}. Returns the new order map.

    Swaps with the adjacent section by `order`. Doesn't try to be
    clever about gaps — re-sequences the affected pair only so the
    rest of the tree stays stable on concurrent edits.
    """
    direction = json.loads(request.body or b"{}").get("direction")
    if direction not in ("up", "down"):
        return JsonResponse({"detail": "direction must be 'up' or 'down'"}, status=400)
    section = FormSection.objects.filter(pk=section_id).first()
    if not section:
        return JsonResponse({"detail": "section not found"}, status=404)
    qs = section.form_version.sections.order_by("order", "code")
    siblings = list(qs)
    idx = next((i for i, s in enumerate(siblings) if s.id == section.id), None)
    if idx is None:
        return JsonResponse({"detail": "section not in form version"}, status=404)
    other_idx = idx - 1 if direction == "up" else idx + 1
    if other_idx < 0 or other_idx >= len(siblings):
        return JsonResponse({"detail": "already at boundary", "moved": False})
    other = siblings[other_idx]
    section.order, other.order = other.order, section.order
    # If they were both 0 (default), pick deterministic new orders.
    if section.order == other.order:
        section.order = other_idx + 1
        other.order = idx + 1
    section.save(update_fields=["order"])
    other.save(update_fields=["order"])
    return JsonResponse({
        "moved": True,
        "order": {
            section.id: section.order,
            other.id: other.order,
        },
    })


@require_POST
def _reorder_question_view(request, question_id):
    """Move a question up or down within its FormSection. Same
    contract as _reorder_section_view; operates on order_in_section."""
    direction = json.loads(request.body or b"{}").get("direction")
    if direction not in ("up", "down"):
        return JsonResponse({"detail": "direction must be 'up' or 'down'"}, status=400)
    question = FormQuestion.objects.filter(pk=question_id).first()
    if not question:
        return JsonResponse({"detail": "question not found"}, status=404)
    siblings = list(
        question.section.questions.order_by("order_in_section", "name"),
    )
    idx = next((i for i, q in enumerate(siblings) if q.id == question.id), None)
    if idx is None:
        return JsonResponse({"detail": "question not in section"}, status=404)
    other_idx = idx - 1 if direction == "up" else idx + 1
    if other_idx < 0 or other_idx >= len(siblings):
        return JsonResponse({"detail": "already at boundary", "moved": False})
    other = siblings[other_idx]
    question.order_in_section, other.order_in_section = (
        other.order_in_section, question.order_in_section,
    )
    if question.order_in_section == other.order_in_section:
        question.order_in_section = other_idx + 1
        other.order_in_section = idx + 1
    question.save(update_fields=["order_in_section"])
    other.save(update_fields=["order_in_section"])
    return JsonResponse({
        "moved": True,
        "order": {
            question.id: question.order_in_section,
            other.id: other.order_in_section,
        },
    })


@require_POST
def _validate_expression_view(request):
    """Run a JSON-DSL expression through apps.dqa.engine to surface
    structural errors at authoring time. Body:
    {"expression": {...}, "sample_record": {...}}.

    Returns {"ok": true, "result": bool} on success or
    {"ok": false, "error": "<DSLError message>"} on failure.
    Doesn't persist anything — pure preview.
    """
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid JSON body"}, status=400)
    expr = body.get("expression")
    if not isinstance(expr, dict):
        return JsonResponse({"ok": False, "error": "expression must be an object"}, status=400)
    sample = body.get("sample_record") or {}
    try:
        from apps.dqa.engine import evaluate_expression
        result = evaluate_expression(expr, sample)
    except Exception as exc:
        # DSLError or anything else collapses to a clean error
        # message — the engine's exceptions are the validation
        # signal.
        msg = str(exc) or exc.__class__.__name__
        return JsonResponse({"ok": False, "error": msg})
    return JsonResponse({"ok": True, "result": bool(result)})


# --- US-117d / US-118 — shared FormVersion resolver ------------------------

def _resolve_form_version(form_version_id: str, *, prefetch: tuple = ()):
    """Look up a FormVersion by ULID (the primary key) OR by version
    number when the path arg is all digits. Lets `/preview/1/` and
    `/preview/01KRRW…/` both resolve to FormVersion v1, which is the
    discoverable URL an operator types when they look at the
    changelist and see "v1".

    Returns the FormVersion row or None.
    """
    qs = FormVersion.objects.all()
    for prefetch_path in prefetch:
        qs = qs.prefetch_related(prefetch_path)
    fv = qs.filter(pk=form_version_id).first()
    if fv is None and form_version_id.isdigit():
        fv = qs.filter(version=int(form_version_id)).first()
    return fv


# --- US-118 XLSForm download -----------------------------------------------

def _export_xlsform_view(request, form_version_id):
    """Stream the FormVersion as a Kobo-compatible XLSForm xlsx.

    Calls apps.intake.xlsform_export.export_to_xlsx and serves the
    bytes with the spreadsheetml MIME + an attachment filename
    derived from the form's name + version.
    """
    from django.http import Http404, HttpResponse

    from .xlsform_export import export_to_xlsx
    fv = _resolve_form_version(form_version_id)
    if fv is None:
        raise Http404("FormVersion not found")
    payload = export_to_xlsx(fv)
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"nsr_form_v{fv.version}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --- US-117d in-admin HTML preview -----------------------------------------

def _preview_form_view(request, form_version_id):
    """Render the FormVersion as HTML — sections as cards, questions
    as disabled form-controls with hints + required markers + an
    annotation strip showing the relevant/constraint expressions.

    The goal is "what does this questionnaire look like to a
    respondent" — NOT the editor view (which lives at the standard
    /change/ URL). Inputs are disabled so an admin doesn't think
    submissions land in the registry."""
    from django.http import Http404
    from django.shortcuts import render

    fv = _resolve_form_version(
        form_version_id,
        prefetch=("sections__questions__choice_list_ref__options",),
    )
    if fv is None:
        raise Http404("FormVersion not found")

    sections = []
    for section in fv.sections.order_by("order", "code"):
        questions = []
        for q in section.questions.order_by("order_in_section", "name"):
            options = []
            if q.choice_list_ref is not None:
                options = list(
                    q.choice_list_ref.options.filter(status="active")
                    .order_by("sort_order", "code")
                    .values("code", "label"),
                )
            questions.append({
                "id": q.id, "name": q.name, "label": q.label,
                "hint": q.hint, "type": q.type, "required": q.required,
                "relevant": q.relevant_expression,
                "constraint": q.constraint_expression,
                "constraint_message": q.constraint_message,
                "appearance": q.appearance,
                "repeat_count": q.repeat_count,
                "options": options,
                "choice_list_name": (
                    q.choice_list_ref.list_name if q.choice_list_ref else ""
                ),
            })
        sections.append({
            "id": section.id, "code": section.code, "name": section.name,
            "label": section.label, "description": section.description,
            "questions": questions,
        })

    return render(request, "admin/intake/formversion/preview.html", {
        "form_version": fv,
        "sections": sections,
        "question_count": sum(len(s["questions"]) for s in sections),
        # admin context bits so the template can fall back to the
        # standard chrome.
        "site_header": "Django administration",
        "site_title": "Django site admin",
        "has_permission": True,
        "is_popup": False,
        "is_nav_sidebar_enabled": True,
        "available_apps": [],
    })


# --- US-117e interactive preview -------------------------------------------

def _build_form_schema(fv) -> dict:
    """Project a FormVersion into a JSON schema the interactive
    preview can hydrate from. Includes section repeat_count, all
    question attributes, and inline ChoiceList options so the
    React harness doesn't need a second round-trip per select."""
    sections = []
    for section in fv.sections.order_by("order", "code"):
        questions = []
        for q in section.questions.order_by("order_in_section", "name"):
            options = []
            if q.choice_list_ref is not None:
                options = [
                    {"code": opt.code, "label": opt.label}
                    for opt in q.choice_list_ref.options.filter(status="active")
                    .order_by("sort_order", "code")
                ]
            questions.append({
                "id": q.id, "name": q.name, "label": q.label,
                "hint": q.hint, "type": q.type, "required": q.required,
                "relevant": q.relevant_expression,
                "constraint": q.constraint_expression,
                "constraint_message": q.constraint_message,
                "appearance": q.appearance,
                "repeat_count": q.repeat_count,
                "options": options,
                "choice_list_name": (
                    q.choice_list_ref.list_name if q.choice_list_ref else ""
                ),
            })
        sections.append({
            "id": section.id, "code": section.code, "name": section.name,
            "label": section.label, "description": section.description,
            "repeat_count": section.repeat_count,
            "questions": questions,
        })
    return {
        "form_version_id": fv.id,
        "name": fv.name,
        "version": fv.version,
        "status": fv.status,
        "sections": sections,
    }


def _interactive_schema_view(request, form_version_id):
    """Return the FormVersion schema as JSON. Used by the US-117e
    React harness via fetch on the page, and useful for contract
    tests that pin the schema shape independent of the renderer."""
    from django.http import Http404, JsonResponse

    fv = _resolve_form_version(
        form_version_id,
        prefetch=("sections__questions__choice_list_ref__options",),
    )
    if fv is None:
        raise Http404("FormVersion not found")
    return JsonResponse(_build_form_schema(fv))


def _interactive_preview_view(request, form_version_id):
    """Render the interactive in-admin preview. The template embeds
    the FormVersion schema as a json_script tag and hydrates a React
    + Babel-standalone harness that evaluates skip-logic, runs
    constraints, and supports adding/removing repeat-section
    instances (roster management)."""
    from django.http import Http404
    from django.shortcuts import render

    fv = _resolve_form_version(
        form_version_id,
        prefetch=("sections__questions__choice_list_ref__options",),
    )
    if fv is None:
        raise Http404("FormVersion not found")
    schema = _build_form_schema(fv)
    return render(request, "admin/intake/formversion/preview_interactive.html", {
        "form_version": fv,
        "schema": schema,
        "section_count": len(schema["sections"]),
        "question_count": sum(len(s["questions"]) for s in schema["sections"]),
        "site_header": "Django administration",
        "site_title": "Django site admin",
        "has_permission": True,
        "is_popup": False,
        "is_nav_sidebar_enabled": True,
        "available_apps": [],
    })


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
