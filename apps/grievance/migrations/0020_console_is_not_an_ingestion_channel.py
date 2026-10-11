"""Move NSR-WEB off `web`, which routes DIH's intake.

Migration 0018 registered the console with `kind="web"` on the
reasoning that it is a web channel. It is, and that is not what the
field means. `SourceSystemKind` is not descriptive: `intake.services.
_connector_for_channel` maps an intake channel to a kind and then
takes `SourceSystem.objects.filter(kind=kind, is_active=True).first()`.
Two active sources of kind `web` makes that lookup a coin toss, and
it landed on the new row, which has no connector — so household
intake over the web channel began failing with "no active Connector
for source 'NSR-WEB'". Six tests caught it.

The lesson is about the register, not the row: `SourceSystem` is not
a passive list of names, it is DIH's operational configuration, and
`kind` is routing. A source that nothing ingests from needs a kind
that no channel maps to. `console` is that kind, and the comment on
it says so, so the next person adding a non-ingesting source does not
reach for `web` as I did.
"""

from django.db import migrations

CODE = "NSR-WEB"


def to_console(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    SourceSystem.objects.filter(code=CODE).update(kind="console")


def back_to_web(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    SourceSystem.objects.filter(code=CODE).update(kind="web")


class Migration(migrations.Migration):

    dependencies = [
        ("grievance", "0019_name_the_sources_as_a_screen_shows_them"),
        ("ingestion_hub", "0010_source_system_kind_console"),
    ]

    operations = [migrations.RunPython(to_console, back_to_web)]
