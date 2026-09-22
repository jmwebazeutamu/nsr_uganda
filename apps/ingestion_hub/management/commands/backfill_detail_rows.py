"""Recover section K and section L detail the Kobo connector used to drop.

K02-K04 (which livelihood, what shock, how severe) were answered, landed
in RawLanding, and discarded at the mapping step. Section L was carried
into the payload but under a key promotion does not read, so no
CopingStrategy row was ever created either.

Both are fixed for new pulls. Households already staged or promoted still
have nothing, and RawLanding is immutable tier 1 and still holds every
answer, so this re-derives the rows from it.

Dry run by default. `--apply` is required to write, because this touches
staged payloads and creates registry rows for households already
promoted.

It never overwrites rows that already exist, and it re-maps nothing other
than shocks and coping.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.data_management.models import CopingStrategy, Shock
from apps.ingestion_hub.connectors.kobo import (
    _kobo_coping_rows, _kobo_flatten, _kobo_shock_rows,
)
from apps.ingestion_hub.models import RawLanding, StageRecord, StageRecordState
from apps.ingestion_hub.services import (
    _create_coping_strategies, _create_shocks, _emit_audit,
)

# (payload key, row builder, registry model, create function, label)
ENTITIES = (
    ("shocks", _kobo_shock_rows, Shock, _create_shocks, "shock"),
    ("coping_strategies", _kobo_coping_rows, CopingStrategy,
     _create_coping_strategies, "coping"),
)


class Command(BaseCommand):
    help = "Backfill section K shock and section L coping rows from RawLanding."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without it nothing is modified.",
        )
        parser.add_argument("--actor", default="backfill-detail-rows")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--only", choices=[key for key, *_ in ENTITIES], default=None,
            help="Restrict to one entity.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        actor = options["actor"]
        entities = [e for e in ENTITIES if not options["only"] or e[0] == options["only"]]

        landings = RawLanding.objects.all().order_by("received_at")
        if options["limit"]:
            landings = landings[:options["limit"]]

        scanned = skipped_no_stage = 0
        staged = {key: 0 for key, *_ in entities}
        promoted = {key: 0 for key, *_ in entities}
        already = {key: 0 for key, *_ in entities}

        for landing in landings.iterator():
            scanned += 1
            # Flatten first. Kobo returns "shocks/k03_crops_shock_type" for
            # a question inside a group and the bare name for one outside
            # it, and both forms are present in the landings.
            # canonicalize() flattens before mapping; reading a landing
            # directly has to do the same or it silently recovers only the
            # ungrouped submissions.
            flat = _kobo_flatten(landing.payload or {})
            derived = {key: build(flat) for key, build, *_ in entities}
            if not any(derived.values()):
                continue

            stage = StageRecord.objects.filter(raw_landing=landing).first()
            if stage is None:
                skipped_no_stage += 1
                continue

            payload = stage.canonical_payload or {}
            household_id = stage.promoted_household_id
            touched = False

            for key, _build, model, create, label in entities:
                rows = derived[key]
                if not rows:
                    continue
                in_payload = bool(payload.get(key))
                in_registry = bool(
                    household_id
                    and model.objects.filter(household_id=household_id).exists()
                )
                if in_payload and (in_registry or not household_id):
                    already[key] += 1
                    continue

                if not apply_changes:
                    if not in_payload:
                        staged[key] += 1
                    if household_id and not in_registry:
                        promoted[key] += 1
                    continue

                with transaction.atomic():
                    if not in_payload:
                        payload[key] = rows
                        touched = True
                        staged[key] += 1
                    # Already in the registry: the promotion fan-out ran
                    # before the payload carried these, so the rows have to
                    # be created directly. Same function promotion uses,
                    # same audit events.
                    if (
                        household_id
                        and not in_registry
                        and stage.state == StageRecordState.PROMOTED
                    ):
                        create(stage.promoted_household, {key: rows}, actor=actor)
                        promoted[key] += 1

            if apply_changes and touched:
                stage.canonical_payload = payload
                stage.save(update_fields=["canonical_payload"])
                _emit_audit(
                    "update", "stage_record", stage.id, actor=actor,
                    reason=(
                        "section K/L detail recovered from the raw landing; "
                        "the connector dropped it at mapping time"
                    ),
                )

        verb = "would be" if not apply_changes else "were"
        self.stdout.write(f"scanned {scanned} landing(s)")
        for key, *_rest in entities:
            self.stdout.write(
                f"  {key}: {staged[key]} stage payload(s) {verb} updated, "
                f"{promoted[key]} promoted household(s) {verb} given rows, "
                f"{already[key]} already had them"
            )
        self.stdout.write(f"  {skipped_no_stage} landing(s) had no stage record")
        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing written. Re-run with --apply to commit."
            ))
