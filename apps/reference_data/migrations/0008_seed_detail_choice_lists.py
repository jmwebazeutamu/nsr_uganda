"""Seed the ~33 ChoiceLists for the US-S22-DE detail-entities build.

Mirrors the pattern from 0003_seed_choice_lists.py — load codes
from a JSON snapshot committed alongside the migration so the
authored history is versioned in git.

Lists land at version=1, status=ACTIVE, author=system,
approved_by=system, effective_from=2026-01-01.

Forward-only per CLAUDE.md (we're well past the Sprint 5
reversibility window). Reverse path deletes the seeded rows by
list_name; the ChoiceList / ChoiceOption tables themselves stay.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.db import migrations

SEED = Path(__file__).resolve().parent.parent / "seeds" / "choice_lists_detail_v1.json"


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    data = json.loads(SEED.read_text())
    for list_name, options in data.items():
        cl, _ = ChoiceList.objects.get_or_create(
            list_name=list_name, version=1,
            defaults={
                "description": "Seeded for US-S22-DE detail-entities build (v1).",
                "effective_from": date(2026, 1, 1),
                "status": "active",
                "author": "system",
                "approved_by": "system",
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
    data = json.loads(SEED.read_text())
    ChoiceList.objects.filter(
        list_name__in=list(data.keys()), version=1, author="system",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0007_seed_referral_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
