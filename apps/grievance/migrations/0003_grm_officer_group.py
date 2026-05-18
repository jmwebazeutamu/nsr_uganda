"""US-S21-003b — create the "GRM Officer" Django group.

Membership in this group is the gate that lets a user see every
grievance + task, not just rows assigned to them, and is the only
role that can scope new tasks onto a grievance. The check lives in
apps.grievance.api._is_grm_officer; this migration ensures the
group exists on every fresh DB (dev, CI, production) so the check
resolves cleanly.

Idempotent: get_or_create — re-running won't create duplicates.
"""

from django.db import migrations


GROUP_NAME = "GRM Officer"


def _create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=GROUP_NAME)


def _drop_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("grievance", "0002_grievancetask"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(_create_group, _drop_group),
    ]
