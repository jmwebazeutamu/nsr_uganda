"""Add `refrigerator` to the asset_type ChoiceList (US-117-FRIDGE).

The PMT v1 model (UNHS 2023/24 calibration, ADR-0024) treats owning
a refrigerator as a high-signal asset. The seeded `asset_type` list
shipped with 11 codes (radio, tv, phone, bicycle, motorcycle, car,
bed, mattress, solar, livestock, other); refrigerator was absent.

This migration adds one ChoiceOption with sort_order = 12, appended
after the existing 11 rows so no existing sort_order is renumbered
(stable IDs for any UI that pinned to a position). Idempotent —
`update_or_create` on (choice_list, code, language) is a no-op when
re-applied.

Out of scope here (deliberately, per the implementation review of
US-117-FRIDGE):
- Authoring the G15 FormSection / FormQuestion so a CAPI submission
  can capture the new asset. The questionnaire structure is not yet
  authored as first-class models; that's a separate ticket.
- Adding a PMT DSL variable + the +0.157 coefficient for
  owns_refrigerator. The ticket assumed the seed already had it, but
  the PMT seed only instruments radio/tv/motorcycle today. PMT
  amendment routes through the recalibration review (ADR-0023).
- Cloning the asset_type ChoiceList to v(N+1). The existing v1 row
  is in ACTIVE status; adding a new ChoiceOption to an active list
  is additive (existing rows untouched), and there is no `clone_
  choice_list` service today. Re-versioning is a separate refactor.

The ingestion path (apps.ingestion_hub.services._create_assets)
accepts any asset_type string and writes an AssetOwnership row
without validating against ChoiceOption — so a canonical_payload
carrying `{"asset_type": "refrigerator", "count": N}` rounds-trips
into the registry as soon as this migration runs.

Forward-only per ADR-0003. Reverse path removes only the
refrigerator row.
"""

from __future__ import annotations

from django.db import migrations


def _add_refrigerator(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    # The active v1 list seeded in 0003_seed_choice_lists. If for any
    # reason it isn't there (a partial seed in a deployment from
    # before 0003 landed), bail silently — the next seed run will
    # cover us.
    cl = (
        ChoiceList.objects
        .filter(list_name="asset_type", version=1)
        .order_by("-effective_from")
        .first()
    )
    if cl is None:
        return

    # Append at the next free sort_order so existing rows don't shift.
    # get_or_create (rather than update_or_create) so a fresh DB where
    # the JSON seed already placed `refrigerator` at sort_order 12 via
    # migration 0003 isn't re-numbered by this follow-up migration.
    # On upgrade paths (DB ran 0003 before the JSON carried
    # refrigerator), the row is created fresh at the next slot.
    next_order = (
        ChoiceOption.objects.filter(choice_list=cl)
        .order_by("-sort_order")
        .values_list("sort_order", flat=True)
        .first()
        or 0
    ) + 1

    ChoiceOption.objects.get_or_create(
        choice_list=cl, code="refrigerator", language="en",
        defaults={
            "label": "Refrigerator / freezer",
            "sort_order": next_order,
            "status": "active",
        },
    )


def _remove_refrigerator(apps, schema_editor):
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    ChoiceOption.objects.filter(
        choice_list__list_name="asset_type",
        choice_list__version=1,
        code="refrigerator",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0011_seed_programme_signoff_status"),
    ]

    operations = [
        migrations.RunPython(_add_refrigerator, _remove_refrigerator),
    ]
