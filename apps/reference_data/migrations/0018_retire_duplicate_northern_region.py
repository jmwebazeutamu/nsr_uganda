"""Retire the duplicate "Northern" region, UG-N.

The Region dropdown in the capture wizard listed five options for four
regions:

    Central (R-CENTRAL), Eastern (R-EASTERN), Northern (R-NORTHERN),
    Western (R-WESTERN), Northern (UG-N)

Two options, identical labels, and no way for an enumerator to tell
which was which. Picking UG-N left Sub-region empty with no error and
no explanation — a dead end mid-interview.

UG-N is the tail of the cleanup in 0015_retire_duplicate_sub_regions:
that migration retired UG-N's only child (UG-N-KAR "Karamoja", folded
into SR-KARAMOJA-NORTHERN) but left the parent region row active. An
active region with no active sub-regions under it is exactly the dead
end the operator hit.

This migration:

1. Repoints any Household.region FK still pointing at UG-N to
   R-NORTHERN (and, defensively, any surviving child GeographicUnit).
2. Marks UG-N `status='retired'` so the API's active filter excludes it.

Safety: the repoint runs before the retire and both are skipped when
R-NORTHERN is absent, so the migration cannot orphan a household. Rows
are retired, never deleted — a household captured against UG-N must
stay interpretable. Idempotent; forward-only per ADR-0003.

No AuditEvent rows: this is a migration-time data fix with no actor,
matching 0015. Operator-driven reference-data edits still go through
apps.reference_data.lifecycle, which does emit audit events.
"""

from __future__ import annotations

from django.db import migrations

CANONICAL_CODE = "R-NORTHERN"
DUPLICATE_CODE = "UG-N"


def _retire_duplicate_region(apps, schema_editor):
    GeographicUnit = apps.get_model("reference_data", "GeographicUnit")
    Household = apps.get_model("data_management", "Household")

    canonical = GeographicUnit.objects.filter(
        level="region", code=CANONICAL_CODE, status="active",
    ).first()
    if canonical is None:
        return
    dup = GeographicUnit.objects.filter(
        level="region", code=DUPLICATE_CODE, status="active",
    ).first()
    if dup is None:
        return

    Household.objects.filter(region=dup).update(region=canonical)
    GeographicUnit.objects.filter(parent=dup).update(parent=canonical)
    dup.status = "retired"
    dup.save(update_fields=["status"])


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0017_alter_geographicunit_code"),
        ("data_management", "0008_household_village_optional"),
    ]

    operations = [
        migrations.RunPython(_retire_duplicate_region, migrations.RunPython.noop),
    ]
