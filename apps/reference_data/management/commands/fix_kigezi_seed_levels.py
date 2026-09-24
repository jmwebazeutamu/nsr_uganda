"""Repair the Kigezi seed's level shift.

`scripts/seed_kigezi_geo.py` was an explicit stopgap: it fabricated a
geographic chain for Rukungiri so one Kobo submission could promote,
"until the real UBOS workbook is supplied". The workbook has since been
loaded — 147 districts, 329 counties, 10,872 parishes — and the seed's
guess turns out to sit one level too high at every rung:

    seeded                              the UBOS frame
    county     412.02     Nyakagyeme    sub_county 412.2.05    Nyakagyeme
    sub_county 412.02.05  Kabwoma       parish     412.2.05.01 Kabwoma
    parish     412.02.05.01 "Kabwoma Parish"       — no equivalent; it is
                                        the parish again, a rung lower

Nyakagyeme is a sub-county of Rujumbura County, not a county. Kabwoma
is a parish of Nyakagyeme, not a sub-county. So a household captured
there reads "Nyakagyeme County", which does not exist, and its real
county — Rujumbura — appears nowhere on the record.

`merge_padded_geo_codes` cannot fix this: it derives its target by
flipping the county segment's padding, and here the target is a
different place entirely. The mapping below is therefore stated, not
derived, and every pair is asserted to be at the same level as its
source — a household's county FK must end up on a county.

The two villages under the seeded parish are Kobo fabrications with no
UBOS equivalent (the workbook carries no village rows at all). They are
reparented onto the real parish, not retired.

Dry run by default; `--apply` needs `--actor`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.reference_data import merge as merge_units
from apps.reference_data.models import GeographicUnit

# (level, seeded code, real UBOS code). Hand-verified against the
# loaded frame: 412.2 is Rujumbura County, 412.2.05 is Nyakagyeme
# sub-county, 412.2.05.01 is Kabwoma parish.
MAPPING = [
    ("county", "412.02", "412.2"),
    ("sub_county", "412.02.05", "412.2.05"),
    ("parish", "412.02.05.01", "412.2.05.01"),
]


def resolve_pairs():
    """(source, target) for every mapping row that is still present.

    Returns (pairs, problems). A mapping row whose source is already
    gone is silently skipped — the command is re-runnable. A row whose
    target is missing, retired, or at a different level is a problem
    and stops the run: moving a household onto the wrong rung is worse
    than leaving it where it is.
    """
    pairs, problems = [], []
    for level, source_code, target_code in MAPPING:
        source = GeographicUnit.objects.filter(
            level=level, code=source_code,
            status=GeographicUnit.Status.ACTIVE,
        ).first()
        if source is None:
            continue
        target = GeographicUnit.objects.filter(
            level=level, code=target_code,
            status=GeographicUnit.Status.ACTIVE,
        ).first()
        if target is None:
            problems.append(
                f"{level} {target_code} is not an ACTIVE unit — "
                f"cannot merge {source_code} into it",
            )
            continue
        if target.level != source.level:
            problems.append(
                f"{source_code} is a {source.level} but {target_code} "
                f"is a {target.level}",
            )
            continue
        if target.pk == source.pk:
            problems.append(f"{source_code} maps to itself")
            continue
        pairs.append((source, target))
    return pairs, problems


class Command(BaseCommand):
    help = "Merge the mis-levelled Kigezi seed chain into the UBOS frame."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor", default="")

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = (options["actor"] or "").strip()
        if apply and not actor:
            raise CommandError("--actor is required with --apply")

        pairs, problems = resolve_pairs()
        for problem in problems:
            self.stdout.write(self.style.ERROR(f"  {problem}"))
        if problems:
            raise CommandError(
                "refusing to run — the mapping does not match the frame",
            )
        if not pairs:
            self.stdout.write("Kigezi seed chain already merged. Nothing to do.")
            return

        for source, target in pairs:
            self.stdout.write(
                f"  {source.level:11} {source.code:14} {source.name:16} -> "
                f"{target.code:14} {target.name}",
            )

        totals = (
            merge_units.merge(pairs, actor=actor, reason_for=_reason)
            if apply else merge_units.plan(pairs)
        )

        self.stdout.write("")
        self.stdout.write("merged:" if apply else "would merge:")
        for key, value in totals.items():
            self.stdout.write(f"  {key:26} {value}")
        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run with --apply --actor <name>.",
            ))


def _reason(source, target) -> str:
    return (
        f"seeded by scripts/seed_kigezi_geo.py one level too high; "
        f"{source.name!r} at {source.level} is really "
        f"{target.name!r} ({target.code})"
    )
