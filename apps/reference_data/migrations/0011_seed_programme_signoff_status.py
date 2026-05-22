"""Seed the programme_signoff_status ChoiceList (US-182, ADR-0010).

ProgrammeSignOff.status is a plain CharField on the model — the
canonical option catalogue lives here so the partners-module lint
gate (no inline choices=[...]) stays satisfied.

Forward-only past Sprint 5 (ADR-0003); RunPython reverse is a noop.
"""

from __future__ import annotations

from datetime import date

from django.db import migrations

AUTHOR_TAG = "system-migration-programme-signoff"

OPTIONS = (
    ("pending",  "Pending"),
    ("signed",   "Signed"),
    ("rejected", "Rejected"),
    ("skipped",  "Skipped"),
    ("on_hold",  "On hold"),
)


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    cl, _ = ChoiceList.objects.get_or_create(
        list_name="programme_signoff_status", version=1,
        defaults={
            "description": (
                "ProgrammeSignOff lifecycle codes per step "
                "(US-182): pending / signed / rejected / skipped / "
                "on_hold."
            ),
            "effective_from": date(2026, 1, 1),
            "status": "active",
            "author": AUTHOR_TAG,
            "approved_by": AUTHOR_TAG,
        },
    )
    for sort_order, (code, label) in enumerate(OPTIONS, start=1):
        ChoiceOption.objects.update_or_create(
            choice_list=cl, code=code, language="en",
            defaults={
                "label": label,
                "sort_order": sort_order,
                "status": "active",
            },
        )


def _unload(apps, schema_editor):
    # Forward-only.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0010_extend_programme_status_codes"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
