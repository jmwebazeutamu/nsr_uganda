"""Seed the five admin-console groups (HANDOFF §2.1).

Group names are referenced by `apps.admin_console.permissions.
ADMIN_CONSOLE_GROUPS` and by the view-level UserPassesTestMixin.
Without these rows, the admin console is unreachable on a fresh
deploy.

Forward-only past Sprint 5 per ADR-0003; the reverse hook removes
the seeded rows so test runs that --keepdb stay clean.
"""

from __future__ import annotations

from django.db import migrations

GROUPS = (
    "nsr_admin",
    "mglsd_statistics",
    "dpo",
    "nsr_dba",
    "nsr_security",
)


def _seed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


def _unseed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
