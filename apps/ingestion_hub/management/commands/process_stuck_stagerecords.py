"""Re-run the staging gates over a batch of StageRecord rows.

Two main use cases:

1. Backfill walk-in submissions that landed before auto-process was
   wired (pre-2026-05-25 commit), or after a connector run that
   crashed before firing the gates. Default --state=provisional.

2. Re-evaluate records after a DQA rule was added or removed.
   Run with --state quality_failed (or any other non-terminal state)
   so records that no longer fail any rule are routed forward.

`process_stage_record` short-circuits on terminal states
(promoted / rejected / quarantined), so those values are rejected
to avoid silent no-ops.

Usage:
    python manage.py process_stuck_stagerecords [--state CSV] [--limit N] [--dry-run]

Examples:
    python manage.py process_stuck_stagerecords
        # default: every provisional record

    python manage.py process_stuck_stagerecords --state quality_failed
        # re-evaluate quality_failed records after rule changes

    python manage.py process_stuck_stagerecords --state provisional,quality_failed,ddup_review
        # comma-separated state list

    python manage.py process_stuck_stagerecords --dry-run
        # list candidates without running the gates
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion_hub.models import StageRecord, StageRecordState
from apps.ingestion_hub.services import DihError, process_stage_record

TERMINAL_STATES = frozenset({
    StageRecordState.PROMOTED,
    StageRecordState.REJECTED,
    StageRecordState.QUARANTINED,
})

VALID_STATES = frozenset(s.value for s in StageRecordState)


class Command(BaseCommand):
    help = "Re-run process_stage_record on every StageRecord in the given state(s)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--state", default=StageRecordState.PROVISIONAL,
            help=(
                "State or comma-separated states to reprocess "
                "(default: provisional). Terminal states "
                "(promoted/rejected/quarantined) are rejected."
            ),
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Stop after N records (default: process every matching row).",
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
        states = [s.strip() for s in opts["state"].split(",") if s.strip()]
        unknown = [s for s in states if s not in VALID_STATES]
        if unknown:
            raise CommandError(f"unknown state(s): {unknown}; valid: {sorted(VALID_STATES)}")
        terminal_requested = [s for s in states if s in TERMINAL_STATES]
        if terminal_requested:
            raise CommandError(
                f"refusing to reprocess terminal state(s) "
                f"{terminal_requested}: process_stage_record short-circuits "
                f"on these; use a separate unmerge/unreject flow instead."
            )

        qs = (
            StageRecord.objects
            .filter(state__in=states)
            .order_by("created_at")
        )
        if opts["limit"]:
            qs = qs[: opts["limit"]]
        rows = list(qs)
        state_label = ",".join(states)
        self.stdout.write(f"found {len(rows)} StageRecord(s) in state {state_label}")
        if opts["dry_run"]:
            for s in rows:
                self.stdout.write(
                    f"  - {s.id} ({s.state}, created {s.created_at:%Y-%m-%d})",
                )
            return

        actor = opts["actor"]
        transitions: dict[str, int] = {}
        failures = 0
        for s in rows:
            before_state = s.state
            try:
                after = process_stage_record(s, actor=actor)
                key = f"{before_state} -> {after.state}"
                transitions[key] = transitions.get(key, 0) + 1
            except DihError as e:
                self.stderr.write(f"FAIL {s.id}: {e}")
                failures += 1
        self.stdout.write(self.style.SUCCESS(
            f"processed {len(rows) - failures} of {len(rows)} "
            f"(failures: {failures})",
        ))
        for transition, count in sorted(transitions.items()):
            self.stdout.write(f"  {transition}: {count}")
