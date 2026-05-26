"""US-S11-021 — seed the `nsr_unit_coordinator` Django group.

The console "Run connector" button (System Admin > Connector runs)
allows both System Admin staff and NSR Unit Coordinators to trigger a
Kobo pull. The permission check in
`apps.ingestion_hub.permissions.IsDihTrigger` reads group membership,
so the group has to exist on every DB (dev, CI, production) for the
check to resolve cleanly.

Idempotent: get_or_create — re-running won't create duplicates.
"""

from django.db import migrations


GROUP_NAME = "nsr_unit_coordinator"


def _create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=GROUP_NAME)


def _drop_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion_hub", "0005_stagerecord_last_edited_tracking"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(_create_group, _drop_group),
    ]
