"""Backfill missing GeographicUnit rows from staged canonical payloads
(US-S11-015 / -016).

Promotion fails with "geographic unit {level}={code} not found" when
a stage record references a geographic code that isn't in
GeographicUnit yet. This module collects every (level, code) tuple
referenced by stage records and creates any missing rows in
hierarchical order so parent FKs resolve.

The same logic is exposed two ways:
- `backfill_missing_geo_from_stages()` — callable from the pull
  action so geo gaps don't block fresh imports.
- `scripts/seed_geo_from_stages.py` — thin CLI wrapper for ops.

Names: regions / sub-regions / villages have names in the Kobo
source (captured in _source_keys.kobo_*_name). Districts / counties
/ sub-counties / parishes carry only codes — for those, the code
doubles as the placeholder name until the UBOS workbook is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction

from apps.reference_data.models import GeographicUnit

from .models import StageRecord

EFFECTIVE_FROM = date(2026, 1, 1)

# Hierarchical relationships. Each level's parent is the previous one
# in the list. Codes are processed in this order so parent FKs resolve.
LEVEL_ORDER = (
    "region", "sub_region", "district", "county",
    "sub_county", "parish", "village",
)

_PARENT_LEVEL = {
    "sub_region": "region",
    "district": "sub_region",
    "county": "district",
    "sub_county": "county",
    "parish": "sub_county",
    "village": "parish",
}


@dataclass(frozen=True)
class BackfillResult:
    """Per-level creates + total. Returned to callers (admin action,
    CLI) so they can report what happened without re-counting."""

    by_level: dict[str, int]
    skipped_present: int

    @property
    def total_created(self) -> int:
        return sum(self.by_level.values())


def _name_for(level: str, code: str, source_keys: dict) -> str:
    """Best display name for a freshly-fabricated row. Region,
    sub_region and village have names in the Kobo source; the rest
    fall back to the code so operators see something deterministic."""
    if level == "region":
        return (source_keys.get("kobo_region_name") or "").title() or code
    if level == "sub_region":
        return (source_keys.get("kobo_subregion_name") or "").title() or code
    if level == "village":
        return source_keys.get("kobo_village_name") or code
    return code


def _collect_targets(stage_qs=None) -> dict[str, dict[str, dict]]:
    """Walk stage records (default: all) and return a nested map
    `targets[level][code] = {"name": str, "parent_code": str | None}`.

    Pass a narrower queryset (e.g. `StageRecord.objects.filter(
    connector_run=run)`) to scope the backfill to a single pull."""
    stage_qs = stage_qs if stage_qs is not None else StageRecord.objects.all()
    targets: dict[str, dict[str, dict]] = {lvl: {} for lvl in LEVEL_ORDER}
    for stage in stage_qs.iterator():
        payload = stage.canonical_payload or {}
        geo = payload.get("geographic") or {}
        sk = payload.get("_source_keys") or {}
        for level in LEVEL_ORDER:
            code = geo.get(level)
            if not code:
                continue
            entry = targets[level].setdefault(code, {
                "name": _name_for(level, code, sk),
                "parent_code": geo.get(_PARENT_LEVEL.get(level)) or None,
            })
            # A later stage may carry a non-placeholder name (mostly
            # matters for villages where the name is the only useful
            # display). Upgrade the entry rather than first-write-wins.
            better = _name_for(level, code, sk)
            if entry["name"] == code and better != code:
                entry["name"] = better
    return targets


@transaction.atomic
def backfill_missing_geo_from_stages(stage_qs=None) -> BackfillResult:
    """Create any GeographicUnit rows the (subset of) stage records
    reference but the DB doesn't have yet. Idempotent — re-runnable
    after every Kobo pull without duplicate-key risk."""
    targets = _collect_targets(stage_qs)
    cache: dict[tuple[str, str], GeographicUnit] = {}
    by_level: dict[str, int] = {lvl: 0 for lvl in LEVEL_ORDER}
    skipped = 0

    for level in LEVEL_ORDER:
        for code, payload in targets[level].items():
            existing = GeographicUnit.objects.filter(
                level=level, code=code,
            ).first()
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
            row = GeographicUnit.objects.create(
                level=level, code=code, name=payload["name"],
                parent=parent, effective_from=EFFECTIVE_FROM,
            )
            cache[(level, code)] = row
            by_level[level] += 1

    return BackfillResult(by_level=by_level, skipped_present=skipped)
