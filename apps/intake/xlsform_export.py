"""US-118 — XLSForm export from FormVersion.

Walks the authored questionnaire (FormVersion → FormSection →
FormQuestion + ChoiceList catalogue) and emits a Kobo-compatible
XLSForm as raw .xlsx bytes. The export is round-trip-compatible
with `scripts/import_legacy_questionnaire.py` — re-importing the
exported xlsx into a fresh FormVersion produces the same shape
modulo the FormVersion id.

Three sheets per the XLSForm spec (https://xlsform.org):

- `survey`   — one row per question, plus begin_group/end_group
              (and begin_repeat/end_repeat) markers reconstructed
              from FormSection ordering + FormQuestion type values.
- `choices`  — one row per (ChoiceList, ChoiceOption) referenced
              by any select_one / select_multiple question in the
              survey sheet. Lists that aren't referenced are
              omitted by design — keeps the xlsx small.
- `settings` — form_title / form_id / version / default_language /
              style. Pulled from FormVersion fields.

Pure-Python (openpyxl). No file system writes; caller is
responsible for streaming the returned bytes wherever they need
to go (admin download, MinIO upload, etc.).
"""

from __future__ import annotations

import io

from openpyxl import Workbook

from .models import FormQuestion, FormSection, FormVersion

# XLSForm column orders — locked to the order the spec uses so a
# round-trip with off-the-shelf XLSForm tools doesn't shuffle
# columns.
SURVEY_COLS = (
    "type", "name", "label", "hint", "required", "relevant",
    "constraint", "constraint_message", "appearance",
    "choice_filter", "calculation", "repeat_count", "parameters",
)
CHOICES_COLS = ("list_name", "name", "label")
SETTINGS_COLS = (
    "form_title", "form_id", "version", "default_language", "style",
)


def _question_row(q: FormQuestion) -> dict:
    """Project a FormQuestion to its XLSForm survey row. select_one /
    select_multiple types embed the ChoiceList name back into the
    `type` cell — same packing the legacy script uses."""
    qtype = q.type
    if qtype in ("select_one", "select_multiple") and q.choice_list_ref:
        qtype = f"{q.type} {q.choice_list_ref.list_name}"
    return {
        "type": qtype,
        "name": q.name,
        "label": q.label,
        "hint": q.hint,
        "required": "yes" if q.required else "",
        "relevant": q.relevant_expression,
        "constraint": q.constraint_expression,
        "constraint_message": q.constraint_message,
        "appearance": q.appearance,
        "choice_filter": "",
        "calculation": "",
        "repeat_count": q.repeat_count,
        "parameters": (q.parameters.get("_") if isinstance(q.parameters, dict) else "") or "",
    }


def _section_open_row(s: FormSection) -> dict:
    """begin_group / begin_repeat for the section opener. We use
    begin_group by default; the legacy script's `household_members`
    section is a begin_repeat — detected by the structural
    questions inside it that share the same name pattern. For
    simplicity, sections export as begin_group; the per-section
    structural questions (which include begin_repeat) ride along
    inside via FormQuestion.type."""
    return {
        "type": "begin_group",
        "name": s.name,
        "label": s.label,
        "hint": "", "required": "",
        "relevant": "", "constraint": "",
        "constraint_message": "", "appearance": "",
        "choice_filter": "", "calculation": "",
        "repeat_count": "", "parameters": "",
    }


def _section_close_row(s: FormSection) -> dict:
    return {
        "type": "end_group",
        "name": s.name,
        "label": "", "hint": "", "required": "",
        "relevant": "", "constraint": "",
        "constraint_message": "", "appearance": "",
        "choice_filter": "", "calculation": "",
        "repeat_count": "", "parameters": "",
    }


def export_to_xlsx(form_version: FormVersion) -> bytes:
    """Render `form_version` as a Kobo-compatible XLSForm. Returns
    raw .xlsx bytes — caller streams them as needed."""
    wb = Workbook()
    # Default sheet → rename to survey to avoid leftover blank sheets.
    ws_survey = wb.active
    ws_survey.title = "survey"
    ws_choices = wb.create_sheet("choices")
    ws_settings = wb.create_sheet("settings")

    # ── survey sheet ────────────────────────────────────────────
    ws_survey.append(SURVEY_COLS)
    sections = list(
        form_version.sections.prefetch_related("questions__choice_list_ref")
        .order_by("order", "code"),
    )
    referenced_choice_lists: set[str] = set()
    for sec in sections:
        ws_survey.append([_section_open_row(sec).get(c, "") for c in SURVEY_COLS])
        for q in sec.questions.order_by("order_in_section", "name"):
            row = _question_row(q)
            ws_survey.append([row.get(c, "") for c in SURVEY_COLS])
            if q.choice_list_ref is not None:
                referenced_choice_lists.add(q.choice_list_ref.list_name)
        ws_survey.append([_section_close_row(sec).get(c, "") for c in SURVEY_COLS])

    # ── choices sheet ──────────────────────────────────────────
    # Only emit lists actually referenced — keeps the xlsx small.
    # Each ChoiceList is the v1 row (matches what the legacy script
    # produced); ChoiceOption rows are sorted by sort_order.
    ws_choices.append(CHOICES_COLS)
    if referenced_choice_lists:
        from apps.reference_data.models import ChoiceList
        for cl in ChoiceList.objects.filter(
            list_name__in=referenced_choice_lists, version=1,
        ).order_by("list_name"):
            for opt in cl.options.filter(status="active").order_by("sort_order", "code"):
                ws_choices.append([cl.list_name, opt.code, opt.label])

    # ── settings sheet ─────────────────────────────────────────
    ws_settings.append(SETTINGS_COLS)
    ws_settings.append([
        form_version.name,
        f"nsr_v{form_version.version}",
        str(form_version.version),
        "en",
        "pages",  # Kobo-friendly multi-page rendering
    ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
