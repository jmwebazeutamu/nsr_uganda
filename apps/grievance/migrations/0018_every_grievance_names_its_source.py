"""Give every grievance a named source, including our own.

`Grievance.source_system` has been "the partner's code, or blank when
it is ours". Blank carried a meaning — "opened here" — that nothing
says out loud, which is fine until a screen has to show it: the
console would have to translate `""` into a name, and a name invented
in JSX is a vocabulary that lives nowhere.

So the registry's own channel is registered like any other source, and
the existing rows are backfilled onto it. After this,
`Grievance.source_system` is always an `ingestion_hub.SourceSystem`
code and the display name is that row's `name` — resolved server-side,
changed by editing the register rather than by a deploy.

Why `SourceSystem` and not a new GRM vocabulary: it is already the
registry's answer to "which system did this record come from", the
STAAC pull already matches its `code` against it, and a second list of
source names would be the same fact in two places. The cost is that a
channel with no connector now appears in DIH's source register; that
is honest — the register is of systems records arrive from, and the
console is one — but it is a cost, and worth knowing before someone
wonders why NSR-WEB has no connector runs.

`external_reference` is untouched and stays blank for a case opened
here: there is no other system's number to record. The uniqueness
constraint only applies where a reference exists, so backfilling the
source cannot collide.
"""

from django.db import migrations

WEB_CODE = "NSR-WEB"


def seed_and_backfill(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    Grievance = apps.get_model("grievance", "Grievance")

    SourceSystem.objects.get_or_create(
        code=WEB_CODE,
        defaults={
            "name": "NSR Web",
            "kind": "web",
            "description": (
                "The NSR operator console. Grievances opened here by a "
                "Parish Chief, CDO or NSR Unit officer rather than "
                "received from a partner system. No connector: records "
                "are entered directly, so there is nothing to pull."
            ),
            "is_active": True,
        },
    )
    # Blank meant "ours". Say so.
    Grievance.objects.filter(source_system="").update(source_system=WEB_CODE)


def unbackfill(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    Grievance = apps.get_model("grievance", "Grievance")

    Grievance.objects.filter(source_system=WEB_CODE).update(source_system="")
    SourceSystem.objects.filter(code=WEB_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("grievance", "0017_staac_landing_and_held_reason"),
        ("ingestion_hub", "0009_source_system_blocks_on_unmapped"),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, unbackfill),
    ]
