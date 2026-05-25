"""Backfill orchestrator for StageRecord rows stuck in `provisional`.

Use case: walk-in submissions that landed before auto-process was
wired (pre-2026-05-25), or after a connector run that crashed before
firing the gates. Loops over every provisional record and runs
process_stage_record on it; failures are reported but do not stop
the run.

Usage:
    python manage.py process_stuck_stagerecords [--limit N] [--dry-run]

The default actor name (`backfill-job`) is recorded on every audit
event so the operation is traceable.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ingestion_hub.models import StageRecord, StageRecordState
from apps.ingestion_hub.services import DihError, process_stage_record


class Command(BaseCommand):
    help = "Run process_stage_record on every StageRecord stuck at provisional."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Stop after N records (default: process every stuck row).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List candidates without running the gates.",
        )
        parser.add_argument(
            "--actor", default="backfill-job",
            help="Audit-event actor name (default: backfill-job).",
        )

    def handle(self, *args, **opts):
        qs = (
            StageRecord.objects
            .filter(state=StageRecordState.PROVISIONAL)
            .order_by("created_at")
        )
        if opts["limit"]:
            qs = qs[: opts["limit"]]
        rows = list(qs)
        self.stdout.write(f"found {len(rows)} provisional StageRecord(s)")
        if opts["dry_run"]:
            for s in rows:
                self.stdout.write(f"  - {s.id} (created {s.created_at:%Y-%m-%d})")
            return

        actor = opts["actor"]
        transitions: dict[str, int] = {}
        failures = 0
        for s in rows:
            try:
                after = process_stage_record(s, actor=actor)
                transitions[after.state] = transitions.get(after.state, 0) + 1
            except DihError as e:
                self.stderr.write(f"FAIL {s.id}: {e}")
                failures += 1
        self.stdout.write(self.style.SUCCESS(
            f"processed {len(rows) - failures} of {len(rows)} "
            f"(failures: {failures})",
        ))
        for state, count in sorted(transitions.items()):
            self.stdout.write(f"  -> {state}: {count}")
