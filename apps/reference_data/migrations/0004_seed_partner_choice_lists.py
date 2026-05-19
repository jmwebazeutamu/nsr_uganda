"""Seed the 14 partner ChoiceLists (US-S23-002 / ADR-0011 §"Coded fields are DB-driven").

Codes are derived from the JSX literals in
design/v0.1/partners-source/screens-partners.jsx and the spec under
the Partners module. Each list lands at version=1, status=ACTIVE,
effective_from=today, mirroring the legacy seed (migration 0003).

Forward-only per ADR-0003 / CLAUDE.md (Sprint > 5). Reverse hook
removes the seeded rows by author tag so a rollback during the
S23 sprint window is safe.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.db import migrations

SEED = (
    Path(__file__).resolve().parent.parent
    / "seeds"
    / "choice_lists_partners_v1.json"
)
AUTHOR_TAG = "system-migration-partners"


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    data = json.loads(SEED.read_text())
    for list_name, options in data.items():
        cl, _ = ChoiceList.objects.get_or_create(
            list_name=list_name, version=1,
            defaults={
                "description": (
                    f"Partner / DSA registry list seeded from "
                    f"design/v0.1/partners-source (US-S23-002)."
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
        ("reference_data", "0003_seed_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
