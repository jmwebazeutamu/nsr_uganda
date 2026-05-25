"""Retire 4 duplicate sub_region GeographicUnit rows.

The seed data shipped four duplicates that leaked into the
operator home's sub-region dropdown — each region appeared twice:

  canonical (kept)                     duplicate (retired)
  ──────────────────────────────────   ───────────────────────────────
  SR-BUGANDA-NORTH-CENTRAL  Buganda North   SR-BUGANDA_NORTH-CENTRAL  Buganda_North
  SR-BUGANDA-SOUTH-CENTRAL  Buganda South   SR-BUGANDA_SOUTH-CENTRAL  Buganda_South
  SR-WEST-NILE-NORTHERN     West Nile       SR-WEST_NILE-NORTHERN     West_Nile
  SR-KARAMOJA-NORTHERN      Karamoja        UG-N-KAR                  Karamoja

This migration:

1. Repoints `Household.sub_region` FK + denormalised
   `sub_region_code` (ADR-0005) from each duplicate to the canonical
   row.
2. Repoints any child `GeographicUnit.parent` FK (districts under
   the duplicate sub-region) to the canonical sub-region.
3. Marks the duplicate rows `status='retired'` so the API's active
   filter excludes them.

Idempotent: each pair is skipped if the canonical row is missing
or if the duplicate is already non-active. Forward-only per
ADR-0003.

No `AuditEvent` rows are emitted — this is a migration-time data
fix, not an operator action; there is no actor. Operator-driven
reference-data edits still go through the lifecycle service
(apps.reference_data.lifecycle.replace_geographic_unit) which
does emit audit events.
"""

from __future__ import annotations

from django.db import migrations

DUP_PAIRS = [
    # (canonical_code, duplicate_code)
    ("SR-BUGANDA-NORTH-CENTRAL", "SR-BUGANDA_NORTH-CENTRAL"),
    ("SR-BUGANDA-SOUTH-CENTRAL", "SR-BUGANDA_SOUTH-CENTRAL"),
    ("SR-WEST-NILE-NORTHERN", "SR-WEST_NILE-NORTHERN"),
    ("SR-KARAMOJA-NORTHERN", "UG-N-KAR"),
]


def _retire_duplicates(apps, schema_editor):
    GeographicUnit = apps.get_model("reference_data", "GeographicUnit")
    Household = apps.get_model("data_management", "Household")

    for canonical_code, dup_code in DUP_PAIRS:
        canonical = GeographicUnit.objects.filter(
            level="sub_region", code=canonical_code, status="active",
        ).first()
        if canonical is None:
            continue
        dup = GeographicUnit.objects.filter(
            level="sub_region", code=dup_code, status="active",
        ).first()
        if dup is None:
            continue

        # 1. Repoint Household FK + denormalised partition key.
        Household.objects.filter(sub_region=dup).update(
            sub_region=canonical,
            sub_region_code=canonical.code,
        )
        # 2. Repoint child geographic units (districts under this sub-region).
        GeographicUnit.objects.filter(parent=dup).update(parent=canonical)
        # 3. Retire the duplicate row.
        dup.status = "retired"
        dup.save(update_fields=["status"])


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0014_geounit_cached_counts_and_partial_unique"),
        # Household model must exist with sub_region FK + sub_region_code field.
        ("data_management", "0008_household_village_optional"),
    ]

    operations = [
        migrations.RunPython(_retire_duplicates, migrations.RunPython.noop),
    ]
