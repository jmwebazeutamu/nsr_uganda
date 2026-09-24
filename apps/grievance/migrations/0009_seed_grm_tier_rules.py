"""Seed the GRM escalation ladder from the SAD.

SAD §5.1 names it: "tier (L1 Parish Chief / L2 CDO / L3 District / L4
NSR Unit)". §4.4's routing table confirms the two district-level ones —
"L3 District M&E sign-off" and "NSR Unit Coordinator dual approval" —
so `m_and_e_officer` and `nsr_unit_coordinator` are the catalogue codes
for "District" and "NSR Unit" rather than a choice made here.

The SLA hours are the values the service has used since US-S21; this
migration moves them, it does not change them.
"""

from django.db import migrations

# (tier, role code from apps.security.roles, sla hours, why)
LADDER = [
    ("l1_parish_chief", "parish_chief", 24,
     "SAD §5.1 — L1 Parish Chief. Parish-scoped role."),
    ("l2_cdo", "cdo", 48,
     "SAD §5.1 — L2 CDO. District-scoped; the L2 approver in the §4.4 "
     "update-routing table."),
    ("l3_district", "m_and_e_officer", 72,
     "SAD §5.1 — L3 District. §4.4 calls this level 'District M&E', "
     "which is m_and_e_officer (adr0006 DISTRICT_M_AND_E)."),
    ("l4_nsr_unit", "nsr_unit_coordinator", 168,
     "SAD §5.1 — L4 NSR Unit. §4.4 names the NSR Unit Coordinator."),
]


def seed(apps, schema_editor):
    GrmTierRule = apps.get_model("grievance", "GrmTierRule")
    for tier, role, hours, note in LADDER:
        GrmTierRule.objects.update_or_create(
            tier=tier, is_active=True,
            defaults={"required_role": role, "sla_hours": hours, "note": note},
        )


def unseed(apps, schema_editor):
    GrmTierRule = apps.get_model("grievance", "GrmTierRule")
    GrmTierRule.objects.filter(tier__in=[t for t, _r, _h, _n in LADDER]).delete()


class Migration(migrations.Migration):
    dependencies = [("grievance", "0008_grmtierrule")]
    operations = [migrations.RunPython(seed, unseed)]
