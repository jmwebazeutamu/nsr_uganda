"""Seed the routing rows for the change types added after 0004.

Migration 0004 seeded the routing matrix from
``routing.DEFAULT_MATRIX``. Migration 0005 then added ADDRESS_MOVE,
ROSTER_CHANGE, ASSET_CHANGE and VERIFICATION to ``ChangeType``, and
LIFE_EVENT gained a PMT-relevant variant — and nothing seeded rows for
any of them. It did not matter while ``route()`` fell back to
DEFAULT_MATRIX when no active row existed: the code answered for the
nine combinations the table did not.

That fallback has now been removed, deliberately, so that routing
policy cannot be changed by a code release. Correct — but it leaves
those nine raising ``UpdError`` instead of routing. On production the
table holds 13 of the 22 combinations, so an address move, a roster
change, an asset change, a verification, or a PMT-relevant life event
would have failed at capture.

This is the seed that should have gone with the removal. Nothing is
invented: each value is the one DEFAULT_MATRIX carried for that
combination, which is what has governed these change types since
US-S22-003. Adding rows only — the 13 already there have been tuned by
hand (production routes correction/False to `cdo`, not the matrix's
`supervisor`), and a migration that overwrote operations' decisions
would be worse than the gap it closes.
"""

from django.db import migrations

# (change_type, pmt_relevant): (required_role, sla_hours)
# Verbatim from routing.DEFAULT_MATRIX as of 6992aee.
SEED = {
    ("life_event",    True):  ("me_officer",       48),
    ("verification",  False): ("cdo",              72),
    ("verification",  True):  ("me_officer",       48),
    ("address_move",  False): ("cdo_receiving",    96),
    ("address_move",  True):  ("district_m_and_e", 48),
    ("roster_change", False): ("cdo",              72),
    ("roster_change", True):  ("district_m_and_e", 48),
    ("asset_change",  False): ("cdo",              72),
    ("asset_change",  True):  ("district_m_and_e", 48),
}

NOTE = (
    "Seeded by 0006 from the DEFAULT_MATRIX values that governed this "
    "combination before the code fallback was removed."
)


def seed(apps, schema_editor):
    UpdRoutingRule = apps.get_model("update_workflow", "UpdRoutingRule")
    for (change_type, pmt_relevant), (role, hours) in SEED.items():
        # get_or_create, not update_or_create: an active row already
        # here is somebody's decision and this migration is not
        # entitled to it.
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


def unseed(apps, schema_editor):
    """Remove only the rows this migration wrote, identified by note."""
    UpdRoutingRule = apps.get_model("update_workflow", "UpdRoutingRule")
    UpdRoutingRule.objects.filter(note=NOTE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("update_workflow", "0005_alter_changerequest_change_type_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
