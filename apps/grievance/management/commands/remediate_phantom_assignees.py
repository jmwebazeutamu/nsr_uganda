"""Deal with the grievances assigned to people who do not exist.

Before assignment was validated against the user catalogue, the console
offered four invented names — "Adong Florence · CDO Tapac" and friends
— and the task modal a free-text username box. Whatever was typed went
into `assigned_to`. Production ended up with three grievances and six
tasks pointing at nobody.

Looking at them changed what the right fix was. All six tasks are
CLOSED and all three grievances date from a single demo run on
18 May 2026; most of the content is placeholder text ("Quia ullam omnis
ut", a reporter called "Et incididunt expedi", a household_id of
"Deserunt esse itaque"). Only ONE record is live work.

So this does two different things:

  * the live grievance is REASSIGNED, through the normal service, so it
    validates, audits and notifies like any other assignment;
  * the rest keep their assignee and get a COMMENT saying what they
    are. Who held a closed case is audit history. Rewriting it would
    put a real operator's name against a task titled "Test Test", which
    is worse than the phantom it replaces — the phantom at least does
    not implicate anyone.

Refuses to act on a record whose assignee is no longer a phantom, so a
re-run after someone has tidied up by hand does nothing.

Dry run by default; --apply needs --actor.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.grievance.models import Grievance
from apps.grievance.services import GrievanceError, add_comment, assign

# The one grievance that is real work, and who owns it. Chosen by the
# registry owner: it carries no household and no geography, so nothing
# in the record could pick an assignee on its own.
REASSIGN = {
    "01KRXTVG4X397NEDX6E9J0QYD0": "johnsonmwebaze",
}

# Grievances kept as-is, with a note. The text says what the record is,
# because in a year nobody will remember that 18 May was a demo.
ANNOTATE = {
    "01KRXS6M58F86HF0EGP3FDFVR2": (
        "Test record from the 18 May 2026 demo run — the description "
        "says so outright. Resolved, with one placeholder task and one "
        "titled \"Test Test\". Its assignee was one of four invented "
        "names the console offered before assignees were checked "
        "against the user catalogue; the value is left as the record of "
        "what the field held, not as a pointer to a person. Nothing is "
        "outstanding."
    ),
    "01KRY9MMENGEGA0ZQCT9122Z3C": (
        "Test record from the 18 May 2026 demo run: the description, "
        "the reporter name and phone, and the household_id are all "
        "placeholder text — \"Deserunt esse itaque\" is not a Registry "
        "ID and names no household. Closed, with two placeholder tasks. "
        "Its assignee was one of the console's four invented names and "
        "is left as the record of what the field held. Nothing is "
        "outstanding."
    ),
}

# A note for the live grievance too — its own tasks came from the same
# run, and whoever picks it up should know the tasks are not evidence.
REASSIGN_NOTE = (
    "Reassigned from \"{was}\", which was never a user account — the "
    "console offered four invented names before assignees were checked "
    "against the user catalogue. The two closed tasks on this grievance "
    "carry placeholder titles from the 18 May 2026 demo run and are not "
    "a record of work done. The grievance itself reads as a real "
    "complaint and is still open."
)


def _is_phantom(username: str) -> bool:
    from django.contrib.auth import get_user_model
    if not username:
        return False
    return not get_user_model().objects.filter(
        username__iexact=username, is_active=True,
    ).exists()


class Command(BaseCommand):
    help = "Reassign the one live grievance; annotate the test records."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor", default="")

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = (options["actor"] or "").strip()
        if apply and not actor:
            raise CommandError("--actor is required with --apply")

        plan, skipped = [], []

        for gid, new_owner in REASSIGN.items():
            grievance = Grievance.objects.filter(id=gid).first()
            if grievance is None:
                skipped.append(f"{gid}: not found")
                continue
            if not _is_phantom(grievance.assigned_to):
                skipped.append(
                    f"{gid}: already assigned to {grievance.assigned_to!r} "
                    "— leaving alone",
                )
                continue
            plan.append(("reassign", grievance, new_owner))

        for gid, note in ANNOTATE.items():
            grievance = Grievance.objects.filter(id=gid).first()
            if grievance is None:
                skipped.append(f"{gid}: not found")
                continue
            if grievance.comments.filter(body=note).exists():
                skipped.append(f"{gid}: already annotated")
                continue
            plan.append(("annotate", grievance, note))

        for line in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {line}"))
        if not plan:
            self.stdout.write("Nothing to do.")
            return

        for kind, grievance, payload in plan:
            if kind == "reassign":
                self.stdout.write(
                    f"  reassign {grievance.id} [{grievance.status}] "
                    f"{grievance.assigned_to!r} -> {payload!r}",
                )
            else:
                self.stdout.write(
                    f"  annotate {grievance.id} [{grievance.status}] "
                    f"(assignee {grievance.assigned_to!r} kept)",
                )

        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run with --apply --actor <name>.",
            ))
            return

        with transaction.atomic():
            for kind, grievance, payload in plan:
                if kind == "reassign":
                    was = grievance.assigned_to
                    try:
                        assign(grievance, assigned_to=payload, actor=actor)
                    except GrievanceError as exc:
                        raise CommandError(
                            f"{grievance.id}: {exc}",
                        ) from exc
                    add_comment(
                        grievance, body=REASSIGN_NOTE.format(was=was),
                        actor=actor,
                    )
                else:
                    add_comment(grievance, body=payload, actor=actor)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Done: {sum(1 for k, _, _ in plan if k == 'reassign')} reassigned, "
            f"{sum(1 for k, _, _ in plan if k == 'annotate')} annotated.",
        ))
