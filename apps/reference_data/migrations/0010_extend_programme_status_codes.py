"""Extend the programme_status ChoiceList with the workflow states
needed by the Programme lifecycle (US-180 / US-182).

The original v1 list (seeded in 0005_seed_programme_choice_lists)
held three codes: draft / active / closed. The lifecycle state
machine adds four more — pending_approval / suspended /
pending_amendment / closing — so the Programme.status column can
carry the canonical lifecycle state instead of forcing a parallel
lifecycle_status column on the model.

Forward-only past Sprint 5 (ADR-0003); RunPython reverse is a noop.
"""

from __future__ import annotations

from django.db import migrations

AUTHOR_TAG = "system-migration-programme-lifecycle"

NEW_OPTIONS = (
    ("pending_approval",  "Pending approval"),
    ("suspended",         "Suspended"),
    ("pending_amendment", "Pending amendment"),
    ("closing",           "Closing"),
)


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    cl = ChoiceList.objects.filter(
        list_name="programme_status", version=1,
    ).first()
    if cl is None:  # seed wasn't run; nothing to extend
        return

    base = cl.options.count()
    for offset, (code, label) in enumerate(NEW_OPTIONS):
        ChoiceOption.objects.update_or_create(
            choice_list=cl, code=code, language="en",
            defaults={
                "label": label,
                "sort_order": base + offset + 1,
                "status": "active",
            },
        )


def _unload(apps, schema_editor):
    # Forward-only past Sprint 5; the noop matches the policy on the
    # other programme-status seed migrations.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0009_seed_pmt_trigger_source"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
