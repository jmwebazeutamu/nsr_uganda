"""Seed the beneficiary-registry ChoiceList (US-S25-006 / ADR-0010).

Adds `programme_enrolment_status` (active/suspended/pending/exited)
so the beneficiary registry's status tabs and chips read from the
DB rather than an inline JSX array.

Forward-only per ADR-0003; the reverse hook removes the seeded
rows by author tag.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.db import migrations

SEED = (
    Path(__file__).resolve().parent.parent
    / "seeds"
    / "choice_lists_beneficiaries_v1.json"
)
AUTHOR_TAG = "system-migration-beneficiaries"


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    data = json.loads(SEED.read_text())
    for list_name, options in data.items():
        cl, _ = ChoiceList.objects.get_or_create(
            list_name=list_name, version=1,
            defaults={
                "description": (
                    "Beneficiary-registry list seeded by US-S25-006."
                ),
                "effective_from": date(2026, 1, 1),
                "status": "active",
                "author": AUTHOR_TAG,
                "approved_by": AUTHOR_TAG,
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
    ChoiceList.objects.filter(author=AUTHOR_TAG, version=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0005_seed_programme_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
