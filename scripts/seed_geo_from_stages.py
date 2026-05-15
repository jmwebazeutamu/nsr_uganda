"""CLI wrapper around apps.ingestion_hub.geo_backfill (US-S11-015).

After a Kobo pull, StageRecord.canonical_payload carries geographic
codes that may not exist yet in GeographicUnit. This script walks
the staged records and creates any missing rows so the next
promotion attempt finds them.

Live promotion runs auto-call backfill_missing_geo_from_stages
already (US-S11-016 wired it into pull_kobo_submissions_action).
This script remains useful for ops fixing historical gaps or for
ad-hoc backfill outside the admin flow.

Usage:
    .venv/bin/python scripts/seed_geo_from_stages.py
    .venv/bin/python scripts/seed_geo_from_stages.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
django.setup()

from apps.ingestion_hub.geo_backfill import (  # noqa: E402
    LEVEL_ORDER,
    _collect_targets,
    backfill_missing_geo_from_stages,
)
from apps.reference_data.models import GeographicUnit  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Print counts; do not write.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        targets = _collect_targets()
        total = 0
        for level in LEVEL_ORDER:
            wanted = set(targets[level].keys())
            existing = set(
                GeographicUnit.objects.filter(level=level, code__in=wanted)
                                       .values_list("code", flat=True),
            )
            missing = len(wanted - existing)
            present = len(wanted & existing)
            print(f"  {level:11s}  would-create={missing:>4}  already-present={present:>4}")
            total += missing
        print(f"\nDry run: would create {total} row(s).")
        return 0

    result = backfill_missing_geo_from_stages()
    for level in LEVEL_ORDER:
        print(f"  {level:11s}  created={result.by_level[level]:>4}")
    print()
    print(f"Created {result.total_created} row(s); skipped {result.skipped_present} already present.")
    print(f"GeographicUnit total rows: {GeographicUnit.objects.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
