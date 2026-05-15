"""Seed the default UPD routing matrix into UpdRoutingRule.

Per UPD-O-01: the hardcoded DEFAULT_MATRIX moves into the DB so
operations can edit it without a deploy. This migration mirrors the
SAD §4.4.4 defaults so behaviour is identical the moment the table
exists.

Reversible: reverse drops the seeded rows; the hardcoded fallback in
apps.update_workflow.routing.route() takes back over.
"""

from __future__ import annotations

from django.db import migrations

# Inlined defaults so the migration doesn't import live code (whose
# constants can drift without breaking the migration history).
DEFAULTS = [
    ("correction",       False, "supervisor",       72),
    ("correction",       True,  "cdo",              48),
    ("addition",         False, "parish_chief",     72),
    ("addition",         True,  "cdo",              48),
    ("removal",          False, "cdo",              48),
    ("removal",          True,  "district_m_and_e", 48),
    ("vital_event",      False, "nira_auto",         0),
    ("vital_event",      True,  "nira_auto",         0),
    ("programme_state",  False, "programme_auto",    0),
    ("programme_state",  True,  "programme_auto",    0),
    ("recertification",  False, "district_m_and_e", 168),
    ("recertification",  True,  "district_m_and_e", 168),
]


def seed(apps, schema_editor):
    UpdRoutingRule = apps.get_model("update_workflow", "UpdRoutingRule")
    for ct, pmt, role, hours in DEFAULTS:
        UpdRoutingRule.objects.get_or_create(
            change_type=ct, pmt_relevant=pmt, is_active=True,
            defaults={"required_role": role, "sla_hours": hours,
                      "note": "Seeded from SAD §4.4.4 defaults"},
        )


def unseed(apps, schema_editor):
    UpdRoutingRule = apps.get_model("update_workflow", "UpdRoutingRule")
    UpdRoutingRule.objects.filter(
        note="Seeded from SAD §4.4.4 defaults",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("update_workflow", "0003_updroutingrule"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
