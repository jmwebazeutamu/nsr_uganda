"""Run duplicate discovery by hand.

The nightly beat task covers normal operation. This is for the cases it
does not: a full sweep after a bulk load or a model-version change, and
seeing what a run produced without waiting for 02:30.
"""

from django.core.management.base import BaseCommand

from apps.ddup.models import MatchPair, PairStatus
from apps.ddup.services import run_discovery


class Command(BaseCommand):
    help = "Run duplicate discovery across all three tiers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full", action="store_true",
            help=(
                "Compare every village block rather than only those holding "
                "a member touched since the last run. At national scale this "
                "is ~2x10^10 comparisons — deliberate, not routine."
            ),
        )
        parser.add_argument("--actor", default="discover-duplicates-command")

    def handle(self, *args, **options):
        before = MatchPair.objects.count()
        run = run_discovery(full=options["full"], actor=options["actor"])
        scope = (
            "full sweep" if run.scanned_from is None
            else f"since {run.scanned_from:%Y-%m-%d %H:%M}"
        )
        self.stdout.write(
            f"discovery run {run.id} ({scope}) — {run.status}\n"
            f"  members considered : {run.members_considered}\n"
            f"  tier 1 (nin)       : {run.tier1_created} new pair(s)\n"
            f"  tier 2 (phone)     : {run.tier2_created} new pair(s)\n"
            f"  tier 3 (fuzzy)     : {run.tier3_created} new pair(s) "
            f"from {run.comparisons} comparison(s)\n"
            f"  pairs before/after : {before} -> {MatchPair.objects.count()}\n"
            f"  pending review now : "
            f"{MatchPair.objects.filter(status=PairStatus.PENDING).count()}"
        )
