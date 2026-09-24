"""Merge the fabricated padded-county-code units into the UBOS frame.

Background in apps/reference_data/code_frames.py. In short: the Kobo
form sends county codes zero-padded and the UBOS workbook does not, so
`geo_backfill` fabricated a placeholder row (``name = code``) for every
county, sub-county and parish it could not find under the padded
spelling — beside the real row that already existed under the UBOS
spelling. Households promoted from those records attached to the
fabrications. The same real county ended up holding households under
two different codes, and no county-scoped query saw both halves.

`resolve_geographic_unit` stops new ones appearing. This repairs what
is already there:

  1. Every placeholder is matched to its real UBOS twin — same level,
     same code but for the county segment's padding, ACTIVE, and NOT
     itself a placeholder. A placeholder with no unambiguous twin is
     reported and left alone.
  2. Household.county / sub_county / parish FKs are repointed to the
     twin, and the denormalised *_code columns re-derived with them.
  3. GeographicUnit children of a placeholder are reparented to the
     twin — villages, mostly, which the Kobo pull fabricates under a
     parish and which have no UBOS equivalent to move to.
  4. OperatorScope rows whose scope_code is a placeholder code are
     rewritten to the twin's code, so an operator's visibility follows
     the households rather than being silently emptied.
  5. The placeholder flips to RETIRED with effective_to = yesterday.
     Nothing is deleted: the row stays queryable with ?status=all, and
     the audit trail keeps its referent.

Every household change emits an AuditEvent — this rewrites the
geography of a registry record, which is personal data.

Dry run by default. `--apply` writes, inside one transaction.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.data_management.models import Household
from apps.reference_data.code_frames import code_spellings
from apps.reference_data.models import GeographicUnit
from apps.security.audit import emit
from apps.security.models import OperatorScope

# Only these levels carry a county segment that can differ.
MERGEABLE_LEVELS = ("county", "sub_county", "parish")

# Household FK -> denormalised code column, for the levels we repoint.
_HOUSEHOLD_FIELDS = {
    "county": "county_code",
    "sub_county": "sub_county_code",
    "parish": "parish_code",
}


def find_placeholders():
    """Placeholder rows: ACTIVE, at a mergeable level, name == code."""
    return list(
        GeographicUnit.objects
        .filter(level__in=MERGEABLE_LEVELS, status=GeographicUnit.Status.ACTIVE)
        .exclude(name="")
        .order_by("level", "code"),
    )


def twin_for(placeholder: GeographicUnit) -> GeographicUnit | None:
    """The real UBOS row this placeholder duplicates, or None.

    Deliberately strict. The twin must be a *different* row, ACTIVE,
    and carry a real name — merging into another placeholder, or into a
    retired row, would move households somewhere no better than where
    they are.
    """
    for candidate in code_spellings(placeholder.code)[1:]:
        row = (
            GeographicUnit.objects
            .filter(
                level=placeholder.level,
                code=candidate,
                status=GeographicUnit.Status.ACTIVE,
            )
            .exclude(pk=placeholder.pk)
            .order_by("-effective_from")
            .first()
        )
        if row is not None and row.name != row.code:
            return row
    return None


class Command(BaseCommand):
    help = "Merge fabricated padded-county-code geographic units into the UBOS frame."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without it, nothing is written.",
        )
        parser.add_argument(
            "--actor", default="",
            help="Actor recorded on the AuditEvents. Required with --apply.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = (options["actor"] or "").strip()
        if apply and not actor:
            raise CommandError("--actor is required with --apply")

        placeholders = [p for p in find_placeholders() if p.name == p.code]
        if not placeholders:
            self.stdout.write("No placeholder geographic units. Nothing to do.")
            return

        pairs, orphans = [], []
        for placeholder in placeholders:
            twin = twin_for(placeholder)
            (pairs if twin is not None else orphans).append(
                (placeholder, twin) if twin is not None else placeholder,
            )

        self.stdout.write(
            f"{len(placeholders)} placeholder unit(s); "
            f"{len(pairs)} with an unambiguous UBOS twin, "
            f"{len(orphans)} without.",
        )
        for orphan in orphans:
            self.stdout.write(
                self.style.WARNING(
                    f"  no twin: {orphan.level} {orphan.code} — left alone",
                ),
            )

        if not pairs:
            return

        if apply:
            with transaction.atomic():
                totals = self._merge(pairs, actor=actor)
        else:
            totals = self._plan(pairs)

        verb = "merged" if apply else "would merge"
        self.stdout.write("")
        self.stdout.write(f"{verb}:")
        for key, value in totals.items():
            self.stdout.write(f"  {key:26} {value}")
        if not apply:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("Dry run — nothing written. Re-run with --apply --actor <name>."),
            )

    # -- planning ---------------------------------------------------------

    def _plan(self, pairs) -> dict:
        totals = {
            "units retired": 0, "households repointed": 0,
            "child units reparented": 0, "operator scopes rewritten": 0,
        }
        households = set()
        for placeholder, twin in pairs:
            field = None
            for level, _column in _HOUSEHOLD_FIELDS.items():
                if placeholder.level == level:
                    field = level
            self.stdout.write(
                f"  {placeholder.level:11} {placeholder.code:14} -> "
                f"{twin.code:12} {twin.name}",
            )
            totals["units retired"] += 1
            if field:
                ids = Household.objects.filter(
                    **{f"{field}_id": placeholder.pk},
                ).values_list("id", flat=True)
                households.update(ids)
            totals["child units reparented"] += GeographicUnit.objects.filter(
                parent=placeholder,
            ).count()
            totals["operator scopes rewritten"] += OperatorScope.objects.filter(
                scope_level=placeholder.level, scope_code=placeholder.code,
            ).count()
        totals["households repointed"] = len(households)
        return totals

    # -- writing ----------------------------------------------------------

    def _merge(self, pairs, *, actor: str) -> dict:
        totals = {
            "units retired": 0, "households repointed": 0,
            "child units reparented": 0, "operator scopes rewritten": 0,
        }
        # Household id -> {column: (before, after)}, accumulated across
        # levels so one household gets one AuditEvent rather than three.
        changes: dict[str, dict] = {}

        for placeholder, twin in pairs:
            level = placeholder.level
            if level in _HOUSEHOLD_FIELDS:
                column = _HOUSEHOLD_FIELDS[level]
                for household in Household.objects.filter(
                    **{f"{level}_id": placeholder.pk},
                ):
                    changes.setdefault(str(household.id), {})[column] = [
                        placeholder.code, twin.code,
                    ]
                    setattr(household, f"{level}_id", twin.pk)
                    # save() re-derives the mirrors from the FKs.
                    household.save()

            totals["child units reparented"] += (
                GeographicUnit.objects
                .filter(parent=placeholder)
                .update(parent=twin)
            )
            totals["operator scopes rewritten"] += (
                OperatorScope.objects
                .filter(scope_level=level, scope_code=placeholder.code)
                .update(scope_code=twin.code)
            )

            placeholder.status = GeographicUnit.Status.RETIRED
            placeholder.effective_to = timezone.localdate() - timedelta(days=1)
            placeholder.save(update_fields=["status", "effective_to"])
            totals["units retired"] += 1

            emit(
                "geo_unit.merged",
                "GeographicUnit",
                str(placeholder.pk),
                actor=actor,
                actor_kind="user",
                reason=(
                    f"padded county-code duplicate of {twin.level} "
                    f"{twin.code} ({twin.name}); retired and merged"
                ),
                field_changes={
                    "code": [placeholder.code, twin.code],
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
                reason=(
                    "geography repointed from a fabricated padded "
                    "county-code unit to the UBOS frame"
                ),
                field_changes=field_changes,
            )
        totals["households repointed"] = len(changes)
        return totals
