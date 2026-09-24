"""Escalate grievances whose tier deadline has passed.

Nothing did this. Cases sat at a tier thousands of hours past their SLA
with no one above them told, because escalation was only ever a manual
act and the deadline was only ever a number on a screen.

Each run moves a breached case one tier — no further, so a case cannot
jump from L1 to L4 in a single sweep and skip the people in between.
An L4 case has nowhere above it: it is flagged instead, once, so the
NSR unit can see it without the sweep looping on it forever.

Idempotent: a case is only moved when its CURRENT tier's window has
expired, and escalation restarts that window, so a second run
immediately afterwards finds nothing. The L4 flag is set once and
checked before re-flagging.

Actor is "system"; the reason is "SLA breached", per the audit chain
convention for anything a schedule did rather than a person.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.grievance.models import Grievance, GrievanceStatus, Tier
from apps.grievance.services import GrievanceError, escalate
from apps.security.audit import emit

# The states a case can be sitting in while its clock runs. RESOLVED
# and CLOSED are done; nothing is owed.
LIVE_STATES = (
    GrievanceStatus.OPEN,
    GrievanceStatus.IN_PROGRESS,
    GrievanceStatus.ESCALATED,
)

SYSTEM_ACTOR = "system"
BREACH_REASON = "SLA breached"


def breached(now=None):
    """Live cases whose current tier's deadline has passed."""
    now = now or timezone.now()
    return (
        Grievance.objects
        .filter(status__in=LIVE_STATES, sla_deadline__lt=now)
        .order_by("sla_deadline")
    )


class Command(BaseCommand):
    help = "Escalate grievances past their tier SLA; flag breached L4 cases."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without it, nothing is written.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        escalated, flagged, refused = 0, 0, []

        for grievance in breached():
            at_top = grievance.tier == Tier.L4_NSR_UNIT
            if at_top and grievance.sla_breach_flagged_at:
                continue  # already flagged; nothing new to say
            self.stdout.write(
                f"  {grievance.id} [{grievance.status}] {grievance.tier} "
                f"due {grievance.sla_deadline:%Y-%m-%d %H:%M} -> "
                + ("flag" if at_top else "escalate"),
            )
            if not apply:
                escalated += 0 if at_top else 1
                flagged += 1 if at_top else 0
                continue
            try:
                with transaction.atomic():
                    if at_top:
                        grievance.sla_breach_flagged_at = timezone.now()
                        grievance.save(update_fields=[
                            "sla_breach_flagged_at", "updated_at",
                        ])
                        emit(
                            "update", "grievance", grievance.id,
                            actor=SYSTEM_ACTOR, actor_kind="system",
                            reason=f"{BREACH_REASON} at L4 — flagged, "
                                   "no tier above",
                            field_changes={"sla_deadline": str(grievance.sla_deadline)},
                        )
                        flagged += 1
                    else:
                        escalate(
                            grievance, actor=SYSTEM_ACTOR,
                            reason=BREACH_REASON,
                        )
                        escalated += 1
            except GrievanceError as exc:
                refused.append(f"{grievance.id}: {exc}")

        for line in refused:
            self.stdout.write(self.style.WARNING(f"  refused {line}"))
        self.stdout.write("")
        verb = "escalated" if apply else "would escalate"
        self.stdout.write(f"{verb}: {escalated} | flagged at L4: {flagged}")
        if not apply:
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run with --apply.",
            ))
