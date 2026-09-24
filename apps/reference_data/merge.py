"""Merging a duplicate GeographicUnit into the row it duplicates.

Two different defects produce the same shape — a unit that should never
have existed, with households, child units and operator scopes hanging
off it, beside the real row for the same place:

  * **Padded county codes.** The UBOS workbook writes the county
    segment unpadded and the Kobo form pads it, so `geo_backfill`
    fabricated a placeholder for a county already in the frame. See
    apps/reference_data/code_frames.py.
  * **The Kigezi seed's level shift.** `scripts/seed_kigezi_geo.py` was
    a stopgap that guessed the ladder from one Kobo submission before
    the UBOS workbook arrived, and guessed it one level too high:
    Nyakagyeme is a sub-county, seeded as a county; Kabwoma is a
    parish, seeded as a sub-county.

They differ only in how the target is found — derived from the code in
the first case, stated explicitly in the second. Everything after that
is identical and security-relevant, so it lives here once.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.audit import emit
from apps.security.models import OperatorScope

# Household FK -> its denormalised code column, for the levels a merge
# can repoint. region / sub_region / village are never merge targets.
HOUSEHOLD_FIELDS = {
    "county": "county_code",
    "sub_county": "sub_county_code",
    "parish": "parish_code",
}

EMPTY_TOTALS = {
    "units retired": 0,
    "households repointed": 0,
    "child units reparented": 0,
    "operator scopes rewritten": 0,
}


def plan(pairs) -> dict:
    """What `merge` would do, without doing it."""
    totals = dict(EMPTY_TOTALS)
    households = set()
    for source, target in pairs:
        totals["units retired"] += 1
        if source.level in HOUSEHOLD_FIELDS:
            households.update(
                Household.objects
                .filter(**{f"{source.level}_id": source.pk})
                .values_list("id", flat=True),
            )
        totals["child units reparented"] += GeographicUnit.objects.filter(
            parent=source,
        ).count()
        totals["operator scopes rewritten"] += OperatorScope.objects.filter(
            scope_level=source.level, scope_code=source.code,
        ).count()
    totals["households repointed"] = len(households)
    return totals


@transaction.atomic
def merge(pairs, *, actor: str, reason_for) -> dict:
    """Repoint everything off `source` onto `target`, then retire it.

    `reason_for(source, target)` supplies the human sentence recorded on
    the unit's AuditEvent, because the two callers are repairing
    different mistakes and should say so.

    Households get ONE event each listing every level that moved, not
    one per level — the household was in the wrong place, once.
    """
    totals = dict(EMPTY_TOTALS)
    changes: dict[str, dict] = {}

    for source, target in pairs:
        if source.level in HOUSEHOLD_FIELDS:
            column = HOUSEHOLD_FIELDS[source.level]
            for household in Household.objects.filter(
                **{f"{source.level}_id": source.pk},
            ):
                changes.setdefault(str(household.id), {})[column] = [
                    source.code, target.code,
                ]
                setattr(household, f"{source.level}_id", target.pk)
                # save() re-derives the mirrors ABAC matches on.
                household.save()

        totals["child units reparented"] += (
            GeographicUnit.objects.filter(parent=source).update(parent=target)
        )
        totals["operator scopes rewritten"] += (
            OperatorScope.objects
            .filter(scope_level=source.level, scope_code=source.code)
            .update(scope_code=target.code)
        )

        source.status = GeographicUnit.Status.RETIRED
        source.effective_to = timezone.localdate() - timedelta(days=1)
        source.save(update_fields=["status", "effective_to"])
        totals["units retired"] += 1

        emit(
            "geo_unit.merged",
            "GeographicUnit",
            str(source.pk),
            actor=actor,
            actor_kind="user",
            reason=reason_for(source, target),
            field_changes={
                "code": [source.code, target.code],
                "name": [source.name, target.name],
                "status": ["active", "retired"],
            },
        )

    for household_id, field_changes in changes.items():
        emit(
            "household.geography_corrected",
            "Household",
            household_id,
            actor=actor,
            actor_kind="user",
            reason="geography repointed off a unit that should not exist",
            field_changes=field_changes,
        )
    totals["households repointed"] = len(changes)
    return totals
