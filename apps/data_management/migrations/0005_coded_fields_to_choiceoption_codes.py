"""Data migration: map enum values to ChoiceOption.code (US-S22-005c).

After ADR-0010 we no longer use TextChoices for sex / nin_status /
urban_rural. The previous schema stored short enum strings ("M",
"rural", "has_card"); the new contract stores the seeded
ChoiceOption.code ("1", "2", "1"). This migration walks each
column, asserts every distinct value has a mapping, and rewrites
in-place.

Reverse plan (per ADR-0003 / CLAUDE.md migration policy, forward-
only after Sprint 5): the inverse map is documented in ADR-0010
and the rollback script is `/scripts/reverse/us_s22_005c.py`. The
RunPython reverse step is a noop to make the forward-only intent
explicit.
"""

from __future__ import annotations

from django.db import migrations

SEX_MAP = {"M": "1", "F": "2"}
URBAN_RURAL_MAP = {"urban": "1", "rural": "2"}
NIN_STATUS_MAP = {
    "has_card": "1",
    "lost": "2",
    "not_issued": "3",
    "no": "4",
    "unknown": "8",
}


def _migrate_column(Model, column: str, mapping: dict[str, str]) -> None:
    """Validate every distinct value is mapped or already a target
    code, then UPDATE each old value to its new code.
    """
    distinct = set(
        Model.objects.values_list(column, flat=True).distinct(),
    )
    distinct.discard("")
    distinct.discard(None)
    allowed = set(mapping) | set(mapping.values())
    unmapped = distinct - allowed
    if unmapped:
        raise RuntimeError(
            f"{Model.__name__}.{column} has unmapped values "
            f"{sorted(unmapped)}; extend the migration mapping or "
            f"add ChoiceOption rows for them before re-running."
        )
    for old, new in mapping.items():
        if old == new:
            continue
        Model.objects.filter(**{column: old}).update(**{column: new})


def _forward(apps, schema_editor):
    Household = apps.get_model("data_management", "Household")
    Member = apps.get_model("data_management", "Member")
    HouseholdVersion = apps.get_model("data_management", "HouseholdVersion")
    MemberVersion = apps.get_model("data_management", "MemberVersion")

    _migrate_column(Household, "urban_rural", URBAN_RURAL_MAP)
    _migrate_column(HouseholdVersion, "urban_rural", URBAN_RURAL_MAP)

    _migrate_column(Member, "sex", SEX_MAP)
    _migrate_column(Member, "nin_status", NIN_STATUS_MAP)
    _migrate_column(MemberVersion, "nin_status", NIN_STATUS_MAP)


class Migration(migrations.Migration):

    dependencies = [
        ("data_management", "0004_coded_fields_drop_textchoices"),
    ]

    operations = [
        migrations.RunPython(_forward, migrations.RunPython.noop),
    ]
