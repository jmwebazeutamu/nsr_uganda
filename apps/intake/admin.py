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


# US-S20-005 — once a FormVersion is ACTIVE or RETIRED its shape is
# load-bearing for past Submissions and cannot drift. The admin locks
# all non-status fields in those states; operators amend by cloning
# to a new DRAFT version.
_LOCKED_FV_STATUSES = ("active", "retired")


def _form_version_is_locked(obj) -> bool:
    """Walk up from FormSection / FormQuestion / constraint inlines to
    the owning FormVersion; True if that FormVersion is in a status
    that forbids in-place edits."""
    if obj is None:
        return False
    fv = None
    if isinstance(obj, FormVersion):
        fv = obj
    elif hasattr(obj, "form_version_id"):
        fv = obj.form_version
    elif hasattr(obj, "section_id"):
        fv = obj.section.form_version
    elif hasattr(obj, "question_id"):
        fv = obj.question.section.form_version
    return fv is not None and fv.status in _LOCKED_FV_STATUSES


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

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj and obj.status in _LOCKED_FV_STATUSES:
            # Lock every non-readonly field except `status` itself —
            # an admin retiring an ACTIVE form, or reactivating a
            # RETIRED one, transitions via status and that needs to
            # stay editable.
            editable = {"status"}
            for f in self.model._meta.fields:
                if f.name not in base and f.name not in editable:
                    base.append(f.name)
        return base

    def has_delete_permission(self, request, obj=None):
        # Locked FormVersions are immutable history — never delete.
        if obj and obj.status in _LOCKED_FV_STATUSES:
            return False
        return super().has_delete_permission(request, obj)
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
            # US-119b — atomic approve + DAT-DQA rule-pack sync.
            path(
                "_us119b/approve/<str:form_version_id>/",
                self.admin_site.admin_view(_approve_form_version_view),
                name="intake_us119b_approve",
            ),
            # US-S20-004 — push xlsx to Kobo (with deploy).
            path(
                "_uskobo/push/<str:form_version_id>/",
                self.admin_site.admin_view(_kobo_push_view),
                name="intake_uskobo_push",
            ),
            # US-S20-005 — clone an existing FormVersion to a fresh draft.
            path(
                "_us-clone/<str:form_version_id>/",
                self.admin_site.admin_view(_clone_form_version_view),
                name="intake_us_clone_form_version",
            ),
            # US-S20-001 — PII lint scan over the whole authored form.
            path(
                "_us-pii-lint/<str:form_version_id>/",
                self.admin_site.admin_view(_pii_lint_view),
                name="intake_us_pii_lint",
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
    # Lazy-load geo options keyed by level; only fetched when at
    # least one geo question is in the form.
    from .geo import GEO_QUESTIONS, geo_options_for
    geo_cache: dict = {}

    def _options_for_geo(q_name):
        level, parent_q = GEO_QUESTIONS[q_name]
        if level not in geo_cache:
            geo_cache[level] = geo_options_for(level)
        return geo_cache[level], parent_q

    sections = []
    for section in fv.sections.order_by("order", "code"):
        questions = []
        for q in section.questions.order_by("order_in_section", "name"):
            options = []
            parent_question = ""
            choice_list_name = ""
            if q.name in GEO_QUESTIONS:
                options, parent_q = _options_for_geo(q.name)
                parent_question = parent_q or ""
                choice_list_name = GEO_QUESTIONS[q.name][0]
            elif q.choice_list_ref is not None:
                options = [
                    {"code": opt.code, "label": opt.label}
                    for opt in q.choice_list_ref.options.filter(status="active")
                    .order_by("sort_order", "code")
                ]
                choice_list_name = q.choice_list_ref.list_name
            questions.append({
                "id": q.id, "name": q.name, "label": q.label,
                "hint": q.hint, "type": q.type, "required": q.required,
                "relevant": q.relevant_expression,
                "constraint": q.constraint_expression,
                "constraint_message": q.constraint_message,
                "appearance": q.appearance,
                "repeat_count": q.repeat_count,
                "options": options,
                "choice_list_name": choice_list_name,
                "parent_question": parent_question,
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


# --- US-S20-004 — Kobo publish --------------------------------------------

@require_POST
def _kobo_push_view(request, form_version_id):
    """Build the FormVersion's xlsx and push it to Kobo. POST-only;
    redirects back to the changeform with a messages banner."""
    from django.contrib import messages
    from django.http import HttpResponseRedirect
    from django.urls import reverse
    from requests.exceptions import RequestException

    from .kobo_push import (
        KoboPushError,
        KoboPushUnavailable,
        publish_form_version,
    )
    fv = _resolve_form_version(form_version_id)
    target = reverse("admin:intake_formversion_change", args=[fv.id]) if fv else \
             reverse("admin:intake_formversion_changelist")
    if fv is None:
        messages.error(request, "FormVersion not found.")
        return HttpResponseRedirect(target)
    actor = request.user.username or "admin"
    try:
        report = publish_form_version(fv, actor=actor)
    except KoboPushUnavailable as exc:
        messages.warning(
            request,
            f"Kobo not configured — {exc}. Add a KoboCredential under "
            "Ingestion hub → SourceSystems first.",
        )
        return HttpResponseRedirect(target)
    except KoboPushError as exc:
        messages.error(request, f"Kobo push refused: {exc}")
        return HttpResponseRedirect(target)
    except RequestException as exc:
        messages.error(request, f"Kobo upstream error: {exc}")
        return HttpResponseRedirect(target)
    status = report.get("status", "?")
    if status == "complete":
        messages.success(
            request,
            f"Published v{report['version']} to Kobo "
            f"(asset {report['asset_uid']}, "
            f"{'deployed' if report.get('deployed') else 'not deployed'}).",
        )
    else:
        messages.warning(
            request,
            f"Kobo import status={status} — asset_uid={report.get('asset_uid') or '(none)'}. "
            "Check Kobo's import log.",
        )
    return HttpResponseRedirect(target)


# --- US-S20-001 — PII lint scan --------------------------------------------

@require_POST
def _pii_lint_view(request, form_version_id):
    """Run the constraint-message PII lint over a whole FormVersion
    and surface violations as admin messages. Redirects back to the
    changeform with one warning per violation (capped) or a single
    success message when clean."""
    from django.contrib import messages
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    from .pii_lint import lint_form_version
    fv = _resolve_form_version(form_version_id)
    target = reverse("admin:intake_formversion_change", args=[fv.id]) if fv else \
             reverse("admin:intake_formversion_changelist")
    if fv is None:
        messages.error(request, "FormVersion not found.")
        return HttpResponseRedirect(target)
    report = lint_form_version(fv)
    violations = report["violations"]
    if not violations:
        messages.success(
            request,
            f"PII lint: clean — scanned {report['questions_scanned']} questions.",
        )
        return HttpResponseRedirect(target)
    # Cap shown violations so a noisy form doesn't drown the admin
    # message stack. The summary line carries the total.
    shown = 0
    cap = 25
    for entry in violations:
        for item in entry["items"]:
            if shown >= cap:
                break
            messages.warning(
                request,
                f"{entry['section']}/{entry['question']}: `{item['matched']}` "
                f"({item['rule']} in {item['where']})",
            )
            shown += 1
        if shown >= cap:
            break
    total_items = sum(len(e["items"]) for e in violations)
    messages.warning(
        request,
        f"PII lint: {total_items} violation(s) across "
        f"{len(violations)} question(s); {report['questions_scanned']} "
        f"questions scanned. Showing first {min(shown, cap)}.",
    )
    return HttpResponseRedirect(target)


# --- US-S20-005 — clone form version --------------------------------------

@require_POST
def _clone_form_version_view(request, form_version_id):
    """Clone an existing FormVersion into a new DRAFT version and
    redirect to its changeform. Lets operators amend an active form
    without mutating the system-of-record shape that past submissions
    depend on."""
    from django.contrib import messages
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    from .services import FormApprovalError, clone_form_version
    fv = _resolve_form_version(form_version_id)
    if fv is None:
        messages.error(request, "FormVersion not found.")
        return HttpResponseRedirect(
            reverse("admin:intake_formversion_changelist"),
        )
    try:
        new_fv = clone_form_version(
            fv, actor=request.user.username or "admin",
        )
    except FormApprovalError as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(
            reverse("admin:intake_formversion_change", args=[fv.id]),
        )
    messages.success(
        request,
        f"Cloned v{fv.version} → v{new_fv.version} (draft). "
        "Edit, then click Approve & sync when ready.",
    )
    return HttpResponseRedirect(
        reverse("admin:intake_formversion_change", args=[new_fv.id]),
    )


# --- US-119b approve + sync action -----------------------------------------

@require_POST
def _approve_form_version_view(request, form_version_id):
    """Move a FormVersion to ACTIVE and sync its rule pack to DAT-DQA
    in a single transaction. POST-only (state-changing); redirects to
    the changeform with a message banner reflecting the outcome."""
    from django.contrib import messages
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    from .services import FormApprovalError, approve_form_version
    fv = _resolve_form_version(form_version_id)
    target = reverse("admin:intake_formversion_change", args=[fv.id]) if fv else \
             reverse("admin:intake_formversion_changelist")
    if fv is None:
        messages.error(request, "FormVersion not found.")
        return HttpResponseRedirect(target)
    try:
        report = approve_form_version(fv, actor=request.user.username or "admin")
    except FormApprovalError as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(target)
    messages.success(
        request,
        f"FormVersion v{report['version']} approved — "
        f"{report['created']} rule(s) created, {report['updated']} updated "
        f"in DAT-DQA.",
    )
    return HttpResponseRedirect(target)


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


class _LockedByParentMixin:
    """Mixin for FormSection / FormQuestion admins (and their inlines).
    When the owning FormVersion is in a locked status, everything is
    readonly and add/delete are refused — operators are expected to
    clone the FormVersion to a fresh draft and edit the draft."""

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if _form_version_is_locked(obj):
            for f in self.model._meta.fields:
                if f.name not in base:
                    base.append(f.name)
        return base

    def has_delete_permission(self, request, obj=None):
        if _form_version_is_locked(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_add_permission(self, request, obj=None):
        if obj is not None and _form_version_is_locked(obj):
            return False
        # ModelAdmin.has_add_permission accepts only (request);
        # InlineModelAdmin accepts (request, obj=None). Branch so
        # the mixin works on either.
        if obj is None:
            return super().has_add_permission(request)
        return super().has_add_permission(request, obj)


@admin.register(FormSection)
class FormSectionAdmin(_LockedByParentMixin, admin.ModelAdmin):
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
class FormQuestionAdmin(_LockedByParentMixin, admin.ModelAdmin):
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

    def save_model(self, request, obj, form, change):
        """After save, run the PII lint over the question's text
        fields (label / hint / constraint_message) and surface any
        violations as admin warnings. Doesn't block save — the
        author may have a legitimate reason (e.g. a placeholder
        regex example) and we don't want to be paternalistic."""
        from django.contrib import messages

        from .pii_lint import lint_form_question
        super().save_model(request, obj, form, change)
        for v in lint_form_question(obj):
            messages.warning(
                request,
                f"PII-shape lint: `{v['matched']}` looks like a "
                f"{v['rule']} in {v['where']}. If that's a real "
                "value, replace it with a placeholder.",
            )


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
