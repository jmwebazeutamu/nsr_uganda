"""Recover section K shock detail the Kobo connector used to drop.

K02-K04 were answered, landed in RawLanding, and discarded at the mapping
step. The connector now carries them, but only for pulls made after the
fix — households already staged or promoted still have nothing. RawLanding
is immutable tier 1 and still holds every answer, so this re-derives the
rows from it.

Dry run by default. `--apply` is required to write, because this touches
staged payloads and creates registry rows for households that are already
promoted.

What it does NOT do: it never overwrites shock rows that already exist,
and it never re-maps anything other than shocks. A household whose stage
payload already carries `shocks` is left alone.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.data_management.models import Shock
from apps.ingestion_hub.connectors.kobo import _kobo_flatten, _kobo_shock_rows
from apps.ingestion_hub.models import RawLanding, StageRecord, StageRecordState
from apps.ingestion_hub.services import _create_shocks, _emit_audit


class Command(BaseCommand):
    help = "Backfill section K shock detail from RawLanding."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without it nothing is modified.",
        )
        parser.add_argument(
            "--actor", default="backfill-shock-detail",
            help="Actor recorded on the audit events.",
        )
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        actor = options["actor"]

        landings = RawLanding.objects.all().order_by("received_at")
        if options["limit"]:
            landings = landings[:options["limit"]]

        scanned = with_detail = staged_updated = promoted_filled = 0
        skipped_has_rows = skipped_no_stage = 0

        for landing in landings.iterator():
            scanned += 1
            # Flatten first. Kobo returns "shocks/k03_crops_shock_type"
            # for a question inside a group and the bare name for one
            # outside it, and both forms are present in the landings.
            # canonicalize() flattens before mapping; reading the landing
            # directly has to do the same or it silently recovers only
            # the ungrouped submissions.
            rows = _kobo_shock_rows(_kobo_flatten(landing.payload or {}))
            if not rows:
                continue
            with_detail += 1

            stage = StageRecord.objects.filter(raw_landing=landing).first()
            if stage is None:
                skipped_no_stage += 1
                continue

            payload = stage.canonical_payload or {}
            already_staged = bool(payload.get("shocks"))
            household_id = stage.promoted_household_id
            already_in_registry = bool(
                household_id
                and Shock.objects.filter(household_id=household_id).exists()
            )
            if already_staged and (already_in_registry or not household_id):
                skipped_has_rows += 1
                continue

            if not apply_changes:
                if not already_staged:
                    staged_updated += 1
                if household_id and not already_in_registry:
                    promoted_filled += 1
                continue

            with transaction.atomic():
                if not already_staged:
                    payload["shocks"] = rows
                    stage.canonical_payload = payload
                    stage.save(update_fields=["canonical_payload"])
                    _emit_audit(
                        "update", "stage_record", stage.id, actor=actor,
                        reason=(
                            "section K shock detail recovered from the raw "
                            "landing; the connector dropped it at mapping time"
                        ),
                    )
                    staged_updated += 1

                # Already in the registry: the promotion fan-out ran before
                # the payload carried any shocks, so the rows have to be
                # created directly. Same function promotion uses, same
                # audit events.
                if (
                    household_id
                    and not already_in_registry
                    and stage.state == StageRecordState.PROMOTED
                ):
                    _create_shocks(
                        stage.promoted_household, {"shocks": rows}, actor=actor,
                    )
                    promoted_filled += 1

        verb = "would be" if not apply_changes else "were"
        self.stdout.write(
            f"scanned {scanned} landing(s); {with_detail} carry section K detail\n"
            f"  {staged_updated} stage payload(s) {verb} updated\n"
            f"  {promoted_filled} promoted household(s) {verb} given Shock rows\n"
            f"  {skipped_has_rows} already had shock rows\n"
            f"  {skipped_no_stage} had no stage record"
        )
        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing written. Re-run with --apply to commit."
            ))
