"""Seed the referral-side ChoiceList (US-S26-002 / ADR-0015).

Adds `referral_status` (sent / accepted / enrolled / rejected /
exited) so the referral.Referral.status field can drop its
TextChoices declaration in US-S26-003.

Note: `enrolled` here means the referral has been converted into
a ProgrammeEnrolment — a terminal state on the referral
lifecycle. This is distinct from the enrolment-status `active`
code (programme_enrolment_status, US-S25-006), which describes
the enrolment lifecycle itself. ADR-0015 §"Decision 4"
documents this asymmetry.

Forward-only per ADR-0003; the reverse hook removes the seeded
row by author tag.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.db import migrations

SEED = (
    Path(__file__).resolve().parent.parent
    / "seeds"
    / "choice_lists_referral_v1.json"
)
AUTHOR_TAG = "system-migration-referral"


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    data = json.loads(SEED.read_text())
    for list_name, options in data.items():
        cl, _ = ChoiceList.objects.get_or_create(
            list_name=list_name, version=1,
            defaults={
                "description": (
                    "Referral-lifecycle list seeded by US-S26-002."
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
        ("reference_data", "0006_seed_beneficiary_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
