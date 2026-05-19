"""Rollback script for US-S22-005c (ADR-0010).

The 005c data migration rewrote three coded columns from legacy
TextChoices values to ChoiceOption codes:

    Member.sex          M → 1, F → 2
    Member.nin_status   has_card → 1, lost → 2, not_issued → 3,
                        no → 4, unknown → 8
    Household.urban_rural   urban → 1, rural → 2

The forward migration's reverse step is a `noop` per ADR-0003
(forward-only after Sprint 5). This script provides the operational
rollback path: it walks each column and flips codes back to the
legacy strings, then prints a verification summary. The Django
schema migration (0004) must be reverted separately via:

    python manage.py migrate data_management 0003

before this rollback runs — the model code in git history still has
the TextChoices classes (apps/data_management/models.py at
commit a53a789^).

Usage:
    source .venv/bin/activate
    DJANGO_SETTINGS_MODULE=nsr_mis.settings \\
        python scripts/reverse/us_s22_005c.py

Idempotent: re-running is safe (already-legacy values are left
alone). Touches all rows in one transaction; abort if any column
holds a value that's neither a current code nor a legacy string.
"""

from __future__ import annotations

import sys
from pathlib import Path

import django


def _bootstrap() -> None:
    """Wire Django so `Model.objects` works when this script is run
    directly (not via ./manage.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    django.setup()


# Reverse maps — inverse of the forward maps in
# apps/data_management/migrations/0005_coded_fields_to_choiceoption_codes.py
SEX_REVERSE = {"1": "M", "2": "F"}
URBAN_RURAL_REVERSE = {"1": "urban", "2": "rural"}
NIN_STATUS_REVERSE = {
    "1": "has_card",
    "2": "lost",
    "3": "not_issued",
    "4": "no",
    "8": "unknown",
}


def _revert_column(model, column: str, reverse_map: dict[str, str]) -> dict:
    distinct = set(
        model.objects.values_list(column, flat=True).distinct(),
    )
    distinct.discard("")
    distinct.discard(None)
    allowed = set(reverse_map) | set(reverse_map.values())
    unmapped = distinct - allowed
    if unmapped:
        raise RuntimeError(
            f"{model.__name__}.{column} has unmapped values {sorted(unmapped)} — "
            "extend the reverse map or fix the rows before re-running."
        )
    updates: dict[str, int] = {}
    for new_code, old_string in reverse_map.items():
        if new_code == old_string:
            continue
        n = model.objects.filter(**{column: new_code}).update(**{column: old_string})
        updates[f"{new_code}->{old_string}"] = n
    return updates


def main() -> int:
    _bootstrap()
    from apps.data_management.models import (
        Household,
        HouseholdVersion,
        Member,
        MemberVersion,
    )
    from django.db import transaction

    with transaction.atomic():
        print("Reverting Household.urban_rural ...")
        print("  ", _revert_column(Household, "urban_rural", URBAN_RURAL_REVERSE))
        print("Reverting HouseholdVersion.urban_rural ...")
        print("  ", _revert_column(HouseholdVersion, "urban_rural", URBAN_RURAL_REVERSE))

        print("Reverting Member.sex ...")
        print("  ", _revert_column(Member, "sex", SEX_REVERSE))

        print("Reverting Member.nin_status ...")
        print("  ", _revert_column(Member, "nin_status", NIN_STATUS_REVERSE))
        print("Reverting MemberVersion.nin_status ...")
        print("  ", _revert_column(MemberVersion, "nin_status", NIN_STATUS_REVERSE))

    print("\nDone. Run `python manage.py migrate data_management 0003` next "
          "to drop the schema-level CharField(max_length=32) widening, "
          "then redeploy the code at commit a53a789^.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
