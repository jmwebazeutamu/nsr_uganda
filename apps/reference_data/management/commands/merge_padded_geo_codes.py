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
from django.utils import timezone

from apps.reference_data import merge as merge_units
from apps.reference_data.code_frames import code_spellings
from apps.reference_data.models import GeographicUnit

# Only these levels carry a county segment that can differ.
MERGEABLE_LEVELS = ("county", "sub_county", "parish")

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

        for placeholder, twin in pairs:
            self.stdout.write(
                f"  {placeholder.level:11} {placeholder.code:14} -> "
                f"{twin.code:12} {twin.name}",
            )

        if apply:
            totals = merge_units.merge(
                pairs, actor=actor, reason_for=_reason,
            )
        else:
            totals = merge_units.plan(pairs)

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


def _reason(source, target) -> str:
    return (
        f"padded county-code duplicate of {target.level} {target.code} "
        f"({target.name}); retired and merged"
    )
