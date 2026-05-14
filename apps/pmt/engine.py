"""PMT scoring engine.

Sprint 1 placeholder. The real formula + calibration dataset is open
item O-03; until it lands, the engine evaluates a simple weighted sum
of attribute paths declared on the active PMTModelVersion. The shape
of variables on the model is stable: variables = [
    {"variable": "<dotted.path>", "weight": <float>, "transform": "identity"|"log1p"|"present_as_one"},
    ...
]

Bands derive from band_cutoffs, an inclusive-lower-bound map of
band -> threshold. The default cutoffs treat scores as 0..100.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from .models import Band, PMTModelVersion

DEFAULT_BAND_CUTOFFS = {
    Band.EXTREME_POVERTY: 0,
    Band.POVERTY: 30,
    Band.VULNERABLE: 60,
    Band.NOT_POOR: 80,
}


def _get(record: Any, path: str) -> Any:
    cur = record
    for part in path.split("."):
        if cur is None:
            return None
        cur = (cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None))
    return cur


def _coerce(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _transform(value: Any, name: str) -> float:
    raw = _coerce(value)
    if name == "log1p":
        return math.log1p(max(raw, 0.0))
    if name == "present_as_one":
        return 1.0 if value not in (None, "", 0, False) else 0.0
    return raw  # identity


def derive_band(score: float, cutoffs: dict[str, float]) -> str:
    """Return the band whose lower cutoff is the largest one not exceeding score."""
    items = sorted((c, b) for b, c in cutoffs.items())
    band = items[0][1]
    for cutoff, b in items:
        if score >= cutoff:
            band = b
    return band


def compute_pmt(household, model_version: PMTModelVersion) -> tuple[float, str, dict]:
    """Apply the model to a Household instance.

    Returns (score, band, inputs_snapshot) where inputs_snapshot logs
    each variable's raw value + transformed contribution for later audit.
    """
    snapshot: dict[str, dict] = {}
    score = float(model_version.intercept or 0)
    members = list(household.members.filter(is_deleted=False))
    record = {
        "household": household,
        "members": members,
        "member_count": len(members),
    }
    for var in (model_version.variables or []):
        path = var.get("variable", "")
        weight = float(var.get("weight", 0))
        transform = var.get("transform", "identity")
        raw = _get(record, path)
        transformed = _transform(raw, transform)
        contribution = weight * transformed
        score += contribution
        snapshot[path] = {
            "raw": raw if isinstance(raw, (int, float, str)) else str(raw),
            "transformed": transformed,
            "weight": weight,
            "contribution": contribution,
        }
    cutoffs = model_version.band_cutoffs or {
        b.value: float(c) for b, c in DEFAULT_BAND_CUTOFFS.items()
    }
    band = derive_band(score, {str(k): float(v) for k, v in cutoffs.items()})
    return score, band, snapshot
