"""Seed the `pmt_trigger_source` ChoiceList.

US-PMT-014 / Audit 2026-05-21 §3. The four-value vocabulary that
`PMTResult.triggered_by` accepts has lived as a hardcoded string
in `apps/pmt/signals.py` (`"upd_commit"`) and the default arg of
`apps/pmt/services.recompute_for_household` (`"manual"`). The
audit recommends promoting these to formal ChoiceOption rows so
labels resolve consistently with the rest of the catalogue.

Codes:
  dih_promote — recompute triggered after a DIH stage record is promoted to the registry
  upd_commit  — recompute triggered when an UPD change request commits
  manual      — recompute initiated by a user via /api/v1/pmt/recompute/
  backfill    — recompute initiated by a batch/backfill job

Codes match `apps/pmt/constants.PMT_TRIGGER_SOURCES` exactly —
the test `apps.pmt.tests.TestTriggerSourceChoiceList` enforces
that. Don't rename without updating both.
"""

from __future__ import annotations

from datetime import date

from django.db import migrations


LIST_NAME = "pmt_trigger_source"

OPTIONS = [
    ("dih_promote", "DIH promotion"),
    ("upd_commit",  "UPD commit"),
    ("manual",      "Manual recompute"),
    ("backfill",    "Backfill job"),
]


def _load(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    cl, _ = ChoiceList.objects.get_or_create(
        list_name=LIST_NAME, version=1,
        defaults={
            "description": "PMT recompute trigger sources (US-PMT-014).",
            "effective_from": date(2026, 1, 1),
            "status": "active",
            "author": "system",
            "approved_by": "system",
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
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceList.objects.filter(
        list_name=LIST_NAME, version=1, author="system",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0008_seed_detail_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_load, _unload),
    ]
