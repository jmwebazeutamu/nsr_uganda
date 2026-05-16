"""Seed the 46 legacy XLSForm choice lists as ChoiceList version 1
(US-116).

The legacy questionnaire's choices were defined inline in
k-forms/build_nsr_xlsform.py as `add_list(name, [(code, label), ...])`
calls. This migration loads those rows verbatim from a JSON snapshot
(committed alongside the migration) so the registry's authoring
model owns the canonical copy going forward.

Versioning: every list is created at version=1, status=ACTIVE,
author="system-migration", with effective_from=2026-01-01 so the
authored history starts when the registry stood up. Subsequent
edits create new versions through the apps.reference_data services
(landed in US-116b).

Forward-only per ADR-0003. Reverse path nukes the seeded rows but
does not delete the ChoiceList/ChoiceOption tables (that's the job
of the previous migration if rolled back).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.db import migrations

SEED = Path(__file__).resolve().parent.parent / "seeds" / "choice_lists_v1.json"


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    data = json.loads(SEED.read_text())
    for list_name, options in data.items():
        cl, _ = ChoiceList.objects.get_or_create(
            list_name=list_name, version=1,
            defaults={
                "description": f"Seeded from legacy XLSForm script (v1).",
                "effective_from": date(2026, 1, 1),
                "status": "active",
                "author": "system-migration",
                "approved_by": "system-migration",
            },
        )
        for sort_order, opt in enumerate(options, start=1):
            ChoiceOption.objects.update_or_create(
                choice_list=cl, code=opt["code"], language="en",
                defaults={
                    "label": opt["label"],
                    "sort_order": sort_order,
                    "status": "active",
                },
            )


def _unload(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceList.objects.filter(
        author="system-migration", version=1,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0002_choice_list"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
