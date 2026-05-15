"""Backfill missing GeographicUnit rows from staged canonical payloads.

After a Kobo pull, StageRecord.canonical_payload carries the
geographic codes the records reference. If those codes don't exist
yet in the GeographicUnit table, promotion fails with
"geographic unit {level}={code} not found". This script walks the
staged records and creates any missing rows so the next promotion
attempt finds them.

Names: the form supplies names only for region/sub_region/village
(captured in _source_keys.kobo_region_name etc.). District / county
/ sub_county / parish carry only codes — for those, the code
doubles as the name placeholder until the UBOS workbook is loaded.

Idempotent. Parent FKs are wired by walking levels in order:
region first, then sub_region (with region as parent), etc.

Usage:
    .venv/bin/python scripts/seed_geo_from_stages.py
    .venv/bin/python scripts/seed_geo_from_stages.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
django.setup()

from apps.ingestion_hub.models import StageRecord  # noqa: E402
from apps.reference_data.models import GeographicUnit  # noqa: E402
from django.db import transaction  # noqa: E402

EFFECTIVE_FROM = date(2026, 1, 1)

# Hierarchical relationships. Each level's parent is the previous one
# in the list. Codes are processed in this order so parent FKs resolve.
LEVEL_ORDER = [
    "region", "sub_region", "district", "county",
    "sub_county", "parish", "village",
]


def _name_for(level: str, code: str, source_keys: dict) -> str:
    """Best display name for a freshly-fabricated row. Region,
    sub_region and village have names in the Kobo source; the rest
    fall back to the code so the operator at least sees something
    deterministic in the admin UI."""
    if level == "region":
        return source_keys.get("kobo_region_name", "").title() or code
    if level == "sub_region":
        return source_keys.get("kobo_subregion_name", "").title() or code
    if level == "village":
        return source_keys.get("kobo_village_name", "") or code
    return code  # district / county / sub_county / parish


def _parent_code(level: str, geo: dict) -> str | None:
    """Resolve the parent's code for `level` from the geographic
    dict. district's parent is sub_region, etc. None for region."""
    parent_level = {
        "sub_region": "region",
        "district": "sub_region",
        "county": "district",
        "sub_county": "county",
        "parish": "sub_county",
        "village": "parish",
    }.get(level)
    if parent_level is None:
        return None
    return geo.get(parent_level) or None


def collect_targets() -> dict[str, dict[str, dict]]:
    """Walk all stages with a geographic block; return a nested map
    `targets[level][code] = {"name": str, "parent_code": str | None}`."""
    targets: dict[str, dict[str, dict]] = {lvl: {} for lvl in LEVEL_ORDER}
    for stage in StageRecord.objects.iterator():
        payload = stage.canonical_payload or {}
        geo = payload.get("geographic") or {}
        sk = payload.get("_source_keys") or {}
        for level in LEVEL_ORDER:
            code = geo.get(level)
            if not code:
                continue
            entry = targets[level].setdefault(code, {
                "name": _name_for(level, code, sk),
                "parent_code": _parent_code(level, geo),
            })
            # If a later stage carries a better name (non-placeholder),
            # promote it. Important for village rows where the name is
            # the only useful display.
            better = _name_for(level, code, sk)
            if entry["name"] == code and better != code:
                entry["name"] = better
    return targets


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true",
                   help="Print counts; do not write.")
    return p.parse_args()


@transaction.atomic
def main() -> int:
    args = parse_args()
    targets = collect_targets()

    total_required = sum(len(by_code) for by_code in targets.values())
    print(f"Distinct (level, code) tuples referenced by stages: {total_required}")

    created_total = 0
    skipped_total = 0
    # Cache of (level, code) -> GeographicUnit so we don't requery
    # for every parent lookup.
    cache: dict[tuple[str, str], GeographicUnit] = {}

    for level in LEVEL_ORDER:
        by_code = targets[level]
        if not by_code:
            continue
        created = 0
        skipped = 0
        for code, payload in by_code.items():
            existing = GeographicUnit.objects.filter(level=level, code=code).first()
            if existing is not None:
                cache[(level, code)] = existing
                skipped += 1
                continue
            parent = None
            parent_code = payload["parent_code"]
            if parent_code:
                parent_level = LEVEL_ORDER[LEVEL_ORDER.index(level) - 1]
                parent = cache.get((parent_level, parent_code))
                if parent is None:
                    parent = GeographicUnit.objects.filter(
                        level=parent_level, code=parent_code,
                    ).first()
            if args.dry_run:
                created += 1
                continue
            row = GeographicUnit.objects.create(
                level=level, code=code, name=payload["name"],
                parent=parent, effective_from=EFFECTIVE_FROM,
            )
            cache[(level, code)] = row
            created += 1
        print(f"  {level:11s}  created={created:>4}  already-present={skipped:>4}")
        created_total += created
        skipped_total += skipped

    print()
    if args.dry_run:
        print(f"Dry run: would create {created_total} row(s).")
    else:
        print(f"Created {created_total} row(s); skipped {skipped_total} already present.")
        print(f"GeographicUnit total rows: {GeographicUnit.objects.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
