"""Loader for the UBOS administrative hierarchy from the supplied workbook.

Sprint 0 item 3 per CLAUDE.md and SAD §11.4.

Input file shape (header row, then 10,854 data rows in the May 2026 supply):
    District_code | District_Name | County_code | County_Name |
    Subcounty_code | Subcounty_Name | Parish_code | Parish_Name

Coverage gap: this source only carries four levels (district to parish).
The schema supports seven (region, sub_region, district, county, sub_county,
parish, village). Region and sub_region come from a separate UBOS sheet
that has not been supplied yet; village polygons depend on DQA-O-03 (UBOS
village polygons availability). The loader leaves those levels empty.

Codes are composed hierarchically so they are globally unique per level
(the raw codes in the file are scoped within their parent, so subcounty
code "01" appears thousands of times):

    District:    "101"
    County:      "101.1"
    Subcounty:   "101.1.01"
    Parish:      "101.1.01.01"

Idempotent: the unique constraint on (level, code, effective_from) lets
re-runs skip rows already present.

Usage:
    .venv/bin/python scripts/load_ubos_geography.py \\
        /Users/johnsonmwebaze/Downloads/Goegraphy_final_with_codes.xlsx

Options:
    --effective-from YYYY-MM-DD   Default 2026-01-01.
    --dry-run                     Print counts; no DB writes.
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

from django.db import transaction  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from apps.reference_data.models import GeographicUnit  # noqa: E402


EXPECTED_HEADER = (
    "District_code", "District_Name", "County_code", "County_Name",
    "Subcounty_code", "Subcounty_Name", "Parish_code", "Parish_Name",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsx", help="Path to the UBOS hierarchy workbook")
    p.add_argument("--effective-from", default="2026-01-01",
                   help="Effective-from date for all rows (ISO). Default 2026-01-01.")
    p.add_argument("--dry-run", action="store_true", help="Print counts only; do not write.")
    return p.parse_args()


def _normalise(value) -> str:
    return str(value).strip() if value is not None else ""


def read_rows(path: str) -> list[tuple[str, ...]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    header = tuple(next(it))
    if header != EXPECTED_HEADER:
        raise SystemExit(f"unexpected header: {header}\nexpected: {EXPECTED_HEADER}")
    rows: list[tuple[str, ...]] = []
    for row in it:
        if row is None or all(v is None for v in row):
            continue
        rows.append(tuple(_normalise(v) for v in row))
    return rows


def build_unique(rows: list[tuple[str, ...]]):
    """Walk the parish-level rows and collect unique nodes per level.

    Returns four dicts:
      districts:    composite_code -> name
      counties:     composite_code -> (name, parent_district_code)
      subcounties:  composite_code -> (name, parent_county_code)
      parishes:     composite_code -> (name, parent_subcounty_code)
    """
    districts: dict[str, str] = {}
    counties: dict[str, tuple[str, str]] = {}
    subcounties: dict[str, tuple[str, str]] = {}
    parishes: dict[str, tuple[str, str]] = {}

    for dc, dn, cc, cn, sc, sn, pc, pn in rows:
        if not (dc and cc and sc and pc):
            continue
        d_code = dc
        c_code = f"{dc}.{cc}"
        s_code = f"{dc}.{cc}.{sc}"
        p_code = f"{dc}.{cc}.{sc}.{pc}"

        districts.setdefault(d_code, dn.title() if dn.isupper() else dn)
        counties.setdefault(c_code, (cn.title() if cn.isupper() else cn, d_code))
        subcounties.setdefault(s_code, (sn.title() if sn.isupper() else sn, c_code))
        parishes.setdefault(p_code, (pn.title() if pn.isupper() else pn, s_code))

    return districts, counties, subcounties, parishes


def load_level(level: str, mapping: dict, parent_lookup: dict[str, GeographicUnit] | None,
               effective_from: date) -> dict[str, GeographicUnit]:
    """Bulk-load one level. Re-runs skip existing rows (idempotent)."""
    existing = {
        u.code: u for u in GeographicUnit.objects.filter(
            level=level, effective_from=effective_from,
        )
    }
    creates: list[GeographicUnit] = []
    for code, payload in mapping.items():
        if code in existing:
            continue
        if isinstance(payload, tuple):
            name, parent_code = payload
            parent = parent_lookup[parent_code] if parent_lookup else None
        else:
            name, parent = payload, None
        creates.append(GeographicUnit(
            level=level, code=code, name=name, parent=parent, effective_from=effective_from,
        ))

    if creates:
        GeographicUnit.objects.bulk_create(creates, batch_size=2000)

    # Re-read so callers can resolve children's parent FKs.
    return {
        u.code: u for u in GeographicUnit.objects.filter(
            level=level, effective_from=effective_from,
        )
    }


def main() -> int:
    args = parse_args()
    eff = date.fromisoformat(args.effective_from)
    rows = read_rows(args.xlsx)
    print(f"read {len(rows)} parish rows from {args.xlsx}")

    districts, counties, subcounties, parishes = build_unique(rows)
    print(f"  unique districts:   {len(districts):>6}")
    print(f"  unique counties:    {len(counties):>6}")
    print(f"  unique sub-counties:{len(subcounties):>6}")
    print(f"  unique parishes:    {len(parishes):>6}")

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    with transaction.atomic():
        d_map = load_level("district", districts, None, eff)
        print(f"  districts in DB at {eff}:   {len(d_map):>6}")
        c_map = load_level("county", counties, d_map, eff)
        print(f"  counties in DB at {eff}:    {len(c_map):>6}")
        s_map = load_level("sub_county", subcounties, c_map, eff)
        print(f"  sub-counties in DB at {eff}:{len(s_map):>6}")
        p_map = load_level("parish", parishes, s_map, eff)
        print(f"  parishes in DB at {eff}:    {len(p_map):>6}")

    print(f"\nGeographicUnit total rows: {GeographicUnit.objects.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
