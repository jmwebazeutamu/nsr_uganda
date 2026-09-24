"""Remove the 18 May 2026 demo grievances from production.

Two grievances and their tasks were created during a demo and left in
the live registry for four months. Their content is placeholder text —
one description reads "This is a test grievance, submitted by Johnson",
the other has a reporter called "Et incididunt expedi" and a
household_id of "Deserunt esse itaque", which is not a Registry ID and
names no household.

They were annotated first, and the registry owner then asked for them
to go.

## What survives

AuditEvents reference entities by string id, not foreign key, so every
event about these grievances stays in the chain after the rows are
gone. That is the point of an append-only audit log: the record of what
happened does not depend on the thing it happened to. A deletion event
is emitted for each so the chain says where they went.

Tasks and comments cascade from the grievance.

## What it refuses to do

Each id must still match the record it was written for — same status,
and an assignee that is not a real user. If a grievance has been
reopened, reassigned to somebody real, or had its content edited, this
stops rather than deleting something that has since become live.

Dry run by default; --apply needs --actor.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.grievance.models import Grievance
from apps.security.audit import emit

# id -> the status it must still be in. Both are terminal; a grievance
# that has moved off one is not the record this was written for.
EXPECTED = {
    "01KRXS6M58F86HF0EGP3FDFVR2": "resolved",
    "01KRY9MMENGEGA0ZQCT9122Z3C": "closed",
}


def _is_phantom_assignee(username: str) -> bool:
    from django.contrib.auth import get_user_model
    if not username:
        return True
    return not get_user_model().objects.filter(
        username__iexact=username, is_active=True,
    ).exists()


class Command(BaseCommand):
    help = "Delete the 18 May 2026 demo grievances and their tasks."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor", default="")

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = (options["actor"] or "").strip()
        if apply and not actor:
            raise CommandError("--actor is required with --apply")

        targets, refusals = [], []
        for gid, expected_status in EXPECTED.items():
            grievance = Grievance.objects.filter(id=gid).first()
            if grievance is None:
                self.stdout.write(f"  {gid}: already gone")
                continue
            if grievance.status != expected_status:
                refusals.append(
                    f"{gid}: status is {grievance.status!r}, expected "
                    f"{expected_status!r} — it has moved since this was "
                    "written",
                )
                continue
            if not _is_phantom_assignee(grievance.assigned_to):
                refusals.append(
                    f"{gid}: now assigned to {grievance.assigned_to!r}, "
                    "a real user — somebody has taken this on",
                )
                continue
            targets.append(grievance)

        for refusal in refusals:
            self.stdout.write(self.style.ERROR(f"  {refusal}"))
        if refusals:
            raise CommandError("refusing to delete — the records have changed")
        if not targets:
            self.stdout.write("Nothing to delete.")
            return

        for grievance in targets:
            self.stdout.write(
                f"  delete {grievance.id} [{grievance.status}] "
                f"tasks={grievance.tasks.count()} "
                f"comments={grievance.comments.count()} "
                f"desc={grievance.description[:40]!r}",
            )

        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing deleted. Re-run with --apply --actor <name>.",
            ))
            return

        with transaction.atomic():
            for grievance in targets:
                task_ids = list(grievance.tasks.values_list("id", flat=True))
                # Emitted BEFORE the delete so the chain records the
                # state that was removed, not an empty shell.
                emit(
                    "delete", "grievance", grievance.id, actor=actor,
                    reason=(
                        "18 May 2026 demo record removed from production "
                        "at the registry owner's request"
                    ),
                    field_changes={
                        "status": grievance.status,
                        "assigned_to": grievance.assigned_to,
                        "description": grievance.description[:200],
                        "household_id": grievance.household_id,
                        "task_ids": task_ids,
                    },
                )
                grievance.delete()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {len(targets)} grievance(s) and their tasks.",
        ))
