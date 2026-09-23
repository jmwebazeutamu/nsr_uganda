"""Author a new DdupModelVersion carrying explicit tier-3 weights.

Authors a DRAFT and stops. Activation is dual approval (SAD
AC-DDUP-MODEL-VERSION) and belongs to the Ministry — a match model
decides which two people the registry treats as one, and this command
does not get to make that call.

Why a new version at all:

The active version carries no `tier3` section, so the weights actually in
force are the fallback defaults in services.py, which nobody has ever
approved. Among those defaults, `village` is weighted 0.15 while tier 3
blocks BY village — so it is 1.0 for every pair the model ever compares.
It cannot separate two candidates; it simply adds 0.15 to all of them and
moves everything closer to the threshold.

The proposal removes it and redistributes to the features that do
discriminate. Run with --show to see the effect before authoring.
"""

from django.core.management.base import BaseCommand

from apps.ddup.models import DdupModelVersion, ModelStatus

# Village is gone: blocking guarantees it. The remainder is weighted
# towards the two features that most often separate two people who share
# a village and a birth cohort — their names.
PROPOSED = {
    "weights": {
        "surname": 0.35,
        "first_name": 0.35,
        "date_of_birth": 0.20,
        "sex": 0.10,
    },
    "threshold": 0.85,
    "auto_merge_threshold": 0.95,
    # Still off. The first production run produced a 0.967 pair that was
    # two different people; that is the evidence for leaving this alone
    # until a reviewer has worked through a sample.
    "auto_merge_enabled": False,
}

CURRENT_DEFAULTS = {
    "surname": 0.30, "first_name": 0.30,
    "date_of_birth": 0.15, "sex": 0.10, "village": 0.15,
}


class Command(BaseCommand):
    help = "Propose tier-3 weights as a new DRAFT DdupModelVersion."

    def add_arguments(self, parser):
        parser.add_argument("--show", action="store_true",
                            help="Print the comparison and write nothing.")
        parser.add_argument("--author", default="propose-tier3-weights")

    def handle(self, *args, **options):
        active = DdupModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()
        in_force = ((active.config or {}).get("tier3") or {}).get("weights") \
            or CURRENT_DEFAULTS
        source = "the active version" if (active and (active.config or {}).get("tier3")) \
            else "services.py defaults (the active version sets none)"

        self.stdout.write(f"weights in force, from {source}:")
        for k in sorted(set(in_force) | set(PROPOSED["weights"])):
            before = in_force.get(k)
            after = PROPOSED["weights"].get(k)
            mark = "  <- removed" if after is None else ("  <- changed" if before != after else "")
            self.stdout.write(
                f"  {k:<16} {str(before if before is not None else '—'):>6}"
                f"  ->  {str(after if after is not None else '—'):>6}{mark}",
            )

        if options["show"]:
            self.stdout.write(self.style.WARNING("\n--show: nothing written."))
            return

        if active and (active.config or {}).get("tier3", {}).get("weights") == PROPOSED["weights"]:
            self.stdout.write(self.style.WARNING(
                "\nThe active version already carries these weights — nothing to propose.",
            ))
            return

        next_version = (DdupModelVersion.objects.order_by("-version")
                        .values_list("version", flat=True).first() or 0) + 1
        config = dict((active.config if active else {}) or {})
        config["tier3"] = PROPOSED
        draft = DdupModelVersion.objects.create(
            version=next_version,
            description=(
                "Tier-3 weights, stated rather than defaulted. Removes "
                "`village`, which blocking fixes at 1.0 for every compared "
                "pair, and redistributes to surname, first name and date of "
                "birth. Proposed after the first production discovery run "
                "scored two different people in one household at 0.967."
            ),
            config=config,
            author=options["author"],
            status=ModelStatus.DRAFT,
        )
        self.stdout.write(self.style.SUCCESS(
            f"\nDdupModelVersion v{draft.version} authored as DRAFT.\n"
            f"Nothing is live: the active version is unchanged. Activation "
            f"is dual approval and the approver must not be "
            f"{options['author']!r}.",
        ))
