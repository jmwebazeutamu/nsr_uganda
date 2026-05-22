"""Registered PMT features (`registered_function` DSL escape hatch).

Features whose computation doesn't fit the JSON DSL grammar live here
as decorated Python functions. Spec §4.1 lists the DSL types it does
cover; this module is the explicit pressure-release valve for
everything else.

Each function takes the household feature graph (the dict produced by
`apps.pmt.engine._household_features`) and returns a float — or any
value the evaluator's _as_float can coerce. Side effects are
forbidden: the evaluator is pure and the registry contract requires
deterministic output for a deterministic input.

The seeded UNHS 2023/24 active model doesn't currently need this
escape hatch — every variable expresses cleanly in the DSL. The two
functions below exist for the FCS / FIES use cases the spec calls out
as "complex features that don't fit the DSL" and for future percentile-
based variables. They're imported via apps.pmt.apps.PmtConfig.ready()
so the registry decorations run at startup.
"""

from __future__ import annotations

from typing import Any

from apps.pmt.registry import register


@register("food_consumption_score_v1")
def fcs_v1(features: Any) -> float:
    """Read the household's pre-computed Food Consumption Score
    (stored on FoodConsumption.fcs_score, computed on save per
    ADR-0020). Returns 0 if the household has no FoodConsumption row."""
    food = _get(features, "food_consumption")
    if food is None:
        return 0.0
    return float(getattr(food, "fcs_score", 0) or 0)


@register("fies_raw_score_v1")
def fies_v1(features: Any) -> float:
    """Read the household's pre-computed FIES raw score (0–8) off
    FoodSecurity.fies_raw_score. Returns 0 when no FoodSecurity row."""
    fs = _get(features, "food_security")
    if fs is None:
        return 0.0
    return float(getattr(fs, "fies_raw_score", 0) or 0)


def _get(features: Any, key: str) -> Any:
    """Tiny shim — `features` is a dict from _household_features.
    Centralised so future changes (e.g. swap to attribute access)
    only touch one place."""
    if isinstance(features, dict):
        return features.get(key)
    return getattr(features, key, None)
