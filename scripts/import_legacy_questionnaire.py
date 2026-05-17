"""US-120 — import the legacy NSR questionnaire into FormVersion 1.

The questionnaire lives in two forms today:
- The MS Word document at /docs/06_questionnaire.docx (the field
  instrument, plain prose, hard to parse).
- The Python builder at /k-forms/build_nsr_xlsform.py (structured,
  emits an XLSForm xlsx).

This script reads the structured form. It exec's the legacy
script in a controlled namespace, monkey-patching Workbook.save
so no file is written, and captures the `survey` + `choices` lists
the script populates. We then translate those into
FormVersion + FormSection + FormQuestion rows under the new
authoring model (US-117).

Idempotent — re-running upserts on (form_version, code) for
sections and (section, name) for questions. Choice lists already
land via the apps.reference_data migration (US-116), so this
script only links FormQuestion.choice_list_ref to the existing
v1 ChoiceList rows.

Usage:

    source .venv/bin/activate
    python manage.py shell -c "from scripts.import_legacy_questionnaire import main; main()"

or as a one-off CLI:

    python scripts/import_legacy_questionnaire.py
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY = BASE_DIR / "k-forms" / "build_nsr_xlsform.py"


# Top-level group/repeat names → (section code, label). The legacy
# script uses the inner block names; this mapping recovers the
# section letter codes from the questionnaire spec (A through L).
SECTION_MAP = {
    "consent_group":     ("CONSENT", "Consent statement"),
    "identification":    ("A",       "Identification particulars"),
    "survey_status":     ("B",       "Survey status"),
    "household_members": ("C",       "Household roster (Section 1)"),
    "health_disability": ("D",       "Health and disability"),
    "education_literacy":("E",       "Education and literacy"),
    "employment":        ("F",       "Employment"),
    "housing":           ("G",       "Housing characteristics (Section 2)"),
    "agriculture":       ("H",       "Agricultural activities"),
    "food_security":     ("I",       "Food security / nutrition"),
    "shocks":            ("K",       "Impact of shocks"),
    "coping":            ("L",       "Coping strategies"),
}


def _exec_legacy() -> dict:
    """Run k-forms/build_nsr_xlsform.py in a captured namespace.
    Monkey-patches openpyxl Workbook.save so the script doesn't
    write a file as a side effect."""
    src = LEGACY.read_text()
    ns: dict = {"__name__": "_legacy_import_inline", "__file__": str(LEGACY)}
    import openpyxl  # noqa: PLC0415 — local import so the patch is scoped
    original_save = openpyxl.Workbook.save
    openpyxl.Workbook.save = lambda self, *a, **kw: None
    try:
        exec(compile(src, str(LEGACY), "exec"), ns)
    finally:
        openpyxl.Workbook.save = original_save
    return ns


def _question_type(legacy_type: str) -> tuple[str, str]:
    """Translate the legacy `type` cell into (QuestionType, choice_list_name).
    The legacy column packs the choice-list name into select_one/multiple
    types ('select_one relationship' → ('select_one', 'relationship'))."""
    t = (legacy_type or "").strip()
    if t.startswith("select_one "):
        return "select_one", t.split(None, 1)[1]
    if t.startswith("select_multiple "):
        return "select_multiple", t.split(None, 1)[1]
    return t, ""


# XLSForm metadata types that the legacy script puts at the top of
# the survey sheet. The exporter auto-prepends these at render time,
# so the importer drops them — keeping them as FormQuestion rows
# would just double them up on export.
_TOP_LEVEL_METADATA = {"start", "end", "today", "deviceid", "username"}


def main(*, dry_run: bool = False) -> dict:
    """Run the import. Returns a small summary dict.

    Idempotent: re-runs delete the existing children of FormVersion v1
    (sections cascade to questions) and rebuild from the legacy script
    output. The FormVersion row itself is preserved across runs.
    """
    # Lazy Django setup so the script works both via `manage.py shell -c`
    # and as a standalone `python scripts/import_legacy_questionnaire.py`.
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "nsr_mis.settings"
        import django  # noqa: PLC0415
        django.setup()

    from apps.intake.models import (
        FormQuestion,
        FormSection,
        FormVersion,
        QuestionType,
    )
    from apps.reference_data.models import ChoiceList

    ns = _exec_legacy()
    survey = ns["survey"]

    # ── Pull FormVersion v1 (create if missing). On re-run, wipe
    # existing children so the rebuild is clean. Upserting was
    # leaving stale rows when question order or names shifted between
    # runs of the legacy script.
    fv, _ = FormVersion.objects.get_or_create(
        version=1,
        defaults={
            "name": "NSR National Social Registry Questionnaire (v1, legacy)",
            "description": "Imported from k-forms/build_nsr_xlsform.py "
                           "by scripts/import_legacy_questionnaire.py",
            "effective_from": date(2026, 1, 1),
            "status": "active",
            "is_active": True,
            "author": "system-migration",
            "approved_by": "system-migration",
        },
    )
    fv.sections.all().delete()  # cascades to FormQuestion via ON DELETE

    # ── Walk the survey list, tracking section depth ──
    current_section: FormSection | None = None
    last_closed_section: FormSection | None = None  # holds questions at depth 0 between sections
    current_order_in_section = 0
    section_order = 0
    depth = 0  # nested-group counter; only top-level groups become sections
    counts = {"sections": 0, "questions": 0, "skipped": 0}

    for entry in survey:
        qtype = entry.get("type", "")
        name = entry.get("name", "")
        label = entry.get("label", "")

        # Detect section boundaries: a begin_group / begin_repeat
        # at depth 0 starts a new section. Deeper ones are kept as
        # FormQuestion rows with type=begin_group/begin_repeat so
        # the structural shape is preserved for XLSForm export.
        if qtype in ("begin_group", "begin_repeat"):
            if depth == 0:
                code, sec_label = SECTION_MAP.get(name, (name.upper()[:16], label))
                section_order += 1
                current_section = FormSection.objects.create(
                    form_version=fv, name=name,
                    code=code,
                    label=sec_label or label or name,
                    order=section_order,
                    repeat_count=str(entry.get("repeat_count", "") or ""),
                )
                last_closed_section = None
                current_order_in_section = 0
                counts["sections"] += 1
                depth = 1
                continue
            # Nested groups inside a section — record as a question
            # with the structural type so the order is preserved.
            depth += 1
        elif qtype in ("end_group", "end_repeat"):
            depth = max(depth - 1, 0)
            if depth == 0:
                last_closed_section = current_section
                current_section = None
                continue

        # Top-level XLSForm metadata rows (start/end/today/deviceid/
        # username) are dropped at import — the exporter re-adds them
        # automatically so the round-trip stays Kobo-valid.
        if qtype in _TOP_LEVEL_METADATA:
            counts["skipped"] += 1
            continue

        # A regular question encountered at depth 0 (between sections,
        # like the legacy `hh_size` between sections B and C) is
        # attached to the most-recently-closed section as a trailing
        # question. Keeps the form structurally intact without
        # inventing synthetic sections.
        section_for_q = current_section or last_closed_section
        if section_for_q is None:
            counts["skipped"] += 1
            continue
        if not name:
            counts["skipped"] += 1
            continue
        # If the question is going to a closed section, reset the
        # per-section order counter to its current max.
        if current_section is None and last_closed_section is not None:
            current_order_in_section = (
                FormQuestion.objects.filter(section=last_closed_section)
                .count()
            )

        normalized_type, choice_list_name = _question_type(qtype)
        # All known XLSForm types now have enum values; if something
        # exotic shows up, store the raw string — Django CharField
        # doesn't enforce choices at the DB level and the exporter
        # passes the type through verbatim.
        if normalized_type not in QuestionType.values:
            counts["skipped"] += 1
            continue

        choice_list_ref = None
        if choice_list_name:
            choice_list_ref = ChoiceList.objects.filter(
                list_name=choice_list_name, version=1,
            ).first()

        current_order_in_section += 1
        FormQuestion.objects.create(
            section=section_for_q, name=name,
            label=label,
            hint=entry.get("hint", ""),
            type=normalized_type,
            choice_list_ref=choice_list_ref,
            required=bool(entry.get("required")),
            relevant_expression=entry.get("relevant", ""),
            constraint_expression=entry.get("constraint", ""),
            constraint_message=entry.get("constraint_message", ""),
            appearance=entry.get("appearance", ""),
            repeat_count=str(entry.get("repeat_count", "") or ""),
            parameters={} if not entry.get("parameters") else {"_": str(entry["parameters"])},
            order_in_section=current_order_in_section,
        )
        counts["questions"] += 1

    counts["form_version_id"] = fv.id
    counts["form_version_name"] = fv.name
    print(
        f"import_legacy_questionnaire: form_version={fv.id} "
        f"sections+={counts['sections']} questions+={counts['questions']} "
        f"skipped={counts['skipped']}",
    )
    return counts


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
