"""Give every (change_type, pmt_relevant) combination an active row.

0006 seeded the nine combinations production was missing. A fresh
database is missing a different set: 0004 seeded twelve, 0005 added
four change types, and `life_event/pmt_relevant=False` was never
seeded by any migration — production has it because somebody added it
by hand.

So the table's completeness depended on which environment you were in
and what had been done to it, which is how nine combinations went
unnoticed until the code fallback was removed.

This backfills from ``routing.DEFAULT_MATRIX`` whatever is still
missing, whatever environment it runs in. Not a list of rows: a list
would need extending every time ``ChangeType`` grows, which is exactly
the mistake 0005 made.

Additive only. An active row already present is somebody's decision
and this migration is not entitled to it.
"""

from django.db import migrations

NOTE = (
    "Backfilled by 0007 from DEFAULT_MATRIX — every change type needs an "
    "active row now that route() has no fallback."
)


def backfill(apps, schema_editor):
    UpdRoutingRule = apps.get_model("update_workflow", "UpdRoutingRule")
    # Imported at run time: DEFAULT_MATRIX is a plain dict of strings
    # and ints, with no model dependency, so reading it here does not
    # couple the migration to the current model state.
    from apps.update_workflow.routing import DEFAULT_MATRIX

    have = {
        (r.change_type, r.pmt_relevant)
        for r in UpdRoutingRule.objects.filter(is_active=True)
    }
    for (change_type, pmt_relevant), (role, hours) in DEFAULT_MATRIX.items():
        if (change_type, pmt_relevant) in have:
            continue
        UpdRoutingRule.objects.get_or_create(
            change_type=change_type,
            pmt_relevant=pmt_relevant,
            is_active=True,
            defaults={
                "required_role": role,
                "sla_hours": hours,
                "note": NOTE,
            },
        )


def unbackfill(apps, schema_editor):
    UpdRoutingRule = apps.get_model("update_workflow", "UpdRoutingRule")
    UpdRoutingRule.objects.filter(note=NOTE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("update_workflow", "0006_seed_routing_added_change_types"),
    ]
    operations = [migrations.RunPython(backfill, unbackfill)]
