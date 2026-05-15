"""Backfill the sub_region_code denormalised partition key for any rows
that pre-date 0002_sub_region_code. Per ADR-0005.

Reversible: the reverse step blanks the column. The column itself is
defined in 0002 and persists either way.
"""

from __future__ import annotations

from django.db import migrations


def forwards(apps, schema_editor):
    Household = apps.get_model("data_management", "Household")
    Member = apps.get_model("data_management", "Member")
    # Use a join through sub_region to avoid hitting save() (which fires
    # cascading FK lookups for every row).
    for hh in Household.objects.select_related("sub_region").iterator(chunk_size=2000):
        if not hh.sub_region_code:
            hh.sub_region_code = hh.sub_region.code
            hh.save(update_fields=["sub_region_code"])
    for m in Member.objects.select_related("household").iterator(chunk_size=2000):
        if not m.sub_region_code and m.household_id:
            m.sub_region_code = m.household.sub_region_code
            m.save(update_fields=["sub_region_code"])


def backwards(apps, schema_editor):
    Household = apps.get_model("data_management", "Household")
    Member = apps.get_model("data_management", "Member")
    Household.objects.update(sub_region_code="")
    Member.objects.update(sub_region_code="")


class Migration(migrations.Migration):

    dependencies = [
        ("data_management", "0002_sub_region_code"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
