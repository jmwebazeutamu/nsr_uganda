"""Give every changerequest a case number: UPD-2026-0001.

Three steps, because the column is unique and the table has rows: add
it without the constraint, fill it, then constrain. Adding a unique
blank column to a populated table fails on the second row.

Existing rows are numbered in the order they were created, so the
sequence reads the way anyone would expect — the first changerequest of 2026
is UPD-2026-0001. The shared counter in
reference_data.ReferenceSequence is then set to where the backfill
finished, so the next one created does not collide with a backfilled
one.

Generated in Python rather than SQL. The format, the padding and the
counter live in apps/reference_data/references.py, and a second
implementation in PL/pgSQL is how two records end up with numbers
issued by different rules.
"""

from django.db import migrations, models


def backfill(apps, schema_editor):
    from django.utils import timezone

    Model = apps.get_model("update_workflow", "changerequest")
    ReferenceSequence = apps.get_model("reference_data", "ReferenceSequence")

    counters: dict[int, int] = {}
    for row in Model.objects.order_by("created_at", "id").iterator():
        raised = getattr(row, "created_at", None) or timezone.now()
        year = timezone.localtime(raised).year
        counters[year] = counters.get(year, 0) + 1
        row.reference = f"UPD-{year:04d}-{counters[year]:04d}"
        row.save(update_fields=["reference"])

    for year, last in counters.items():
        seq, created = ReferenceSequence.objects.get_or_create(
            prefix="UPD", year=year, defaults={"last_number": last},
        )
        if not created and seq.last_number < last:
            # Never move a counter backwards: a lower number is one
            # somebody already holds.
            seq.last_number = last
            seq.save(update_fields=["last_number"])


def unbackfill(apps, schema_editor):
    Model = apps.get_model("update_workflow", "changerequest")
    Model.objects.update(reference="")


class Migration(migrations.Migration):
    dependencies = [
        ('update_workflow', '0007_backfill_routing_completeness'),
        ("reference_data", "0022_reference_sequence"),
    ]

    operations = [
        migrations.AddField(
            model_name="changerequest",
            name="reference",
            # No db_index: the unique constraint below brings its own,
            # and asking for both makes Django build the _like index
            # twice and fail on the second.
            field=models.CharField(blank=True, default="", max_length=16),
            preserve_default=False,
        ),
        migrations.RunPython(backfill, unbackfill),
        migrations.AlterField(
            model_name="changerequest",
            name="reference",
            field=models.CharField(blank=True, max_length=16, unique=True),
        ),
    ]
