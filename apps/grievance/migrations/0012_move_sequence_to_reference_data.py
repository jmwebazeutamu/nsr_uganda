"""Move the GRM counter into the shared ReferenceSequence table.

0011 gave grievances a per-year counter in `GrmReferenceSequence`. UPD,
DRS and REF now need the same thing, and four copies of "take the next
number" is four chances to disagree about whether a rolled-back
transaction burns its number.

The rows move rather than being recreated: `last_number` is the only
thing standing between the next grievance and a duplicate reference, so
it is carried across before the old table goes.
"""

from django.db import migrations


def move(apps, schema_editor):
    GrmReferenceSequence = apps.get_model("grievance", "GrmReferenceSequence")
    ReferenceSequence = apps.get_model("reference_data", "ReferenceSequence")

    for row in GrmReferenceSequence.objects.all():
        target, created = ReferenceSequence.objects.get_or_create(
            prefix="GRM", year=row.year,
            defaults={"last_number": row.last_number},
        )
        if not created and target.last_number < row.last_number:
            # Never move a counter backwards: a lower number is a
            # reference somebody already holds.
            target.last_number = row.last_number
            target.save(update_fields=["last_number"])


def unmove(apps, schema_editor):
    GrmReferenceSequence = apps.get_model("grievance", "GrmReferenceSequence")
    ReferenceSequence = apps.get_model("reference_data", "ReferenceSequence")

    for row in ReferenceSequence.objects.filter(prefix="GRM"):
        GrmReferenceSequence.objects.update_or_create(
            year=row.year, defaults={"last_number": row.last_number},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("grievance", "0011_grm_reference_sequence"),
        ("reference_data", "0022_reference_sequence"),
    ]
    operations = [
        migrations.RunPython(move, unmove),
        migrations.DeleteModel(name="GrmReferenceSequence"),
    ]
