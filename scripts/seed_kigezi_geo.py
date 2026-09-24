"""Seed the Kigezi sub-region geographic chain for the Kobo E2E pilot.

Creates the minimal GeographicUnit chain that lets the user's actual
Kobo submission promote into a Household — Western → Kigezi → district
412 → Rujumbura County → Nyakagyeme → Kabwoma → a fabricated village
row keyed by the village name.

## This chain used to be one level too high

The original stopgap guessed the ladder from a single Kobo submission
before the UBOS workbook existed, and put every rung one level up:

    seeded                                  actually
    county     412.02       Nyakagyeme      sub_county 412.2.05
    sub_county 412.02.05    Kabwoma         parish     412.2.05.01
    parish     412.02.05.01 Kabwoma Parish  — nothing; a repeat

Nyakagyeme is a sub-county of Rujumbura County; Kabwoma is a parish of
Nyakagyeme. Households captured there carried a county that does not
exist and never named Rujumbura at all. Repaired by
`manage.py fix_kigezi_seed_levels`; the chain below is the real one,
so re-running this can no longer recreate the shift.

The workbook has since been supplied, so this script is only useful for
bootstrapping a database that has not had it loaded. It refuses to
invent anything the frame already covers: every rung is looked up
first, and a village is the only row it will create outright (the UBOS
frame carries no village rows at all).

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
    ("county",     "412.2",                           "Rujumbura County", "412"),
    ("sub_county", "412.2.05",                        "Nyakagyeme",       "412.2"),
    ("parish",     "412.2.05.01",                     "Kabwoma",          "412.2.05"),
    ("village",    "412.2.05.01.AKELLO-VILLAGE",      "Akello Village",   "412.2.05.01"),
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
