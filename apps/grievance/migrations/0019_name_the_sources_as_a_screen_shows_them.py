"""Shorten the source names to what a case panel can show.

Migration 0017 registered STAAC as "STAAC GRM (Inspectorate of
Government)" — accurate, and too long for the 380px rail the case
detail lives in. The institution belongs in the register's
`description`, where an operator can read it; the `name` is what a
screen prints beside "SOURCE".

This is the demonstration of why the name lives in the register
rather than in the console: changing what an operator sees is a row
edit, not a deploy. The codes, which everything matches on, do not
move.
"""

from django.db import migrations

NAMES = {
    "STAAC_GRM": (
        "STAAC",
        "STAAC GRM, operated by the Inspectorate of Government. "
        "Approved grievance handovers pulled from its partner API. "
        "Registered for provenance, agreement and run accounting; the "
        "records it brings are grievances and do not enter DIH's "
        "staging pipeline. See ADR-0044.",
    ),
    "NSR-WEB": (
        "NSR Web",
        "The NSR operator console. Grievances opened here by a Parish "
        "Chief, CDO or NSR Unit officer rather than received from a "
        "partner system. No connector: records are entered directly, "
        "so there is nothing to pull.",
    ),
}

PREVIOUS = {
    "STAAC_GRM": "STAAC GRM (Inspectorate of Government)",
    "NSR-WEB": "NSR Web",
}


def rename(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    for code, (name, description) in NAMES.items():
        SourceSystem.objects.filter(code=code).update(
            name=name, description=description,
        )


def unrename(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    for code, name in PREVIOUS.items():
        SourceSystem.objects.filter(code=code).update(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("grievance", "0018_every_grievance_names_its_source"),
    ]

    operations = [migrations.RunPython(rename, unrename)]
