"""Seed the Kigezi sub-region geographic chain for the Kobo E2E pilot.

Creates the minimal GeographicUnit chain that lets the user's actual
Kobo submission promote into a Household — Western → Kigezi → district
412 → county 412.02 → sub-county 412.02.05 → parish 412.02.05.01 → a
fabricated village row keyed by the village name.

This is a stopgap until the real UBOS workbook is supplied to
scripts/load_ubos_geography.py. Both loaders use the same code
conventions so they can coexist; idempotent — re-running this is a
no-op once rows are present.

Usage:
    .venv/bin/python scripts/seed_kigezi_geo.py
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
django.setup()

from apps.reference_data.models import GeographicUnit  # noqa: E402
from django.db import transaction  # noqa: E402

EFFECTIVE_FROM = date(2026, 1, 1)


# Geographic chain matching the Kobo NSR socio-economic questionnaire's
# encoding once it passes through kobo_to_canonical(). Each tuple is
# (level, code, name, parent_code-or-None). Parent is resolved by
# code lookup at insert time so the rows can be listed in any order.
CHAIN = [
    ("region",     "R-WESTERN",                       "Western",          None),
    ("sub_region", "SR-KIGEZI-WESTERN",               "Kigezi",           "R-WESTERN"),
    ("district",   "412",                             "Rukungiri",        "SR-KIGEZI-WESTERN"),
    ("county",     "412.02",                          "Nyakagyeme",       "412"),
    ("sub_county", "412.02.05",                       "Kabwoma",          "412.02"),
    ("parish",     "412.02.05.01",                    "Kabwoma Parish",   "412.02.05"),
    ("village",    "412.02.05.01.AKELLO-VILLAGE",     "Akello Village",   "412.02.05.01"),
]


@transaction.atomic
def main() -> int:
    cache: dict[str, GeographicUnit] = {}
    created = 0
    skipped = 0
    for level, code, name, parent_code in CHAIN:
        existing = GeographicUnit.objects.filter(
            level=level, code=code, effective_from=EFFECTIVE_FROM,
        ).first()
        if existing is not None:
            cache[code] = existing
            skipped += 1
            continue
        parent = cache.get(parent_code) if parent_code else None
        if parent_code and parent is None:
            # Look it up from DB in case it was created in a prior run.
            parent = GeographicUnit.objects.filter(code=parent_code).first()
        row = GeographicUnit.objects.create(
            level=level, code=code, name=name, parent=parent,
            effective_from=EFFECTIVE_FROM,
        )
        cache[code] = row
        created += 1
        print(f"  + {level:11s} {code:35s} {name}")
    print(f"\nKigezi seed: {created} created, {skipped} already present.")
    print(f"GeographicUnit total rows: {GeographicUnit.objects.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
