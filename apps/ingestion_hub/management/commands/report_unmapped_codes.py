"""Report unresolved inbound codes recorded by the DIH mapping gate.

The report is read-only.  It deliberately groups the immutable
``UnmappedChoiceValue`` observations rather than attempting to select a
replacement value.  A ConnectorRun is the ingestion wave/run contract until
the incoming UBOS wave identifier is promoted into the source contract.
"""

from __future__ import annotations

import csv
import sys

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.ingestion_hub.models import UnmappedChoiceValue


def _rows() -> list[dict]:
    rows = list(
        UnmappedChoiceValue.objects.filter(is_current=True)
        .values(
            "choice_list_name",
            "canonical_path",
            "source_code",
            "stage_record__connector_run_id",
            "stage_record__connector_run__connector__source_system__code",
        )
        .annotate(records=Count("stage_record_id", distinct=True))
        .order_by(
            "stage_record__connector_run__connector__source_system__code",
            "stage_record__connector_run_id",
            "choice_list_name",
            "canonical_path",
            "source_code",
        ),
    )
    return [
        {
            "source_system": row[
                "stage_record__connector_run__connector__source_system__code"
            ],
            "wave_run": row["stage_record__connector_run_id"],
            "choice_list": row["choice_list_name"],
            "canonical_path": row["canonical_path"],
            "source_code": row["source_code"],
            "records": row["records"],
            "decision_outstanding": (
                "Approve an exact ChoiceList mapping or correct the canonical payload; "
                "no nearest-code substitution is permitted."
            ),
        }
        for row in rows
    ]


class Command(BaseCommand):
    help = "Report current DIH answer codes with no approved exact ChoiceList mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format", choices=("table", "csv"), default="table",
            help="table (default) or csv for the mapping sign-off pack.",
        )

    def handle(self, *args, **options):
        rows = _rows()
        if options["format"] == "csv":
            writer = csv.DictWriter(
                sys.stdout,
                fieldnames=(
                    "source_system", "wave_run", "choice_list", "canonical_path",
                    "source_code", "records", "decision_outstanding",
                ),
            )
            writer.writeheader()
            writer.writerows(rows)
            return

        if not rows:
            self.stdout.write(self.style.SUCCESS(
                "No current unmapped DIH choice codes.",
            ))
            return
        total = sum(row["records"] for row in rows)
        self.stdout.write(
            f"{total} staged record(s) contain {len(rows)} unresolved "
            "(wave, item, code) mapping group(s).",
        )
        for row in rows:
            self.stdout.write(
                f"  {row['records']:>7}  {row['source_system']} / "
                f"{row['wave_run']}  {row['canonical_path']} "
                f"[{row['choice_list']}] = {row['source_code']!r}",
            )
            self.stdout.write(f"           {row['decision_outstanding']}")
