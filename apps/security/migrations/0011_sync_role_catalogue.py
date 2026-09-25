"""Apply the current canonical role catalogue to existing role groups."""

from django.db import migrations


def sync_role_catalogue(apps, schema_editor):
    # The catalogue is the SSOT for Group permission membership. This is
    # additive/idempotent and leaves any operational groups outside it alone.
    from apps.security.roles import sync_groups

    sync_groups(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0010_alter_operatorscope_scope_level"),
    ]

    operations = [
        migrations.RunPython(sync_role_catalogue, migrations.RunPython.noop),
    ]
