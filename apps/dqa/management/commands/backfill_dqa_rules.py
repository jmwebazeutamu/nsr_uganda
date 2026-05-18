"""US-080b — sweep DQA rules against stored records (CLI).

Usage:

    python manage.py backfill_dqa_rules --all
    python manage.py backfill_dqa_rules --rule AC-FORM-1-c6_age_years
    python manage.py backfill_dqa_rules --all --entity member
    python manage.py backfill_dqa_rules --all --dry-run

`--dry-run` evaluates without writing DqaResult rows — useful for
sizing a batch before letting it land.

The audit `rules_backfilled` event lands per-rule even on dry-run,
so the DPO feed picks up the scan intent.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.dqa.backfill import backfill_all, backfill_rule
from apps.dqa.models import DqaRule


class Command(BaseCommand):
    help = "Backfill DAT-DQA rule evaluation across stored records."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument(
            "--all", action="store_true",
            help="Sweep every ACTIVE rule (optionally narrowed by --entity).",
        )
        target.add_argument(
            "--rule", metavar="RULE_ID",
            help="Sweep one rule by rule_id (most recent version).",
        )
        parser.add_argument(
            "--entity", choices=("household", "member"),
            help="When used with --all, restrict to rules of this entity scope.",
        )
        parser.add_argument(
            "--actor", default="system-backfill",
            help="Audit actor identifier. Defaults to 'system-backfill'.",
        )
        parser.add_argument(
            "--batch-size", type=int, default=500,
            help="Records-per-bulk-insert batch (and queryset chunk).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Evaluate without writing DqaResult rows.",
        )

    def handle(self, *args, **opts):
        if opts["rule"]:
            rule = (
                DqaRule.objects.filter(rule_id=opts["rule"])
                .order_by("-version").first()
            )
            if not rule:
                raise CommandError(
                    f"rule_id {opts['rule']!r} not found",
                )
            report = backfill_rule(
                rule, actor=opts["actor"],
                batch_size=opts["batch_size"], dry_run=opts["dry_run"],
            )
            self.stdout.write(self.style.SUCCESS(
                f"{report['rule_id']} v{report['rule_version']} → "
                f"{report['records_scanned']} {report['entity']}(s) scanned, "
                f"{report['failures']} failure(s)",
            ))
            return

        # --all path
        report = backfill_all(
            actor=opts["actor"], batch_size=opts["batch_size"],
            entity=opts["entity"], dry_run=opts["dry_run"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"{report['rules_processed']} rule(s) processed; "
            f"{report['total_records']} record(s) scanned; "
            f"{report['total_failures']} failure(s)",
        ))
        for r in report["reports"]:
            if r.get("skipped"):
                self.stdout.write(self.style.WARNING(
                    f"  ↳ {r['rule_id']}: skipped ({r['reason']})",
                ))
            else:
                self.stdout.write(
                    f"  ↳ {r['rule_id']} v{r['rule_version']}: "
                    f"{r['records_scanned']} {r['entity']}(s), "
                    f"{r['failures']} failure(s)",
                )
