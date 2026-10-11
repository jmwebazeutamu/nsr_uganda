"""Run one STAAC pull cycle from the command line.

Operator-initiated, the way DIH's connector pull is: there is no beat
entry yet, because a schedule for an integration whose credential has
not been issued would be a job that fails every night. Adding one is a
line in `nsr_mis/celery.py`, which the file's own comment insists is
the only place a schedule may live.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.grievance.external.client import DEFAULT_PAGE_SIZE, StaacError
from apps.grievance.external.pull import pull
from apps.grievance.external.service import file_held


class Command(BaseCommand):
    help = (
        "Pull approved grievance handovers from STAAC's partner API and "
        "file them, holding any this registry cannot yet classify."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--environment", default="",
            help="Which stored credential to use. Omit when there is one.",
        )
        parser.add_argument(
            "--limit", type=int, default=DEFAULT_PAGE_SIZE,
            help="Page size, 1-200 (STAAC's own bounds).",
        )
        parser.add_argument(
            "--changed-since", default="",
            help="RFC 3339 UTC. First request only; ignored when resuming.",
        )
        parser.add_argument(
            "--restart", action="store_true",
            help="Ignore the stored cursor and read the collection from "
                 "the beginning. Records already held are recognised and "
                 "not re-fetched.",
        )
        parser.add_argument(
            "--file-held", action="store_true",
            help="Do not call STAAC. Re-apply the mapping to snapshots "
                 "held earlier, which is how cases that arrived before a "
                 "category binding get filed once it is approved.",
        )

    def handle(self, *args, **options):
        if options["file_held"]:
            results = file_held()
            filed = sum(1 for r in results if r.created)
            self.stdout.write(
                f"{len(results)} held snapshot(s) re-applied, {filed} filed.",
            )
            for result in results:
                if not result.created:
                    self.stdout.write(self.style.WARNING(
                        f"  still held: {result.handover.tracking_number or result.handover.handover_id}"
                        f" — {result.handover.outcome_detail}",
                    ))
            return

        try:
            report = pull(
                environment=options["environment"],
                limit=options["limit"],
                changed_since=options["changed_since"],
                restart=options["restart"],
            )
        except StaacError as exc:
            raise SystemExit(f"STAAC pull failed: {exc}") from exc

        self.stdout.write(report.summary())
        self.stdout.write(f"correlation id: {report.correlation_id}")
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING(f"  {warning}"))
        for error in report.errors:
            self.stdout.write(self.style.ERROR(f"  {error}"))
        if report.held:
            self.stdout.write(self.style.WARNING(
                f"\n{report.held} snapshot(s) were stored but not filed. They "
                "are not lost: once the missing binding is approved, run "
                "this command with --file-held.",
            ))
