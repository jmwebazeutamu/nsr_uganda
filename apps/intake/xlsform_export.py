"""US-118 — XLSForm export from FormVersion.

Walks the authored questionnaire (FormVersion → FormSection →
FormQuestion + ChoiceList catalogue) and emits a Kobo-compatible
XLSForm as raw .xlsx bytes. Output structure mirrors what
`k-forms/build_nsr_xlsform.py` produces — the legacy script is
the gold standard of Kobo-validity for this project.

Three sheets per the XLSForm spec (https://xlsform.org):

- `survey`   — top-level metadata rows (start/end/today/deviceid/
              username) auto-prepended, followed by one row per
              section opener + each question + section closer.
              Sections with `repeat_count` set are emitted as
              begin_repeat/end_repeat blocks (the household roster
              is the canonical case).
- `choices`  — one row per (ChoiceList, ChoiceOption) referenced
              by any select_one / select_multiple question in the
              survey sheet. Unreferenced lists are omitted to keep
              the xlsx small.
- `settings` — form_title / form_id / version / default_language /
              style. Matches the legacy Kobo-valid file:
              `English`, `theme-grid`, slugged form_id, YYYYMMDD
              version.

Pure-Python (openpyxl). No file system writes; caller is
responsible for streaming the returned bytes wherever they need
to go (admin download, MinIO upload, etc.).
"""

from __future__ import annotations

import io
import re

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

# Auto-prepended at the top of every export. Kobo's preview tolerates
# their absence but partner MIS tools sometimes don't — emitting them
# unconditionally keeps the output portable.
_METADATA_ROWS = (
    {"type": "start", "name": "start"},
    {"type": "end", "name": "end"},
    {"type": "today", "name": "today"},
    {"type": "deviceid", "name": "deviceid"},
    {"type": "username", "name": "username"},
)


def _slug(value: str) -> str:
    """Lowercase + underscore-only slug, suitable for form_id. Kobo
    accepts arbitrary strings but rejects ones with whitespace and
    odd punctuation — keep it conservative."""
    value = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value).strip("_") or "form"


def _flatten_parameters(value) -> str:
    """Project the FormQuestion.parameters dict to an XLSForm
    `parameters` cell string. Legacy script packs single values
    under the `_` key; richer dicts get key=value;... encoding."""
    if not value or not isinstance(value, dict):
        return ""
    if "_" in value and len(value) == 1:
        return str(value["_"])
    return ";".join(f"{k}={v}" for k, v in sorted(value.items()))


def _resolve_select_type(q: FormQuestion) -> str:
    """Pack the choice-list name back into the type cell for select
    questions. When a select question has no choice_list_ref (broken
    data) fall back to `text` — emitting a bare `select_one` row
    fails Kobo validation with the "Survey information not complete"
    error so we'd rather degrade gracefully."""
    if q.type in ("select_one", "select_multiple"):
        if q.choice_list_ref:
            return f"{q.type} {q.choice_list_ref.list_name}"
        return "text"  # fallback — see _question_row hint annotation
    return q.type


def _question_row(q: FormQuestion) -> dict:
    """Project a FormQuestion to its XLSForm survey row."""
    qtype = _resolve_select_type(q)
    hint = q.hint
    if q.type in ("select_one", "select_multiple") and not q.choice_list_ref:
        # Surface the data defect in the export so an operator
        # looking at the xlsx in LibreOffice notices the missing list.
        hint = (hint + " [missing choice list — exported as text]").strip()
    return {
        "type": qtype,
        "name": q.name,
        "label": q.label,
        "hint": hint,
        "required": "yes" if q.required else "",
        "relevant": q.relevant_expression,
        "constraint": q.constraint_expression,
        "constraint_message": q.constraint_message,
        "appearance": q.appearance,
        "choice_filter": "",
        "calculation": "",
        "repeat_count": q.repeat_count,
        "parameters": _flatten_parameters(q.parameters),
    }


def _section_open_row(s: FormSection) -> dict:
    """begin_group or begin_repeat for the section opener. Sections
    with a non-empty `repeat_count` (the household roster) emit as
    begin_repeat with the repeat_count column populated."""
    opener = "begin_repeat" if s.repeat_count else "begin_group"
    return {
        "type": opener,
        "name": s.name,
        "label": s.label,
        "hint": "", "required": "",
        "relevant": "", "constraint": "",
        "constraint_message": "", "appearance": "",
        "choice_filter": "", "calculation": "",
        "repeat_count": s.repeat_count or "", "parameters": "",
    }


def _section_close_row(s: FormSection) -> dict:
    closer = "end_repeat" if s.repeat_count else "end_group"
    return {
        "type": closer,
        "name": f"{s.name}_end",
        "label": "", "hint": "", "required": "",
        "relevant": "", "constraint": "",
        "constraint_message": "", "appearance": "",
        "choice_filter": "", "calculation": "",
        "repeat_count": "", "parameters": "",
    }


def _settings_row(form_version: FormVersion) -> tuple:
    """Kobo-shaped settings row. Mirrors the legacy file:
    `English` (not `en`), `theme-grid` (not `pages`), slugged
    form_id, datestamp version derived from updated_at so each
    re-export bumps the version even if FormVersion.version
    doesn't (Kobo uses version to detect "is this a new upload")."""
    form_id = f"{_slug(form_version.name)}_v{form_version.version}"
    version_stamp = form_version.updated_at.strftime("%Y%m%d%H%M")
    return (
        form_version.name,
        form_id,
        version_stamp,
        "English",
        "theme-grid",
    )


def export_to_xlsx(form_version: FormVersion) -> bytes:
    """Render `form_version` as a Kobo-compatible XLSForm. Returns
    raw .xlsx bytes — caller streams them as needed."""
    wb = Workbook()
    ws_survey = wb.active
    ws_survey.title = "survey"
    ws_choices = wb.create_sheet("choices")
    ws_settings = wb.create_sheet("settings")

    # ── survey sheet ────────────────────────────────────────────
    ws_survey.append(SURVEY_COLS)

    # Auto-prepend top-level metadata rows. The importer drops these
    # from FormQuestion (would otherwise duplicate them here on each
    # round-trip).
    for meta in _METADATA_ROWS:
        ws_survey.append([meta.get(c, "") for c in SURVEY_COLS])

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
    ws_settings.append(list(_settings_row(form_version)))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
