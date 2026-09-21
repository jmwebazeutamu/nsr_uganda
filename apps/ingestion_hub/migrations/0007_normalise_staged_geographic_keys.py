"""Canonicalise the geographic chain on staged records.

Two separate corruptions of the same field, both of which made a staged
record disagree with the registry about where its household is.

1. LEVEL KEY SPELLING.  The capture wizard's form state used `subregion`
   and `subcounty`; the registry resolves the ladder by `sub_region` and
   `sub_county`. The wizard posted its state verbatim, so every walk-in
   capture failed promotion on "canonical_payload.geographic.sub_region
   required" — and the walk-in endpoint swallowed the DihError, leaving
   the record at `provisional` with an empty dqa_summary, which the
   review queue renders as "clean · 0 blocking · 0 warnings".

   Four captures had been taken. Four records were stuck. Nothing
   anywhere said so.

2. FREE-TEXT REGION VALUES.  The review queue's Region filter listed
   four regions as six options — "Northern" beside "R-NORTHERN",
   "Western" beside "R-WESTERN" — and picking one returned a subset with
   no indication the rest existed. That turned out to be a read-side
   fault (the row was keyed on whatever display name its connector left
   lying around, not on the code), fixed in screens-dih.jsx.

   This migration covers the other direction: a record whose geographic
   chain actually STORES a region name rather than a code. There are
   none on the development database — the Kobo connector has always
   written `R-{SLUG}` and kept the name in `_source_keys` — but that is
   a statement about this database, not about every environment, and a
   name stored in the chain is unresolvable by promotion's `_geo()`
   lookup. Idempotent, so running it where there is nothing to do is
   free.

Names are resolved against ACTIVE GeographicUnits only. Resolving by
name alone would map "Northern" to UG-N, the retired duplicate that
reference_data.0018 retired precisely because it was a dead end.

Raw landings are NOT touched: RawLanding is append-only by contract
(AC-DIH-LANDING-IMMUTABLE), and the whole point of keeping it is that it
still shows what the source actually sent.

Forward-only per ADR-0003. The reverse is a no-op — putting a record
back on a spelling that cannot be promoted is not a state worth being
able to return to.
"""

from __future__ import annotations

from django.db import migrations

# canonical level key -> the wizard's historical spelling
LEVEL_ALIASES = {
    "sub_region": "subregion",
    "sub_county": "subcounty",
}


def _normalise(apps, schema_editor):
    StageRecord = apps.get_model("ingestion_hub", "StageRecord")
    GeographicUnit = apps.get_model("reference_data", "GeographicUnit")

    # name -> code, ACTIVE rows only, so "Northern" cannot resolve to
    # the retired UG-N.
    by_name = {
        unit.name.strip().casefold(): unit.code
        for unit in GeographicUnit.objects.filter(level="region", status="active")
    }
    valid_codes = set(by_name.values())

    updated = []
    for stage in StageRecord.objects.all().only("id", "canonical_payload").iterator():
        payload = stage.canonical_payload
        if not isinstance(payload, dict):
            continue
        geo = payload.get("geographic")
        if not isinstance(geo, dict):
            continue

        fixed = dict(geo)
        changed = False

        # 1. Copy an aliased level onto its canonical key. The alias is
        #    left in place: it is what the wizard sent, and the two
        #    agreeing is easier to audit than one having been erased.
        for canonical, alias in LEVEL_ALIASES.items():
            if not fixed.get(canonical) and geo.get(alias):
                fixed[canonical] = geo[alias]
                changed = True

        # 2. Region stored as a name rather than a code.
        region = (fixed.get("region") or "").strip()
        if region and region not in valid_codes:
            resolved = by_name.get(region.casefold())
            if resolved:
                labels = dict(fixed.get("_labels") or {})
                labels.setdefault("region", region)   # keep what was shown
                fixed["_labels"] = labels
                fixed["region"] = resolved
                changed = True

        if changed:
            payload = dict(payload)
            payload["geographic"] = fixed
            stage.canonical_payload = payload
            updated.append(stage)

    for i in range(0, len(updated), 500):
        StageRecord.objects.bulk_update(
            updated[i:i + 500], ["canonical_payload"],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion_hub", "0006_seed_nsr_unit_coordinator_group"),
        # Needs UG-N already retired, so a name lookup cannot land on it.
        ("reference_data", "0018_retire_duplicate_northern_region"),
    ]

    operations = [
        migrations.RunPython(_normalise, migrations.RunPython.noop),
    ]
