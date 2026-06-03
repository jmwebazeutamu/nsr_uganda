"""Refresh programme PMT band labels to the current catalogue.

This keeps the existing stored codes intact for backward
compatibility, while updating the user-facing labels to the live PMT
bands now used by the registry and programme screens.
"""

from __future__ import annotations

from django.db import migrations


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    cl = ChoiceList.objects.filter(
        list_name="programme_pmt_band", version=1,
    ).first()
    if cl is None:
        return

    labels = {
        "poorest_20": "Extreme poverty",
        "poorest_40": "Poverty",
        "middle_40": "Vulnerable",
        "top_20": "Not poor",
    }
    for sort_order, (code, label) in enumerate(labels.items(), start=1):
        ChoiceOption.objects.update_or_create(
            choice_list=cl,
            code=code,
            language="en",
            defaults={
                "label": label,
                "sort_order": sort_order,
                "status": "active",
            },
        )


def _unload(apps, schema_editor):
    # Reverse migration intentionally leaves the updated labels in
    # place; older programme rows still depend on the same codes.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0015_retire_duplicate_sub_regions"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
