"""Seed the programme-wizard ChoiceLists (US-S25-001 / ADR-0010).

Eight new lists carry the dropdowns the Programme registration
wizard uses (units of enrolment, disbursement cycle, PMT band, exit
reason, composition flag, auto-exit trigger, webhook event, sex
filter), plus two new options appended to the existing
``programme_kind`` v1 list (grant + subsidy).

Per ADR-0003 forward-only past Sprint 5; the reverse hook removes
the seeded rows by author tag so a rollback inside the Sprint 25
window is safe.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.db import migrations

SEED = (
    Path(__file__).resolve().parent.parent
    / "seeds"
    / "choice_lists_programmes_v1.json"
)
AUTHOR_TAG = "system-migration-programmes"

# Lists in the seed file other than programme_kind v2 additions.
NEW_LISTS = (
    "programme_unit_of_enrolment",
    "programme_disbursement_cycle",
    "programme_pmt_band",
    "programme_exit_reason",
    "programme_composition_flag",
    "programme_auto_exit_trigger",
    "programme_webhook_event",
    "programme_sex_filter",
)


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    data = json.loads(SEED.read_text())

    for list_name in NEW_LISTS:
        cl, _ = ChoiceList.objects.get_or_create(
            list_name=list_name, version=1,
            defaults={
                "description": (
                    "Programme-registration wizard list seeded by "
                    "US-S25-001."
                ),
                "effective_from": date(2026, 1, 1),
                "status": "active",
                "author": AUTHOR_TAG,
                "approved_by": AUTHOR_TAG,
            },
        )
        for sort_order, opt in enumerate(data[list_name], start=1):
            ChoiceOption.objects.update_or_create(
                choice_list=cl, code=opt["code"], language="en",
                defaults={
                    "label": opt["label"],
                    "sort_order": sort_order,
                    "status": "active",
                },
            )

    # Append grant + subsidy to the existing programme_kind v1.
    kind_cl = ChoiceList.objects.filter(
        list_name="programme_kind", version=1,
    ).first()
    if kind_cl is not None:
        existing = kind_cl.options.count()
        for offset, opt in enumerate(data["programme_kind_v2_additions"]):
            ChoiceOption.objects.update_or_create(
                choice_list=kind_cl, code=opt["code"], language="en",
                defaults={
                    "label": opt["label"],
                    "sort_order": existing + offset + 1,
                    "status": "active",
                },
            )


def _unload(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    ChoiceList.objects.filter(author=AUTHOR_TAG, version=1).delete()
    ChoiceOption.objects.filter(
        choice_list__list_name="programme_kind",
        choice_list__version=1,
        code__in=("grant", "subsidy"),
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0004_seed_partner_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
