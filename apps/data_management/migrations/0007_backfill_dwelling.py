"""US-S22-DE-05 — backfill `Dwelling` rows from `Household.dwelling_tenure`.

Per US-S22-DE-04 promotion writes Dwelling on every new household.
This migration handles the existing rows: for every Household with
a non-empty `dwelling_tenure` and no Dwelling yet, create the
matching Dwelling row carrying the same tenure.

Idempotent — Dwelling has a OneToOne FK to Household, so the
`get_or_create(household=hh)` guard ensures re-runs are no-ops on
households that already have a row.

Batched in 1000s so the data step survives a 100k-row sample
inside the per-deploy migration window (prompt §6 hard constraint).

Forward-only per CLAUDE.md (we are past the Sprint 5 reversibility
window). Reverse plan, if needed: delete Dwelling rows whose
`tenure` matches the parent `Household.dwelling_tenure` AND whose
created_at is later than this migration's run time. Mark the
release ticket with the reverse SQL before deploy.
"""

from __future__ import annotations

from django.db import migrations

_BATCH = 1000


def _backfill(apps, schema_editor):
    Household = apps.get_model("data_management", "Household")
    Dwelling = apps.get_model("data_management", "Dwelling")

    qs = (
        Household.objects
        .exclude(dwelling_tenure="")
        .filter(dwelling__isnull=True)
        .only("id", "dwelling_tenure", "sub_region_code")
    )

    # iterator(chunk_size) keeps SQLite/Postgres memory bounded on the
    # 12 M-household target scale.
    batch: list = []
    for hh in qs.iterator(chunk_size=_BATCH):
        batch.append(
            Dwelling(
                household=hh,
                tenure=hh.dwelling_tenure,
                sub_region_code=hh.sub_region_code or "",
            ),
        )
        if len(batch) >= _BATCH:
            Dwelling.objects.bulk_create(batch, ignore_conflicts=True)
            batch.clear()
    if batch:
        Dwelling.objects.bulk_create(batch, ignore_conflicts=True)


def _unload(apps, schema_editor):
    # Reverse path: delete the Dwelling rows whose tenure mirrors the
    # parent Household.dwelling_tenure AND no other detail columns
    # populated (i.e. they look like backfill artefacts, not
    # promotion-written rows). Per the prompt §6 the migration is
    # documented forward-only; this reverse path is conservative —
    # an operator running it should expect to lose any Dwelling row
    # they think looks like a backfill.
    Household = apps.get_model("data_management", "Household")
    Dwelling = apps.get_model("data_management", "Dwelling")
    for hh in Household.objects.exclude(dwelling_tenure="").iterator(chunk_size=_BATCH):
        Dwelling.objects.filter(
            household=hh, tenure=hh.dwelling_tenure,
            dwelling_type="", roof_material="", wall_material="",
            floor_material="", total_rooms__isnull=True,
            sleeping_rooms__isnull=True,
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("data_management", "0006_detail_entities_part1"),
    ]

    operations = [
        migrations.RunPython(_backfill, _unload),
    ]
