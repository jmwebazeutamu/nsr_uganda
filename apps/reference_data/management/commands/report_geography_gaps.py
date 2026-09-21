"""Numbering gaps in the loaded UBOS geographic frame.

An enumerator drilling Kampala Central Division sees parish codes run
…01.09 then …01.11: there is no …01.10. That reads as a lost row, and
the natural response is to "restore" it — which would mean inventing an
administrative unit and giving it a national code.

It is not one row. Across the loaded frame, 65 of 2,224 sub-counties
have a gap in their parish numbering. `scripts/load_ubos_geography.py`
does not generate these numbers; it takes each parish code straight from
the source workbook's own column and skips only rows whose district /
county / sub-county / parish key is incomplete. A gap therefore means
one of two things, and this command cannot tell them apart:

  * the source workbook has no row for that number — typically a parish
    that was merged or abolished between frame revisions, in which case
    the gap is correct and permanent; or
  * the source workbook has the row but with a blank key column, in
    which case the loader dropped it and it needs reloading.

Resolving that means diffing against the UBOS workbook, which lives
outside this repository (see the path in load_ubos_geography.py). This
command produces the list to diff, so the question is answerable instead
of being rediscovered one dropdown at a time.

    python manage.py report_geography_gaps
    python manage.py report_geography_gaps --level parish --format csv
    python manage.py report_geography_gaps --parent 102.1.01

Read-only. It writes nothing and invents nothing.

Tracked as OI-REFDATA-07.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.reference_data.models import GeographicUnit

#: "<parent>.<n>" — the dotted numeric frame UBOS uses below district.
CODE = re.compile(r"^(?P<parent>.+)\.(?P<n>\d+)$")


def _gaps(level: str, parent_prefix: str = "") -> list[dict]:
    groups: dict[str, list[int]] = defaultdict(list)
    names: dict[str, str] = {}

    qs = GeographicUnit.objects.filter(level=level, status="active")
    if parent_prefix:
        qs = qs.filter(code__startswith=f"{parent_prefix}.")
    for unit in qs.only("code", "name").iterator():
        match = CODE.match(unit.code)
        if not match:
            continue
        groups[match.group("parent")].append(int(match.group("n")))
        names.setdefault(match.group("parent"), "")

    # Name the parent so the report is readable without a second query
    # per row.
    parents = {
        u.code: u.name
        for u in GeographicUnit.objects.filter(code__in=list(groups)).only("code", "name")
    }

    out = []
    for parent, numbers in groups.items():
        present = set(numbers)
        missing = [n for n in range(1, max(present) + 1) if n not in present]
        if not missing:
            continue
        out.append({
            "parent_code": parent,
            "parent_name": parents.get(parent, "(unknown)"),
            "present": len(present),
            "highest": max(present),
            "missing_codes": " ".join(f"{parent}.{n:02d}" for n in missing),
        })
    out.sort(key=lambda r: r["parent_code"])
    return out


class Command(BaseCommand):
    help = "Report numbering gaps in the loaded UBOS geographic frame."

    def add_arguments(self, parser):
        parser.add_argument("--level", default="parish",
                            help="Geographic level to check (default: parish).")
        parser.add_argument("--parent", default="",
                            help="Restrict to codes under this parent prefix.")
        parser.add_argument("--format", choices=("table", "csv"), default="table")

    def handle(self, *args, **options):
        rows = _gaps(options["level"], options["parent"])

        if options["format"] == "csv":
            writer = csv.DictWriter(sys.stdout, fieldnames=[
                "parent_code", "parent_name", "present", "highest", "missing_codes",
            ])
            writer.writeheader()
            writer.writerows(rows)
            return

        if not rows:
            self.stdout.write(self.style.SUCCESS(
                f"No numbering gaps at level {options['level']!r}.",
            ))
            return

        total = sum(len(r["missing_codes"].split()) for r in rows)
        self.stdout.write(
            f"{total} missing code(s) across {len(rows)} parent(s) at level "
            f"{options['level']!r}.\n",
        )
        for row in rows:
            self.stdout.write(
                f"  {row['parent_code']}  {row['parent_name']}"
                f"  ({row['present']} present, highest {row['highest']})",
            )
            self.stdout.write(f"      missing: {row['missing_codes']}")
        self.stdout.write(
            "\nA gap is not automatically a lost row. Diff these against the "
            "UBOS workbook named in scripts/load_ubos_geography.py: a code the "
            "workbook does not contain is a merged or abolished unit and the "
            "gap is correct; a code it does contain was dropped on load and "
            "needs reloading. Nothing here may be filled in by hand — these "
            "are national administrative codes (OI-REFDATA-07).",
        )
