"""What is still coded against the retired single-digit frame.

Migration 0019 rewrote every legacy code with an exact UBOS 2024
counterpart and deprecated the whole legacy frame. What it deliberately
did NOT touch is rows sitting on a legacy code the UBOS frame has no
equivalent for — rewriting those would put an answer nobody gave into a
household's record, and from there into its PMT score.

This command is the backlog those rows form: run it, take the table to
MGLSD/UBOS, get a mapping signed off, then add the decided pairs to
EXACT in apps/reference_data/legacy_code_frames.py and ship a follow-up
data migration.

    python manage.py report_legacy_choice_codes
    python manage.py report_legacy_choice_codes --format csv

Read-only. It writes nothing.
"""

from __future__ import annotations

import csv
import sys

from django.apps import apps as global_apps
from django.core.management.base import BaseCommand

from apps.reference_data.legacy_code_frames import AMBIGUOUS, CODED_FIELDS, EXACT
from apps.reference_data.models import ChoiceList


def _label_for(list_name: str, code: str) -> str:
    choice_list = (
        ChoiceList.objects.filter(list_name=list_name).order_by("-version").first()
    )
    if choice_list is None:
        return "(list not found)"
    option = choice_list.options.filter(code=code).first()
    return option.label if option else "(code not in list)"


def _rows() -> list[dict]:
    out: list[dict] = []
    for app_label, model_name, field_name, list_name in CODED_FIELDS:
        model = global_apps.get_model(app_label, model_name)
        for code, reason in (AMBIGUOUS.get(list_name) or {}).items():
            count = model.objects.filter(**{field_name: code}).count()
            if not count:
                continue
            out.append({
                "model": model_name,
                "field": field_name,
                "list_name": list_name,
                "legacy_code": code,
                "legacy_label": _label_for(list_name, code),
                "rows": count,
                "why_unmapped": reason,
            })
    out.sort(key=lambda r: (-r["rows"], r["model"], r["field"], r["legacy_code"]))
    return out


def _exact_leftovers() -> list[str]:
    """Rows still on an EXACT legacy code — migration 0019 should have
    left none, so any here means it did not run or something wrote a
    legacy code afterwards."""
    out = []
    for app_label, model_name, field_name, list_name in CODED_FIELDS:
        mapping = EXACT.get(list_name) or {}
        if not mapping:
            continue
        model = global_apps.get_model(app_label, model_name)
        n = model.objects.filter(**{f"{field_name}__in": list(mapping)}).count()
        if n:
            out.append(f"{model_name}.{field_name}: {n} row(s)")
    return out


class Command(BaseCommand):
    help = "Report registry rows still coded against the retired legacy choice frame."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format", choices=("table", "csv"), default="table",
            help="table (default, for reading) or csv (for the sign-off pack).",
        )

    def handle(self, *args, **options):
        rows = _rows()
        leftovers = _exact_leftovers()

        if options["format"] == "csv":
            writer = csv.DictWriter(sys.stdout, fieldnames=[
                "model", "field", "list_name", "legacy_code",
                "legacy_label", "rows", "why_unmapped",
            ])
            writer.writeheader()
            writer.writerows(rows)
            return

        if not rows:
            self.stdout.write(self.style.SUCCESS(
                "No rows remain on an unmapped legacy code.",
            ))
        else:
            total = sum(r["rows"] for r in rows)
            self.stdout.write(
                f"{total} row(s) across {len(rows)} (field, code) pair(s) are still "
                f"on a legacy code with no UBOS 2024 equivalent.\n",
            )
            for r in rows:
                self.stdout.write(
                    f"  {r['rows']:>7}  {r['model']}.{r['field']} "
                    f"= {r['legacy_code']!r} ({r['legacy_label']})",
                )
                self.stdout.write(f"           {r['why_unmapped']}")
            self.stdout.write(
                "\nEach needs an MGLSD/UBOS mapping decision. Once decided, add "
                "the pair to EXACT in apps/reference_data/legacy_code_frames.py "
                "and ship a follow-up data migration.",
            )

        if leftovers:
            self.stdout.write(self.style.ERROR(
                "\nRows on a legacy code that DOES have an exact mapping — "
                "migration 0019 has not run, or something wrote a legacy "
                "code after it did:\n  " + "\n  ".join(leftovers),
            ))
